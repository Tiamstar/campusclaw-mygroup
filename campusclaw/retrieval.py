import json
import math
import re
import time
import urllib.error
import urllib.request

import click
from flask import Blueprint, abort, current_app, g, jsonify, request
from sqlalchemy import delete, func, select, text, update

from .auth import protected, require_csrf
from .chunking import split_text
from .models import ClassMembership, KnowledgeChunk, KnowledgeDocument, Material, db


retrieval = Blueprint("retrieval", __name__)
NOT_FOUND_MESSAGE = "资料中未找到相关内容"


def valid_citations(answer, source_count):
    """Require at least one citation and reject numbers outside this request's hits."""
    markers = {int(number) for number in re.findall(r"\[(\d+)\]", answer)}
    return bool(markers) and all(1 <= number <= source_count for number in markers)


class DependencyUnavailable(RuntimeError):
    pass


class JsonGateway:
    def __init__(self, base_url, api_key="", timeout=10, api_key_header="Authorization", retries=2):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.api_key_header = api_key_header
        self.retries = retries

    def post(self, path, payload):
        return self.request("POST", path, payload)

    def request(self, method, path, payload=None, allow_not_found=False):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers[self.api_key_header] = (
                f"Bearer {self.api_key}" if self.api_key_header == "Authorization" else self.api_key
            )
        req = urllib.request.Request(
            self.base_url + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers=headers,
            method=method,
        )
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as error:
                if allow_not_found and error.code == 404:
                    return None
                if error.code != 429 and error.code < 500:
                    raise DependencyUnavailable(f"http_{error.code}") from error
                last_error = error
            except (OSError, ValueError) as error:
                last_error = error
            if attempt < self.retries:
                time.sleep(0.2 * (2 ** attempt))
        raise DependencyUnavailable(type(last_error).__name__) from last_error


class EmbeddingClient:
    def __init__(self, gateway, model, dimensions=None):
        self.gateway = gateway
        self.model = model
        self.dimensions = dimensions

    def embed(self, values):
        response = self.gateway.post("/embeddings", {"model": self.model, "input": values})
        try:
            ordered = sorted(response["data"], key=lambda item: item["index"])
            vectors = [item["embedding"] for item in ordered]
        except (KeyError, TypeError) as error:
            raise DependencyUnavailable("invalid_embedding_response") from error
        if len(vectors) != len(values) or any(not isinstance(v, list) or not v for v in vectors):
            raise DependencyUnavailable("invalid_embedding_response")
        expected = self.dimensions or len(vectors[0])
        if any(len(vector) != expected or not all(math.isfinite(float(x)) for x in vector) for vector in vectors):
            raise DependencyUnavailable("invalid_embedding_dimensions")
        return vectors


class QdrantClient:
    def __init__(self, gateway, collection):
        self.gateway = gateway
        self.collection = collection

    def upsert(self, points):
        if not points:
            return
        self.ensure_collection(len(points[0]["vector"]))
        self.gateway.request("PUT", f"/collections/{self.collection}/points?wait=true", {"points": points})

    def ensure_collection(self, dimensions):
        existing = self.gateway.request(
            "GET", f"/collections/{self.collection}", allow_not_found=True,
        )
        if existing is None:
            self.gateway.request("PUT", f"/collections/{self.collection}", {
                "vectors": {"size": dimensions, "distance": "Cosine"},
            })
            self.gateway.request("PUT", f"/collections/{self.collection}/index", {
                "field_name": "class_id", "field_schema": "integer",
            })

    def available(self):
        try:
            self.gateway.request("GET", "/collections")
            return True
        except DependencyUnavailable:
            return False

    def search(self, vector, class_id, limit=40):
        response = self.gateway.post(f"/collections/{self.collection}/points/search", {
            "vector": vector,
            "limit": limit,
            "with_payload": False,
            "filter": {"must": [{"key": "class_id", "match": {"value": class_id}}]},
        })
        try:
            return [(int(point["id"]), float(point["score"])) for point in response["result"]]
        except (KeyError, TypeError, ValueError) as error:
            raise DependencyUnavailable("invalid_qdrant_response") from error

    def delete(self, ids):
        if ids:
            self.gateway.post(
                f"/collections/{self.collection}/points/delete?wait=true", {"points": ids},
            )

    def list_ids(self):
        ids = []
        offset = None
        while True:
            payload = {"limit": 256, "with_payload": False, "with_vector": False}
            if offset is not None:
                payload["offset"] = offset
            response = self.gateway.post(f"/collections/{self.collection}/points/scroll", payload)
            try:
                result = response["result"]
                ids.extend(int(point["id"]) for point in result["points"])
                offset = result.get("next_page_offset")
            except (KeyError, TypeError, ValueError) as error:
                raise DependencyUnavailable("invalid_qdrant_scroll_response") from error
            if offset is None:
                return ids


