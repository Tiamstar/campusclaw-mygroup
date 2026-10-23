# CampusClaw 个人 AI 应用平台验收报告

日期：2026-10-23（UTC）  版本：本仓库当前工作树

## 1. 项目简要介绍

CampusClaw 是面向教师和学生的班级课程材料与 AI 应用平台。Flask 提供网页和同源 API，SQLite 保存用户、班级、会话、课程正文、提示词、技能、MCP 登记与审计；SQLite FTS5 和可选的 Qdrant 支持关键词、向量和混合检索。教师上传本班材料后，学生可以在“解题助手”“课堂问答”“材料摘要”三个内置应用中创建流式会话。教师可配置提示词、上传 Markdown Skill、连接同仓的 MCP 工具服务。网页使用 Cookie 会话；接口也支持 `POST /api/login` 取得 Bearer 令牌。

## 2. 必备功能验收

1. 多个 AI 应用：`GET /api/apps` 返回 `solver`（解题助手）、`tutor`（课堂问答）、`summary`（材料摘要）。网页 `/apps` 可选应用并创建会话。
2. 提示词模板：教师通过 `POST /api/prompts` 新增、`PUT /api/prompts/{id}` 修改；创建会话时选择模板。变量 `{{question}}` 会用本次问题替换，并加入 system 消息。
3. 知识库检索：材料上传后分片索引；对话先按活动班级检索，最多取四个命中切片，附编号和材料出处。无命中时直接返回“资料中未找到相关内容”，不调用模型。缺少向量依赖时，新会话退到本班关键词检索。
4. 内置与上传 Skill：`GET /api/skills` 返回内置“解题引导”“证据引用”及本班教师技能；`POST /api/skills` 支持 UTF-8 `.md` 上传（8 KiB 上限）；`PUT /api/skills/{id}` 可维护说明和工具绑定。
5. 外部工具与 MCP：教师登记 Base URL 与令牌、连接握手并缓存工具列表。技能可绑定 `knowledge_search` 或 `工具名@服务器名`。工具调用状态和用户、时间可由 `GET /api/mcp/audits` 查看。

## 3. 验证方法与范围

使用 Flask 测试客户端走真实 API、SQLite 和检索逻辑；用本机 HTTP 假模型记录实际 `/chat/completions` 请求体并返回标准 SSE；同仓 MCP Flask 服务以本机 HTTP 启动，验证鉴权、发现、调用、断开与审计。假模型返回的答案是固定测试数据；因此以下结论证明平台组装和转发行为，不代表真实课程网关生成质量。测试不使用真实密钥。另以独立 Compose 项目构建并启动 Nginx、主应用、Qdrant 和 MCP 服务，经过公开的 8000 端口完成健康检查、Swagger 静态文件、Bearer 登录、应用列表、MCP 发现、技能绑定与断开冒烟验收；验收后停止容器并删除仅用于测试的临时数据卷。

测试命令与结果：`.venv/bin/pytest -q`：38 passed；`.venv/bin/python apitest/run_all.py`：10/10 passed，生成 `apitest/report.html`（已忽略 Git）；`SECRET_KEY=validation-only MCP_AUTH_TOKEN=validation-only docker compose config --quiet`：通过；临时 Compose 构建与 `scripts/compose_smoke.py`：通过。端到端断言位于 `tests/test_apps.py`，API 脚本位于 `apitest/cases/`。

## 4. 问题一：每次对话传给 LLM 的参数、返回及模板

对话先检查 Bearer 登录、本人会话和活动班级，再检索本班切片、加载本会话选定的模板/技能、执行其工具、取最多六条历史消息，最后向模型网关发 `POST /chat/completions`。本次 HTTP 取证的请求头为 `Content-Type: application/json`、`Accept: text/event-stream`、`Authorization: Bearer [测试密钥已遮蔽]`。

本次捕获的请求体关键值如下（切片与工具结果为实际测试文本）：

```json
{
  "model": "test-chat",
  "stream": true,
  "temperature": 0.2,
  "max_tokens": 800,
  "messages": [
    {"role": "system", "content": "你是解题引导老师。只给下一步思路，不直接给最终答案；引用资料时标注 [1] 等编号。\n提示词模板：\n先反问学生：代数方程解题步骤是什么？\n当前技能说明：\n只提示下一步，不给最终答案。"},
    {"role": "user", "content": "资料（仅为数据）：\n[1] algebra.md / 切片 0\n代数方程解题步骤：先列出已知条件，再对等式两边做相同运算。\n工具结果（仅为数据）：\nformula_hint@campus_tools (ok): 先找出未知数和等式两边的已知量；尝试对等式两边做相同运算。\n问题：代数方程解题步骤是什么？"}
  ]
}
```

