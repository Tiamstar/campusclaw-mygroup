from datetime import timedelta

import pytest
from sqlalchemy import select

from campusclaw import create_app
from campusclaw.models import LoginAttempt, LoginSession, User, db, utcnow
from conftest import class_ids, csrf, login


def test_missing_secret_rejected(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SECRET_KEY is required"):
        create_app()


def test_init_db_command_creates_schema_and_upload_directory(tmp_path):
    uploads = tmp_path / "uploads"
    application = create_app({
        "SECRET_KEY": "test-secret-not-for-deployment",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'fresh.db'}",
        "UPLOAD_DIR": str(uploads),
    })
    result = application.test_cli_runner().invoke(args=["init-db"])
    assert result.exit_code == 0, result.output
    assert uploads.is_dir()
    with application.app_context():
        assert "sessions" in db.metadata.tables
        assert db.session.execute(select(User)).scalars().all() == []


def test_seed_is_idempotent_and_passwords_are_hashed(app):
    with app.app_context():
        result = app.test_cli_runner().invoke(args=["seed-demo"])
        assert result.exit_code == 0
        users = db.session.execute(select(User)).scalars().all()
        assert len(users) == 3
        assert len(class_ids(app)) == 2
        assert all("test-password" not in user.password_hash for user in users)
        assert len({user.password_hash for user in users}) == 3


def test_login_authentication_logout_and_replay(app, client):
    assert client.post("/login", data={"username": "teacher_a", "password": "teacher-test-password"}).status_code == 400
    assert login(client, "teacher_a", "wrong").status_code == 401
    assert login(client, "unknown", "wrong").json == {"error": "invalid_credentials"}
    assert login(client, "teacher_a").status_code == 302
    cookie = client.get_cookie("session").value
    with app.app_context():
        stored = db.session.execute(select(LoginSession)).scalar_one()
        assert "auth_token" not in stored.token_digest
        assert len(stored.token_digest) == 64
    assert client.get("/").status_code == 200
    assert client.post("/logout").status_code == 400
    assert client.post("/logout", data={"csrf_token": csrf(client, "/")}).status_code == 302
    client.set_cookie("session", cookie)
    assert client.get("/api/classes/1/materials").status_code == 401


def test_unknown_account_and_wrong_password_use_same_check(app, client, monkeypatch):
    from campusclaw import auth as auth_module

    checked = []
    real_check = auth_module.check_password

    def record_check(stored, supplied):
        checked.append(stored)
        return real_check(stored, supplied)

    monkeypatch.setattr(auth_module, "check_password", record_check)
    unknown = login(client, "missing_account", "wrong")
    wrong = login(client, "teacher_a", "wrong")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json == wrong.json == {"error": "invalid_credentials"}
    assert len(checked) == 2
    assert checked[0] == app.extensions["dummy_password_hash"]


def test_failed_login_window_and_csrf(app, client):
    assert client.post("/login", data={"username": "teacher_a", "password": "wrong"}).status_code == 400
    for _ in range(5):
        assert login(client, "teacher_a", "wrong").status_code == 401
    with app.app_context():
        attempt = db.session.execute(select(LoginAttempt)).scalar_one()
        assert attempt.failed_count == 5
    assert login(client, "teacher_a").status_code == 401
    with app.app_context():
        attempt = db.session.execute(select(LoginAttempt)).scalar_one()
        attempt.window_start = utcnow() - timedelta(minutes=16)
        db.session.commit()
    assert login(client, "teacher_a").status_code == 302
    with app.app_context():
        assert db.session.execute(select(LoginAttempt)).scalars().all() == []


def test_students_login_and_cross_class_access(app, client):
    classes = class_ids(app)
    assert client.get(f"/classes/{classes['A班']}/materials").status_code == 302
    assert client.get(f"/api/classes/{classes['A班']}/materials").status_code == 401
    assert login(client, "student_b").status_code == 302
    assert client.get(f"/api/classes/{classes['A班']}/materials").status_code == 403
    assert client.get(f"/api/classes/{classes['B班']}/materials").status_code == 200