class ChatClient:
    def __init__(self, gateway, model):
        self.gateway = gateway
        self.model = model

    def answer(self, messages):
        response = self.gateway.post("/chat/completions", {
            "model": self.model, "messages": messages, "stream": False,
        })
        try:
            return str(response["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as error:
            raise DependencyUnavailable("invalid_chat_response") from error

    def stream(self, messages):
        payload = {"model": self.model, "messages": messages, "stream": True,
                   "temperature": 0.2, "max_tokens": 800}
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if self.gateway.api_key:
            headers["Authorization"] = f"Bearer {self.gateway.api_key}"
        req = urllib.request.Request(self.gateway.base_url + "/chat/completions",
                                     data=json.dumps(payload, ensure_ascii=False).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.gateway.timeout) as response:
                for raw in response:
                    line = raw.decode("utf-8").strip()
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    event = json.loads(line[6:])
                    content = event.get("choices", [{}])[0].get("delta", {}).get("content")
                    if content:
                        yield content
        except (OSError, ValueError, KeyError, IndexError) as error:
            raise DependencyUnavailable("chat_stream_failed") from error


def initialize_chunk_index():
    connection = db.session.connection()
    existing = connection.exec_driver_sql(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='knowledge_chunks_fts'"
    ).first()
    connection.exec_driver_sql(
        "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5("
        "chunk_text, content='knowledge_chunks', content_rowid='id', tokenize='trigram')"
    )
    if not existing:
        connection.exec_driver_sql("INSERT INTO knowledge_chunks_fts(knowledge_chunks_fts) VALUES ('rebuild')")
    connection.exec_driver_sql(
        "CREATE TRIGGER IF NOT EXISTS chunks_fts_insert AFTER INSERT ON knowledge_chunks BEGIN "
        "INSERT INTO knowledge_chunks_fts(rowid, chunk_text) VALUES (new.id, new.chunk_text); END"
    )
    connection.exec_driver_sql(
        "CREATE TRIGGER IF NOT EXISTS chunks_fts_delete AFTER DELETE ON knowledge_chunks BEGIN "
        "INSERT INTO knowledge_chunks_fts(knowledge_chunks_fts, rowid, chunk_text) "
        "VALUES ('delete', old.id, old.chunk_text); END"
    )
    connection.exec_driver_sql(
        "CREATE TRIGGER IF NOT EXISTS chunks_fts_update AFTER UPDATE OF chunk_text ON knowledge_chunks BEGIN "
        "INSERT INTO knowledge_chunks_fts(knowledge_chunks_fts, rowid, chunk_text) "
        "VALUES ('delete', old.id, old.chunk_text); "
        "INSERT INTO knowledge_chunks_fts(rowid, chunk_text) VALUES (new.id, new.chunk_text); END"
    )
    db.session.commit()


def _embedding_client(required=False):
    configured = current_app.extensions.get("embedding_client")
    if configured:
        return configured
    url = current_app.config.get("EMBEDDING_API_URL", "")
    if not url:
        if required:
            raise DependencyUnavailable("embedding_not_configured")
        return None
    return EmbeddingClient(
        JsonGateway(
            url, current_app.config.get("EMBEDDING_API_KEY", ""), current_app.config["MODEL_TIMEOUT"],
            retries=current_app.config["MODEL_RETRIES"],
        ),
        current_app.config["EMBEDDING_MODEL"], current_app.config.get("EMBEDDING_DIMENSIONS"),
    )


def _qdrant_client(required=False):
    configured = current_app.extensions.get("qdrant_client")
    if configured:
        return configured
    url = current_app.config.get("QDRANT_URL", "")
    if not url:
        if required:
            raise DependencyUnavailable("qdrant_not_configured")
        return None
    return QdrantClient(
        JsonGateway(
            url, current_app.config.get("QDRANT_API_KEY", ""), current_app.config["MODEL_TIMEOUT"],
            api_key_header="api-key", retries=current_app.config["MODEL_RETRIES"],
        ),
        current_app.config["QDRANT_COLLECTION"],
    )


def _chat_client():
    configured = current_app.extensions.get("chat_client")
    if configured:
        return configured
    url = current_app.config.get("CHAT_API_URL", "")
    if not url:
        raise DependencyUnavailable("chat_not_configured")
    return ChatClient(
        JsonGateway(
            url, current_app.config.get("CHAT_API_KEY", ""), current_app.config["MODEL_TIMEOUT"],
            retries=current_app.config["MODEL_RETRIES"],
        ),
        current_app.config["CHAT_MODEL"],
    )


def active_class_id():
    memberships = list(db.session.execute(
        select(ClassMembership.class_id).where(ClassMembership.user_id == g.user.id)
    ).scalars())
    chosen = g.login_session.active_class_id
    if chosen in memberships:
        return chosen
    if len(memberships) == 1:
        g.login_session.active_class_id = memberships[0]
        db.session.commit()
        return memberships[0]
    abort(409)


@retrieval.post("/api/session/active-class")
@protected()
def choose_active_class():
    require_csrf()
    payload = request.get_json(silent=True) or {}
    try:
        chosen = int(payload.get("class_id"))
    except (TypeError, ValueError):
        abort(400)
    membership = db.session.execute(select(ClassMembership.id).where(
        ClassMembership.user_id == g.user.id, ClassMembership.class_id == chosen,
    )).scalar_one_or_none()
    if membership is None:
        abort(404)
    g.login_session.active_class_id = chosen
    db.session.commit()
    return jsonify(active_class_id=chosen)


@retrieval.get("/classes/<int:class_id>/retrieval")
@protected(api=False)
def retrieval_page(class_id):
    from flask import render_template
    from .auth import csrf_token
    from .models import Class

    membership = db.session.execute(select(ClassMembership.id).where(
        ClassMembership.user_id == g.user.id, ClassMembership.class_id == class_id,
    )).scalar_one_or_none()
    if membership is None:
        abort(404)
    g.login_session.active_class_id = class_id
    db.session.commit()
    records = db.session.execute(select(Material).where(
        Material.class_id == class_id, Material.status == "ready",
    ).order_by(Material.created_at.desc())).scalars().all()
    return render_template(
        "retrieval.html", classroom=db.session.get(Class, class_id), records=records,
        user=g.user, csrf=csrf_token(),
    )


def index_document(document, strategy=None):
    chunks = split_text(document.body, strategy)
    if not chunks:
        raise ValueError("document has no indexable text")
    generation = (db.session.execute(select(func.max(KnowledgeChunk.generation)).where(
        KnowledgeChunk.knowledge_document_id == document.id,
    )).scalar_one() or 0) + 1
    records = [KnowledgeChunk(
        knowledge_document_id=document.id,
        material_id=document.material_id,
        class_id=document.class_id,
        generation=generation,
        chunk_index=chunk.index,
        chunk_text=chunk.text,
        start_offset=chunk.start,
        end_offset=chunk.end,
        offset_basis=chunk.offset_basis,
        index_status="pending",
        vector_status="pending",
        is_active=False,
    ) for chunk in chunks]
    db.session.add_all(records)
    db.session.commit()

    embedding = _embedding_client()
    qdrant = _qdrant_client()
    try:
        if embedding and qdrant:
            vectors = embedding.embed([record.chunk_text for record in records])
            qdrant.upsert([{
                "id": record.id,
                "vector": vector,
                "payload": {
                    "class_id": record.class_id,
                    "material_id": record.material_id,
                    "knowledge_document_id": record.knowledge_document_id,
                    "chunk_id": record.id,
                    "chunk_index": record.chunk_index,
                },
            } for record, vector in zip(records, vectors)])
            for record in records:
                record.vector_status = "ready"
        else:
            for record in records:
                record.vector_status = "disabled"
        old_ids = list(db.session.execute(select(KnowledgeChunk.id).where(
            KnowledgeChunk.knowledge_document_id == document.id,
            KnowledgeChunk.is_active.is_(True),
        )).scalars())
        db.session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.id.in_(old_ids)))
        for record in records:
            record.index_status = "ready"
            record.is_active = True
        db.session.commit()
        if qdrant:
            qdrant.delete(old_ids)
        return records
    except Exception:
        db.session.rollback()
        db.session.execute(update(KnowledgeChunk).where(
            KnowledgeChunk.knowledge_document_id == document.id,
            KnowledgeChunk.generation == generation,
        ).values(index_status="failed", vector_status="failed", is_active=False))
        db.session.commit()
        if qdrant:
            try:
                qdrant.delete([record.id for record in records])
            except Exception:
                pass
        raise


