from campusclaw.models import ConversationMessage, db


def run(ctx):
    result = ctx["student"].post(f"/api/conversations/{ctx['conversation_id']}/messages",
                                  headers=ctx["student_headers"], json={"query": "代数方程解题步骤"})
    assert result.status_code == 200
    body = result.get_data(as_text=True)
    assert "event: meta" in body and "event: delta" in body and "event: done" in body
    with ctx["app"].app_context():
        rows = db.session.query(ConversationMessage).filter_by(conversation_id=ctx["conversation_id"]).all()
        assert [x.role for x in rows] == ["user", "assistant"]
        assert rows[1].content == "先列出已知条件。[1]"
    assert "先问：代数方程" in ctx["chat"].calls[0][0]["content"]
    assert "先分析，再提示下一步" in ctx["chat"].calls[0][0]["content"]
