from io import BytesIO

from campusclaw.models import Skill, db


def run(ctx):
    assert ctx["student"].post("/api/skills", headers=ctx["student_headers"], json={}).status_code == 403
    response = ctx["teacher"].post("/api/skills", headers=ctx["teacher_headers"], data={
        "name": "分步引导", "description": "不直接给答案", "tools": '["knowledge_search"]',
        "file": (BytesIO("先分析，再提示下一步。".encode()), "guide.md")})
    assert response.status_code == 201
    ctx["skill_id"] = response.json["skill"]["id"]
    with ctx["app"].app_context():
        assert db.session.get(Skill, ctx["skill_id"]).content == "先分析，再提示下一步。"
