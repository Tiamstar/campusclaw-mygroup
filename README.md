# CampusClaw 教学知识库

价值主张：为教师和学生提供具备账号登录、角色权限与班级数据隔离的课程材料知识库，让教学资料能够安全地按班级沉淀和共享。
核心场景：教师登录后向所属班级上传教学材料并写入知识库，教师和学生可查询本班材料，学生上传或任何跨班访问均由服务端拒绝。
本学期不做：不实现语义搜索、检索问答、RAG、对话助手、作业提交与批改、成绩管理、超级管理员、SSO、多因素认证及生产级高可用部署；本期只做本班关键词检索。

## 本地开发（可选）

需要 Python 3.12+。安装依赖后，在服务端设置 `SECRET_KEY`；数据库与上传文件默认存于 `instance/`。

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[test]'
export SECRET_KEY='替换为随机生成的长密钥'
.venv/bin/flask --app campusclaw:create_app init-db
.venv/bin/flask --app campusclaw:create_app run
.venv/bin/pytest
```

## Docker Compose

复制 `.env.example` 为 `.env`，填入随机 `SECRET_KEY` 和演示账号密码后运行：

```bash
docker compose up --build -d
docker compose exec app flask --app campusclaw:create_app seed-demo
docker compose ps
curl http://localhost:8000/health
```

演示账号为 `teacher_a`、`student_a`、`student_b`；前两者属于 A 班，后者属于 B 班。演示密码只从 `.env` 的 `SEED_TEACHER_PASSWORD` 和 `SEED_STUDENT_PASSWORD` 读取，初始化命令可重复运行且不会覆盖已有密码。退出或过期的会话不可重用。

教师可在班级页面上传 `.pdf`、`.txt`、`.md`（TXT/MD 为 UTF-8），每个文件不超过 10 MiB。上传成功时同时写入可查正文：TXT/MD 读取 UTF-8，PDF 提取文字层；新上传的空白或扫描版 PDF 因没有可提取正文而被拒绝（本期不做 OCR）。材料原件只作为附件下载，不内联渲染。SQLite 数据、会话和上传文件在本地主机命名卷中持久化；本项目只支持单实例，不适用于生产 HA。HTTP 本地演示可将 `COOKIE_SECURE=false`，部署在 HTTPS 后应设置为 `true`。

本班成员可在材料页进入“检索知识库”，按关键词查正文，查看纯文本详情及材料来源，再经过授权下载原件。使用 SQLite FTS5 trigram，短于三个字符的词走班级范围子串查询；**不使用向量数据库或嵌入模型**。升级现有 Compose 数据时会补录旧材料的可提取正文；旧的无法提取文字的 PDF 仍可下载，但不能用正文检索。

接口与边界（网页由 Flask 服务端渲染，刷新时重新校验会话和班级，不需要前端调用 `/api/me`）：

| 路径 | 权限与结果 |
| --- | --- |
| `GET /login`、`POST /login`、`POST /logout` | 账号密码登录、CSRF、退出撤销会话；失败统一提示，同一账号 15 分钟内失败 5 次后暂拒登录 |
| `GET /classes/<class_id>/materials`、`GET /api/classes/<class_id>/materials` | 本班成员可见；未登录页面跳登录、API 返回 401；跨班 403 |
| `POST /api/classes/<class_id>/materials` | 仅本班教师且需 CSRF；学生或跨班 403 |
| `GET /api/classes/<class_id>/materials/<material_id>`、`GET /classes/<class_id>/materials/<material_id>/download` | 本班详情及鉴权附件下载，未授权班级 403，本班不存在的材料 404；上传目录不公开 |
| `GET /classes/<class_id>/knowledge/search?q=...`、`GET /api/classes/<class_id>/knowledge/search?q=...` | 本班正文关键词检索与来源；跨班 403，空或异常关键词 400 |
| `GET /classes/<class_id>/knowledge/documents/<id>`、对应 `/api/` 路径 | 本班正文与原件来源；其他班级文档 ID 在已授权班级路径下返回 404 |
| `GET /health` | 无需登录；SQLite 和上传目录均可用时返回 `{"status":"ok"}`，故障返回 503（就绪检查） |

本期采用单一 Flask 服务提供网页和同源 `/api`，没有单独暴露的数据库或 API 容器端口。跨班 URL 统一返回 403；已授权班级中不存在或不属于该班的材料/文档 ID 返回 404。该选择与本仓库的 OpenSpec、实现和测试一致，不沿用教程演示栈的跨班 404 约定。

回滚应用时先停止新容器并保留 `app_data` 卷。不要运行 `docker compose down -v`，否则会删除数据库和材料文件。中断上传后可执行 `docker compose exec app flask --app campusclaw:create_app cleanup-orphans` 清理超过 24 小时且不被数据库引用的孤儿文件。真实 `.env`、上传文件与数据库不得提交 Git。

更新已有数据前应先备份 `app_data` 卷；`init-db` 会非破坏性增加正文列并重建 FTS5 索引，可重复执行。首次建索引需 SQLite 支持 FTS5 trigram；缺失时启动失败，不降级为不受班级约束的检索。验收命令和可复核结果记录在变更的 `tasks.md` 末尾。
