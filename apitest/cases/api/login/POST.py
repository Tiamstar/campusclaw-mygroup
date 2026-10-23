from campusclaw.models import LoginSession, db


def run(ctx):
    for role, username, password in (("teacher", "teacher_a", "teacher-test-password"),
                                     ("student", "student_a", "student-test-password")):
        response = ctx[role].post("/api/login", json={"username": username, "password": password})
        assert response.status_code == 200 and response.json["token_type"] == "Bearer"
        ctx[role + "_headers"] = {"Authorization": "Bearer " + response.json["access_token"]}
    assert ctx["student"].post("/api/login", json={"username": "student_a", "password": "wrong"}).status_code == 401
    with ctx["app"].app_context():
        assert db.session.query(LoginSession).count() == 2
