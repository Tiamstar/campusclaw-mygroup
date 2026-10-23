import os
import re
import hmac

from flask import Flask, jsonify, request

app = Flask(__name__)

TOOLS = [
    {"name": "formula_hint", "description": "给出代数方程的下一步提示，不直接求最终答案", "inputSchema": {
        "type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}},
    {"name": "unit_convert", "description": "将米与厘米相互换算", "inputSchema": {
        "type": "object", "properties": {"value": {"type": "number"}, "from_unit": {"type": "string"},
                                       "to_unit": {"type": "string"}}, "required": ["value", "from_unit", "to_unit"]}},
]


@app.get("/health")
def health():
    return jsonify(status="ok")


def error(request_id, code, message):
    return jsonify(jsonrpc="2.0", id=request_id, error={"code": code, "message": message})


@app.post("/mcp")
def mcp():
    expected = os.environ.get("MCP_AUTH_TOKEN", "")
    if not expected or not hmac.compare_digest(request.headers.get("Authorization", ""), f"Bearer {expected}"):
        return error(None, -32001, "Unauthorized"), 401
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error(None, -32600, "Invalid JSON-RPC request"), 400
    request_id = data.get("id")
    if data.get("jsonrpc") != "2.0" or not isinstance(data.get("method"), str):
        return error(request_id, -32600, "Invalid JSON-RPC request"), 400
    method = data["method"]
    if method == "initialize":
        result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "campus-tools", "version": "1.0"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = data.get("params") or {}
        if not isinstance(params, dict) or not isinstance(params.get("arguments"), dict):
            return error(request_id, -32602, "Invalid tool arguments"), 400
        name, args = params.get("name"), params["arguments"]
        if name == "formula_hint":
            question = args.get("question", "")
            if not isinstance(question, str) or not question.strip() or len(question) > 500:
                return error(request_id, -32602, "question must be a nonempty string"), 400
            result = {"content": [{"type": "text", "text": "先找出未知数和等式两边的已知量；尝试对等式两边做相同运算。"}]}
        elif name == "unit_convert":
            try:
                value = float(args["value"])
                source, target = args["from_unit"], args["to_unit"]
                if (source, target) not in {("m", "cm"), ("cm", "m")}:
                    raise ValueError()
                converted = value * (100 if source == "m" else .01)
                if not re.fullmatch(r"-?\d+(?:\.\d+)?", str(args["value"])):
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                return error(request_id, -32602, "Use value and m/cm units"), 400
            result = {"content": [{"type": "text", "text": f"{value:g} {source} = {converted:g} {target}"}]}
        else:
            return error(request_id, -32601, "Unknown tool"), 404
    else:
        return error(request_id, -32601, "Unknown method"), 404
    return jsonify(jsonrpc="2.0", id=request_id, result=result)
