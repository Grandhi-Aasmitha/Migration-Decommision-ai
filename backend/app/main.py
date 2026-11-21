import hashlib
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .assessment import AssessmentService
from .config import Settings
from .database import Database, now
from .extraction import stable_id
from .graph import MemoryGraph, Neo4jGraph
from .graph_view import graph_snapshot
from .ingestion import IngestionService
from .models import AssessmentRequest, ChatRequest, ClarificationAnswer, DocumentType
from .providers import ModelProvider
from .retrieval import RetrievalService

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, graph_override=None):
    settings = settings or Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    uploads = settings.data_dir / "uploads"
    uploads.mkdir(exist_ok=True)
    db = Database(settings.data_dir / "metadata.sqlite")
    graph = graph_override or (MemoryGraph(settings) if settings.graph_backend == "memory" else Neo4jGraph(settings))
    provider = ModelProvider(settings)
    retrieval = RetrievalService(graph, provider, db)
    ingestion = IngestionService(db, graph, provider)
    assessments = AssessmentService(db, retrieval, settings.data_dir / "checkpoints.sqlite")

    @asynccontextmanager
    async def lifespan(app):
        # Memory mode cannot recover evidence across restarts; re-ingest saved uploads.
        if settings.graph_backend == "memory":
            for job in db.list("jobs"):
                if job["status"] == "ready":
                    doc = db.get("documents", job["document_id"])
                    db.save("documents", {**doc, "status": "queued"})
                    db.save("jobs", {**job, "status": "queued", "step": "Restoring demo evidence"})
        ingestion.recover()
        assessments.recover()
        yield
        ingestion.close()
        assessments.close()
        graph.close()

    app = FastAPI(title="Migration & Decommission AI", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","),
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    app.state.db, app.state.graph = db, graph
    app.state.ingestion, app.state.assessments = ingestion, assessments

    def public_document(doc):
        return {k: v for k, v in doc.items() if k != "path"}

    @app.get("/health")
    def health():
        try:
            graph.health()
            graph_status = "ready"
        except Exception:
            graph_status = "unavailable"
        return {"status": "ok" if graph_status == "ready" else "degraded",
                "graph": graph_status, "graph_backend": settings.graph_backend,
                "model_provider": settings.model_provider,
                "demo": settings.model_provider == "demo" or settings.graph_backend == "memory"}

    @app.post("/documents", status_code=202)
    def upload(file: UploadFile = File(...), document_type: DocumentType = Form(...),
               application_id: str = Form(...), version: str = Form(...)):
        application_id, version = application_id.strip(), version.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}|_shared", application_id):
            raise HTTPException(422, "Use an application ID with letters, numbers, '.', '_' or '-'.")
        if application_id == "_shared" and document_type not in {"policy", "nfr"}:
            raise HTTPException(422, "Only policy/NFR documents may use _shared.")
        if not version or len(version) > 100:
            raise HTTPException(422, "Provide a version of 1–100 characters.")
        filename = (file.filename or "document").replace("\\", "/").split("/")[-1]
        filename = re.sub(r"[^\w .()-]", "_", filename)[:180]
        suffix = Path(filename).suffix.lower()
        if suffix not in {".pdf", ".docx", ".txt"}:
            raise HTTPException(415, "Upload a text-based PDF, DOCX or UTF-8 TXT file.")
        temporary = uploads / f"{uuid4().hex}.part"
        digest, length = hashlib.sha256(), 0
        try:
            with temporary.open("wb") as output:
                while block := file.file.read(1024 * 1024):
                    length += len(block)
                    if length > settings.max_upload_mb * 1024 * 1024:
                        raise HTTPException(413, f"Maximum upload size is {settings.max_upload_mb} MB.")
                    digest.update(block)
                    output.write(block)
            if length == 0:
                raise HTTPException(422, "The uploaded file is empty.")
            content_hash = digest.hexdigest()
            document_id = stable_id(content_hash, application_id, document_type, version)
            with ingestion.upload_lock:
                existing = db.get("documents", document_id)
                if existing and existing["status"] != "failed":
                    return {"document": public_document(existing), "job_id": existing["job_id"], "duplicate": True}
                path = uploads / f"{document_id}{suffix}"
                temporary.replace(path)
                job_id = existing["job_id"] if existing else uuid4().hex
                document = {"id": document_id, "filename": filename, "path": str(path.resolve()),
                            "application_id": application_id, "document_type": document_type,
                            "version": version, "hash": content_hash, "size_bytes": length,
                            "status": "queued", "created_at": now(), "job_id": job_id}
                db.save("documents", document)
                db.save("jobs", {"id": job_id, "document_id": document_id,
                                 "status": "queued", "step": "Queued", "error": None})
                ingestion.submit(job_id)
            return {"document": public_document(document), "job_id": job_id, "duplicate": False}
        finally:
            temporary.unlink(missing_ok=True)
            file.file.close()

    @app.get("/documents")
    def documents():
        return {"documents": [public_document(d) for d in db.list("documents")]}

    @app.get("/graph")
    def view_graph(application_id: str | None = None, document_id: str | None = None,
                   max_nodes: int = Query(default=180, ge=10, le=300)):
        ready = [d for d in db.list("documents") if d["status"] == "ready"]
        if document_id:
            document = db.get("documents", document_id)
            if not document:
                raise HTTPException(404, "Document not found.")
            if document["status"] != "ready":
                raise HTTPException(409, "The document is still processing. Its graph will be available when ready.")
            ready = [d for d in ready if d["id"] == document_id]
        if application_id:
            ready = [d for d in ready if d["application_id"] == application_id or
                     (d["application_id"] == "_shared" and d["document_type"] in {"policy", "nfr"})]
        try:
            return graph_snapshot(graph, ready, max_nodes)
        except Exception:
            logger.exception("Graph exploration failed")
            raise HTTPException(503, "Cannot load the graph. Check graph availability and API logs.")

    @app.get("/ingestion-jobs/{job_id}")
    def job(job_id: str):
        result = db.get("jobs", job_id)
        if not result:
            raise HTTPException(404, "Ingestion job not found.")
        return result

    @app.get("/documents/{document_id}/chunks")
    def chunks(document_id: str):
        doc = db.get("documents", document_id)
        if not doc:
            raise HTTPException(404, "Document not found.")
        if doc["status"] != "ready":
            raise HTTPException(409, "The document is not ready.")
        return {"chunks": graph.document_chunks(document_id)}

    @app.get("/documents/{document_id}/content")
    def content(document_id: str):
        doc = db.get("documents", document_id)
        if not doc or not Path(doc["path"]).is_file():
            raise HTTPException(404, "Document file not found.")
        return FileResponse(doc["path"], filename=doc["filename"], content_disposition_type="inline")

    @app.post("/chat/messages")
    def chat(request: ChatRequest):
        try:
            evidence = retrieval.retrieve(request.question, request.application_id,
                                          request.document_types, request.top_k)
            return provider.answer(request.question, evidence)
        except Exception:
            logger.exception("Document Q&A failed")
            raise HTTPException(503, "Retrieval or generation failed. Check Neo4j/model availability and API logs.")

    @app.post("/assessments", status_code=202)
    def start_assessment(request: AssessmentRequest):
        ready = [d for d in db.list("documents") if d["status"] == "ready"]
        if not any(d["application_id"] == request.application_id and d["document_type"] == "source_app" for d in ready):
            raise HTTPException(422, "Upload and finish processing source application documents first.")
        available = sorted({d["application_id"] for d in ready if d["document_type"] == "target"} - {request.application_id})
        targets = list(dict.fromkeys(request.target_ids)) or available[:5]
        if any(t not in available for t in targets):
            raise HTTPException(422, "Every selected target needs a ready target document and a distinct application ID.")
        record = {"id": uuid4().hex, "status": "running", "step": "Queued",
                  "created_at": now(), "request": {**request.model_dump(), "target_ids": targets},
                  "question": None, "result": None, "error": None}
        db.save("assessments", record)
        assessments.submit(record)
        return record

    @app.get("/assessments")
    def list_assessments():
        return {"assessments": db.list("assessments")[:30]}

    @app.get("/assessments/{assessment_id}")
    def get_assessment(assessment_id: str):
        record = db.get("assessments", assessment_id)
        if not record:
            raise HTTPException(404, "Assessment not found.")
        return record

    @app.post("/assessments/{assessment_id}/answers", status_code=202)
    def answer(assessment_id: str, request: ClarificationAnswer):
        record = get_assessment(assessment_id)
        if record["status"] != "paused":
            raise HTTPException(409, "Only paused assessments accept a clarification answer.")
        ready_ids = {d["id"] for d in db.list("documents") if d["status"] == "ready"}
        snapshot = assessments.graph.get_state({"configurable": {"thread_id": assessment_id}})
        evidence_ids = {p["document_id"] for b in snapshot.values.get("evidence", {}).values() for p in b["passages"]}
        if not evidence_ids <= ready_ids:
            raise HTTPException(409, "Evidence is still processing. Wait for all documents to be ready.")
        claimed = db.claim_assessment(assessment_id)
        if not claimed:
            raise HTTPException(409, "The assessment has already resumed.")
        assessments.submit(claimed, request.model_dump())
        return claimed

    return app


# Uvicorn factory avoids constructing databases when modules are imported by tests.
