# CampusClaw 教学知识库

价值主张：为教师和学生提供具备账号登录、角色权限与班级数据隔离的课程材料知识库，让教学资料能够安全地按班级沉淀和共享。
核心场景：教师登录后向所属班级上传教学材料并写入知识库，教师和学生可查询本班材料，学生上传或任何跨班访问均由服务端拒绝。
当前版本在班级知识库基础上提供三个内置 AI 应用（解题助手、课堂问答、材料摘要）、教师提示词模板、内置与上传的 Markdown Skill、流式多轮会话及 MCP 工具接入。检索支持关键词、向量与 RRF 混合模式；会话每次只把本班最多四个命中切片交给模型。暂不支持 OCR、作业批改、成绩管理、SSO 或生产级高可用部署。

## 本地开发（可选）

需要 Python 3.12+。安装依赖后，在服务端设置 `SECRET_KEY`；数据库与上传文件默认存于 `instance/`。

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[test]'
export SECRET_KEY='替换为随机生成的长密钥'
.venv/bin/flask --app campusclaw:create_app init-db
.venv/bin/flask --app campusclaw:create_app run
.venv/bin/pytest
.venv/bin/python apitest/run_all.py
```

## Docker Compose

复制 `.env.example` 为 `.env`，填入随机 `SECRET_KEY`、`MCP_AUTH_TOKEN` 和演示账号密码后运行：

```bash
docker compose up --build -d
docker compose exec app flask --app campusclaw:create_app seed-demo
docker compose exec app flask --app campusclaw:create_app seed-demo-materials
docker compose ps
curl http://localhost:8000/health
```

Compose 只向宿主机公开 Nginx 的 `8000` 端口；应用和 Qdrant 仅位于内部网络。首次升级已有数据卷后，可回填正文切片：

```bash
docker compose exec app flask --app campusclaw:create_app reindex-knowledge
```

未配置嵌入网关时，上传和回填仍建立关键词切片索引，向量与混合**检索接口**返回 503；新流式会话会退到本班关键词检索。课程网关使用 `EMBEDDING_BASE_URL`、`EMBEDDING_API_KEY`、`EMBEDDING_MODEL=course-embedding`、`EMBEDDING_DIM=2048` 和 `CHAT_MODEL=course-chat`；聊天默认复用同一 base URL 与密钥，也可用 `CHAT_BASE_URL`、`CHAT_API_KEY` 单独覆盖。密钥只进入应用容器，不会写入浏览器或 Qdrant payload。

## AI 应用、Skill 与 MCP

登录后打开 `/apps`。教师可创建和修改本班提示词模板、上传 UTF-8 `.md` 技能（不超过 8 KiB）、登记 MCP 服务器、连接发现工具并查看审计；学生可选择应用、模板和技能，新建会话并查看 SSE 流式回答。内置技能为“解题引导”和“证据引用”。技能的 `tools` 可写 `knowledge_search` 或 `formula_hint@campus_tools` 等已连接且已发现的 MCP 引用。技能说明作为系统消息的一部分；MCP 工具由服务端执行，返回文本作为用户消息中的数据。断开后清除发现缓存，再调用将记录为 `denied`。

自建 MCP 服务位于同仓 `mcp-server/`，Compose 内部地址为 `http://mcp-demo:8090`。在 `/apps` 登记名称 `campus_tools`、该地址和与 `.env` 中 `MCP_AUTH_TOKEN` 相同的令牌，再点击“连接”，即可发现 `formula_hint` 与 `unit_convert`。令牌只存于服务端数据库，不在列表、审计或模型请求中返回。`/docs` 是可离线打开的 Swagger UI，`/openapi.json` 提供 OpenAPI 3 描述。

Bearer API 登录示例（网页表单登录仍可使用 Cookie 与 CSRF）：

```text
POST /api/login {"username":"teacher_a","password":"..."}
Authorization: Bearer <access_token>
POST /api/conversations {"app_key":"solver","builtin_skill":"guide"}
POST /api/conversations/<id>/messages {"query":"下一步怎么做？"}
```

最后一个接口返回 `text/event-stream`，事件顺序为 `meta`（引用和工具状态）、`delta`（文本增量）、`done`（最终状态和回答）。新应用接口的班级从服务端活动会话读取，不相信请求体的 `class_id`。测试命令 `.venv/bin/pytest -q` 与 `.venv/bin/python apitest/run_all.py`；后者在 `apitest/report.html` 生成不提交 Git 的 HTML 记录。完整验收和 LLM 参数样例见 `docs/acceptance-report.pdf`。

