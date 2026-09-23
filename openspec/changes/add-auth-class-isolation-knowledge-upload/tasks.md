## 1. Flask 项目与配置基线

- [x] 1.1 创建 Flask 应用工厂、路由蓝图、SQLAlchemy 和 pytest 骨架；Verify: 运行测试命令时应用可在测试配置下创建且基础测试通过
- [x] 1.2 实现集中配置并从环境变量读取 `SECRET_KEY`、SQLite 路径、上传目录、10 MiB 单文件上限和请求体上限；Verify: 缺少 `SECRET_KEY` 时应用拒绝进入健康状态且错误信息不含敏感值
- [x] 1.3 配置会话 Cookie、统一 401/403/4xx 响应和敏感日志脱敏；Verify: HTTP 测试确认 Cookie 属性正确，日志中不出现密码、Cookie 或密钥

## 2. SQLite 模型与预置数据

- [x] 2.1 创建 `users`、`classes`、`class_memberships`、`sessions`、`materials` 和 `knowledge_documents` 模型及建表/迁移逻辑；Verify: 在空 SQLite 数据库执行初始化后表、外键、唯一约束和必要索引存在，`sessions` 不保存原始令牌
- [x] 2.2 实现基于 scrypt 或 Argon2id 的密码生成与校验服务；Verify: 相同密码生成的哈希不同、正确密码校验成功、用户表不含明文密码
- [x] 2.3 实现幂等 `flask seed-demo` 命令，创建 A/B 班、A 班教师、A 班学生和 B 班学生；Verify: 连续执行两次后记录不重复且三个账号可使用环境变量密码登录，密码不经 CLI 参数、日志或输出回显
- [x] 2.4 为模型和预置数据增加测试夹具；Verify: 测试可明确取得 A 班与 B 班用户及不同班级成员关系

## 3. 登录、退出与会话保护

- [x] 3.1 实现登录页面、账号密码登录与高熵随机服务端会话；Verify: 教师与学生可登录，错误凭据返回通用失败，数据库只存令牌摘要且登录轮换旧会话
- [x] 3.2 实现 8 小时会话有效期、当前用户加载、停用账号检查与统一页面/API 认证；Verify: 未登录页面跳登录页、API 返回 401，过期/停用会话均被拒绝
- [x] 3.3 实现安全的登录后 `next` 跳转和服务端会话撤销；Verify: 站内目标可返回、外部目标被拒绝、退出前复制的 Cookie 重放仍返回 401
- [x] 3.4 实现服务端教师/学生角色判断且忽略客户端角色字段；Verify: 学生伪造教师角色仍无法通过教师专属检查
- [x] 3.5 为登录、退出、上传等 Cookie 认证的写操作实现 CSRF 防护，协调认证和角色检查顺序；Verify: 有效令牌可提交、缺失/伪造令牌无副作用，未登录上传优先 401、学生上传优先 403

## 4. 班级隔离与材料读取

- [x] 4.1 实现 `/classes/<class_id>/materials` 的班级成员关系验证，不从 Cookie 或表单自称班级授权；Verify: A 班用户选择 B 班返回 403，同时属于 A/B 班的教师可分别进入两个班
- [x] 4.2 实现本班材料列表查询并只返回 `ready` 材料；Verify: A 班列表不包含 B 班材料，B 班列表不包含 A 班材料
- [x] 4.3 实现材料详情和附件下载路由，查询同时约束材料 ID 与已授权班级；Verify: 跨班返回 403、班内不存在返回 404，本班下载有 `attachment` 和 `nosniff` 且 Markdown 不内联渲染
- [x] 4.4 增加班级隔离集成测试；Verify: 列表、详情、文件和篡改班级 ID 的跨班用例全部通过

## 5. 教师上传与知识库入库

