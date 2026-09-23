import pytest

from campusclaw import create_app
from campusclaw.models import Class, db
from campusclaw.knowledge import initialize_knowledge_index


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("SEED_TEACHER_PASSWORD", "teacher-test-password")
    monkeypatch.setenv("SEED_STUDENT_PASSWORD", "student-test-password")
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    application = create_app({
        "SECRET_KEY": "test-secret-not-for-deployment",
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
        "UPLOAD_DIR": str(uploads),
    })
    with application.app_context():
        db.create_all()
        initialize_knowledge_index()
        result = application.test_cli_runner().invoke(args=["seed-demo"])
        assert result.exit_code == 0, result.output
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client, path="/login"):
    client.get(path)
    with client.session_transaction() as session:
        return session["csrf"]


def login(client, username, password=None):
    password = password or ("teacher-test-password" if username.startswith("teacher") else "student-test-password")
    return client.post("/login", data={
        "username": username,
        "password": password,
        "csrf_token": csrf(client),
    })


def class_ids(app):
    with app.app_context():
        return {record.name: record.id for record in db.session.query(Class).all()}
