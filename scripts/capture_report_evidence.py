"""Capture reproducible report figures from scripts/report_live_runtime.py."""
import html
import json
import os
import re
import shutil
import urllib.request
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "evidence"
BASE = "http://127.0.0.1:8765"
cached_chromium = sorted((Path.home() / ".cache" / "ms-playwright").glob("chromium-*/chrome-linux/chrome"))
BROWSER = os.environ.get("CAMPUSCLAW_BROWSER") or (str(cached_chromium[-1]) if cached_chromium else None)


def api(path, token=None, data=None, multipart=None):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if multipart is not None:
        boundary = "----campusclaw" + uuid4().hex
        chunks = []
        for name, value in multipart.items():
            if isinstance(value, tuple):
                filename, content = value
                chunks.extend([f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\nContent-Type: text/markdown\r\n\r\n".encode(), content, b"\r\n"])
            else:
                chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
        chunks.append(f"--{boundary}--\r\n".encode())
        body = b"".join(chunks)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif data is not None:
        body = json.dumps(data, ensure_ascii=False).encode()
        headers["Content-Type"] = "application/json"
    else:
        body = None
    request = urllib.request.Request(BASE + path, data=body, headers=headers,
                                     method="POST" if body is not None else "GET")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def bearer(username, password):
    return api("/api/login", data={"username": username, "password": password})


def login_page(page, username, password):
    page.goto(BASE + "/login")
    page.locator("#username").fill(username)
    page.locator("#password").fill(password)
    page.locator("button[type=submit]").click()
    page.wait_for_url(BASE + "/")


def capture_wire(browser, trace_path=None):
    trace_path = trace_path or EVIDENCE / "llm-trace.json"
    assert trace_path.exists(), "The model trace was not written"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["upstream_status"] == 200
    assert trace["request_body"]["stream"] is True
    assert len(trace["request_body"]["messages"]) >= 2
    system = trace["request_body"]["messages"][0]["content"]
    user = trace["request_body"]["messages"][-1]["content"]
    assert "苏格拉底" in system and "当前技能说明" in system
    assert "formula_hint@campus_tools" in user
    assert "OPENROUTER_API_KEY" not in trace_path.read_text()
    assert any("data: " in line for line in trace["response_lines"])
    if trace_path.name != "llm-trace-connected.json":
        shutil.copyfile(trace_path, EVIDENCE / "llm-trace-connected.json")

    chunks = []
    for line in trace["response_lines"]:
        if line.startswith("data: ") and line != "data: [DONE]":
            try:
                chunks.append(json.loads(line[6:])["choices"][0].get("delta", {}).get("content", ""))
            except (KeyError, IndexError, TypeError, ValueError):
                pass
    assembled = "".join(chunks)
    assert assembled and trace["response_lines"][-1] == "data: [DONE]"
    stream_excerpt = ("首条 data 事件含 delta.content；完整原始事件见 JSON。\n"
                      f"delta 片段数：{len(chunks)}；终止标记：data: [DONE]")
    properties = {key: trace["request_body"].get(key) for key in ("model", "stream", "temperature", "max_tokens")}
    markup = """<!doctype html><meta charset='utf-8'><style>
    body{font:17px/1.55 system-ui,'Noto Sans CJK SC',sans-serif;margin:28px;background:#f4f5f7;color:#20252c}
    h1{font-size:26px;margin:0 0 7px}.sub{color:#5c6772;margin-bottom:18px}
    .grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.box{background:white;border:1px solid #dfe4e8;border-radius:10px;padding:16px;overflow-wrap:anywhere}
    .box h2{font-size:17px;color:#8b1a1a;margin:0 0 8px}.wide{grid-column:1 / -1}
    pre{white-space:pre-wrap;word-break:break-word;font:14px/1.4 ui-monospace,monospace;margin:0}
    .foot{font-size:13px;color:#52616d;margin-top:15px}
    </style>"""
    markup += "<h1>真实模型请求与返回 · 脱敏抓包</h1>"
    markup += "<div class='sub'>OpenRouter /chat/completions · HTTP 200 · 2026-10-28</div><div class='grid'>"
    for title, value, wide in (("请求参数", json.dumps(properties, ensure_ascii=False, indent=2), False),
                               ("鉴权", "Authorization: Bearer [REDACTED]", False),
                               ("system：应用 + 模板 + Skill", system, True),
                               ("user：检索片段 + MCP 结果 + 问题", user, True),
                               ("模型返回文本（由 SSE 增量拼接）", assembled, True),
                               ("原始 SSE 结构", stream_excerpt, True)):
        markup += f"<section class='box{' wide' if wide else ''}'><h2>{html.escape(title)}</h2><pre>{html.escape(value)}</pre></section>"
    markup += "</div><div class='foot'>来源：llm-trace-connected.json；本图由本地代理原始记录生成，未展示 API Key。</div>"
    page = browser.new_page(viewport={"width": 1100, "height": 900}, device_scale_factor=1)
    page.set_content(markup)
    page.screenshot(path=str(EVIDENCE / "07-llm-request-response.png"), full_page=True)
    page.close()
    return trace


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    teacher = bearer("teacher_a", "report-teacher-password")
    student = bearer("student_a", "report-student-password")
    teacher_token, student_token = teacher["access_token"], student["access_token"]
    class_id = teacher["active_class_id"]
    uploaded = api(f"/api/classes/{class_id}/materials", teacher_token, multipart={
        "file": ("algebra.md", "代数方程解题步骤：先列出已知条件，再对等式两边做相同运算。".encode())})
    assert uploaded["material"]["name"] == "algebra.md"
    prompt = api("/api/prompts", teacher_token, data={"app_key": "solver", "name": "苏格拉底引导",
        "content": "你是苏格拉底式解题教练。先追问：{{question}}；每次只提示一步。"})["prompt"]
    server = api("/api/mcp/servers", teacher_token, data={"name": "campus_tools",
        "base_url": "http://127.0.0.1:8767", "auth_token": "report-only-mcp-token"})["server"]
    connected = api(f"/api/mcp/servers/{server['id']}/connect", teacher_token, data={})["server"]
    assert {x["name"] for x in connected["tools"]} == {"formula_hint", "unit_convert"}
    skill = api("/api/skills", teacher_token, multipart={
        "name": "公式引导演示", "description": "只给下一步提示",
        "tools": '["knowledge_search","formula_hint@campus_tools"]',
        "file": ("guide.md", "先引导学生列出已知条件，然后只给下一步提示；不要直接给完整答案。".encode())})["skill"]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=BROWSER, args=["--no-sandbox"])
        teacher_page = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
        login_page(teacher_page, "teacher_a", "report-teacher-password")
        teacher_page.screenshot(path=str(EVIDENCE / "01-running-dashboard.png"))
        teacher_page.goto(BASE + "/apps")
        teacher_page.wait_for_function("document.querySelectorAll('#prompt-edit option').length > 1")
        teacher_page.screenshot(path=str(EVIDENCE / "02-app-platform.png"))
        teacher_page.locator("#prompt-edit").select_option(str(prompt["id"]))
        teacher_page.locator("#prompt-form").screenshot(path=str(EVIDENCE / "03-prompt-template.png"))
        teacher_page.locator("#skill-edit").select_option(str(skill["id"]))
        teacher_page.locator("#skill-form").screenshot(path=str(EVIDENCE / "04-uploaded-skill.png"))
        upload_form = teacher_page.locator("#skill-form")
        teacher_page.locator("#skill-edit").select_option("")
        upload_form.locator("[name=name]").fill("上传演示技能")
        upload_form.locator("[name=description]").fill("教师上传的 Markdown 引导技能")
        upload_form.locator("[name=tools]").fill("knowledge_search")
        upload_form.locator("[name=file]").set_input_files({
            "name": "demo-upload.md", "mimeType": "text/markdown",
            "buffer": "先问学生已知条件，再提示下一步。".encode(),
        })
        upload_form.screenshot(path=str(EVIDENCE / "04a-skill-upload-example.png"))
        upload_form.locator("button").click()
        teacher_page.wait_for_function("document.querySelector('#chat-status').textContent.includes('技能已保存')")
        teacher_page.locator("#skill-edit").select_option(label="上传演示技能")
        upload_form.screenshot(path=str(EVIDENCE / "04b-skill-upload-saved.png"))

        student_page = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
        login_page(student_page, "student_a", "report-student-password")
        student_page.goto(BASE + f"/classes/{class_id}/retrieval")
        student_page.locator("#retrieval-query").fill("代数方程解题步骤")
        student_page.locator('input[name="mode"][value="keyword"]').check()
        student_page.locator('#retrieval-form button[type="submit"]').click()
        student_page.locator("#retrieval-results .search-result").wait_for(timeout=15000)
        student_page.locator(".retrieval-main").screenshot(path=str(EVIDENCE / "05-knowledge-retrieval.png"))

        student_page.goto(BASE + "/apps")
        student_page.wait_for_function("document.querySelectorAll('#app-key option').length === 3")
        student_page.locator("#app-key").select_option("solver")
        student_page.locator("#prompt-id").select_option(str(prompt["id"]))
        student_page.locator("#skill-id").select_option(f"skill:{skill['id']}")
        student_page.locator("#chat-start").screenshot(path=str(EVIDENCE / "06-selected-app-prompt-skill.png"))
        student_page.locator("#chat-start button").click()
        student_page.locator("#chat-panel").wait_for()
        student_page.locator("#chat-query").fill("代数方程解题步骤")
        student_page.locator("#chat-send button").click()
        student_page.wait_for_function("document.querySelector('#chat-status').textContent === '完成'", timeout=120000)
        assert "formula_hint@campus_tools (ok)" in student_page.locator("#chat-tools").inner_text()
        student_page.locator("#chat-panel").screenshot(path=str(EVIDENCE / "08-chat-answer-mcp.png"))
        trace = capture_wire(browser)
        assert "苏格拉底" in trace["request_body"]["messages"][0]["content"]

        teacher_page.goto(BASE + "/apps")
        teacher_page.wait_for_function("document.querySelector('#mcp-audits').textContent.includes('formula_hint@campus_tools')")
        teacher_page.locator("#mcp-audits").locator("xpath=..").screenshot(path=str(EVIDENCE / "09-mcp-discovery-audit.png"))
        teacher_page.goto(BASE + "/docs")
        teacher_page.locator(".swagger-ui .opblock").first.wait_for(timeout=30000)
        teacher_page.screenshot(path=str(EVIDENCE / "10-swagger-api.png"))

        student_page.locator("#chat-query").fill("光合作用")
        student_page.locator("#chat-send button").click()
        student_page.wait_for_function("document.querySelector('#chat-status').textContent === '完成'", timeout=15000)
        assert "资料中未找到相关内容" in student_page.locator("#chat-history").inner_text()
        student_page.locator("#chat-panel").screenshot(path=str(EVIDENCE / "11-no-evidence-no-model.png"))

        teacher_page.goto(BASE + "/apps")
        teacher_page.wait_for_function("document.querySelector('#mcp-servers').textContent.includes('已连接')")
        teacher_page.locator("#mcp-servers button").first.click()
        teacher_page.wait_for_function("document.querySelector('#mcp-servers').textContent.includes('未连接')")
        student_page.locator("#chat-query").fill("代数方程解题步骤")
        student_page.locator("#chat-send button").click()
        student_page.wait_for_function("document.querySelector('#chat-status').textContent === '完成'", timeout=120000)
        assert "formula_hint@campus_tools (denied)" in student_page.locator("#chat-tools").inner_text()
        student_page.locator("#chat-tools").scroll_into_view_if_needed()
        student_page.screenshot(path=str(EVIDENCE / "12-disconnected-denied.png"))
        teacher_page.reload()
        teacher_page.wait_for_function("document.querySelector('#mcp-audits').textContent.includes('denied')")
        teacher_page.locator("#mcp-audits").locator("xpath=..").screenshot(path=str(EVIDENCE / "13-mcp-denied-audit.png"))
        browser.close()

    assert len(list(EVIDENCE.glob("*.png"))) >= 11
    print("Captured 11+ real screenshots, a redacted model trace, and MCP ok/denied evidence.")


if __name__ == "__main__":
    main()