- [x] 5.1 实现 `.pdf`、`.txt`、`.md` 白名单与内容校验（PDF 含可提取正文、TXT/MD 严格 UTF-8）；Verify: 三种有效文件通过，空白/扫描 PDF、伪装扩展名、损坏 PDF、无效 UTF-8、DOCX/PPTX/ZIP 均返回 400 且无记录
- [x] 5.2 实现 10 MiB 单文件与含 multipart 开销的请求体上限、文件名长度和安全路径限制；Verify: 超限返回 413，路径穿越不能写出非公开上传目录，客户端 MIME 不能绕过内容检查
- [x] 5.3 实现教师上传页面和上传 API 的会话、角色、CSRF 与目标班级授权；Verify: 本班教师可进入上传流程，学生直接调用返回 403、教师跨班上传返回 403，拒绝路径均无文件和数据库新增
- [x] 5.4 实现非公开文件保存及 `materials` 与含正文的 `knowledge_documents` 同事务写入和索引更新；Verify: 成功上传后正文可查、索引可命中、两表班级一致、文件存在且状态为 `ready`
- [x] 5.5 实现数据库失败回滚、文件清理和超过安全等待期的孤儿文件对账命令；Verify: 注入数据库失败无新增记录或残留文件，模拟异常中断后对账仅删除未被记录引用的旧文件
- [x] 5.6 实现上传成功后的本班材料列表展示；Verify: A 班教师上传 PDF/TXT/MD 后 A 班教师和学生都能查到相应记录，B 班学生查不到

## 6. Docker Compose 与健康检查

- [x] 6.1 实现无需认证的 `GET /health`，检查配置、SQLite `SELECT 1` 和上传目录可写；Verify: 正常返回 200 与 `{"status":"ok"}`，数据库不可用时返回非 2xx 且不泄露路径或堆栈
- [x] 6.2 创建非 root Dockerfile 和单实例 Docker Compose，将 SQLite 数据库目录（含 journal/WAL）与上传目录放在本地主机命名卷并注入环境变量；Verify: `docker compose up --build` 后应用可访问、目录权限正确且容器 healthy
- [x] 6.3 验证 Compose 数据持久化与初始化流程；Verify: 执行预置命令并上传材料后重建应用容器，账号、班级、材料、知识库记录和文件仍存在
- [x] 6.4 编写运行说明和 `.env.example`；Verify: 按文档从空环境完成构建、预置数据、登录、上传、列表查询和健康检查，仓库中不存在真实密钥

## 7. 综合验收与 OpenSpec 校验

- [x] 7.1 运行认证、CSRF 与密码安全测试；Verify: 覆盖教师/学生登录、错误凭据、未登录跳转、API 401、过期/停用与撤销会话重放、伪造 CSRF 和数据库无明文密码
- [x] 7.2 运行角色与班级安全测试；Verify: 覆盖学生上传 403、角色伪造、教师跨班上传、A 班访问 B 班列表/详情/文件并全部被服务端拒绝
- [x] 7.3 运行上传入库和授权下载测试；Verify: 覆盖可提取正文 PDF/TXT/MD、超限 413、伪装与损坏文件、本班列表和正文可查、跨班下载 403、知识库关联和失败/中断清理
- [x] 7.4 运行本地完整测试及 Docker Compose 环境健康检查和检索冒烟测试；Verify: `.venv/bin/pytest -q` 全部通过、`GET /health` 与 Compose healthy 状态一致，已迁移材料在容器中可检索
- [x] 7.5 执行 `openspec validate add-auth-class-isolation-knowledge-upload --strict`；Verify: 命令以退出码 0 完成且没有规格格式或场景校验错误

## 8. 登录安全及知识库正文扩展

- [x] 8.1 实现不存在账号等价哈希验证和 SQLite 账号失败窗口；Verify: `.venv/bin/pytest -q tests/test_auth.py`，五次失败后正确密码仍通用 401、窗口到期可登录、未知账号与错误密码结果一致
- [x] 8.2 增加现有 SQLite 数据库的正文列迁移、旧文件补录及 FTS5 trigram 索引维护；Verify: `.venv/bin/pytest -q tests/test_materials.py`，旧库重复初始化后记录/会话/文件不丢失，旧 TXT/MD 可检索，新增文档与索引同事务
- [x] 8.3 上传时提取三类文件正文并拒绝无文字 PDF；Verify: `.venv/bin/pytest -q tests/test_materials.py`，三类正文可读，空白 PDF 无文件、记录和索引残留
- [x] 8.4 实现服务端班级范围搜索、正文详情、来源字段及安全页面；Verify: `.venv/bin/pytest -q tests/test_materials.py`，中文与短词能命中，本班可查，跨班 URL 403、异班文档 ID 404、材料下载链接再次鉴权
- [x] 8.5 统一实际路由与鉴权说明、403/404、服务端渲染身份恢复及无 OCR/向量方案边界；Verify: `rg -n '403|404|FTS5|正文|溯源' README.md openspec/changes/add-auth-class-isolation-knowledge-upload/{design.md,proposal.md}`，与接口测试结果相符
- [x] 8.6 改进上传页登录失效与失败提示；Verify: `.venv/bin/pytest -q tests/test_auth.py`，401 引导登录且保留站内返回路径，不削弱服务端权限

