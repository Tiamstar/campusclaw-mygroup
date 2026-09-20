## Context

当前仓库没有既有业务代码，本变更面向课程项目和可重复验收。实现需要覆盖登录、教师/学生角色、班级隔离、教师上传入库、预置演示数据、Docker Compose 和健康检查，但不需要生产级分布式架构。行为契约见三份 delta spec。

## Goals / Non-Goals

**Goals:**

- 使用小型、易测试的 Flask 服务实现完整的服务端认证、角色授权和班级过滤。
- 使用 SQLite 保存用户、班级、材料与知识库记录，并在 Compose 中持久化。
- 让上传成功、数据库记录、知识库记录和材料列表之间具有清晰的一致性规则。
- 提供预置 A/B 班账号，使跨班拒绝、学生 403 和上传后可查可直接验收。
- `docker compose up` 一键启动；`GET /health` 供探活；密钥与 DB 路径可配置。

**Non-Goals:**

见 `proposal.md` Non-goals（检索问答、对话、作业、SSO、生产 HA 等）

## Decisions

### 1. 使用 Flask、SQLAlchemy 和 SQLite

应用采用 Flask 应用工厂组织配置和扩展，SQLAlchemy 或 Flask-SQLAlchemy 管理模型与事务，pytest 使用 Flask test client 做路由和权限测试。SQLite 数据库文件放在 Flask `instance` 目录或显式数据目录中，容器运行时挂载命名卷。

数据模型至少包含：

- `users`: `id`、唯一 `username`、`password_hash`、`role`、`is_active`。
- `classes`: `id`、唯一 `name`。
- `class_memberships`: `user_id`、`class_id` 唯一组合。
- `materials`: `id`、`class_id`、`uploaded_by`、原始文件名、内部存储名、状态、创建时间。
- `knowledge_documents`: `id`、`material_id` 唯一关联、`class_id`、标题、存储位置和创建时间。



SQLite 启用外键约束。写请求使用短事务，避免长时间持锁；课程规模下 SQLite 足够，未来扩展到 PostgreSQL 时保持模型和仓储边界不变。

### 2. 使用 Flask 会话与数据库用户加载

登录成功后把最小用户标识写入 Flask 签名会话 Cookie，`SECRET_KEY` 只从环境变量读取。Cookie 设置 `HttpOnly`、`SameSite=Lax`，生产模式设置 `Secure`。每次受保护请求根据会话中的用户 ID 重新从数据库加载用户、角色和班级成员关系，不信任客户端提交的角色或班级。

页面路由未登录时重定向到登录页；JSON API 未登录时返回 401。退出登录清除会话。登录后的 `next` 参数只允许站内安全路径，防止开放重定向。

选择 Flask 内置签名会话而不是 JWT，是因为课程项目只有单应用和浏览器客户端，配置更少，并且角色、班级变更可在下一请求重新读取数据库后立即生效。

受保护路由使用统一前置逻辑（装饰器或 `before_request`）：无有效 session → 页面 `302` 至 `/login`；API 返回 `401` JSON。
### 3. 使用专用密码哈希函数

账号初始化和后续密码变更统一调用密码服务。优先使用 Werkzeug `generate_password_hash(..., method="scrypt")` 与 `check_password_hash`；若项目依赖已包含 Argon2，也可使用 Argon2id，但不得使用 SHA-256 等通用快速哈希直接存密码。

初始化密码通过 `SEED_TEACHER_PASSWORD`、`SEED_STUDENT_PASSWORD` 等服务端环境变量或 CLI 参数传入，只在内存中参与哈希，不写入日志。用户表只保存 `password_hash`。

### 4. 预置数据通过幂等 Flask CLI 命令创建

提供类似 `flask seed-demo` 的命令，使用稳定用户名或自然键幂等创建：A 班、B 班、A 班教师、A 班学生和 B 班学生及成员关系。重复执行时更新缺失关系但不生成重复记录。命令输出只显示创建/已存在状态，不回显密码。

预置数据既用于课堂演示，也作为跨班测试夹具：A 班账号访问 B 班材料必须得到 403；学生直接调用上传接口必须得到 403。

### 5. 班级过滤在服务端查询层强制执行

