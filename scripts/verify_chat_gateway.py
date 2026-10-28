"""Run one isolated CampusClaw chat against the selected real model gateway.

Use --gateway course with CHAT_API_KEY (or EMBEDDING_API_KEY), or
--gateway openrouter with the existing OPENROUTER_API_KEY. Credentials stay
in process memory. The temporary database is deleted when the check exits.
"""

import argparse
import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select

from campusclaw import create_app
from campusclaw.knowledge import initialize_knowledge_index
from campusclaw.models import Class, db
from campusclaw.retrieval import ChatClient, JsonGateway


class CountingChatClient(ChatClient):
    def __init__(self, gateway, model):
        super().__init__(gateway, model)
        self.requests = 0

    def stream(self, messages):
        self.requests += 1
        yield from super().stream(messages)


def events(response):
    result = []
    for frame in response.get_data(as_text=True).split("\n\n"):
        lines = frame.splitlines()
        event = next((line[7:] for line in lines if line.startswith("event: ")), None)
        data = next((line[6:] for line in lines if line.startswith("data: ")), None)
        if event and data:
            result.append((event, json.loads(data)))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway", choices=("course", "openrouter"), default="course")
    args = parser.parse_args()
    if args.gateway == "course":
        base_url = os.environ.get("CHAT_BASE_URL", "https://ai-gateway.devops.hello1023.com/v1")
        if urlparse(base_url).hostname != "ai-gateway.devops.hello1023.com":
            parser.error("course check must target ai-gateway.devops.hello1023.com")
        key = os.environ.get("CHAT_API_KEY") or os.environ.get("EMBEDDING_API_KEY")
        model = os.environ.get("CHAT_MODEL", "course-chat")
    else:
        base_url = os.environ.get("OPENROUTER_BASE_URL", "")
        key = os.environ.get("OPENROUTER_API_KEY")
        model = "openai/gpt-4o-mini"
    if not base_url or not key:
        parser.error(f"{args.gateway} gateway URL and API key must be configured")

    teacher_password = secrets.token_urlsafe(24)
    student_password = secrets.token_urlsafe(24)
    os.environ["SEED_TEACHER_PASSWORD"] = teacher_password
    os.environ["SEED_STUDENT_PASSWORD"] = student_password
    with tempfile.TemporaryDirectory(prefix="campusclaw-gateway-") as directory:
        uploads = Path(directory) / "uploads"
        uploads.mkdir()
        app = create_app({
            "SECRET_KEY": secrets.token_urlsafe(32),
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{directory}/test.db",
            "UPLOAD_DIR": str(uploads),
            "CHAT_API_URL": base_url.rstrip("/"),
            "CHAT_API_KEY": key,
            "CHAT_MODEL": model,
            "EMBEDDING_API_URL": "",
            "QDRANT_URL": "",
            "MODEL_TIMEOUT": 90,
            "MODEL_RETRIES": 0,
        })
        chat = CountingChatClient(JsonGateway(base_url, key, timeout=90, retries=0), model)
        app.extensions["chat_client"] = chat
        with app.app_context():
            db.create_all()
            initialize_knowledge_index()
            seeded = app.test_cli_runner().invoke(args=["seed-demo"])
            if seeded.exit_code:
                raise RuntimeError("demo setup failed") from seeded.exception
            class_id = db.session.execute(select(Class.id).where(Class.name == "A班")).scalar_one()

        teacher = app.test_client()
        login = teacher.post("/api/login", json={"username": "teacher_a", "password": teacher_password})
        if login.status_code != 200:
            raise RuntimeError("teacher login failed")
        teacher_headers = {"Authorization": "Bearer " + login.json["access_token"]}
        uploaded = teacher.post(f"/api/classes/{class_id}/materials", headers=teacher_headers,
            data={"file": (BytesIO("代数方程解题步骤：先列出已知条件，再对等式两边做相同运算。".encode()), "algebra.md")})
        if uploaded.status_code != 201:
            raise RuntimeError(f"material upload failed: HTTP {uploaded.status_code}")

        student = app.test_client()
        login = student.post("/api/login", json={"username": "student_a", "password": student_password})
        if login.status_code != 200:
            raise RuntimeError("student login failed")
        student_headers = {"Authorization": "Bearer " + login.json["access_token"]}
        created = student.post("/api/conversations", headers=student_headers, json={"app_key": "tutor"})
        if created.status_code != 201:
            raise RuntimeError("conversation creation failed")
        response = student.post(f"/api/conversations/{created.json['conversation']['id']}/messages",
                                headers=student_headers, json={"query": "代数方程解题步骤"})
        frames = events(response)
        meta = next((data for event, data in frames if event == "meta"), {})
        done = next((data for event, data in frames if event == "done"), {})
        answer = done.get("answer", "")
        result = {"checked_at": datetime.now(timezone.utc).isoformat(),
                  "gateway": args.gateway, "host": urlparse(base_url).hostname,
                  "model": model, "http_status": response.status_code,
                  "model_requests": chat.requests,
                  "retrieved_sources": len(meta.get("citations", [])),
                  "status": done.get("status", "missing_done"),
                  "citation_numbers": [int(x) for x in re.findall(r"\[(\d+)\]", answer)],
                  "answer": answer if done.get("status") == "ok" else None,
                  "error": done.get("error")}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if response.status_code != 200 or result["status"] != "ok" or not result["citation_numbers"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
