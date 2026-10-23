from campusclaw.models import PromptTemplate, db


def run(ctx):
    assert ctx["student"].post("/api/prompts", headers=ctx["student_headers"], json={}).status_code == 403
    response = ctx["teacher"].post("/api/prompts", headers=ctx["teacher_headers"],
                                   json={"app_key": "solver", "name": "引导", "content": "先问：{{question}}"})
    assert response.status_code == 201
    ctx["prompt_id"] = response.json["prompt"]["id"]
    with ctx["app"].app_context():
        assert db.session.get(PromptTemplate, ctx["prompt_id"]).content == "先问：{{question}}"
