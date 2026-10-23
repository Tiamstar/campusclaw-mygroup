import campusclaw.mcp as mcp


def run(ctx):
    path = f"/api/mcp/servers/{ctx['mcp_id']}/disconnect"
    result = ctx["teacher"].post(path, headers=ctx["teacher_headers"])
    assert result.status_code == 200 and result.json["server"]["tools"] == []
    rejected = ctx["teacher"].post("/api/skills", headers=ctx["teacher_headers"], json={
        "name": "断开的工具", "description": "不可绑定", "content": "test", "tools": ["formula_hint@campus_tools"]})
    assert rejected.status_code == 400
    mcp.rpc = ctx["original_rpc"]
