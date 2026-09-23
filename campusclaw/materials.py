import os
import re
import tempfile
import unicodedata
import uuid
from datetime import timedelta
from io import BytesIO
from pathlib import Path

import click
from flask import Blueprint, abort, current_app, g, jsonify, render_template, request, send_file
from pypdf import PdfReader
from sqlalchemy import select

from .auth import csrf_token, protected, require_csrf
from .models import Class, ClassMembership, KnowledgeDocument, Material, db, utcnow


materials = Blueprint("materials", __name__)
EXTENSIONS = {".pdf", ".txt", ".md"}


def require_class(class_id):
    membership = db.session.execute(select(ClassMembership).where(
        ClassMembership.user_id == g.user.id,
        ClassMembership.class_id == class_id,
    )).scalar_one_or_none()
    if not membership:
        abort(403)


def _get_material(class_id, material_id):
    record = db.session.execute(select(Material).where(
        Material.id == material_id,
        Material.class_id == class_id,
        Material.status == "ready",
    )).scalar_one_or_none()
    if not record:
        abort(404)
    return record


def _as_json(record):
    return {
        "id": record.id,
        "class_id": record.class_id,
        "name": record.original_name,
        "uploaded_by": record.uploaded_by,
        "status": record.status,
        "created_at": record.created_at.isoformat(),
    }


def _list_materials(class_id):
    return db.session.execute(select(Material).where(
        Material.class_id == class_id,
        Material.status == "ready",
    ).order_by(Material.created_at.desc())).scalars().all()


@materials.get("/classes/<int:class_id>/materials")
@protected(api=False)
def materials_page(class_id):
    require_class(class_id)
    records = _list_materials(class_id)
    return render_template(
        "materials.html", records=records, classroom=db.session.get(Class, class_id),
        user=g.user, csrf=csrf_token(),
    )


@materials.get("/api/classes/<int:class_id>/materials")
@protected()
def list_materials(class_id):
    require_class(class_id)
    return jsonify(materials=[_as_json(record) for record in _list_materials(class_id)])


@materials.get("/api/classes/<int:class_id>/materials/<int:material_id>")
@protected()
def detail(class_id, material_id):
    require_class(class_id)
    return jsonify(material=_as_json(_get_material(class_id, material_id)))


@materials.get("/classes/<int:class_id>/materials/<int:material_id>/download")
@protected()
def download(class_id, material_id):
    require_class(class_id)
    record = _get_material(class_id, material_id)
    upload_dir = Path(current_app.config["UPLOAD_DIR"])
    path = upload_dir / record.stored_name
    if not path.is_file() or path.is_symlink():
        abort(404)
    response = send_file(path, as_attachment=True, download_name=record.original_name)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@materials.get("/classes/<int:class_id>/materials/upload")
@protected(api=False, teacher=True)
def upload_page(class_id):
    require_class(class_id)
    return render_template(
        "upload.html", classroom=db.session.get(Class, class_id), user=g.user, csrf=csrf_token(),
    )


def _validate_file(file):
    raw_name = file.filename or ""
    safe_name = unicodedata.normalize("NFC", raw_name.replace("\\", "/").rsplit("/", 1)[-1]).strip()
    extension = Path(safe_name).suffix.lower()
    if (not safe_name or len(safe_name.encode("utf-8")) > 255
            or any(ord(char) < 32 or char == "\x7f" for char in safe_name)
            or safe_name.startswith(".") or extension not in EXTENSIONS):
        abort(400)
    size_limit = current_app.config["MAX_FILE_SIZE"]
    data = file.stream.read(size_limit + 1)
    if len(data) > size_limit:
        abort(413)
    if not data:
        abort(400)
    if extension == ".pdf":
        if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-1024:]:
            abort(400)
        try:
            reader = PdfReader(BytesIO(data), strict=True)
            page_count = len(reader.pages)
        except Exception:
            abort(400)
        if not 1 <= page_count <= 500:
            abort(400)
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeError:
            abort(400)
        if not text.strip() or "\x00" in text or any(ord(char) < 32 and char not in "\n\r\t" for char in text):
            abort(400)
        if data.startswith((b"%PDF-", b"PK\x03\x04", b"MZ")):
            abort(400)
    from .knowledge import extract_body

    try:
        body = extract_body(data, extension)
    except Exception:
        abort(400)
    if not body.strip():
        abort(400)
    return safe_name, extension, data, body


@materials.post("/api/classes/<int:class_id>/materials")
@protected(teacher=True)
def upload(class_id):
    require_csrf()
    require_class(class_id)
    if "class_id" in request.form and request.form["class_id"] != str(class_id):
        abort(403)
    file = request.files.get("file")
    if not file:
        abort(400)
    display_name, extension, data, body = _validate_file(file)
    upload_dir = Path(current_app.config["UPLOAD_DIR"])
    stored_name = f"{uuid.uuid4().hex}{extension}"
    destination = upload_dir / stored_name
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=upload_dir, delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
        os.replace(temporary, destination)
        temporary = None
        record = Material(
            class_id=class_id, uploaded_by=g.user.id,
            original_name=display_name, stored_name=stored_name, status="ready",
        )
        db.session.add(record)
        db.session.flush()
        db.session.add(KnowledgeDocument(
            material_id=record.id, class_id=class_id,
            title=display_name, stored_name=stored_name, body=body,
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()
        destination.unlink(missing_ok=True)
        if temporary:
            temporary.unlink(missing_ok=True)
        raise
    return jsonify(material=_as_json(record)), 201


def register_cleanup_command(app):
    @app.cli.command("cleanup-orphans")
    def cleanup_orphans():
        upload_dir = Path(current_app.config["UPLOAD_DIR"])
        if not upload_dir.is_dir():
            raise click.ClickException("Upload directory is unavailable")
        referenced = set(db.session.execute(select(Material.stored_name)).scalars())
        cutoff = (utcnow() - timedelta(hours=24)).timestamp()
        removed = 0
        for candidate in upload_dir.iterdir():
            if candidate.is_symlink() or not candidate.is_file() or candidate.name in referenced:
                continue
            if not (re.fullmatch(r"[0-9a-f]{32}\.(pdf|txt|md)", candidate.name)
                    or re.fullmatch(r"tmp[A-Za-z0-9_-]+", candidate.name)):
                continue
            if candidate.stat().st_mtime < cutoff:
                candidate.unlink()
                removed += 1
        click.echo(f"Removed {removed} orphan files")
