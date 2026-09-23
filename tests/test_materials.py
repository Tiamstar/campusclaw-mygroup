import os
import uuid
from io import BytesIO
from datetime import timedelta

from sqlalchemy import text

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select

from campusclaw.models import ClassMembership, KnowledgeDocument, Material, User, db, utcnow
from campusclaw import create_app
from conftest import class_ids, csrf, login


def upload(client, target_class_id, name="notes.md", content=b"# Lesson\n", token=None, **fields):
    if token is None:
        token = csrf(client, f"/classes/{target_class_id}/materials/upload")
    return client.post(f"/api/classes/{target_class_id}/materials", data={
        "csrf_token": token,
        "file": (BytesIO(content), name),
        **fields,
    })


def pdf_bytes():
    buffer = BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=100)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
    })
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 20 50 Td (Photosynthesis lesson) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    writer.write(buffer)
    return buffer.getvalue()


def test_teacher_upload_and_class_scoped_read(app, client):
    classes = class_ids(app)
    own_class, other_class = classes["A班"], classes["B班"]
    login(client, "teacher_a")
    for name, content in (("讲义.md", "# 学习资料".encode()), ("notes.txt", b"hello"), ("paper.pdf", pdf_bytes())):
        response = upload(client, own_class, name, content)
        assert response.status_code == 201, response.json
    own_list = client.get(f"/api/classes/{own_class}/materials").json["materials"]
    assert len(own_list) == 3
    material_id = own_list[0]["id"]
    with app.app_context():
        records = db.session.execute(select(Material)).scalars().all()
        documents = db.session.execute(select(KnowledgeDocument)).scalars().all()
        assert len(records) == len(documents) == 3
        assert {record.id for record in records} == {document.material_id for document in documents}
        assert all(record.class_id == own_class and record.status == "ready" for record in records)
        assert all(document.body.strip() for document in documents)
    assert client.get(f"/api/classes/{other_class}/materials").status_code == 403
    assert client.get(f"/api/classes/{other_class}/materials/{material_id}").status_code == 403
    assert client.get(f"/api/classes/{own_class}/materials/999999").status_code == 404
    download = client.get(f"/classes/{own_class}/materials/{material_id}/download")
    assert download.status_code == 200
    assert download.headers["Content-Disposition"].startswith("attachment;")
    assert download.headers["X-Content-Type-Options"] == "nosniff"
    assert client.get(f"/classes/{other_class}/materials/{material_id}/download").status_code == 403


def test_student_cannot_upload_even_without_csrf(app, client):
    classes = class_ids(app)
    login(client, "student_a")
    response = upload(client, classes["A班"], token="invalid", role="teacher")
    assert response.status_code == 403
    with app.app_context():
        assert db.session.query(Material).count() == 0
        assert db.session.query(KnowledgeDocument).count() == 0
        assert db.session.execute(text("SELECT COUNT(*) FROM knowledge_fts")).scalar_one() == 0
    assert not os.listdir(app.config["UPLOAD_DIR"])


def test_teacher_cross_class_and_csrf_rejected(app, client):
    classes = class_ids(app)
    login(client, "teacher_a")
    assert upload(client, classes["B班"]).status_code == 403
    assert upload(client, classes["A班"], token="invalid").status_code == 400
    assert upload(client, classes["A班"], class_id=str(classes["B班"])).status_code == 403
    with app.app_context():
        assert db.session.query(Material).count() == 0
    assert not os.listdir(app.config["UPLOAD_DIR"])


def test_guest_upload_without_csrf_is_unauthorized(app, client):
    class_id = class_ids(app)["A班"]
    assert upload(client, class_id, token="").status_code == 401
    assert not os.listdir(app.config["UPLOAD_DIR"])


