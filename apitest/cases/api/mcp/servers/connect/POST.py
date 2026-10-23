
def run(ctx):
    path = f"/api/mcp/servers/{ctx['mcp_id']}/connect"
    assert ctx["student"].post(path, headers=ctx["student_headers"]).status_code == 403
    result = ctx["teacher"].post(path, headers=ctx["teacher_headers"])
    assert result.status_code == 200
    assert result.json["server"]["tools"][0]["name"] == "formula_hint"
    listed = ctx["student"].get(f"/api/mcp/servers/{ctx['mcp_id']}/tools", headers=ctx["student_headers"])
    assert listed.json["tools"][0]["name"] == "formula_hint"
