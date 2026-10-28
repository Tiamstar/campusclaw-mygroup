import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path

from werkzeug.serving import make_server

from campusclaw.models import MCPAudit, db
from campusclaw.retrieval import ChatClient, JsonGateway, NOT_FOUND_MESSAGE
from conftest import class_ids
from test_retrieval import FakeEmbedding, FakeQdrant


class ModelHandler(BaseHTTPRequestHandler):
    calls = []
    responses = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).calls.append({"path": self.path, "headers": dict(self.headers), "body": body})
        content = type(self).responses.pop(0) if type(self).responses else "先列出已知条件。[1]"
        response = ('data: ' + json.dumps({"choices": [{"delta": {"content": content}}]}, ensure_ascii=False) + '\n\n'
                    'data: [DONE]\n\n').encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


def start_mcp(monkeypatch):
    spec = importlib.util.spec_from_file_location("demo_mcp", Path(__file__).parents[1] / "mcp-server" / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-mcp-token")
    server = make_server("127.0.0.1", 0, module.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def bearer(client, username):
    response = client.post("/api/login", json={"username": username,
        "password": "teacher-test-password" if username.startswith("teacher") else "student-test-password"})
    assert response.status_code == 200, response.json
    return {"Authorization": "Bearer " + response.json["access_token"]}


def test_apps_prompt_skill_mcp_stream_and_audit(app, monkeypatch):
    mcp_server = start_mcp(monkeypatch)
    model_server = ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
    model_thread = threading.Thread(target=model_server.serve_forever, daemon=True)
    model_thread.start()
    ModelHandler.calls.clear()
    app.extensions["embedding_client"] = FakeEmbedding()
    app.extensions["qdrant_client"] = FakeQdrant()
    app.extensions["chat_client"] = ChatClient(JsonGateway(
        f"http://127.0.0.1:{model_server.server_port}", "test-model-key", retries=0), "test-chat")
    try:
        teacher = app.test_client()
        teacher_headers = bearer(teacher, "teacher_a")
        own_class = class_ids(app)["A班"]
        upload = teacher.post(f"/api/classes/{own_class}/materials", headers=teacher_headers,
            data={"file": (BytesIO("代数方程解题步骤：先列出已知条件，再对等式两边做相同运算。".encode()), "algebra.md")})
        assert upload.status_code == 201, upload.json
        prompt = teacher.post("/api/prompts", headers=teacher_headers, json={
            "app_key": "solver", "name": "苏格拉底", "content": "先反问学生：{{question}}"})
        assert prompt.status_code == 201
        assert teacher.put(f"/api/prompts/{prompt.json['prompt']['id']}", headers=teacher_headers,
            json={"content": "先反问学生：{{question}}"}).status_code == 200
        server = teacher.post("/api/mcp/servers", headers=teacher_headers, json={
            "name": "campus_tools", "base_url": f"http://127.0.0.1:{mcp_server.server_port}",
            "auth_token": "test-mcp-token"})
        assert server.status_code == 201
        assert "test-mcp-token" not in server.get_data(as_text=True)
        server_id = server.json["server"]["id"]
        connected = teacher.post(f"/api/mcp/servers/{server_id}/connect", headers=teacher_headers)
        assert connected.status_code == 200, connected.json
        assert {x["name"] for x in connected.json["server"]["tools"]} == {"formula_hint", "unit_convert"}
        skill = teacher.post("/api/skills", headers=teacher_headers, data={
            "name": "公式引导", "description": "引导列式", "tools": '["knowledge_search","formula_hint@campus_tools"]',
            "file": (BytesIO("只提示下一步，不给最终答案。".encode()), "guide.md")})
        assert skill.status_code == 201, skill.json
        assert teacher.put(f"/api/skills/{skill.json['skill']['id']}", headers=teacher_headers,
            json={"content": "只提示下一步，不给最终答案。", "tools": ["knowledge_search", "formula_hint@campus_tools"]}).status_code == 200
        student = app.test_client()
        student_headers = bearer(student, "student_a")
        assert student.post("/api/mcp/servers", headers=student_headers, json={}).status_code == 403
        conversation = student.post("/api/conversations", headers=student_headers, json={
            "app_key": "solver", "prompt_id": prompt.json["prompt"]["id"],
            "skill_id": skill.json["skill"]["id"]})
        assert conversation.status_code == 201, conversation.json
        cid = conversation.json["conversation"]["id"]
        answer = student.post(f"/api/conversations/{cid}/messages", headers=student_headers,
                              json={"query": "代数方程解题步骤是什么？", "class_id": 999})
        assert answer.status_code == 200
        frames = answer.get_data(as_text=True)
        assert 'event: meta' in frames and '"status": "ok"' in frames
        assert 'formula_hint@campus_tools' in frames and '先列出已知条件' in frames
        assert len(ModelHandler.calls) == 1
        call = ModelHandler.calls[0]
        assert call["path"] == "/chat/completions"
        assert call["headers"]["Authorization"] == "Bearer test-model-key"
        assert call["body"]["model"] == "test-chat"
        assert call["body"]["stream"] is True
        assert call["body"]["temperature"] == 0.2
        assert call["body"]["max_tokens"] == 800
        messages = call["body"]["messages"]
        assert "先反问学生" in messages[0]["content"]
        assert "只提示下一步" in messages[0]["content"]
        assert "formula_hint@campus_tools" in messages[-1]["content"]
        assert "代数方程解题步骤" in messages[-1]["content"]
        assert "999" not in json.dumps(call["body"], ensure_ascii=False)
        no_evidence = student.post(f"/api/conversations/{cid}/messages", headers=student_headers,
                                   json={"query": "光合作用"})
        assert NOT_FOUND_MESSAGE in no_evidence.get_data(as_text=True)
        assert len(ModelHandler.calls) == 1
        audits = teacher.get("/api/mcp/audits", headers=teacher_headers).json["audits"]
        assert audits[0]["tool"] == "formula_hint@campus_tools" and audits[0]["status"] == "ok"
        other = app.test_client()
        other_headers = bearer(other, "student_b")
        assert other.get(f"/api/conversations/{cid}", headers=other_headers).status_code == 404
        assert teacher.post(f"/api/mcp/servers/{server_id}/disconnect", headers=teacher_headers).status_code == 200
        assert teacher.put(f"/api/skills/{skill.json['skill']['id']}", headers=teacher_headers,
            json={"content": "继续使用远端工具", "tools": ["formula_hint@campus_tools"]}).status_code == 400
        again = student.post(f"/api/conversations/{cid}/messages", headers=student_headers,
                             json={"query": "代数方程解题步骤是什么？"})
        assert '"status": "denied"' in again.get_data(as_text=True)
        assert teacher.get("/api/mcp/audits", headers=teacher_headers).json["audits"][0]["status"] == "denied"
        with app.app_context():
            assert db.session.query(MCPAudit).count() == 2
    finally:
        model_server.shutdown(); mcp_server.shutdown()


def test_stream_citation_retry_rejects_invalid_drafts(app):
    model_server = ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
    thread = threading.Thread(target=model_server.serve_forever, daemon=True)
    thread.start()
    ModelHandler.calls.clear()
    app.extensions["chat_client"] = ChatClient(JsonGateway(
        f"http://127.0.0.1:{model_server.server_port}", "test-model-key", retries=0), "test-chat")
    try:
        teacher = app.test_client()
        teacher_headers = bearer(teacher, "teacher_a")
        own_class = class_ids(app)["A班"]
        upload = teacher.post(f"/api/classes/{own_class}/materials", headers=teacher_headers,
            data={"file": (BytesIO("代数方程解题步骤：先列出已知条件。".encode()), "algebra.md")})
        assert upload.status_code == 201
        student = app.test_client()
        student_headers = bearer(student, "student_a")
        conversation = student.post("/api/conversations", headers=student_headers,
                                    json={"app_key": "tutor"})
        cid = conversation.json["conversation"]["id"]
        path = f"/api/conversations/{cid}/messages"

        ModelHandler.responses = ["没有注明出处的草稿。", "依据资料，先列出已知条件。[1]"]
        response = student.post(path, headers=student_headers, json={"query": "代数方程解题步骤"})
        frames = response.get_data(as_text=True)
        assert response.status_code == 200
        assert '"status": "ok"' in frames
        assert "没有注明出处的草稿" not in frames
        assert "依据资料，先列出已知条件。[1]" in frames
        assert len(ModelHandler.calls) == 2
        assert "引用格式校正" in ModelHandler.calls[1]["body"]["messages"][0]["content"]
        assert student.get(f"/api/conversations/{cid}", headers=student_headers).json["messages"][-1] == {
            "role": "assistant", "content": "依据资料，先列出已知条件。[1]"}

        ModelHandler.responses = ["错误出处。[9]", "还是没有出处。"]
        failed = student.post(path, headers=student_headers, json={"query": "代数方程解题步骤"})
        failed_frames = failed.get_data(as_text=True)
        assert '"status": "error"' in failed_frames
        assert '"error": "invalid_model_citation"' in failed_frames
        assert "错误出处" not in failed_frames and "还是没有出处" not in failed_frames
        assert 'event: delta' not in failed_frames
        assert len(ModelHandler.calls) == 4
        history = student.get(f"/api/conversations/{cid}", headers=student_headers).json["messages"]
        assert [item["role"] for item in history] == ["user", "assistant", "user"]
    finally:
        ModelHandler.responses = []
        model_server.shutdown()


def test_mcp_json_rpc_and_openapi(monkeypatch, app):
    server = start_mcp(monkeypatch)
    try:
        import urllib.error
        import urllib.request
        url = f"http://127.0.0.1:{server.server_port}/mcp"
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/health") as response:
            assert json.load(response)["status"] == "ok"
        payload = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/list"}).encode()
        try:
            urllib.request.urlopen(urllib.request.Request(url, data=payload,
                headers={"Content-Type": "application/json"}))
            assert False, "missing token must fail"
        except urllib.error.HTTPError as error:
            assert error.code == 401 and json.load(error)["error"]["message"] == "Unauthorized"
        req = urllib.request.Request(url, data=payload, headers={"Authorization": "Bearer test-mcp-token",
            "Content-Type": "application/json"})
        with urllib.request.urlopen(req) as response:
            assert {x["name"] for x in json.load(response)["result"]["tools"]} == {"formula_hint", "unit_convert"}
        call = json.dumps({"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {
            "name": "formula_hint", "arguments": {"question": "x+2=5 怎么做"}}}).encode()
        with urllib.request.urlopen(urllib.request.Request(url, data=call,
            headers={"Authorization": "Bearer test-mcp-token", "Content-Type": "application/json"})) as response:
            assert "未知数" in json.load(response)["result"]["content"][0]["text"]
        convert = json.dumps({"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": {
            "name": "unit_convert", "arguments": {"value": 2, "from_unit": "m", "to_unit": "cm"}}}).encode()
        with urllib.request.urlopen(urllib.request.Request(url, data=convert,
            headers={"Authorization": "Bearer test-mcp-token", "Content-Type": "application/json"})) as response:
            assert json.load(response)["result"]["content"][0]["text"] == "2 m = 200 cm"
        bad = json.dumps({"jsonrpc": "1.0", "id": 9, "method": "tools/list"}).encode()
        try:
            urllib.request.urlopen(urllib.request.Request(url, data=bad,
                headers={"Authorization": "Bearer test-mcp-token", "Content-Type": "application/json"}))
            assert False, "invalid JSON-RPC must fail"
        except urllib.error.HTTPError as error:
            assert error.code == 400 and json.load(error)["error"]["code"] == -32600
        client = app.test_client()
        spec = client.get("/openapi.json").json
        assert spec["paths"]["/api/conversations/{conversation_id}/messages"]["post"]["responses"]["200"]["content"].get("text/event-stream")
        assert client.get("/docs").status_code == 200
    finally:
        server.shutdown()