def test_upload_validation_and_cleanup(app, client):
    class_id = class_ids(app)["A班"]
    login(client, "teacher_a")
    for name, content in (
        ("empty.md", b""), ("bad.pdf", b"%PDF-fake\n%%EOF"),
        ("blank.pdf", _blank_pdf_bytes()),
        ("bad.md", b"\xff"), ("not-text.txt", b"PK\x03\x04hello"),
        ("slides.pptx", b"slides"), ("bad.md", b"abc\x00def"),
    ):
        assert upload(client, class_id, name, content).status_code == 400
    assert upload(client, class_id, "big.md", b"x" * (10 * 1024 * 1024 + 1)).status_code == 413
    assert upload(client, class_id, "too-large-request.md", b"x" * (11 * 1024 * 1024)).status_code == 413
    assert upload(client, class_id, "a" * 256 + ".md", b"# Lesson").status_code == 400
    assert upload(client, class_id, "..\\folder\\lesson.md", b"# Lesson").status_code == 201
    with app.app_context():
        record = db.session.execute(select(Material)).scalar_one()
        assert record.original_name == "lesson.md"
        assert "/" not in record.stored_name


def test_list_visible_to_same_class_student_and_membership_revocation(app, client):
    class_id = class_ids(app)["A班"]
    login(client, "teacher_a")
    material_id = upload(client, class_id).json["material"]["id"]
    student = app.test_client()
    login(student, "student_a")
    assert any(item["id"] == material_id for item in student.get(f"/api/classes/{class_id}/materials").json["materials"])
    with app.app_context():
        user = db.session.execute(select(User).where(User.username == "student_a")).scalar_one()
        membership = db.session.execute(select(ClassMembership).where(ClassMembership.user_id == user.id)).scalar_one()
        db.session.delete(membership)
        db.session.commit()
    assert student.get(f"/classes/{class_id}/materials/{material_id}/download").status_code == 403
    other = app.test_client()
    login(other, "student_b")
    assert other.get(f"/api/classes/{class_ids(app)['B班']}/materials").json["materials"] == []


def test_health_without_login_and_storage_failure(app, client):
    assert client.get("/health").json == {"status": "ok"}
    upload_dir = app.config["UPLOAD_DIR"]
    os.rmdir(upload_dir)
    assert client.get("/health").status_code == 503


def test_health_when_database_unavailable(app, client, monkeypatch):
    with app.app_context():
        def fail_query(statement):
            raise RuntimeError("connection unavailable")

        with monkeypatch.context() as patch:
            patch.setattr(db.session, "execute", fail_query)
            assert client.get("/health").status_code == 503
            assert "connection unavailable" not in client.get("/health").get_data(as_text=True)


def test_multiple_class_membership_uses_selected_url(app, client):
    classes = class_ids(app)
    with app.app_context():
        teacher = db.session.execute(select(User).where(User.username == "teacher_a")).scalar_one()
        db.session.add(ClassMembership(user_id=teacher.id, class_id=classes["B班"]))
        db.session.commit()
    login(client, "teacher_a")
    assert upload(client, classes["A班"]).status_code == 201
    assert upload(client, classes["B班"]).status_code == 201
    with app.app_context():
        assert {record.class_id for record in db.session.execute(select(Material)).scalars()} == set(classes.values())


def test_upload_transaction_failure_cleans_file(app, client, monkeypatch):
    class_id = class_ids(app)["A班"]
    login(client, "teacher_a")
    with app.app_context():
        def fail_commit():
            raise RuntimeError("database write failed")

        with monkeypatch.context() as patch:
            patch.setattr(db.session, "commit", fail_commit)
            try:
                response = upload(client, class_id)
            except RuntimeError:
                pass
            else:
                assert response.status_code == 500
        assert db.session.query(Material).count() == 0
        assert db.session.query(KnowledgeDocument).count() == 0
        assert db.session.execute(text("SELECT COUNT(*) FROM knowledge_fts")).scalar_one() == 0
    assert not os.listdir(app.config["UPLOAD_DIR"])


