"""Run API acceptance cases and write an HTML report (not committed)."""
import html
import importlib.util
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from campusclaw import create_app
from campusclaw.knowledge import initialize_knowledge_index
from campusclaw.models import Class, db


class Chat:
    def __init__(self):
        self.calls = []

    def answer(self, messages):
        self.calls.append(messages)
        return "先列出已知条件。[1]"


def run():
    os.environ["SEED_TEACHER_PASSWORD"] = "teacher-test-password"
    os.environ["SEED_STUDENT_PASSWORD"] = "student-test-password"
    with tempfile.TemporaryDirectory() as directory:
        app = create_app({"SECRET_KEY": "apitest-only-secret", "TESTING": True,
                          "SQLALCHEMY_DATABASE_URI": f"sqlite:///{directory}/test.db",
                          "UPLOAD_DIR": directory, "EMBEDDING_API_URL": "", "QDRANT_URL": ""})
        with app.app_context():
            db.create_all()
            initialize_knowledge_index()
            assert app.test_cli_runner().invoke(args=["seed-demo"]).exit_code == 0
            classes = {x.name: x.id for x in db.session.query(Class).all()}
        context = {"app": app, "teacher": app.test_client(), "student": app.test_client(),
                   "classes": classes, "chat": Chat()}
        app.extensions["chat_client"] = context["chat"]
        results = []
        order = ["api/login/POST.py", "api/retrieval/search/POST.py", "api/prompts/POST.py",
                 "api/skills/POST.py", "api/conversations/POST.py", "api/conversations/messages/POST.py",
                 "api/mcp/servers/POST.py", "api/mcp/servers/connect/POST.py",
                 "api/mcp/flow/POST.py", "api/mcp/servers/disconnect/POST.py"]
        for path in [ROOT / "apitest" / "cases" / name for name in order]:
            spec = importlib.util.spec_from_file_location("case_" + str(len(results)), path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            try:
                module.run(context)
                results.append((str(path.relative_to(ROOT / "apitest")), "PASS", ""))
            except Exception:
                results.append((str(path.relative_to(ROOT / "apitest")), "FAIL", traceback.format_exc()))
        rows = "".join(f"<tr><td>{html.escape(path)}</td><td>{status}</td><td><pre>{html.escape(error)}</pre></td></tr>"
                       for path, status, error in results)
        report = ROOT / "apitest" / "report.html"
        report.write_text(f"<!doctype html><meta charset='utf-8'><title>CampusClaw API 验收</title>"
                          f"<h1>CampusClaw API 验收</h1><p>{sum(x[1] == 'PASS' for x in results)}/{len(results)} 通过</p>"
                          f"<table border='1'><tr><th>接口用例</th><th>结果</th><th>详情</th></tr>{rows}</table>", encoding="utf-8")
        for path, status, error in results:
            print(status, path)
            if error:
                print(error)
        print("HTML report:", report)
        return all(status == "PASS" for _, status, _ in results)


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
