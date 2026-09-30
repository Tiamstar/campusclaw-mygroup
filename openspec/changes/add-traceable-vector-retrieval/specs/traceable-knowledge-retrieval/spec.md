## Purpose

在服务端班级边界内提供可追溯的切片、关键词/向量/混合检索和有依据问答，使每个结果与回答引用都能回到本班原始材料。

## ADDED Requirements

### Requirement: 正文必须按受控策略切分且保留原文
系统 SHALL 支持 `auto`、`custom` 和 `hierarchy` 三种切分策略。未指定策略、上传后的首次索引及种子材料回填 SHALL 使用 auto：最大 800 字、重叠 80 字并优先在空行、换行或句号处断开。custom SHALL 只接受 100–2000 字最大长度、0%–50% 重叠及受支持分隔符；hierarchy SHALL 按 Markdown `#` 至 `###` 标题分章并保留标题，超长章再按 auto 切分。切分和预处理 MUST NOT 改写已保存的原始正文。

#### Scenario: 默认自动切分
- **WHEN** 教师上传有非空正文的材料且未指定策略
- **THEN** 系统以 800/80 auto 规则产生有序切片，并记录每片在待切分文本中的起止偏移

#### Scenario: 自定义参数越界
- **WHEN** 请求的 custom 最大长度小于 100 或大于 2000、重叠比例超出 0%–50% 或分隔符不受支持
- **THEN** 系统返回 HTTP 400，且不切换该材料当前可用索引

#### Scenario: 标题层级切分
- **WHEN** hierarchy 处理含 `#`、`##` 或 `###` 标题且章节过长的 Markdown 正文
- **THEN** 标题保留在对应章节切片内，过长章节继续按 auto 规则切分

#### Scenario: 预处理不修改原文
- **WHEN** custom 启用移除 URL/邮箱或折叠空白
- **THEN** 预处理只影响切分输入和嵌入内容，知识库原始正文不变，响应标明偏移基于处理后文本

### Requirement: 切片正文与向量必须分库存储并以同一主键关联
系统 SHALL 在关系数据库保存切片正文、班级、材料、文档、序号、字符区间和索引状态；SHALL 在 Qdrant `campusclaw_chunks` cosine collection 保存向量。向量 point ID MUST 等于切片 ID 和 payload `chunk_id`；payload SHALL 只含关联标识且 MUST NOT 含切片正文。嵌入模型向量维度 MUST 与 collection 一致。

#### Scenario: 切片嵌入成功
- **WHEN** 服务端成功切分并嵌入一条本班正文
- **THEN** 关系库含切片文本和偏移，Qdrant 含同 ID 向量及标识 payload，且 payload 不含正文

#### Scenario: 嵌入失败
- **WHEN** 嵌入网关超时、失败或返回错误维度
- **THEN** 原材料和原文仍保留，失败批次不成为可检索的 ready 索引，Qdrant 不保留可用的部分批次

### Requirement: 教师可以为本班材料安全重建索引
系统 SHALL 仅允许教师对活动班级内材料以本次请求指定的策略重建索引。成功切换新索引后 SHALL 删除旧切片与旧向量；失败时 MUST NOT 返回或混用半完成的新批次，也 MUST NOT 修改原始正文。

#### Scenario: 更换策略重建成功
- **WHEN** 本班教师对已有材料选择新策略并完成重建
- **THEN** 后续检索只使用新策略切片，旧切片和旧向量不再可查，原文保持不变

#### Scenario: 学生或跨班重建
- **WHEN** 学生请求重建或教师请求不属于其活动班级的材料
- **THEN** 服务端拒绝请求，且切片、向量和原文均无变化

#### Scenario: 重建中途失败
- **WHEN** 新批次在切分、嵌入或 Qdrant 写入阶段失败
- **THEN** 系统保留完整旧活动代次，或明确将材料索引标记为 failed，绝不暴露新旧混合的半批次

### Requirement: 系统必须提供三种语义明确的检索模式
系统 SHALL 提供 `keyword`、`vector`、`hybrid` 模式并默认使用 hybrid。keyword SHALL 只查询关系库全文索引；vector SHALL 嵌入问句、在 Qdrant 按班级过滤、丢弃 cosine 小于 0.35 的候选并回关系库取正文；hybrid SHALL 对两路各自过滤后的排名执行 `k = 60` 的 RRF，缺席的一路不贡献分数。系统 MUST NOT 直接相加全文相关度与 cosine 分数。

#### Scenario: 原词关键词检索
- **WHEN** 本班用户以原文中出现的词使用 keyword 模式
- **THEN** 系统仅访问关系库并按全文相关度返回命中，不调用嵌入网关或 Qdrant

#### Scenario: 语义改写向量检索
- **WHEN** 本班用户以表述不同但语义相近的问题使用 vector 模式
- **THEN** 系统按 cosine 降序保留不低于 0.35 的本班候选，并从关系库返回对应正文