def test_cleanup_only_old_unreferenced_uploads(app):
    uploads = app.config["UPLOAD_DIR"]
    orphan = os.path.join(uploads, f"{uuid.uuid4().hex}.md")
    unrelated = os.path.join(uploads, "keep-this.txt")
    for path in (orphan, unrelated):
        with open(path, "wb") as output:
            output.write(b"test")
        old_time = (utcnow() - timedelta(hours=25)).timestamp()
        os.utime(path, (old_time, old_time))
    with app.app_context():
        result = app.test_cli_runner().invoke(args=["cleanup-orphans"])
        assert result.exit_code == 0
    assert not os.path.exists(orphan)
    assert os.path.exists(unrelated)


def _blank_pdf_bytes():
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(buffer)
    return buffer.getvalue()


def test_knowledge_search_body_source_and_isolation(app, client):
    classes = class_ids(app)
    own_class, other_class = classes["A班"], classes["B班"]
    login(client, "teacher_a")
    material_id = upload(client, own_class, "植物.md", "# 光合作用\n<script>alert(1)</script>".encode()).json["material"]["id"]
    pdf_id = upload(client, own_class, "lesson.pdf", pdf_bytes()).json["material"]["id"]
    student = app.test_client()
    login(student, "student_a")
    url = f"/api/classes/{own_class}/knowledge/search?q=光合作用"
    response = student.get(url)
    assert response.status_code == 200
    assert len(response.json["results"]) == 1
    source = response.json["results"][0]
    assert source["material_id"] == material_id
    assert source["download_url"] == f"/classes/{own_class}/materials/{material_id}/download"
    assert "光合作用" in source["excerpt"]
    assert student.get(source["download_url"]).status_code == 200
    assert student.get(f"/api/classes/{own_class}/knowledge/search?q=光合").json["results"][0]["material_id"] == material_id
    assert student.get(f"/api/classes/{own_class}/knowledge/search?q=Photosynthesis").json["results"][0]["material_id"] == pdf_id
    detail = student.get(f"/api/classes/{own_class}/knowledge/documents/{source['document_id']}")
    assert "<script>" in detail.json["document"]["body"]
    page = student.get(source["detail_url"])
    assert b"&lt;script&gt;" in page.data
    assert b"<script>alert(1)</script>" not in page.data
    assert student.get(f"/api/classes/{other_class}/knowledge/search?q=光合作用").status_code == 403
    other = app.test_client()
    login(other, "student_b")
    assert other.get(f"/api/classes/{other_class}/knowledge/documents/{source['document_id']}").status_code == 404
    assert other.get(f"/api/classes/{other_class}/knowledge/search?q=光合作用").json["results"] == []
    assert other.get(source["download_url"]).status_code == 403
    for query in ("", "a" * 101, "hi%0Abad", "hi%0A"):
        assert student.get(f"/api/classes/{own_class}/knowledge/search?q={query}").status_code == 400
    assert student.get(f"/classes/{own_class}/knowledge/search?q=").status_code == 400
    assert student.get(f"/classes/{own_class}/knowledge/search").status_code == 200
    assert app.test_client().get(f"/api/classes/{own_class}/knowledge/search?q=光合作用").status_code == 401
    for query in ('"""', "OR *", "a' OR 1=1 --"):
        assert student.get(f"/api/classes/{own_class}/knowledge/search", query_string={"q": query}).status_code == 200
    with app.app_context():
        user = db.session.execute(select(User).where(User.username == "student_a")).scalar_one()
        membership = db.session.execute(select(ClassMembership).where(ClassMembership.user_id == user.id)).scalar_one()
        db.session.delete(membership)
        db.session.commit()
    assert student.get(url).status_code == 403
    assert student.get(source["detail_url"]).status_code == 403