认证装饰器负责加载当前用户；教师装饰器只负责角色判断；班级授权函数根据 `class_memberships` 判断目标 `class_id` 是否允许。材料列表、详情、下载和上传均必须先验证班级成员关系。

查询材料时同时使用资源条件和班级条件，例如按 `material_id` 查询时仍附加允许的 `class_id`。不能先取出任意材料再依赖前端隐藏，也不能使用请求中的 `user_id` 或 `role`。学生可读取本班 `ready` 材料，但任何上传请求在保存文件之前返回 403。

上传与写入

- 新记录的 `class_id` **只取自 session**，忽略表单中的 class 字段（若有则丢弃或拒绝）。
- 教师仅能在本会话班级写入；不存在「代传 B 班」API。

测试关注点

- 学生 A1 列表不见 B 班标题；教师 A 用 B 班 material id 访问被拒；与 spec 三个班级 Scenario 一一对应。

### 6. 上传采用“先授权、再校验、后事务入库”的数据流

上传流程如下：

1. 验证会话、教师角色和目标班级成员关系。
2. 校验文件存在、允许类型、大小和安全文件名；生成不可预测的内部存储名。
3. 将文件写入受控上传目录。
4. 在同一 SQLite 事务中创建 `materials` 和 `knowledge_documents`，两条记录使用相同 `class_id`，材料状态设为 `ready`。
5. 提交事务后返回材料摘要；材料列表只查询当前用户班级的 `ready` 记录。
6. 如果数据库写入失败，回滚事务并删除刚保存的文件，避免孤儿文件或只有材料没有知识库记录。

本课中的“写入知识库”定义为创建可被后续知识能力使用的 `knowledge_documents` 记录并关联原始材料；不在本次实现文本切块、向量化或检索问答。该边界与 proposal 的 Non-Goals 一致。



### 7. Compose 持久化 SQLite 与上传目录

Dockerfile 运行 Flask 应用，Compose 负责构建应用、传入环境变量、暴露 HTTP 端口，并挂载持久化数据卷到 SQLite 与上传目录。仓库只提交 `.env.example`，真实 `SECRET_KEY` 和初始化密码由运行者提供。

课程基线可以只有一个应用服务，因为 SQLite 与知识库记录都在应用数据卷中。容器启动命令应先完成数据库建表或迁移，再启动 Web 服务；初始化演示数据通过显式命令执行，避免每次启动覆盖已有账号。

### 8. GET /health 同时用于人工和 Compose 探活

`GET /health` 不受登录保护。端点检查：必需配置已加载、SQLite 可执行 `SELECT 1`、上传目录存在且可写。全部通过时返回 `200 {"status":"ok"}`；任一关键检查失败时返回 503 和简化组件状态，不返回数据库绝对路径、密钥或异常堆栈。

Compose healthcheck 使用容器内 HTTP 请求访问该端点，并配置合理的启动等待、间隔和重试次数。

## Risks / Trade-offs

- [SQLite 并发写能力有限] → 本课使用短事务和单应用实例；生产 HA 明确不在范围内。
- [签名 Cookie 被窃取会导致会话冒用] → 设置 `HttpOnly`、`SameSite`、生产 `Secure`，退出时清除会话，并避免日志记录 Cookie。
- [遗漏查询中的班级条件会造成越权] → 把班级检查封装为复用函数，并对列表、详情、下载和上传逐一路由编写跨班测试。
- [文件已保存但数据库事务失败会产生孤儿文件] → 捕获异常、回滚事务并删除本次文件，测试故障分支。
- [预置密码可能被当作生产密码] → 密码只从环境变量或 CLI 参数传入，文档明确预置数据仅用于课程演示。

## Migration Plan

1. 创建 Flask 应用工厂、配置、数据库和测试骨架。
2. 创建 SQLite 模型、建表/迁移与幂等 `seed-demo` 命令。
3. 实现登录、退出、会话保护和角色检查。
4. 实现班级过滤、材料列表和跨班拒绝。
5. 实现教师上传、知识库记录事务与失败清理。
6. 添加 Dockerfile、Compose、持久化卷和 `GET /health`。
7. 在 Compose 环境执行完整测试和规格严格校验；回滚时停止新容器并保留数据卷。