检索 API 使用登录会话在服务端记录的活动班级，不接受请求中的 `class_id` 作为授权依据：

```text
POST /api/retrieval/search  {"query":"光合作用","mode":"keyword|vector|hybrid"}
POST /api/ask               {"query":"植物如何制造养分？"}
```

多班用户须先用带 CSRF 令牌的 `POST /api/session/active-class` 选择已有成员关系的班级；该值保存在服务端 `sessions` 表，不写入身份 Cookie。

演示账号为 `teacher_a`、`student_a`、`student_b`；前两者属于 A 班，后者属于 B 班。演示密码只从 `.env` 的 `SEED_TEACHER_PASSWORD` 和 `SEED_STUDENT_PASSWORD` 读取，初始化命令可重复运行且不会覆盖已有密码。退出或过期的会话不可重用。

教师可在班级页面上传 `.pdf`、`.txt`、`.md`（TXT/MD 为 UTF-8），每个文件不超过 10 MiB。上传成功时同时写入可查正文：TXT/MD 读取 UTF-8，PDF 提取文字层；新上传的空白或扫描版 PDF 因没有可提取正文而被拒绝（本期不做 OCR）。材料原件只作为附件下载，不内联渲染。SQLite 数据、会话和上传文件在本地主机命名卷中持久化；本项目只支持单实例，不适用于生产 HA。HTTP 本地演示可将 `COOKIE_SECURE=false`，部署在 HTTPS 后应设置为 `true`。

本班成员可在材料页进入“检索知识库”，按关键词查正文，查看纯文本详情及材料来源，再经过授权下载原件。关键词路径使用 SQLite FTS5 trigram，短于三个字符的词走班级范围子串查询；向量与混合检索在配置嵌入网关及 Qdrant 后启用。升级现有 Compose 数据时会补录旧材料的可提取正文；旧的无法提取文字的 PDF 仍可下载，但不能用正文检索。

接口与边界（网页由 Flask 服务端渲染，刷新时重新校验会话和班级，不需要前端调用 `/api/me`）：

| 路径 | 权限与结果 |
| --- | --- |
| `GET /login`、`POST /login`、`POST /logout` | 账号密码登录、CSRF、退出撤销会话；失败统一提示，同一账号 15 分钟内失败 5 次后暂拒登录 |
| `GET /classes/<class_id>/materials`、`GET /api/classes/<class_id>/materials` | 本班成员可见；未登录页面跳登录、API 返回 401；跨班 404 |
| `POST /api/classes/<class_id>/materials` | 仅本班教师且需 CSRF；本班学生 403，跨班 404 |
| `GET /api/classes/<class_id>/materials/<material_id>`、`GET /classes/<class_id>/materials/<material_id>/download` | 本班详情及鉴权附件下载，未授权班级与不存在材料均 404；上传目录不公开 |
| `GET /classes/<class_id>/knowledge/search?q=...`、`GET /api/classes/<class_id>/knowledge/search?q=...` | 本班正文关键词检索与来源；跨班 404，空或异常关键词 400 |
| `GET /classes/<class_id>/knowledge/documents/<id>`、对应 `/api/` 路径 | 本班正文与原件来源；其他班级文档 ID 在已授权班级路径下返回 404 |
| `GET /health` | 无需登录；SQLite 和上传目录均可用时返回 `{"status":"ok"}`，故障返回 503（就绪检查） |

本期采用单一 Flask 服务提供网页和同源 `/api`，没有单独暴露的数据库或 API 容器端口。跨班 URL 与不存在或不属于本班的材料/文档 ID 均返回 404；本班学生执行教师专属操作返回 403。

回滚应用时先停止新容器并保留 `app_data` 卷。不要运行 `docker compose down -v`，否则会删除数据库和材料文件。中断上传后可执行 `docker compose exec app flask --app campusclaw:create_app cleanup-orphans` 清理超过 24 小时且不被数据库引用的孤儿文件。真实 `.env`、上传文件与数据库不得提交 Git。

更新已有数据前应先备份 `app_data` 卷；`init-db` 会非破坏性增加正文列并重建 FTS5 索引，可重复执行。首次建索引需 SQLite 支持 FTS5 trigram；缺失时启动失败，不降级为不受班级约束的检索。验收命令和可复核结果记录在变更的 `tasks.md` 末尾。