#### Scenario: 混合排序
- **WHEN** hybrid 的两条路径分别产生过滤后的候选名次
- **THEN** 系统按每路 `1/(60+rank)` 之和排序，未出现在某路的切片在该路得零分

#### Scenario: 空或无效查询
- **WHEN** 查询去空白后为空、超过上限或包含控制字符
- **THEN** 系统返回 HTTP 400 且不调用嵌入、Qdrant或对话网关

#### Scenario: 向量依赖不可用
- **WHEN** Qdrant 或嵌入网关不可用
- **THEN** keyword 仍可正常检索，vector 与 hybrid 返回 HTTP 503 且不编造相似度或静默降级

### Requirement: 检索班级必须只来自认证上下文并在两条路径强制执行
系统 SHALL 只使用认证模块从数据库成员关系建立并逐请求复核的活动班级。查询参数、JSON 或请求头中的 `class_id` MUST NOT 改变检索范围。关键词 SQL、Qdrant 查询以及向量命中后的关系库回表 SHALL 分别使用同一个活动班级条件，且只返回 ready 切片与 ready 材料。

#### Scenario: 客户端伪造其他班级
- **WHEN** A 班用户在检索请求中携带 B 班 `class_id`
- **THEN** 系统丢弃该值并仍只检索 A 班，不返回 B 班标题、正文、分数或标识

#### Scenario: 向量库含异班候选
- **WHEN** Qdrant 意外返回一个不属于活动班级的 point ID
- **THEN** 关系库回表班级条件再次排除该切片，响应不泄露其内容或存在性

#### Scenario: 搜索其他班独有内容
- **WHEN** A 班用户搜索只存在于 B 班材料的内容
- **THEN** 系统返回 HTTP 200 与空 hits，而不是用 403 或 404 暗示 B 班资料存在

### Requirement: 每条检索结果必须可追溯至授权原材料
每条命中 SHALL 至少包含材料 ID、材料标题、切片 ID、切片序号、字符区间、取自关系库切片正文的摘录以及经过再次授权的材料链接。系统 MUST NOT 从 Qdrant payload 生成正文或向客户端返回向量。所有候选被过滤时 SHALL 返回 HTTP 200、空 `hits` 和固定文案“资料中未找到相关内容”。

#### Scenario: 命中结果溯源
- **WHEN** 本班用户的查询命中一个 ready 切片
- **THEN** 响应包含该切片的标题、序号、区间、关系库摘录和本班可授权打开的材料链接

#### Scenario: 无相关依据
- **WHEN** 所选模式在阈值与班级过滤后没有候选切片
- **THEN** 系统返回 HTTP 200、`hits: []` 和“资料中未找到相关内容”，不以低分候选凑数

### Requirement: 问答必须先检索且仅依据命中切片生成
`POST /api/ask` SHALL 仅以最新用户问题对活动班级执行 hybrid 检索并最多选择前 4 条。零命中时系统 SHALL 直接返回“资料中未找到相关内容”和空 citations，MUST NOT 调用对话网关。有命中时，对话网关 SHALL 只接收服务端指令、编号后的材料标题/切片序号/正文、最新问题及受限历史；MUST NOT 接收向量、其他班内容或客户端 system 消息。

#### Scenario: 有依据时生成回答
- **WHEN** 本班 hybrid 检索返回一个或多个切片
- **THEN** 系统按 citations 顺序以 `[1]`、`[2]` 编号上下文，生成简短回答并保证回答引用只指向返回的 citations

#### Scenario: 无依据时不调用模型
- **WHEN** 最新问题在本班没有命中切片
- **THEN** 系统返回 HTTP 200、固定文案和空 citations，对话网关不被调用

#### Scenario: 客户端注入 system 或班级
- **WHEN** 问答请求携带自定义 system 消息或其他班级 ID
- **THEN** 系统丢弃这些字段，检索范围和服务端提示均不被客户端改变

### Requirement: Qdrant 与模型网关必须保持服务端私有
浏览器 SHALL 只访问本站 HTTP 入口。Qdrant、嵌入网关、对话网关及上传目录 MUST NOT 作为公开静态资源或客户端可直连端口；模型密钥、向量和完整服务端提示 MUST NOT 出现在页面、API 响应或日志中。

#### Scenario: 检查容器入口
- **WHEN** 操作者启动 Compose 并查看宿主机端口
- **THEN** 仅本站 web 入口公开，Qdrant 与应用内部依赖没有宿主机端口映射

#### Scenario: 检查客户端与日志
- **WHEN** 用户执行检索或问答并检查页面源代码、网络响应和应用日志
- **THEN** 其中不包含模型密钥、向量分量、Qdrant 原始 point 或完整服务端提示
