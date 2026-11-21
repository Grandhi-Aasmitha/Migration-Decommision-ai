"""Run against a disposable Neo4j database: NEO4J_TEST_URI=bolt://localhost:7687."""
import os

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.graph import Neo4jGraph
from app.main import create_app
from test_workflow import corpus, upload, wait


@pytest.mark.skipif(not os.getenv("NEO4J_TEST_URI"), reason="No disposable Neo4j configured")
def test_real_neo4j_ingestion_hybrid_graph_scope_and_assessment(tmp_path):
    settings=Settings(data_dir=tmp_path,model_provider="demo",embedding_dimensions=64,
                      neo4j_uri=os.environ["NEO4J_TEST_URI"],
                      neo4j_password=os.getenv("NEO4J_TEST_PASSWORD","local-development-only"),_env_file=None)
    graph=Neo4jGraph(settings)
    graph.query("MATCH (n) DETACH DELETE n")
    try:
        with TestClient(create_app(settings,graph_override=graph)) as client:
            corpus(client)
            upload(client,application_id="beta",text=b"DEPENDS_ON: Secret Beta Store")
            response=client.post("/chat/messages",json={"application_id":"ledger-core","question":"What systems does Ledger Core depend on?"})
            assert response.status_code==200,response.text
            answer=response.json()
            assert "Identity Gateway" in answer["answer"]
            assert "Secret Beta Store" not in str(answer)
            before=graph.query("MATCH (c:Chunk) RETURN count(c) AS n")[0]["n"]
            corpus(client)
            assert graph.query("MATCH (c:Chunk) RETURN count(c) AS n")[0]["n"]==before
            assert graph.query("MATCH (:Application)-[r:DEPENDS_ON]->(:System) WHERE r.chunk_id IS NOT NULL RETURN count(r) AS n")[0]["n"]>0
            started=client.post("/assessments",json={"application_id":"ledger-core","objective":"balanced"}).json()
            result=wait(client,f"/assessments/{started['id']}",("completed","failed"))
            assert result["result"]["recommendation"]=="atlas-platform"
    finally:
        # App lifespan owns and closes the driver. No cleanup of any non-test database.
        graph.close()
