import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from .extraction import extract_sections, make_chunks

logger = logging.getLogger(__name__)


class IngestionService:
    def __init__(self, db, graph, provider):
        self.db, self.graph, self.provider = db, graph, provider
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ingestion")
        self.upload_lock = threading.Lock()

    def submit(self, job_id):
        self.pool.submit(self.process, job_id)

    def update(self, job, step, **extra):
        job.update(status="processing", step=step, **extra)
        self.db.save("jobs", job)

    def process(self, job_id):
        job = self.db.get("jobs", job_id)
        document = self.db.get("documents", job["document_id"])
        try:
            self.update(job, "Extracting text")
            from pathlib import Path
            chunks = make_chunks(document["id"], extract_sections(Path(document["path"])))
            self.update(job, "Generating embeddings", chunk_count=len(chunks))
            embeddings = self.provider.embed([c["text"] for c in chunks])
            self.update(job, "Extracting graph facts")
            for chunk, embedding in zip(chunks, embeddings):
                chunk.update(embedding=embedding, facts=self.provider.facts(chunk["text"]),
                             application_id=document["application_id"], document_type=document["document_type"])
            self.update(job, "Writing knowledge graph")
            self.graph.write(document, chunks)
            document.update(status="ready", chunk_count=len(chunks),
                            fact_count=sum(len(c["facts"]) for c in chunks))
            self.db.save("documents", document)
            job.update(status="ready", step="Ready", error=None)
            self.db.save("jobs", job)
        except Exception as exc:
            logger.exception("Ingestion failed for %s", job_id)
            # Return a useful error without exposing connection strings or provider bodies.
            message = str(exc) if isinstance(exc, (ValueError, UnicodeError)) else "Processing failed. Check the API logs and Neo4j/model availability; retry this upload."
            self.db.save("documents", {**document, "status": "failed"})
            self.db.save("jobs", {**job, "status": "failed", "step": "Failed", "error": message})

    def recover(self):
        for job in self.db.list("jobs"):
            if job["status"] in {"queued", "processing"}:
                self.submit(job["id"])

    def close(self):
        self.pool.shutdown(wait=True)
