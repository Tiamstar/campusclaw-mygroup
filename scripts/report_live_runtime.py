"""Run isolated local CampusClaw, MCP and a redacting OpenRouter trace proxy.

Requires OPENROUTER_BASE_URL and OPENROUTER_API_KEY in the environment.
No API key is written to disk or included in the trace.
"""
import importlib.util
import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from werkzeug.serving import make_server

from campusclaw import create_app
from campusclaw.knowledge import initialize_knowledge_index
from campusclaw.models import db

ROOT = Path(__file__).resolve().parents[1]
TRACE = ROOT / "docs" / "evidence" / "llm-trace.json"
APP_PORT, PROXY_PORT, MCP_PORT = 8765, 8766, 8767


class TraceProxy(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        if self.path != "/chat/completions":
            self.send_error(404)
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = json.loads(body)
        upstream = urllib.request.Request(
            os.environ["OPENROUTER_BASE_URL"].rstrip("/") + self.path,
            data=body,
            headers={"Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"],
                     "Content-Type": "application/json", "Accept": "text/event-stream"},
        )
        record = {"captured_at": datetime.now(timezone.utc).isoformat(),
                  "gateway": "OpenRouter", "request_path": self.path,
                  "request_headers": {"Content-Type": "application/json",
                                      "Accept": "text/event-stream",
                                      "Authorization": "Bearer [REDACTED]"},
                  "request_body": payload, "response_lines": []}
        try:
            response = urllib.request.urlopen(upstream, timeout=90)
        except urllib.error.HTTPError as error:
            result = error.read()
            record["upstream_status"] = error.code
            record["error_excerpt"] = result.decode("utf-8", errors="replace")[:500]
            self.send_response(error.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)
        else:
            with response:
                record["upstream_status"] = response.status
                self.send_response(response.status)
                self.send_header("Content-Type", response.headers.get("Content-Type", "text/event-stream"))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                for line in response:
                    self.wfile.write(line)
                    self.wfile.flush()
                    decoded = line.decode("utf-8", errors="replace").strip()
                    if decoded and len(record["response_lines"]) < 100:
                        record["response_lines"].append(decoded[:3000])
        TRACE.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(record, ensure_ascii=False, indent=2)
        TRACE.write_text(serialized, encoding="utf-8")
        number = len(list(TRACE.parent.glob("llm-trace-*.json"))) + 1
        (TRACE.parent / f"llm-trace-{number:03d}.json").write_text(serialized, encoding="utf-8")


def load_mcp_app():
    path = ROOT / "mcp-server" / "app.py"
    spec = importlib.util.spec_from_file_location("report_mcp", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app


def main():
    if not os.environ.get("OPENROUTER_API_KEY") or not os.environ.get("OPENROUTER_BASE_URL"):
        raise SystemExit("OPENROUTER_API_KEY and OPENROUTER_BASE_URL are required")
    with tempfile.TemporaryDirectory(prefix="campusclaw-report-") as directory:
        uploads = Path(directory) / "uploads"
        uploads.mkdir()
        os.environ.update({
            "DATA_DIR": directory,
            "SECRET_KEY": os.urandom(32).hex(),
            "SEED_TEACHER_PASSWORD": "report-teacher-password",
            "SEED_STUDENT_PASSWORD": "report-student-password",
            "MCP_AUTH_TOKEN": "report-only-mcp-token",
            "CHAT_BASE_URL": f"http://127.0.0.1:{PROXY_PORT}",
            "CHAT_API_KEY": "",
            "CHAT_MODEL": "openai/gpt-4o-mini",
            "EMBEDDING_BASE_URL": "",
            "QDRANT_URL": "",
            "MODEL_RETRIES": "0",
            "MODEL_TIMEOUT": "90",
        })
        app = create_app()
        with app.app_context():
            db.create_all()
            initialize_knowledge_index()
            seeded = app.test_cli_runner().invoke(args=["seed-demo"])
            if seeded.exit_code:
                raise RuntimeError(seeded.output)
        servers = [
            make_server("127.0.0.1", APP_PORT, app, threaded=True),
            make_server("127.0.0.1", MCP_PORT, load_mcp_app(), threaded=True),
            ThreadingHTTPServer(("127.0.0.1", PROXY_PORT), TraceProxy),
        ]
        for server in servers:
            threading.Thread(target=server.serve_forever, daemon=True).start()
        print(f"Report runtime ready: http://127.0.0.1:{APP_PORT}", flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            for server in servers:
                server.shutdown()


if __name__ == "__main__":
    main()
