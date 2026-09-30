import os
import tempfile
from datetime import timedelta
from pathlib import Path

import click
from flask import Flask, jsonify
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from werkzeug.exceptions import HTTPException

from .logging_config import SensitiveLogFilter
from .models import db


@event.listens_for(Engine, "connect")
def enable_sqlite_foreign_keys(connection, connection_record):
    if connection.__class__.__module__.startswith("sqlite3"):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    secret = os.environ.get("SECRET_KEY")
    if test_config is not None:
        secret = test_config.get("SECRET_KEY", secret)
    if not secret:
        raise RuntimeError("SECRET_KEY is required")

    data_dir = Path(os.environ.get("DATA_DIR", app.instance_path)).resolve()
    embedding_base_url = os.environ.get("EMBEDDING_BASE_URL") or os.environ.get("EMBEDDING_API_URL", "")
    chat_base_url = os.environ.get("CHAT_BASE_URL") or os.environ.get("CHAT_API_URL") or embedding_base_url
    app.config.update(
        SECRET_KEY=secret,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{data_dir / 'campusclaw.db'}",
        UPLOAD_DIR=str(data_dir / "uploads"),
        MAX_CONTENT_LENGTH=11 * 1024 * 1024,
        MAX_FILE_SIZE=10 * 1024 * 1024,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "false").lower() == "true",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        EMBEDDING_API_URL=embedding_base_url,
        CHAT_API_URL=chat_base_url,
        EMBEDDING_API_KEY=os.environ.get("EMBEDDING_API_KEY") or os.environ.get("MODEL_API_KEY", ""),
        CHAT_API_KEY=os.environ.get("CHAT_API_KEY") or os.environ.get("MODEL_API_KEY") or os.environ.get("EMBEDDING_API_KEY", ""),
        EMBEDDING_MODEL=os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small"),
        CHAT_MODEL=os.environ.get("CHAT_MODEL", "course-chat"),
        EMBEDDING_DIMENSIONS=int(os.environ.get("EMBEDDING_DIM", os.environ.get("EMBEDDING_DIMENSIONS", "2048"))),
        MODEL_TIMEOUT=float(os.environ.get("MODEL_TIMEOUT", "10")),
        MODEL_RETRIES=int(os.environ.get("MODEL_RETRIES", "2")),
        QDRANT_URL=os.environ.get("QDRANT_URL", ""),
        QDRANT_API_KEY=os.environ.get("QDRANT_API_KEY", ""),
        QDRANT_COLLECTION=os.environ.get("QDRANT_COLLECTION", "campusclaw_chunks"),
    )
    if test_config:
        app.config.update(test_config)
    app.logger.addFilter(SensitiveLogFilter())
    db.init_app(app)
    from .auth import hash_password

    app.extensions["dummy_password_hash"] = hash_password(os.urandom(32).hex())
    app.register_blueprint(_auth_blueprint())
    app.register_blueprint(_materials_blueprint())
    from .knowledge import knowledge

    app.register_blueprint(knowledge)
    from .retrieval import retrieval

    app.register_blueprint(retrieval)

    @app.get("/health")
    def health():
        try:
            db.session.execute(text("SELECT 1"))
            upload_dir = Path(app.config["UPLOAD_DIR"])
            with tempfile.NamedTemporaryFile(dir=upload_dir):
                pass
        except Exception:
            return jsonify(status="unavailable"), 503
        if app.config.get("QDRANT_URL"):
            from .retrieval import _qdrant_client

            vector_status = "ok" if _qdrant_client().available() else "unavailable"
            return jsonify(status="ok", components={
                "database": "ok", "uploads": "ok", "vector": vector_status,
            })
        return jsonify(status="ok")

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if error.code == 413:
            return jsonify(error="file_too_large"), 413
        if error.code in (400, 401, 403, 404):
            return jsonify(error=error.name.lower().replace(" ", "_")), error.code
        return jsonify(error="request_failed"), error.code

    @app.cli.command("init-db")
    def init_db():
        data_dir.mkdir(parents=True, exist_ok=True)
        Path(app.config["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)
        db.create_all()
        session_columns = {
            row[1] for row in db.session.connection().exec_driver_sql("PRAGMA table_info(sessions)")
        }
        if "active_class_id" not in session_columns:
            db.session.connection().exec_driver_sql(
                "ALTER TABLE sessions ADD COLUMN active_class_id INTEGER REFERENCES classes(id)"
            )
            db.session.commit()
        from .knowledge import initialize_knowledge_index

        initialize_knowledge_index()
        click.echo("Database initialized")

    from .seed import register_seed_commands
    from .materials import register_cleanup_command
    from .retrieval import register_retrieval_commands

    register_seed_commands(app)
    register_cleanup_command(app)
    register_retrieval_commands(app)
    return app


def _auth_blueprint():
    from .auth import auth

    return auth


def _materials_blueprint():
    from .materials import materials

    return materials