def ensure_document_index(document):
    exists = db.session.execute(select(KnowledgeChunk.id).where(
        KnowledgeChunk.knowledge_document_id == document.id,
        KnowledgeChunk.is_active.is_(True),
        KnowledgeChunk.index_status == "ready",
    ).limit(1)).first()
    if not exists:
        return index_document(document)
    return []


def register_retrieval_commands(app):
    @app.cli.command("reindex-knowledge")
    @click.option("--force", is_flag=True, help="Rebuild documents that already have an active index.")
    def reindex_knowledge(force):
        indexed = failed = skipped = 0
        for document in db.session.execute(select(KnowledgeDocument).order_by(KnowledgeDocument.id)).scalars():
            if not document.body.strip():
                skipped += 1
                continue
            try:
                records = index_document(document) if force else ensure_document_index(document)
                indexed += bool(records)
                skipped += not bool(records)
            except Exception as error:
                current_app.logger.warning(
                    "Retrieval indexing failed for document %s: %s", document.id, type(error).__name__,
                )
                failed += 1
        click.echo(f"Indexed {indexed}; skipped {skipped}; failed {failed}")

    @app.cli.command("cleanup-orphan-vectors")
    def cleanup_orphan_vectors():
        qdrant = _qdrant_client(required=True)
        referenced = set(db.session.execute(select(KnowledgeChunk.id).where(
            KnowledgeChunk.vector_status == "ready",
        )).scalars())
        orphaned = sorted(set(qdrant.list_ids()) - referenced)
        qdrant.delete(orphaned)
        click.echo(f"Removed {len(orphaned)} orphan vectors")


