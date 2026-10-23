from flask import Blueprint, jsonify, render_template_string, url_for

api_docs = Blueprint("api_docs", __name__)

ENDPOINTS = [
    ("/api/login", "post", "登录并取得 Bearer 令牌", False, [200, 401]),
    ("/api/logout", "post", "撤销令牌", True, [200, 401]),
    ("/api/session/active-class", "post", "选择本人成员班级", True, [200, 400, 404]),
    ("/api/apps", "get", "列出内置 AI 应用", True, [200, 401]),
    ("/api/prompts", "get", "列出本班提示词", True, [200, 401]),
    ("/api/prompts", "post", "教师新增提示词", True, [201, 400, 403, 409]),
    ("/api/prompts/{prompt_id}", "put", "教师更新本班提示词", True, [200, 400, 403, 404]),
    ("/api/skills", "get", "列出内置与上传技能", True, [200, 401]),
    ("/api/skills", "post", "教师新增或上传 Markdown 技能", True, [201, 400, 403, 409]),
    ("/api/skills/{skill_id}", "put", "教师更新本班技能与工具绑定", True, [200, 400, 403, 404]),
    ("/api/retrieval/search", "post", "检索本班知识库", True, [200, 400, 503]),
    ("/api/ask", "post", "单次资料问答", True, [200, 400, 502, 503]),
    ("/api/conversations", "post", "创建会话", True, [201, 400, 404]),
    ("/api/conversations/{conversation_id}", "get", "查看本人会话", True, [200, 404]),
    ("/api/conversations/{conversation_id}/messages", "post", "发送问题并返回 SSE: meta/delta/done", True, [200, 400, 404]),
    ("/api/mcp/servers", "get", "列出本班 MCP 服务器及缓存工具", True, [200]),
    ("/api/mcp/servers", "post", "教师登记 MCP 服务器", True, [201, 400, 403, 409]),
    ("/api/mcp/servers/{server_id}/connect", "post", "教师握手并发现工具", True, [200, 403, 404, 502]),
    ("/api/mcp/servers/{server_id}/disconnect", "post", "教师断开并清空工具缓存", True, [200, 403, 404]),
    ("/api/mcp/servers/{server_id}/tools", "get", "查看缓存工具", True, [200, 404]),
    ("/api/mcp/audits", "get", "教师查看本班工具调用审计", True, [200, 403]),
]

REQUESTS = {
    "/api/login": {"username": "teacher_a", "password": "string"},
    "/api/session/active-class": {"class_id": 1},
    "/api/prompts": {"app_key": "solver", "name": "引导", "content": "先解释思路"},
    "/api/prompts/{prompt_id}": {"content": "先引导学生列出已知"},
    "/api/skills": {"name": "代数引导", "description": "下一步提示", "content": "只引导", "tools": ["knowledge_search"]},
    "/api/skills/{skill_id}": {"description": "下一步提示", "content": "只引导", "tools": ["knowledge_search"]},
    "/api/retrieval/search": {"query": "光合作用", "mode": "keyword"},
    "/api/ask": {"query": "光合作用是什么"},
    "/api/conversations": {"app_key": "solver", "prompt_id": None, "skill_id": None, "builtin_skill": "guide"},
    "/api/conversations/{conversation_id}/messages": {"query": "下一步怎么做"},
    "/api/mcp/servers": {"name": "campus_tools", "base_url": "http://mcp-demo:8090", "auth_token": "string"},
}