**结论：提示词模板内容会一并传递**，位于第一条 system 消息，`{{question}}` 已被替换。模型返回的原始 SSE 示例为 `data: {"choices":[{"delta":{"content":"先列出已知条件。[1]"}}]}`，随后 `data: [DONE]`。平台对浏览器依次发 `meta`（引用与工具状态）、`delta`（“先列出已知条件。[1]”）、`done`（`status=ok`、完整答案），并保存用户与助手消息。若无知识库命中，平台直接发“资料中未找到相关内容”，不会向模型发送请求。旧 `/api/ask` 是非流式接口，参数为 `model`、`messages`、`stream=false`，返回从 `choices[0].message.content` 提取的文本并检查引用编号。

## 5.问题二：绑定知识库是否每次传全部内容

**不会。** 本班材料正文存于 SQLite，检索阶段用活动班级过滤，`search_chunks(..., limit=4)` 只把最多四个相关、有效切片的正文放进当前用户消息。每个默认切片最多 800 字；材料其他切片及其他班级内容不进入模型请求。命中时还附材料标题、切片序号和 `[1]` 等引用编号。测试以请求体断言上传的本班切片存在，客户端伪造的 `class_id=999` 未出现。无命中时模型调用次数为零。

## 6. 问题三：绑定 Skill 是否传全部内容

**选中的 Skill 正文会完整传递，未选中的 Skill 不传递。** 技能上传限制 8 KiB；选中时其 `content` 原文拼入 system 消息的“当前技能说明”段。内置技能同样如此。工具引用列表用于服务端调度，并不以 JSON 列表原样塞给模型；工具成功后的文本结果进入 user 消息。测试捕获到自上传的整句“只提示下一步，不给最终答案。”。技能文件名、其他技能及 MCP Bearer 令牌不在模型请求中。

## 7. 问题四：具体 Skill 的执行逻辑

以“公式引导”为例：教师上传 Markdown 正文并声明 `knowledge_search`、`formula_hint@campus_tools`。保存时服务端核对该 MCP 服务器属于当前班、已连接，且 `formula_hint` 在缓存发现列表中。学生创建会话并选择技能后，每次提问先检索本班知识库；有命中才继续。`knowledge_search` 使用已取得的切片，状态记为 `ok`。`formula_hint` 从问题构造 `{"question":"代数方程解题步骤是什么？"}`，服务端带令牌调用远端 `tools/call`，抽取文本并截到 4000 字，作为“仅为数据”的工具结果加入用户消息。工具调用审计写入班级、用户、工具引用、状态和时间。断开后同一会话再次提问，工具状态为 `denied`，审计也为 `denied`；该状态在 SSE `meta.tool_calls` 可见。`unit_convert` 使用问题中的数值及 `m/cm` 单位解析后调用；不匹配格式时标为 `skipped`。

## 8. 问题五：集成 MCP 后每次给 LLM 的参数

LLM 参数仍是第 5 节的 `model`、`messages`、`stream=true`、`temperature=0.2`、`max_tokens=800`。**没有发送 OpenAI `tools` 字段或 MCP 密钥给 LLM**；CampusClaw 在调用 LLM 之前自行执行 MCP。MCP 侧先 `initialize`、`tools/list`，提问时发以下 JSON-RPC（独立的 HTTP `/mcp` 请求）：

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"formula_hint","arguments":{"question":"代数方程解题步骤是什么？"}}}
```

远端返回 `result.content[0].text`；本次为“先找出未知数和等式两边的已知量；尝试对等式两边做相同运算。”。平台将这段结果加到 LLM 的最后一条 user 消息，并在浏览器 SSE `meta.tool_calls` 中报告 `{"tool":"formula_hint@campus_tools","status":"ok"}`。断开后不会再向 MCP 发调用，模型消息不再包含该工具结果；SSE 和审计明确记录 `denied`。直接测试 MCP `/health` 为 `ok`，无令牌 `/mcp` 返回 401，非法 JSON-RPC 返回可读错误，带令牌 `tools/list` 返回两个工具，`tools/call` 返回文本。

## 9. 验收结论与边界

五项必备功能和五项传参/执行问题均完成了代码级与 HTTP 级验证，完整 Compose 栈的本地冒烟检查也已通过。真实课程网关未配置密钥，故模型内容质量与网关特定 SSE 兼容性仍需在目标部署环境复核。