def _query_value(payload):
    raw = payload.get("query", "")
    if not isinstance(raw, str):
        abort(400)
    value = raw.strip()
    if not value or len(value) > 500 or any(ord(char) < 32 or ord(char) == 127 for char in raw):
        abort(400)
    return value


def _rows_for_ids(ids, class_id):
    if not ids:
        return {}
    rows = db.session.execute(select(KnowledgeChunk, KnowledgeDocument, Material).join(
        KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.knowledge_document_id,
    ).join(Material, Material.id == KnowledgeChunk.material_id).where(
        KnowledgeChunk.id.in_(ids),
        KnowledgeChunk.class_id == class_id,
        KnowledgeChunk.is_active.is_(True),
        KnowledgeChunk.index_status == "ready",
        KnowledgeDocument.class_id == class_id,
        Material.class_id == class_id,
        Material.status == "ready",
    )).all()
    return {chunk.id: (chunk, document, material) for chunk, document, material in rows}


def _keyword_ids(query, class_id, limit=40):
    if len(query) >= 3:
        phrase = '"' + query.replace('"', '""') + '"'
        rows = db.session.execute(text(
            "SELECT c.id, bm25(knowledge_chunks_fts) AS score "
            "FROM knowledge_chunks_fts JOIN knowledge_chunks c ON c.id = knowledge_chunks_fts.rowid "
            "JOIN materials m ON m.id = c.material_id "
            "WHERE knowledge_chunks_fts MATCH :phrase AND c.class_id = :class_id "
            "AND c.is_active = 1 AND c.index_status = 'ready' AND m.class_id = :class_id "
            "AND m.status = 'ready' ORDER BY score ASC LIMIT :limit"
        ), {"phrase": phrase, "class_id": class_id, "limit": limit}).all()
        return [(row[0], float(-row[1])) for row in rows]
    rows = db.session.execute(select(KnowledgeChunk.id).join(
        Material, Material.id == KnowledgeChunk.material_id,
    ).where(
        KnowledgeChunk.class_id == class_id,
        KnowledgeChunk.is_active.is_(True),
        KnowledgeChunk.index_status == "ready",
        Material.class_id == class_id,
        Material.status == "ready",
        func.instr(func.lower(KnowledgeChunk.chunk_text), query.lower()) > 0,
    ).limit(limit)).all()
    return [(row[0], 1.0) for row in rows]


def _vector_ids(query, class_id, limit=40):
    embedding = _embedding_client(required=True)
    qdrant = _qdrant_client(required=True)
    vector = embedding.embed([query])[0]
    candidates = [(chunk_id, score) for chunk_id, score in qdrant.search(vector, class_id, limit) if score >= 0.35]
    rows = _rows_for_ids([item[0] for item in candidates], class_id)
    return [(chunk_id, score) for chunk_id, score in candidates if chunk_id in rows]