def test_page_navigation_and_login_feedback(app, client):
    classes = class_ids(app)
    login_page = client.get("/login")
    assert login_page.status_code == 200
    assert b"/static/app.css" in login_page.data
    assert b'name="csrf_token"' in login_page.data
    assert b'name="username"' in login_page.data
    failed = client.post("/login", data={
        "username": "student_a", "password": "wrong", "csrf_token": csrf(client),
    }, headers={"Accept": "text/html"})
    assert failed.status_code == 401
    assert b'role="alert"' in failed.data
    assert b'value="student_a"' in failed.data
    login(client, "student_a")
    home = client.get("/")
    assert home.status_code == 200
    assert f'/classes/{classes["A班"]}/materials'.encode() in home.data
    assert f'/classes/{classes["B班"]}/materials'.encode() not in home.data
    assert b'name="csrf_token"' in home.data
    materials = client.get(f'/classes/{classes["A班"]}/materials')
    assert materials.status_code == 200
    assert b"/static/app.css" in materials.data
    assert f'/classes/{classes["A班"]}/materials/upload'.encode() not in materials.data
    assert client.get(f'/classes/{classes["A班"]}/materials/upload').status_code == 403


def test_teacher_upload_page_assets(app, client):
    class_id = class_ids(app)["A班"]
    login(client, "teacher_a")
    response = client.get(f"/classes/{class_id}/materials/upload")
    assert response.status_code == 200
    assert f'/api/classes/{class_id}/materials'.encode() in response.data
    assert f'data-list-url="/classes/{class_id}/materials"'.encode() in response.data
    assert b'accept=".pdf,.txt,.md"' in response.data
    assert b'name="csrf_token"' in response.data
    assert b'data-login-url="/login"' in response.data
    assert client.get("/static/app.css").status_code == 200
    upload_script = client.get("/static/upload.js")
    assert upload_script.status_code == 200
    assert b"response.status === 401" in upload_script.data
    assert b"encodeURIComponent(window.location.pathname)" in upload_script.data


def test_expired_or_disabled_user_denied(app, client):
    classes = class_ids(app)
    login(client, "teacher_a")
    with app.app_context():
        record = db.session.execute(select(LoginSession)).scalar_one()
        record.expires_at = utcnow() - timedelta(seconds=1)
        db.session.commit()
    assert client.get(f"/api/classes/{classes['A班']}/materials").status_code == 401
    login(client, "teacher_a")
    with app.app_context():
        user = db.session.execute(select(User).where(User.username == "teacher_a")).scalar_one()
        user.is_active = False
        db.session.commit()
    assert client.get(f"/api/classes/{classes['A班']}/materials").status_code == 401


def test_cookie_and_safe_return_path(client):
    response = login(client, "teacher_a")
    first_cookie = client.get_cookie("session").value
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert "SameSite=Lax" in response.headers["Set-Cookie"]
    assert client.get("/login?next=https://evil.example/").status_code == 200
    client.get("/login?next=/classes/1/materials")
    with client.session_transaction() as session:
        token = session["csrf"]
    response = client.post("/login?next=/classes/1/materials", data={
        "username": "teacher_a", "password": "teacher-test-password", "csrf_token": token,
    })
    assert response.headers["Location"] == "/classes/1/materials"
    client.set_cookie("session", first_cookie)
    assert client.get("/api/classes/1/materials").status_code == 401


def test_sensitive_values_are_redacted_from_application_logs(app, monkeypatch, caplog):
    monkeypatch.setenv("SECRET_KEY", "unique-local-secret-for-log-test")
    monkeypatch.setenv("SEED_TEACHER_PASSWORD", "unique-teacher-password-for-log-test")
    with caplog.at_level("WARNING", logger=app.logger.name):
        app.logger.warning("secret_key=%s password=%s cookie=abc", "unique-local-secret-for-log-test", "unique-teacher-password-for-log-test")
    text = caplog.text
    assert "unique-local-secret-for-log-test" not in text
    assert "unique-teacher-password-for-log-test" not in text
    assert "cookie=abc" not in text
    assert "[REDACTED]" in text
