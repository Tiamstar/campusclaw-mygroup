## Purpose

扩展现有容器运行基线，使向量检索依赖在服务端私有网络中持久、可探测且具有明确故障语义。

## ADDED Requirements

### Requirement: 向量检索依赖必须由 Compose 私有编排
Docker Compose SHALL 提供带持久化命名卷的 Qdrant 服务，并 SHALL 只允许应用通过内部网络访问。Qdrant、嵌入网关和对话网关 MUST NOT 向宿主机映射客户端可绕过认证访问的端口；上传目录只挂载到需要处理文件的应用服务。

#### Scenario: 启动检索服务
- **WHEN** 操作者提供必需服务端配置并执行 Compose 启动
- **THEN** 应用可通过内部网络访问 Qdrant，浏览器只通过本站 HTTP 入口调用检索 API

#### Scenario: 容器重建后向量保留
- **WHEN** 已建立切片向量后重新创建 Qdrant 容器但保留命名卷
- **THEN** collection、向量 point 与 payload 仍存在并能与关系库切片关联

#### Scenario: 检查公开端口
- **WHEN** 操作者检查 Compose 展开的端口映射
- **THEN** Qdrant 和内部模型网关没有宿主机端口映射

### Requirement: 检索依赖状态必须可探测且不泄露配置
系统 SHALL 在健康/就绪响应中以简化组件状态报告关系库、上传目录和 Qdrant 可用性，不得返回内部 URL、数据库路径、密钥或异常堆栈。Qdrant 或嵌入网关故障时 SHALL 保留关键词检索能力，并使依赖向量的操作返回 HTTP 503。

#### Scenario: 所有依赖就绪
- **WHEN** 关系库、上传目录、Qdrant 和所需服务端配置均可用
- **THEN** 就绪检查返回成功及机器可读的简化状态

#### Scenario: Qdrant 不可用
- **WHEN** Qdrant 停止或超时
- **THEN** 状态只报告向量组件不可用，keyword 检索仍工作且 vector/hybrid 返回 HTTP 503

#### Scenario: 故障信息脱敏
- **WHEN** 内部依赖连接或鉴权失败
- **THEN** 健康响应与日志不包含密钥、完整内部 URL、切片正文或异常堆栈
