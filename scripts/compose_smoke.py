"""Smoke test a temporary Compose stack through its published Nginx endpoint."""
import json
import os
import urllib.request
from uuid import uuid4

BASE = os.environ.get("ACCEPTANCE_BASE_URL", "http://127.0.0.1:8000")


def request(path, method="GET", data=None, token=None, content_type="application/json"):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if data is not None:
        headers["Content-Type"] = content_type
    payload = json.dumps(data).encode() if content_type == "application/json" and data is not None else data
    req = urllib.request.Request(BASE + path, data=payload, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as response:
        body = response.read()
        return response.status, json.loads(body) if response.headers.get_content_type() == "application/json" else body.decode()


def login(username, password):
    status, body = request("/api/login", "POST", {"username": username, "password": password})
    assert status == 200
    return body["access_token"]


def main():
    assert request("/health")[1]["status"] == "ok"
    assert "SwaggerUIBundle" in request("/docs")[1]
    assert "swagger" in request("/static/swagger-ui-bundle.js")[1].lower()
    teacher = login("teacher_a", os.environ["ACCEPTANCE_TEACHER_PASSWORD"])
    student = login("student_a", os.environ["ACCEPTANCE_STUDENT_PASSWORD"])
    apps = request("/api/apps", token=student)[1]["apps"]
    assert {x["key"] for x in apps} == {"solver", "tutor", "summary"}
    name = "campus_tools_" + uuid4().hex[:6]
    server = request("/api/mcp/servers", "POST", {"name": name, "base_url": "http://mcp-demo:8090",
        "auth_token": os.environ["ACCEPTANCE_MCP_TOKEN"]}, teacher)[1]["server"]
    assert "auth_token" not in server
    connected = request(f"/api/mcp/servers/{server['id']}/connect", "POST", {}, teacher)[1]["server"]
    assert {x["name"] for x in connected["tools"]} == {"formula_hint", "unit_convert"}
    skill = request("/api/skills", "POST", {"name": "smoke_" + uuid4().hex[:6],
        "description": "MCP 联通验证", "content": "只提示下一步。",
        "tools": ["knowledge_search", f"formula_hint@{name}"]}, teacher)[1]["skill"]
    assert skill["tools"][-1] == f"formula_hint@{name}"
    disconnected = request(f"/api/mcp/servers/{server['id']}/disconnect", "POST", {}, teacher)[1]["server"]
    assert disconnected["tools"] == [] and not disconnected["connected"]
    print("Compose smoke: health, Swagger, Bearer, apps, MCP connect/discover, skill bind, disconnect PASS")


if __name__ == "__main__":
    main()
