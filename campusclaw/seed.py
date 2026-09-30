import os
import uuid
from pathlib import Path

import click
from flask import current_app
from sqlalchemy import select

from .auth import hash_password
from .models import Class, ClassMembership, KnowledgeDocument, Material, User, db


DEMO_MATERIALS = (
    (
        "A班", "光合作用课程讲义.md",
        """# 光合作用课程讲义

光合作用是绿色植物利用光能，把二氧化碳和水合成储存能量的有机物，并释放氧气的过程。主要场所是叶绿体。

## 两个主要阶段

光反应阶段吸收太阳能，将光能转化为活跃的化学能，同时分解水并释放氧气。碳反应阶段利用前一阶段提供的能量固定二氧化碳，逐步合成糖类。

## 影响因素

光照强度、二氧化碳浓度、温度和水分都会影响光合作用速率。在一定范围内增强光照或提高二氧化碳浓度可以提高速率；超过适宜范围后，其他因素会成为限制条件。

## 课堂结论

植物通过光合作用将太阳能转化为化学能，并把能量储存在有机物中。判断实验结论时，需要设置对照组并只改变一个自变量。
""",
    ),
    (
        "A班", "化学实验室安全规范.md",
        """# 化学实验室安全规范

进入实验室必须穿实验服、佩戴护目镜，长发应束起。禁止在实验区域饮食，不得擅自品尝或直接闻取化学试剂。

稀释浓硫酸时，必须把浓硫酸沿器壁缓慢加入水中并不断搅拌，严禁把水倒入浓硫酸。加热试管时，管口不得朝向自己或他人。

若少量酸液溅到皮肤，应立即用大量流动清水冲洗并报告教师。发生火情时先切断火源，根据燃烧物选择灭火器材，不得盲目用水。

实验结束后应分类回收废液，清洗器材，关闭水、电、气源，并在教师检查后离开。
""",
    ),
    (
        "B班", "机器人课程项目说明.md",
        """# B 班机器人课程项目说明

B 班本期项目是制作循迹机器人。传感器读取地面反射光强，控制器根据左右偏差调整两个电机的转速。调试时应先校准传感器阈值，再逐步调整比例参数。

本材料仅用于验证班级隔离：A 班用户搜索“循迹机器人”时不应获得任何结果。
""",
    ),
)


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

    @app.cli.command("seed-demo-materials")
    def seed_demo_materials():
        from .retrieval import ensure_document_index

        upload_dir = Path(current_app.config["UPLOAD_DIR"])
        upload_dir.mkdir(parents=True, exist_ok=True)
        created = indexed = failed = 0
        for class_name, filename, body in DEMO_MATERIALS:
            classroom = db.session.execute(select(Class).where(Class.name == class_name)).scalar_one_or_none()
            if not classroom:
                raise click.ClickException("Run seed-demo before seed-demo-materials")
            document = db.session.execute(select(KnowledgeDocument).where(
                KnowledgeDocument.class_id == classroom.id,
                KnowledgeDocument.title == filename,
            )).scalar_one_or_none()
            if not document:
                username = "teacher_a" if class_name == "A班" else "student_b"
                uploader = db.session.execute(select(User).where(User.username == username)).scalar_one()
                stored_name = f"{uuid.uuid4().hex}.md"
                (upload_dir / stored_name).write_text(body, encoding="utf-8")
                material = Material(
                    class_id=classroom.id, uploaded_by=uploader.id, original_name=filename,
                    stored_name=stored_name, status="ready",
                )
                db.session.add(material)
                db.session.flush()
                document = KnowledgeDocument(
                    material_id=material.id, class_id=classroom.id, title=filename,
                    body=body, stored_name=stored_name,
                )
                db.session.add(document)
                db.session.commit()
                created += 1
            try:
                indexed += bool(ensure_document_index(document))
            except Exception as error:
                current_app.logger.warning(
                    "Demo material indexing failed for document %s: %s", document.id, type(error).__name__,
                )
                failed += 1
        click.echo(f"Demo materials ready; created {created}; indexed {indexed}; failed {failed}")
