from campusclaw.models import Conversation, db


def run(ctx):
    response = ctx["student"].post("/api/conversations", headers=ctx["student_headers"], json={
        "app_key": "solver", "prompt_id": ctx["prompt_id"], "skill_id": ctx["skill_id"]})
    assert response.status_code == 201
    ctx["conversation_id"] = response.json["conversation"]["id"]
    with ctx["app"].app_context():
        assert db.session.get(Conversation, ctx["conversation_id"]).class_id == ctx["classes"]["A班"]
