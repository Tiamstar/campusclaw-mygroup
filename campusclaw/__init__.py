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

    @app.get("/health")
    def health():
        try:
            db.session.execute(text("SELECT 1"))
            upload_dir = Path(app.config["UPLOAD_DIR"])
            with tempfile.NamedTemporaryFile(dir=upload_dir):
                pass
        except Exception:
            return jsonify(status="unavailable"), 503
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
        from .knowledge import initialize_knowledge_index

        initialize_knowledge_index()
        click.echo("Database initialized")

    from .seed import register_seed_commands
    from .materials import register_cleanup_command

    register_seed_commands(app)
    register_cleanup_command(app)
    return app


def _auth_blueprint():
    from .auth import auth

    return auth


def _materials_blueprint():
    from .materials import materials

    return materials