def test_existing_database_backfills_text_without_losing_session(tmp_path, monkeypatch):
    monkeypatch.setenv("SEED_TEACHER_PASSWORD", "teacher-test-password")
    monkeypatch.setenv("SEED_STUDENT_PASSWORD", "student-test-password")
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    application = create_app({
        "SECRET_KEY": "test-secret-not-for-deployment",
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'existing.db'}",
        "UPLOAD_DIR": str(uploads),
    })
    with application.app_context():
        db.create_all()
        db.session.execute(text("ALTER TABLE knowledge_documents DROP COLUMN body"))
        db.session.commit()
        assert application.test_cli_runner().invoke(args=["seed-demo"]).exit_code == 0
        class_id = class_ids(application)["A班"]
        teacher = db.session.execute(select(User).where(User.username == "teacher_a")).scalar_one()
        material = Material(class_id=class_id, uploaded_by=teacher.id, original_name="旧讲义.md", stored_name="legacy.md", status="ready")
        db.session.add(material)
        db.session.flush()
        db.session.execute(text(
            "INSERT INTO knowledge_documents (material_id, class_id, title, stored_name, created_at) "
            "VALUES (:material_id, :class_id, :title, :stored_name, :created_at)"
        ), {"material_id": material.id, "class_id": class_id, "title": "旧讲义.md", "stored_name": "legacy.md", "created_at": utcnow().isoformat(sep=" ")})
        blank = Material(class_id=class_id, uploaded_by=teacher.id, original_name="旧扫描.pdf", stored_name="legacy.pdf", status="ready")
        db.session.add(blank)
        db.session.flush()
        blank_id = blank.id
        db.session.execute(text(
            "INSERT INTO knowledge_documents (material_id, class_id, title, stored_name, created_at) "
            "VALUES (:material_id, :class_id, :title, :stored_name, :created_at)"
        ), {"material_id": blank.id, "class_id": class_id, "title": "旧扫描.pdf", "stored_name": "legacy.pdf", "created_at": utcnow().isoformat(sep=" ")})
        db.session.commit()
        (uploads / "legacy.md").write_text("旧材料的光合作用", encoding="utf-8")
        (uploads / "legacy.pdf").write_bytes(_blank_pdf_bytes())
    student = application.test_client()
    assert login(student, "student_a").status_code == 302
    for _ in range(2):
        result = application.test_cli_runner().invoke(args=["init-db"])
        assert result.exit_code == 0, result.output
    response = student.get(f"/api/classes/{class_id}/knowledge/search?q=光合作用")
    assert response.status_code == 200
    assert len(response.json["results"]) == 1
    with application.app_context():
        documents = db.session.execute(select(KnowledgeDocument)).scalars().all()
        assert len(documents) == 2
        assert {document.title: document.body for document in documents} == {"旧讲义.md": "旧材料的光合作用", "旧扫描.pdf": ""}
        assert db.session.execute(text("SELECT COUNT(*) FROM knowledge_fts")).scalar_one() == 2
    assert (uploads / "legacy.md").exists()
    assert student.get(f"/classes/{class_id}/materials/{blank_id}/download").status_code == 200


def test_database_schema_enforces_relationships(app):
    with app.app_context():
        assert db.session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        indexes = db.session.execute(text("PRAGMA index_list('materials')")).all()
        assert any("ix_materials_class_status_created" in index.name for index in indexes)
        with db.engine.begin() as connection:
            memberships = connection.execute(text("SELECT user_id, class_id FROM class_memberships LIMIT 1")).first()
            try:
                connection.execute(text("INSERT INTO class_memberships (user_id, class_id) VALUES (:user_id, :class_id)"), {
                    "user_id": memberships.user_id, "class_id": memberships.class_id,
                })
            except IntegrityError:
                pass
            else:
                raise AssertionError("duplicate membership was accepted")
            try:
                connection.execute(text("INSERT INTO class_memberships (user_id, class_id) VALUES (999999, :class_id)"), {
                    "class_id": memberships.class_id,
                })
            except IntegrityError:
                pass
            else:
                raise AssertionError("missing user foreign key was accepted")