RESPONSES = {
    "/api/login": {"access_token": "<token>", "token_type": "Bearer", "expires_in": 28800},
    "/api/apps": {"apps": [{"key": "solver", "name": "解题助手"}]},
    "/api/prompts": {"prompts": [{"id": 1, "app_key": "solver", "name": "引导", "content": "先解释思路"}]},
    ("/api/prompts", "post"): {"prompt": {"id": 1, "app_key": "solver", "name": "引导", "content": "先解释思路"}},
    ("/api/prompts/{prompt_id}", "put"): {"prompt": {"id": 1, "app_key": "solver", "name": "引导", "content": "先解释思路"}},
    "/api/skills": {"skills": [{"key": "guide", "name": "解题引导", "builtin": True,
                                  "content": "先给下一步", "tools": ["knowledge_search"]}]},
    ("/api/skills", "post"): {"skill": {"id": 1, "name": "代数引导", "description": "下一步提示",
                                          "content": "只引导", "tools": ["knowledge_search"], "builtin": False}},
    ("/api/skills/{skill_id}", "put"): {"skill": {"id": 1, "name": "代数引导", "description": "下一步提示",
                                                "content": "只引导", "tools": ["knowledge_search"], "builtin": False}},
    "/api/retrieval/search": {"mode": "keyword", "hits": [{"chunk_id": 1, "title": "lesson.md",
                                                      "excerpt": "课程正文"}], "message": None},
    "/api/ask": {"answer": "课程答案。[1]", "citations": [{"chunk_id": 1, "title": "lesson.md"}]},
    "/api/conversations": {"conversation": {"id": 1, "app_key": "solver", "prompt_id": None,
                                              "skill_id": None, "builtin_skill": "guide"}},
    "/api/conversations/{conversation_id}": {"conversation": {"id": 1, "app_key": "solver"},
                                               "messages": [{"role": "user", "content": "问题"}]},
    "/api/mcp/servers": {"servers": [{"id": 1, "name": "campus_tools", "connected": True,
                                      "base_url": "http://mcp-demo:8090", "tools": [{"name": "formula_hint"}]}]},
    ("/api/mcp/servers", "post"): {"server": {"id": 1, "name": "campus_tools", "connected": False,
                                               "base_url": "http://mcp-demo:8090", "tools": []}},
    "/api/mcp/servers/{server_id}/connect": {"server": {"id": 1, "name": "campus_tools",
                                                        "connected": True, "tools": [{"name": "formula_hint"}]}},
    "/api/mcp/servers/{server_id}/disconnect": {"server": {"id": 1, "name": "campus_tools",
                                                           "connected": False, "tools": []}},
    "/api/mcp/servers/{server_id}/tools": {"tools": [{"name": "formula_hint"}]},
    "/api/mcp/audits": {"audits": [{"tool": "formula_hint@campus_tools", "status": "ok",
                                    "user_id": 2, "created_at": "2026-10-23T00:00:00Z"}]},
}


@api_docs.get("/openapi.json")
def openapi():
    paths = {}
    for path, method, summary, secured, codes in ENDPOINTS:
        operation = {"summary": summary, "security": [{"BearerAuth": []}] if secured else [],
                     "responses": {str(code): {"description": "成功" if code < 300 else "错误",
                        "content": {"application/json": {"schema": {"type": "object",
                            "example": RESPONSES.get((path, method), RESPONSES.get(path, {}))
                            if code < 300 else {"error": "error_code"}}}}}
                        for code in codes}}
        if "{" in path:
            name = next(x.split("}")[0] for x in path.split("{")[1:])
            operation["parameters"] = [{"name": name, "in": "path", "required": True,
                                        "schema": {"type": "integer"}}]
        if method in ("post", "put") and path in REQUESTS:
            operation["requestBody"] = {"required": True, "content": {"application/json": {
                "schema": {"type": "object", "example": REQUESTS[path]}}}}
        if path == "/api/skills" and method == "post":
            operation["requestBody"]["content"]["multipart/form-data"] = {"schema": {
                "type": "object", "properties": {"name": {"type": "string"}, "description": {"type": "string"},
                "file": {"type": "string", "format": "binary"}, "tools": {"type": "string", "example": '["knowledge_search"]'}}}}
        if path.endswith("/messages"):
            operation["responses"]["200"]["content"] = {"text/event-stream": {"schema": {"type": "string",
                "example": 'event: meta\\ndata: {"citations":[],"tool_calls":[]}\\n\\nevent: delta\\ndata: {"content":"答案"}\\n\\nevent: done\\ndata: {"status":"ok"}\\n\\n'}}}
        paths.setdefault(path, {})[method] = operation
    return jsonify({"openapi": "3.0.3", "info": {"title": "CampusClaw API", "version": "1.0"},
                    "components": {"securitySchemes": {"BearerAuth": {"type": "http", "scheme": "bearer"}}},
                    "paths": paths})


@api_docs.get("/docs")
def swagger():
    return render_template_string("""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>CampusClaw Swagger</title><link rel="stylesheet" href="{{ css }}">
<div id="swagger-ui"></div><script src="{{ js }}"></script>
<script>SwaggerUIBundle({url:'/openapi.json',dom_id:'#swagger-ui',persistAuthorization:true})</script></html>""",
        css=url_for("static", filename="swagger-ui.css"),
        js=url_for("static", filename="swagger-ui-bundle.js"))
