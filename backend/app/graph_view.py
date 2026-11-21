"""Bounded graph projection of processed uploads, with evidence on every edge."""
from .extraction import stable_id
from .graph import LABELS


def graph_snapshot(graph, documents, max_nodes=180):
    nodes, edges = {}, {}
    truncated = False

    def node(node_id, kind, label, **properties):
        nonlocal truncated
        if node_id not in nodes:
            if len(nodes) >= max_nodes:
                truncated = True
                return False
            nodes[node_id] = {"id": node_id, "kind": kind, "label": label, **properties}
        return True

    def edge(source, target, relation, evidence):
        if source not in nodes or target not in nodes:
            return
        edge_id = stable_id(source, target, relation, evidence["chunk_id"])
        edges[edge_id] = {"id": edge_id, "source": source, "target": target,
                          "relation": relation, "evidence": evidence}

    for index, document in enumerate(documents):
        if len(nodes) >= max_nodes - 2:
            truncated = True
            break
        doc_id, app_id = document["id"], "application:" + document["application_id"]
        doc_node = "document:" + doc_id
        node(doc_node, "Document", document["filename"], document_id=doc_id,
             application_id=document["application_id"], version=document["version"],
             document_type=document["document_type"], url=f"/documents/{doc_id}/content")
        node(app_id, "Application", document["application_id"])
        chunks = graph.document_chunks(doc_id)
        included_chunks = []
        for chunk in chunks:
            chunk_node = "chunk:" + chunk["id"]
            if not node(chunk_node, "Chunk", chunk.get("section") or "Passage",
                        document_id=doc_id, chunk_id=chunk["id"], text=chunk["text"],
                        page=chunk.get("page"), section=chunk.get("section")):
                break
            citation = {"document_id": doc_id, "chunk_id": chunk["id"],
                        "filename": document["filename"], "version": document["version"],
                        "page": chunk.get("page"), "section": chunk.get("section"),
                        "text": chunk["text"], "url": f"/documents/{doc_id}/content" +
                        (f"#page={chunk['page']}" if chunk.get("page") else "")}
            edge(doc_node, chunk_node, "HAS_CHUNK", citation)
            edge(chunk_node, app_id, "MENTIONS", citation)
            included_chunks.append(chunk["id"])
        facts = graph.facts(included_chunks) if included_chunks else []
        citations = {e["evidence"]["chunk_id"]: e["evidence"] for e in edges.values()}
        for fact in facts:
            label = LABELS[fact["relation"]]
            entity = stable_id(label, fact["name"].casefold().strip())
            if not node(entity, label, fact["name"]):
                continue
            citation = {**citations[fact["chunk_id"]], "quote": fact["quote"]}
            edge("chunk:" + fact["chunk_id"], entity, "MENTIONS", citation)
            edge(app_id, entity, fact["relation"], citation)
        if index < len(documents) - 1 and len(nodes) >= max_nodes:
            truncated = True
    return {"nodes": list(nodes.values()), "edges": list(edges.values()),
            "truncated": truncated, "document_count": sum(n["kind"] == "Document" for n in nodes.values()),
            "available_document_count": len(documents)}
