from test_workflow import client, settings, upload


def test_fresh_workspace_has_no_bundled_documents_or_graph(client):
    assert client.get("/documents").json() == {"documents": []}
    graph = client.get("/graph").json()
    assert graph["nodes"] == graph["edges"] == []
    assert graph["document_count"] == 0


def test_manual_upload_produces_graph_and_provenance(client):
    document = upload(client, text=b"DEPENDS_ON: Payment Gateway\nHAS_CAPABILITY: reconciliation\nMUST_MEET: audit retention")["document"]
    response = client.get("/graph", params={"document_id": document["id"]})
    assert response.status_code == 200
    graph = response.json()
    kinds = {n["kind"] for n in graph["nodes"]}
    assert kinds == {"Document", "Chunk", "Application", "System", "Capability", "Policy"}
    relations = {e["relation"] for e in graph["edges"]}
    assert relations == {"HAS_CHUNK", "MENTIONS", "DEPENDS_ON", "HAS_CAPABILITY", "MUST_MEET"}
    ids = {n["id"] for n in graph["nodes"]}
    for edge in graph["edges"]:
        assert edge["source"] in ids and edge["target"] in ids
        assert edge["evidence"]["document_id"] == document["id"]
        assert edge["evidence"]["chunk_id"]
        assert client.get(edge["evidence"]["url"]).status_code == 200


def test_graph_filters_and_duplicate_uploads(client):
    first = upload(client)
    upload(client, text=b"DEPENDS_ON: Private Beta Store", application_id="beta")
    upload(client, text=b"Shared retention policy.", application_id="_shared", document_type="policy")
    graph = client.get("/graph", params={"application_id": "ledger-core"}).json()
    assert graph["document_count"] == 2
    assert "Private Beta Store" not in str(graph)
    before = client.get("/graph", params={"document_id": first["document"]["id"]}).json()
    upload(client)
    after = client.get("/graph", params={"document_id": first["document"]["id"]}).json()
    assert before == after
    assert client.get("/graph", params={"document_id": "absent"}).status_code == 404


def test_graph_limit_never_leaves_dangling_edges(client):
    upload(client, text="\n".join(f"DEPENDS_ON: System {i}" for i in range(30)).encode())
    graph = client.get("/graph", params={"max_nodes": 10}).json()
    assert graph["truncated"] and len(graph["nodes"]) == 10
    ids = {n["id"] for n in graph["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in graph["edges"])
