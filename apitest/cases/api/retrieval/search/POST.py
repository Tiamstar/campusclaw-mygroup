from io import BytesIO

from campusclaw.models import KnowledgeChunk, db


def run(ctx):
    response = ctx["teacher"].post(f"/api/classes/{ctx['classes']['A班']}/materials",
        headers=ctx["teacher_headers"], data={"file": (BytesIO("代数方程解题步骤：先列出已知条件。".encode()), "algebra.md")})
    assert response.status_code == 201
    result = ctx["student"].post("/api/retrieval/search", headers=ctx["student_headers"],
                                  json={"query": "代数方程解题步骤", "mode": "keyword", "class_id": ctx["classes"]["B班"]})
    assert result.status_code == 200 and result.json["hits"]
    with ctx["app"].app_context():
        assert db.session.get(KnowledgeChunk, result.json["hits"][0]["chunk_id"]).class_id == ctx["classes"]["A班"]
