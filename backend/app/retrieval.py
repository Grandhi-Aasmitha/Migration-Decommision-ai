class RetrievalService:
    """The same scoped hybrid + graph evidence interface serves chat and assessment."""

    def __init__(self, graph, provider, db):
        self.graph, self.provider, self.db = graph, provider, db

    def citation(self, chunk):
        doc = self.db.get("documents", chunk["document_id"])
        return {"chunk_id": chunk["id"], "document_id": chunk["document_id"],
                "filename": doc["filename"], "version": doc["version"],
                "application_id": doc["application_id"], "document_type": doc["document_type"],
                "page": chunk.get("page"), "section": chunk.get("section"),
                "text": chunk["text"], "score": chunk.get("score"),
                "url": f"/documents/{doc['id']}/content" +
                       (f"#page={chunk['page']}" if chunk.get("page") else "")}

    def retrieve(self, question, application_id, document_types, top_k=6):
        vector = self.provider.embed([question])[0]
        chunks = self.graph.search(question, vector, [application_id], document_types, top_k)
        # Only ready documents are consumable, including after an interrupted ingestion.
        chunks = [c for c in chunks if (self.db.get("documents", c["document_id"]) or {}).get("status") == "ready"]
        return {"passages": [self.citation(c) for c in chunks],
                "facts": self.graph.facts([c["id"] for c in chunks])}

    def all_facts(self, application_id, document_type):
        facts = self.graph.application_facts(application_id, document_type)
        return [f for f in facts if (self.db.get("documents", f["document_id"]) or {}).get("status") == "ready"]
