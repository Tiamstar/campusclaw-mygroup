import campusclaw.mcp as mcp
from campusclaw.models import MCPServer, db


def run(ctx):
    assert ctx["student"].post("/api/mcp/servers", headers=ctx["student_headers"], json={}).status_code == 403
    response = ctx["teacher"].post("/api/mcp/servers", headers=ctx["teacher_headers"], json={
        "name": "campus_tools", "base_url": "http://mcp-demo:8090", "auth_token": "apitest-token"})
    assert response.status_code == 201 and "apitest-token" not in response.get_data(as_text=True)
    ctx["mcp_id"] = response.json["server"]["id"]
    with ctx["app"].app_context():
        assert db.session.get(MCPServer, ctx["mcp_id"]).auth_token == "apitest-token"
    ctx["original_rpc"] = mcp.rpc
    def fake_rpc(server, method, params=None):
        if method == "initialize": return {"protocolVersion": "2025-03-26"}
        if method == "tools/list": return {"tools": [{"name": "formula_hint", "description": "提示"}]}
        if method == "tools/call": return {"content": [{"type": "text", "text": "先列式。"}]}
        raise ValueError(method)
    mcp.rpc = fake_rpc
