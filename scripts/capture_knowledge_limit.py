"""Verify that six matching documents yield only four chunks in one LLM call."""
import html
import json
import re
import shutil
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.capture_report_evidence import BASE, BROWSER, EVIDENCE, api, bearer


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    teacher = bearer("teacher_a", "report-teacher-password")
    student = bearer("student_a", "report-student-password")
    class_id = teacher["active_class_id"]
    titles = []
    for index in range(1, 7):
        title = f"limit-{index:02d}.md"
        body = f"知识库截断验证：第 {index} 份资料。请先整理已知条件，再检查解题步骤。"
        response = api(f"/api/classes/{class_id}/materials", teacher["access_token"],
                       multipart={"file": (title, body.encode())})
        assert response["material"]["name"] == title
        titles.append(title)
    conversation = api("/api/conversations", student["access_token"],
                       data={"app_key": "tutor"})["conversation"]
    path = f"/api/conversations/{conversation['id']}/messages"
    payload = json.dumps({"query": "知识库截断验证"}, ensure_ascii=False).encode()
    request = urllib.request.Request(BASE + path, data=payload,
        headers={"Authorization": "Bearer " + student["access_token"],
                 "Content-Type": "application/json"})
    trace_path = EVIDENCE / "llm-trace.json"
    old_mtime = trace_path.stat().st_mtime_ns if trace_path.exists() else 0
    with urllib.request.urlopen(request, timeout=120) as response:
        browser_sse = response.read().decode()
    assert 'event: done' in browser_sse and '"status": "ok"' in browser_sse
    for _ in range(30):
        if trace_path.exists() and trace_path.stat().st_mtime_ns != old_mtime:
            break
        time.sleep(.1)
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["upstream_status"] == 200
    message = trace["request_body"]["messages"][-1]["content"]
    selected = re.findall(r"(?m)^\[(\d+)\] (limit-\d+\.md) / 切片", message)
    assert len(selected) == 4, selected
    selected_titles = [name for _, name in selected]
    omitted = sorted(set(titles) - set(selected_titles))
    assert len(omitted) == 2
    shutil.copyfile(trace_path, EVIDENCE / "llm-trace-knowledge-limit.json")
    summary = {"uploaded_documents": titles, "sent_chunk_count": len(selected),
               "sent_titles": selected_titles, "omitted_titles": omitted,
               "query": "知识库截断验证", "model": trace["request_body"]["model"]}
    (EVIDENCE / "knowledge-limit.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    markup = """<!doctype html><meta charset='utf-8'><style>
    body{font:18px/1.55 system-ui,sans-serif;background:#f5f5f5;color:#20242a;margin:30px}
    h1{font-size:27px;margin:0 0 8px}.sub{color:#56616d;margin-bottom:22px}
    .flow{display:grid;grid-template-columns:1fr 80px 1fr;align-items:center;gap:10px}
    .box{background:white;border:1px solid #d9dfe5;border-radius:10px;padding:18px}
    .box h2{font-size:18px;color:#8b1a1a;margin:0 0 10px}.box p{margin:7px 0}
    .arrow{text-align:center;font-size:36px;color:#8b1a1a}.omitted{margin-top:18px;color:#56616d}
    .foot{margin-top:24px;font-size:13px;color:#56616d}
    </style>"""
    markup += "<h1>知识库内容传递范围 · 实测对照</h1>"
    markup += "<div class='sub'>同一班级上传 6 份均命中关键词的材料，提问后检查真实 LLM 请求</div><div class='flow'>"
    markup += "<section class='box'><h2>已上传：6 份材料</h2>" + "".join(f"<p>{html.escape(x)}</p>" for x in titles) + "</section>"
    markup += "<div class='arrow'>→</div><section class='box'><h2>发送给模型：4 个切片</h2>"
    markup += "".join(f"<p>[{html.escape(n)}] {html.escape(name)}</p>" for n, name in selected)
    markup += "</section></div><div class='omitted'>未发送给模型：" + "、".join(omitted) + "</div>"
    markup += "<div class='foot'>来源：knowledge-limit.json 与 llm-trace-knowledge-limit.json；由真实请求体提取，未包含 API Key。</div>"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=BROWSER, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1040, "height": 650})
        page.set_content(markup)
        page.screenshot(path=str(EVIDENCE / "05b-knowledge-limit.png"), full_page=True)
        browser.close()
    print("Six documents uploaded; four chunks sent; two omitted; actual model request verified.")


if __name__ == "__main__":
    main()
