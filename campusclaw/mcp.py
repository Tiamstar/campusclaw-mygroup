import json
import re
from urllib.parse import urlsplit

from flask import Blueprint, abort, g, jsonify, request
from sqlalchemy import select

from .auth import protected, require_csrf
from .models import MCPAudit, MCPServer, db
from .retrieval import DependencyUnavailable, JsonGateway, active_class_id

mcp = Blueprint("mcp", __name__)
NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def public_server(server):
    return {"id": server.id, "name": server.name, "base_url": server.base_url,
            "connected": server.connected, "tools": json.loads(server.tools_json)}


def gateway(server):
    return JsonGateway(server.base_url, server.auth_token, timeout=5, retries=0)


def rpc(server, method, params=None):
    result = gateway(server).post("/mcp", {"jsonrpc": "2.0", "id": 1, "method": method,
                                           "params": params or {}})
    if not isinstance(result, dict) or "error" in result or "result" not in result:
        raise DependencyUnavailable("invalid_mcp_response")
    return result["result"]


def validate_tool_refs(refs, class_id):
    if not isinstance(refs, list) or len(refs) > 8 or any(not isinstance(x, str) for x in refs):
        abort(400)
    for ref in refs:
        if ref == "knowledge_search":
            continue
        parts = ref.split("@")
        if len(parts) != 2 or not all(NAME.fullmatch(x) for x in parts):
            abort(400)
        tool, server_name = parts
        server = db.session.execute(select(MCPServer).where(
            MCPServer.class_id == class_id, MCPServer.name == server_name,
        )).scalar_one_or_none()
        if not server or not server.connected or tool not in [x["name"] for x in json.loads(server.tools_json)]:
            abort(400, description="mcp_tool_not_connected_or_discovered")


def call_tool(ref, arguments, class_id, user_id):
    tool, server_name = ref.split("@", 1)
    server = db.session.execute(select(MCPServer).where(
        MCPServer.class_id == class_id, MCPServer.name == server_name,
    )).scalar_one_or_none()
    status = "denied"
    content = ""
    if server and server.connected and tool in [x["name"] for x in json.loads(server.tools_json)]:
        try:
            result = rpc(server, "tools/call", {"name": tool, "arguments": arguments})
            content = "\n".join(x["text"] for x in result["content"] if x.get("type") == "text")[:4000]
            status = "ok" if content else "error"
        except (DependencyUnavailable, KeyError, TypeError, ValueError):
            status = "error"
    db.session.add(MCPAudit(class_id=class_id, user_id=user_id, tool_ref=ref, status=status))
    db.session.commit()
    return {"tool": ref, "status": status, "content": content}


@mcp.route("/api/mcp/servers", methods=["GET", "POST"])
@protected()
def servers():
    class_id = active_class_id()
    if request.method == "GET":
        rows = db.session.execute(select(MCPServer).where(MCPServer.class_id == class_id)).scalars()
        return jsonify(servers=[public_server(row) for row in rows])
    if g.user.role != "teacher":
        abort(403)
    require_csrf()
    data = request.get_json(silent=True) or {}
    name, base_url, token = data.get("name"), data.get("base_url"), data.get("auth_token")
    if not isinstance(name, str) or not NAME.fullmatch(name) or not isinstance(base_url, str) or not isinstance(token, str):
        abort(400)
    parsed = urlsplit(base_url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ("", "/") or len(base_url) > 500 or not token):
        abort(400)
    if db.session.execute(select(MCPServer.id).where(
        MCPServer.class_id == class_id, MCPServer.name == name,
    )).scalar_one_or_none():
        return jsonify(error="server_name_exists"), 409
    server = MCPServer(class_id=class_id, name=name, base_url=base_url.rstrip("/"), auth_token=token)
    db.session.add(server)
    db.session.commit()
    return jsonify(server=public_server(server)), 201


def owned_server(server_id):
    server = db.session.get(MCPServer, server_id)
    if not server or server.class_id != active_class_id():
        abort(404)
    return server


@mcp.post("/api/mcp/servers/<int:server_id>/connect")
@protected(teacher=True)
def connect(server_id):
    require_csrf()
    server = owned_server(server_id)
    try:
        handshake = rpc(server, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                                "clientInfo": {"name": "CampusClaw", "version": "1"}})
        if not isinstance(handshake, dict) or "protocolVersion" not in handshake:
            raise DependencyUnavailable("invalid_mcp_handshake")
        discovered = rpc(server, "tools/list")
        tools = discovered["tools"]
        if not isinstance(tools, list) or any(
            not isinstance(x, dict) or not isinstance(x.get("name"), str)
            or not NAME.fullmatch(x["name"]) for x in tools
        ):
            raise DependencyUnavailable("invalid_mcp_tools")
    except (DependencyUnavailable, KeyError, TypeError):
        return jsonify(error="mcp_connection_failed"), 502
    server.tools_json = json.dumps(tools, ensure_ascii=False)
    server.connected = True
    db.session.commit()
    return jsonify(server=public_server(server))


@mcp.post("/api/mcp/servers/<int:server_id>/disconnect")
@protected(teacher=True)
def disconnect(server_id):
    require_csrf()
    server = owned_server(server_id)
    server.connected = False
    server.tools_json = "[]"
    db.session.commit()
    return jsonify(server=public_server(server))


@mcp.get("/api/mcp/servers/<int:server_id>/tools")
@protected()
def tools(server_id):
    return jsonify(tools=public_server(owned_server(server_id))["tools"])


@mcp.get("/api/mcp/audits")
@protected(teacher=True)
def audits():
    rows = db.session.execute(select(MCPAudit).where(MCPAudit.class_id == active_class_id())
                              .order_by(MCPAudit.id.desc()).limit(100)).scalars()
    return jsonify(audits=[{"tool": x.tool_ref, "status": x.status, "user_id": x.user_id,
                            "created_at": x.created_at.isoformat() + "Z"} for x in rows])
