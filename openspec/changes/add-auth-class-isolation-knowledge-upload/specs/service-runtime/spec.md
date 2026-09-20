## Purpose

提供适合课程验收的一致容器化启动方式和标准健康检查，使 Flask 应用、SQLite 数据和上传文件能够通过 Docker Compose 启动、持久化并被可靠探活。

## ADDED Requirements

### Requirement: 应用可通过 Docker Compose 启动
项目 SHALL 提供 Dockerfile 和 Docker Compose 配置，使应用可通过单条 Compose 命令启动。Compose SHALL 从服务端环境变量注入配置，并 SHALL 为 SQLite 数据库和上传文件挂载持久化卷。

#### Scenario: 配置完整时启动
- **WHEN** 操作者提供必需环境变量并执行 `docker compose up --build`
- **THEN** Compose 构建并启动应用，数据库和上传目录位于持久化卷中

#### Scenario: 容器重启后数据保留
- **WHEN** 操作者上传材料后重启或重新创建应用容器但保留 Compose 卷
- **THEN** 预置用户、班级、材料记录、知识库记录和上传文件仍然存在

#### Scenario: 必需配置缺失
- **WHEN** 操作者在缺少会话密钥等必需环境变量时启动 Compose
- **THEN** 应用不得报告为健康，并输出不含敏感值的配置错误

### Requirement: 应用提供 GET /health
应用 SHALL 提供无需认证的 `GET /health` 端点。该端点 SHALL 检查应用配置已加载、SQLite 可执行最小查询且上传目录可用，并返回机器可读状态。

#### Scenario: 应用健康
- **WHEN** 客户端请求 `GET /health` 且配置、SQLite 和上传目录均可用
- **THEN** 系统返回 HTTP 200 和包含 `status: "ok"` 的 JSON

#### Scenario: SQLite 不可用
- **WHEN** 客户端请求 `GET /health` 且应用无法打开数据库或执行最小查询
- **THEN** 系统返回非 2xx 和不包含数据库路径、密钥或堆栈的 JSON 状态

#### Scenario: 健康检查无需登录
- **WHEN** 未认证客户端请求 `GET /health`
- **THEN** 系统直接返回健康状态而不跳转登录页或返回 HTTP 401

### Requirement: Compose 使用健康端点探测应用
Docker Compose SHALL 为应用服务配置基于 `GET /health` 的健康检查，以便操作者和自动化测试判断服务是否就绪。

#### Scenario: Compose 报告健康
- **WHEN** 应用启动完成且 `GET /health` 持续返回 HTTP 200
- **THEN** Compose 将应用服务状态标记为 healthy

#### Scenario: Compose 报告不健康
- **WHEN** `GET /health` 在配置的重试次数内持续返回非 2xx 或无法连接
- **THEN** Compose 将应用服务状态标记为 unhealthy
