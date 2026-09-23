import os

import click
from flask import current_app
from sqlalchemy import select

from .auth import hash_password
from .models import Class, ClassMembership, User, db


def register_seed_commands(app):
    @app.cli.command("seed-demo")
    def seed_demo():
        teacher_password = os.environ.get("SEED_TEACHER_PASSWORD")
        student_password = os.environ.get("SEED_STUDENT_PASSWORD")
        if not teacher_password or not student_password:
            raise click.ClickException("Seed passwords must be set in server environment")

        class_records = {}
        for name in ("A班", "B班"):
            record = db.session.execute(select(Class).where(Class.name == name)).scalar_one_or_none()
            if not record:
                record = Class(name=name)
                db.session.add(record)
                db.session.flush()
            class_records[name] = record

        for username, role, class_name, password in (
            ("teacher_a", "teacher", "A班", teacher_password),
            ("student_a", "student", "A班", student_password),
            ("student_b", "student", "B班", student_password),
        ):
            user = db.session.execute(select(User).where(User.username == username)).scalar_one_or_none()
            if not user:
                user = User(username=username, role=role, password_hash=hash_password(password))
                db.session.add(user)
                db.session.flush()
            membership = db.session.execute(select(ClassMembership).where(
                ClassMembership.user_id == user.id,
                ClassMembership.class_id == class_records[class_name].id,
            )).scalar_one_or_none()
            if not membership:
                db.session.add(ClassMembership(user_id=user.id, class_id=class_records[class_name].id))
        db.session.commit()
        click.echo("Demo accounts and classes ready")