def search_chunks(query, mode, class_id, limit=20):
    if mode not in {"keyword", "vector", "hybrid"}:
        abort(400)
    keyword = _keyword_ids(query, class_id) if mode in {"keyword", "hybrid"} else []
    vector = _vector_ids(query, class_id) if mode in {"vector", "hybrid"} else []
    keyword_map = {chunk_id: (rank, score) for rank, (chunk_id, score) in enumerate(keyword, 1)}
    vector_map = {chunk_id: (rank, score) for rank, (chunk_id, score) in enumerate(vector, 1)}
    ids = set(keyword_map) | set(vector_map)
    rows = _rows_for_ids(ids, class_id)
    ranked = []
    for chunk_id in ids & rows.keys():
        kr = keyword_map.get(chunk_id)
        vr = vector_map.get(chunk_id)
        rrf = (1 / (60 + kr[0]) if kr else 0) + (1 / (60 + vr[0]) if vr else 0)
        sort_score = rrf if mode == "hybrid" else (kr[1] if kr else vr[1])
        ranked.append((chunk_id, sort_score, kr, vr, rrf))
    ranked.sort(key=lambda item: (-item[1], item[0]))
    hits = []
    for chunk_id, _, kr, vr, rrf in ranked[:limit]:
        chunk, document, material = rows[chunk_id]
        hits.append({
            "material_id": material.id,
            "title": document.title,
            "chunk_id": chunk.id,
            "chunk_index": chunk.chunk_index,
            "start_offset": chunk.start_offset,
            "end_offset": chunk.end_offset,
            "offset_basis": chunk.offset_basis,
            "excerpt": chunk.chunk_text[:240],
            "material_url": f"/classes/{class_id}/materials/{material.id}/download",
            "keyword_rank": kr[0] if kr else None,
            "keyword_score": kr[1] if kr else None,
            "vector_rank": vr[0] if vr else None,
            "vector_score": vr[1] if vr else None,
            "rrf_score": rrf if mode == "hybrid" else None,
            "_text": chunk.chunk_text,
        })
    return hits


def _public_hit(hit):
    return {key: value for key, value in hit.items() if not key.startswith("_")}


@retrieval.post("/api/retrieval/search")
@protected()
def search_api():
    payload = request.get_json(silent=True) or {}
    query = _query_value(payload)
    mode = payload.get("mode", "hybrid")
    try:
        hits = search_chunks(query, mode, active_class_id())
    except DependencyUnavailable:
        return jsonify(error="retrieval_dependency_unavailable"), 503
    return jsonify(
        mode=mode,
        message=None if hits else NOT_FOUND_MESSAGE,
        hits=[_public_hit(hit) for hit in hits],
    )


@retrieval.post("/api/materials/<int:material_id>/index")
@protected(teacher=True)
def rebuild_index(material_id):
    require_csrf()
    class_id = active_class_id()
    row = db.session.execute(select(KnowledgeDocument).join(
        Material, Material.id == KnowledgeDocument.material_id,
    ).where(
        Material.id == material_id,
        Material.class_id == class_id,
        KnowledgeDocument.class_id == class_id,
    )).scalar_one_or_none()
    if not row:
        abort(404)
    payload = request.get_json(silent=True) or {}
    try:
        chunks = index_document(row, payload.get("strategy"))
    except ValueError:
        abort(400)
    except DependencyUnavailable:
        return jsonify(error="retrieval_dependency_unavailable"), 503
    return jsonify(material_id=material_id, chunk_count=len(chunks))


@retrieval.post("/api/ask")
@protected()
def ask():
    payload = request.get_json(silent=True) or {}
    query = _query_value(payload)
    try:
        hits = search_chunks(query, "hybrid", active_class_id(), limit=4)
        if not hits:
            return jsonify(answer=NOT_FOUND_MESSAGE, citations=[])
        context = "\n\n".join(
            f"[{number}] 材料：{hit['title']}；切片：{hit['chunk_index']}\n{hit['_text']}"
            for number, hit in enumerate(hits, 1)
        )
        answer = _chat_client().answer([
            {"role": "system", "content": "仅依据给定资料简短回答；用 [1] 等编号标注出处，不得使用资料外知识。"},
            {"role": "user", "content": f"资料：\n{context}\n\n问题：{query}"},
        ])
    except DependencyUnavailable:
        return jsonify(error="retrieval_dependency_unavailable"), 503
    if not valid_citations(answer, len(hits)):
        return jsonify(error="invalid_model_citation"), 502
    return jsonify(answer=answer, citations=[_public_hit(hit) for hit in hits])