## 9. 可复核的交付证据

- [x] 9.1 记录场景与完整命令/输出，不把真实密钥或密码写入证据；Verify: `.venv/bin/pytest -q && openspec validate add-auth-class-isolation-knowledge-upload --strict`，记录教师上传、学生 403、跨班 403、正文搜索与来源、健康检查各自结果
- [x] 9.2 核对交付文件、忽略规则、干净环境启动步骤与未提交工作树；Verify: `git status --short && git check-ignore .env && docker compose config --quiet`，确认 `.env.example`、Docker、应用、测试和文档均纳入拟交付清单，且不添加真实 `.env`

## 本轮验收记录（2026-09-23）

以下命令在仓库根目录执行；测试使用临时 SQLite 与测试账号，不需记录或打印演示密码。用例名称与断言是可复核的判定依据。

| 场景 | 可复核命令 | 本轮结果 |
| --- | --- | --- |
| 完整回归 | `.venv/bin/pytest -q` | `26 passed` |
| 登录失败窗口、教师上传、学生上传 403、正文溯源及跨班 403、旧库升级 | `.venv/bin/pytest -q tests/test_auth.py::test_failed_login_window_and_csrf tests/test_materials.py::test_teacher_upload_and_class_scoped_read tests/test_materials.py::test_student_cannot_upload_even_without_csrf tests/test_materials.py::test_knowledge_search_body_source_and_isolation tests/test_materials.py::test_existing_database_backfills_text_without_losing_session` | `5 passed`；搜索测试还核对了异班文档 ID 404、来源下载 200、脚本转义和短词命中 |
| OpenSpec | `openspec validate add-auth-class-isolation-knowledge-upload --strict` | `Change 'add-auth-class-isolation-knowledge-upload' is valid` |
| Compose 与健康检查 | `docker compose up -d --build`、`docker compose ps`、`curl -fsS http://localhost:8000/health` | `healthy`；`{"status":"ok"}`；启动时短暂 `health: starting` 属正常初始化过程 |
| 未登录检索 | `curl -s -o /dev/null -w '%{http_code}\n' 'http://localhost:8000/api/classes/1/knowledge/search?q=test'` | `401` |
| 已有数据迁移 | `docker compose exec -T app python -c 'from campusclaw import create_app; from campusclaw.models import db; from sqlalchemy import text; app=create_app(); ctx=app.app_context(); ctx.push(); print(db.session.execute(text("SELECT COUNT(*) FROM materials")).scalar_one(), db.session.execute(text("SELECT COUNT(*) FROM knowledge_documents")).scalar_one(), db.session.execute(text("SELECT COUNT(*) FROM knowledge_documents WHERE length(trim(body)) > 0")).scalar_one()); ctx.pop()'` | 材料 `3`、知识库记录 `3`、有可查正文 `2`；旧无文字 PDF 保留下载但不伪造正文 |
| 演示账号的容器内冒烟 | 在容器中用服务端 `SEED_STUDENT_PASSWORD` 登录后，用 A 班已有正文词调用本班检索和来源下载，再用 B 班账号调用 A 班检索；不输出凭据或正文 | 登录 `302`、本班检索 `200`（2 条）、来源下载 `200`、跨班 `403`；对应可直接重跑的自动化断言见上方搜索测试 |
| 配置和交付清单 | `docker compose config --quiet && git check-ignore .env && git diff --cached --name-only` | 配置有效；`.env` 被忽略；`.env.example`、Dockerfile、Compose、`campusclaw/`、`tests/`、`pyproject.toml` 均已纳入暂存清单，未暂存数据库和上传文件 |
| 干净提交克隆 | `git clone . /private/tmp/campusclaw-clean-acceptance-20260923 && cd /private/tmp/campusclaw-clean-acceptance-20260923 && /Users/lifeifan/campusclaw-mygroup/.venv/bin/python -m pytest -q && openspec validate add-auth-class-isolation-knowledge-upload --strict` | 从新提交克隆的源码加载应用，`26 passed`，OpenSpec 有效；克隆中无 `.env` 与 `instance/`。测试依赖复用本机虚拟环境，第三方从零安装步骤见 README |

更新前已把现有 `/srv/data` 复制到本机 `/private/tmp/campusclaw-data-backup-2026-09-23`。本轮已通过现有数据卷升级、容器重建与提交后的干净本地克隆测试；远程 GitHub 推送结果另行核对，不把本地克隆冒充远程下载验收。
