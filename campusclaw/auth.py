import hashlib
import hmac
import secrets
from datetime import timedelta
from functools import wraps
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, g, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import delete, select
from werkzeug.security import check_password_hash, generate_password_hash

from .models import LoginAttempt, LoginSession, User, db, utcnow


auth = Blueprint("auth", __name__)


def hash_password(password):
    return generate_password_hash(password, method="scrypt")


def check_password(stored, supplied):
    return check_password_hash(stored, supplied)


def _digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _login_key(username):
    return hmac.new(current_app.secret_key.encode("utf-8"), username.encode("utf-8"), hashlib.sha256).hexdigest()


def _login_failure(next_path, username):
    if "text/html" in request.headers.get("Accept", ""):
        return render_template(
            "login.html", next_path=next_path, csrf=csrf_token(),
            error="账号或密码不正确，请重试。", username=username,
        ), 401
    return jsonify(error="invalid_credentials"), 401


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def require_csrf():
    supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    expected = session.get("csrf", "")
    if not expected or not hmac.compare_digest(expected, supplied):
        abort(400)


def current_user():
    if "user_loaded" not in g:
        g.user_loaded = True
        g.user = None
        g.login_session = None
        token = session.get("auth_token")
        if token:
            record = db.session.execute(
                select(LoginSession).where(LoginSession.token_digest == _digest(token))
            ).scalar_one_or_none()
            if record and not record.revoked_at and record.expires_at > utcnow():
                user = db.session.get(User, record.user_id)
                if user and user.is_active:
                    g.user = user
                    g.login_session = record
    return g.user


def protected(api=True, teacher=False):
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                if api:
                    return jsonify(error="unauthorized"), 401
                return redirect(url_for("auth.login", next=request.path))
            if teacher and user.role != "teacher":
                return jsonify(error="forbidden"), 403
            return view(*args, **kwargs)

        return wrapped

    return decorate


def _safe_next(value):
    parsed = urlsplit(value or "")
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return url_for("auth.index")
    return parsed.path


@auth.get("/")
@protected(api=False)
def index():
    from .models import Class, ClassMembership

    classes = db.session.execute(
        select(Class)
        .join(ClassMembership, ClassMembership.class_id == Class.id)
        .where(ClassMembership.user_id == current_user().id)
        .order_by(Class.name)
    ).scalars().all()
    return render_template("classes.html", classes=classes, user=g.user, csrf=csrf_token())


@auth.route("/login", methods=["GET", "POST"])
def login():
    next_path = _safe_next(request.values.get("next"))
    if request.method == "POST":
        require_csrf()
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        now = utcnow()
        db.session.execute(delete(LoginAttempt).where(LoginAttempt.window_start < now - timedelta(minutes=15)))
        attempt = db.session.get(LoginAttempt, _login_key(username))
        user = db.session.execute(select(User).where(User.username == username)).scalar_one_or_none()
        supplied_valid = check_password(
            user.password_hash if user else current_app.extensions["dummy_password_hash"], password,
        )
        if not user or not user.is_active or not supplied_valid or (attempt and attempt.failed_count >= 5):
            if not attempt:
                attempt = LoginAttempt(key_digest=_login_key(username), failed_count=0, window_start=now)
                db.session.add(attempt)
            if attempt.failed_count < 5:
                attempt.failed_count += 1
            db.session.commit()
            return _login_failure(next_path, username)
        if attempt:
            db.session.delete(attempt)
        previous_token = session.get("auth_token")
        if previous_token:
            previous = db.session.execute(
                select(LoginSession).where(LoginSession.token_digest == _digest(previous_token))
            ).scalar_one_or_none()
            if previous:
                previous.revoked_at = utcnow()
        session.clear()
        token = secrets.token_urlsafe(32)
        session["auth_token"] = token
        session["csrf"] = secrets.token_urlsafe(32)
        session.permanent = True
        db.session.add(LoginSession(
            token_digest=_digest(token),
            user_id=user.id,
            expires_at=utcnow() + timedelta(hours=8),
        ))
        db.session.commit()
        return redirect(next_path)
    return render_template("login.html", next_path=next_path, csrf=csrf_token())


@auth.post("/logout")
@protected()
def logout():
    require_csrf()
    g.login_session.revoked_at = utcnow()
    db.session.commit()
    session.clear()
    return redirect(url_for("auth.login"))
