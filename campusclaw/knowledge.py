from io import BytesIO
from pathlib import Path

from flask import Blueprint, abort, current_app, g, jsonify, render_template, request, url_for
from pypdf import PdfReader
from sqlalchemy import func, select, text

from .auth import csrf_token, protected
from .models import Class, KnowledgeDocument, Material, db
from .materials import require_class


knowledge = Blueprint("knowledge", __name__)


def extract_body(data, extension):
    if extension in (".txt", ".md"):
        return data.decode("utf-8-sig")
    reader = PdfReader(BytesIO(data), strict=True)
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def initialize_knowledge_index():
    connection = db.session.connection()
    columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(knowledge_documents)")}
    if "body" not in columns:
        connection.exec_driver_sql("ALTER TABLE knowledge_documents ADD COLUMN body TEXT NOT NULL DEFAULT ''")
    existing = connection.exec_driver_sql(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='knowledge_fts'"
    ).first()
    connection.exec_driver_sql(
        "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5("
        "title, body, content='knowledge_documents', content_rowid='id', tokenize='trigram')"
    )
    if not existing:
        connection.exec_driver_sql("INSERT INTO knowledge_fts(knowledge_fts) VALUES ('rebuild')")
    connection.exec_driver_sql(
        "CREATE TRIGGER IF NOT EXISTS knowledge_fts_insert AFTER INSERT ON knowledge_documents BEGIN "
        "INSERT INTO knowledge_fts(rowid, title, body) VALUES (new.id, new.title, new.body); END"
    )
    connection.exec_driver_sql(
        "CREATE TRIGGER IF NOT EXISTS knowledge_fts_delete AFTER DELETE ON knowledge_documents BEGIN "
        "INSERT INTO knowledge_fts(knowledge_fts, rowid, title, body) "
        "VALUES ('delete', old.id, old.title, old.body); END"
    )
    connection.exec_driver_sql(
        "CREATE TRIGGER IF NOT EXISTS knowledge_fts_update AFTER UPDATE ON knowledge_documents BEGIN "
        "INSERT INTO knowledge_fts(knowledge_fts, rowid, title, body) "
        "VALUES ('delete', old.id, old.title, old.body); "
        "INSERT INTO knowledge_fts(rowid, title, body) VALUES (new.id, new.title, new.body); END"
    )
    upload_dir = Path(current_app.config["UPLOAD_DIR"])
    for document in db.session.execute(select(KnowledgeDocument).where(KnowledgeDocument.body == "")).scalars():
        path = upload_dir / document.stored_name
        if not path.is_file() or path.is_symlink():
            continue
        try:
            body = extract_body(path.read_bytes(), path.suffix.lower())
        except Exception as error:
            current_app.logger.warning("Could not index old material %s: %s", document.id, type(error).__name__)
            continue
        if body.strip():
            document.body = body
    db.session.flush()
    db.session.commit()


def _term():
    raw_query = request.args.get("q", "")
    query = raw_query.strip()
    if not query or len(query) > 100 or any(ord(char) < 32 or ord(char) == 127 for char in raw_query):
        abort(400)
    return query


def _snippet(body, query):
    location = body.lower().find(query.lower())
    if location < 0:
        return body[:160]
    start = max(0, location - 65)
    return ("…" if start else "") + body[start:start + 160] + ("…" if start + 160 < len(body) else "")


def _source(document, material, class_id, query=None):
    result = {
        "document_id": document.id,
        "material_id": material.id,
        "class_id": class_id,
        "title": document.title,
        "download_url": url_for("materials.download", class_id=class_id, material_id=material.id),
        "detail_url": url_for("knowledge.document_page", class_id=class_id, document_id=document.id),
    }
    if query is not None:
        result["excerpt"] = _snippet(document.body, query)
    return result


def _search(class_id, query):
    statement = select(KnowledgeDocument, Material).join(
        Material, Material.id == KnowledgeDocument.material_id,
    ).where(
        KnowledgeDocument.class_id == class_id,
        Material.class_id == class_id,
        Material.status == "ready",
    )
    parameters = {}
    if len(query) >= 3:
        statement = statement.where(KnowledgeDocument.id.in_(
            select(text("rowid")).select_from(text("knowledge_fts"))
            .where(text("knowledge_fts MATCH :phrase"))
        ))
        parameters["phrase"] = '"' + query.replace('"', '""') + '"'
    else:
        statement = statement.where(
            (func.instr(func.lower(KnowledgeDocument.body), query.lower()) > 0)
            | (func.instr(func.lower(KnowledgeDocument.title), query.lower()) > 0)
        )
    return db.session.execute(statement.order_by(Material.created_at.desc()).limit(20), parameters).all()


def _document(class_id, document_id):
    result = db.session.execute(select(KnowledgeDocument, Material).join(
        Material, Material.id == KnowledgeDocument.material_id,
    ).where(
        KnowledgeDocument.id == document_id,
        KnowledgeDocument.class_id == class_id,
        Material.class_id == class_id,
        Material.status == "ready",
    )).one_or_none()
    if not result:
        abort(404)
    return result


@knowledge.get("/api/classes/<int:class_id>/knowledge/search")
@protected()
def search_api(class_id):
    require_class(class_id)
    query = _term()
    return jsonify(results=[_source(document, material, class_id, query) for document, material in _search(class_id, query)])


@knowledge.get("/classes/<int:class_id>/knowledge/search")
@protected(api=False)
def search_page(class_id):
    require_class(class_id)
    query = _term() if "q" in request.args else ""
    results = [] if not query else [_source(document, material, class_id, query) for document, material in _search(class_id, _term())]
    return render_template(
        "search.html", classroom=db.session.get(Class, class_id), user=g.user,
        csrf=csrf_token(), query=query, results=results,
    )


@knowledge.get("/api/classes/<int:class_id>/knowledge/documents/<int:document_id>")
@protected()
def document_api(class_id, document_id):
    require_class(class_id)
    document, material = _document(class_id, document_id)
    return jsonify(document={**_source(document, material, class_id), "body": document.body})


@knowledge.get("/classes/<int:class_id>/knowledge/documents/<int:document_id>")
@protected(api=False)
def document_page(class_id, document_id):
    require_class(class_id)
    document, material = _document(class_id, document_id)
    return render_template(
        "document.html", classroom=db.session.get(Class, class_id), user=g.user,
        csrf=csrf_token(), document=document, source=_source(document, material, class_id),
    )
