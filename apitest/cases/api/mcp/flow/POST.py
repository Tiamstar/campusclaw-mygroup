
def run(ctx):
    skill = ctx["teacher"].post("/api/skills", headers=ctx["teacher_headers"], json={
        "name": "MCP 解题", "description": "远端工具辅助", "content": "只提示下一步。",
        "tools": ["knowledge_search", "formula_hint@campus_tools"]})
    assert skill.status_code == 201
    conversation = ctx["student"].post("/api/conversations", headers=ctx["student_headers"], json={
        "app_key": "solver", "skill_id": skill.json["skill"]["id"]})
    assert conversation.status_code == 201
    cid = conversation.json["conversation"]["id"]
    response = ctx["student"].post(f"/api/conversations/{cid}/messages", headers=ctx["student_headers"],
                                   json={"query": "代数方程解题步骤"})
    assert '"status": "ok"' in response.get_data(as_text=True)
    audits = ctx["teacher"].get("/api/mcp/audits", headers=ctx["teacher_headers"]).json["audits"]
    assert audits[0]["tool"] == "formula_hint@campus_tools" and audits[0]["status"] == "ok"
