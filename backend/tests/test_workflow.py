import json
import time
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.config import Settings
from app.extraction import extract_sections
from app.main import create_app

SAMPLES = Path(__file__).resolve().parent / "fixtures/documents"


def wait(client, path, statuses=("ready", "paused", "completed", "failed")):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = client.get(path)
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] in statuses:
            assert body["status"] != "failed", body
            return body
        time.sleep(0.02)
    pytest.fail(f"Timed out waiting for {path}")


def upload(client, name="source.txt", text=b"HAS_CAPABILITY: posting\nDEPENDS_ON: Identity Gateway",
           application_id="ledger-core", document_type="source_app", version="1"):
    response = client.post("/documents", data={"application_id": application_id,
                          "document_type": document_type, "version": version},
                           files={"file": (name, text, "text/plain")})
    assert response.status_code == 202, response.text
    body = response.json()
    wait(client, f"/ingestion-jobs/{body['job_id']}")
    return body


def corpus(client):
    for item in json.loads((SAMPLES / "manifest.json").read_text()):
        upload(client, name=item["file"], text=(SAMPLES / item["file"]).read_bytes(),
               **{k: v for k, v in item.items() if k != "file"})


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, graph_backend="memory", model_provider="demo",
                    embedding_dimensions=64, _env_file=None)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def test_ingestion_dedup_and_citations(client):
    first, second = upload(client), upload(client)
    assert first["document"]["id"] == second["document"]["id"]
    assert second["duplicate"]
    assert len(client.get("/documents").json()["documents"]) == 1
    answer = client.post("/chat/messages", json={"question": "What systems does App A depend on?",
                                               "application_id": "ledger-core"}).json()
    assert "Identity Gateway" in answer["answer"]
    assert answer["facts"][0]["document_id"] == first["document"]["id"]
    citation = answer["citations"][0]
    assert citation["page"] is None  # TXT sections are not PDF pages.
    assert citation["chunk_id"]
    assert client.get(citation["url"]).status_code == 200
    assert client.get(f"/documents/{first['document']['id']}/chunks").json()["chunks"]
    assert client.get("/assessments").json()["assessments"] == []


def test_metadata_is_part_of_document_identity(client):
    a = upload(client)
    b = upload(client, version="2")
    assert a["document"]["id"] != b["document"]["id"]


def test_application_scope_prevents_graph_leakage(client):
    upload(client)
    upload(client, text=b"DEPENDS_ON: Secret Beta Store", application_id="beta")
    result = client.post("/chat/messages", json={"question": "dependencies", "application_id": "ledger-core"}).json()
    assert "Secret Beta Store" not in str(result)
    assert all(f["application_id"] == "ledger-core" for f in result["facts"])


def test_source_only_assessment_is_honest(client):
    upload(client)
    run = client.post("/assessments", json={"application_id": "ledger-core"}).json()
    result = wait(client, f"/assessments/{run['id']}")
    assert result["status"] == "completed"
    assert "not yet possible" in result["result"]["summary"]
    assert result["result"]["recommendation"] is None


def test_sample_priorities_and_resume(client):
    corpus(client)
    started = client.post("/assessments", json={"application_id": "ledger-core"}).json()
    run = wait(client, f"/assessments/{started['id']}")
    assert run["status"] == "paused"
    assert len(run["question"]["choices"]) == 3
    response = client.post(f"/assessments/{run['id']}/answers", json={"objective": "balanced"})
    assert response.status_code == 202
    result = wait(client, f"/assessments/{run['id']}", ("completed", "failed"))["result"]
    assert result["recommendation"] == "atlas-platform"
    assert result["candidates"][0]["coverage_score"] == 90
    assert result["draft"]
    assert any(c["document_type"] == "policy" for c in result["citations"])
    assert "compliance" in str(result["gaps"])
    assert client.post(f"/assessments/{run['id']}/answers", json={"objective": "balanced"}).status_code == 409
    second = client.post("/assessments", json={"application_id": "ledger-core", "objective": "integrations"}).json()
    result2 = wait(client, f"/assessments/{second['id']}", ("completed", "failed"))["result"]
    assert result2["recommendation"] == "nova-platform"


def test_pause_survives_process_recreation(settings):
    with TestClient(create_app(settings)) as first:
        corpus(first)
        started = first.post("/assessments", json={"application_id": "ledger-core"}).json()
        wait(first, f"/assessments/{started['id']}")
    with TestClient(create_app(settings)) as second:
        for doc in second.get("/documents").json()["documents"]:
            wait(second, f"/ingestion-jobs/{doc['job_id']}")
        assert second.get(f"/assessments/{started['id']}").json()["status"] == "paused"
        assert second.post(f"/assessments/{started['id']}/answers", json={"objective": "balanced"}).status_code == 202
        result = wait(second, f"/assessments/{started['id']}", ("completed", "failed"))
        assert result["result"]["recommendation"] == "atlas-platform"


@pytest.mark.parametrize("name,text,status", [("bad.exe",b"bad",415),("empty.txt",b"",422)])
def test_invalid_uploads(client,name,text,status):
    response = client.post("/documents", data={"application_id":"app","document_type":"source_app","version":"1"},
                           files={"file":(name,text)})
    assert response.status_code == status


def test_failed_job_can_be_retried(client):
    args={"data":{"application_id":"app","document_type":"source_app","version":"1"},
          "files":{"file":("broken.pdf",b"not a PDF")}}
    response=client.post("/documents",**args).json()
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        job=client.get(f"/ingestion-jobs/{response['job_id']}").json()
        if job["status"]=="failed": break
        time.sleep(.02)
    assert job["status"]=="failed"
    retry=client.post("/documents",**args).json()
    assert not retry["duplicate"]
    assert retry["document"]["id"]==response["document"]["id"]


def test_no_evidence_and_missing_records(client):
    answer=client.post("/chat/messages",json={"application_id":"absent","question":"dependencies"}).json()
    assert answer["citations"]==[]
    assert "could not find" in answer["answer"]
    assert client.get("/ingestion-jobs/absent").status_code==404
    assert client.get("/assessments/absent").status_code==404
    assert client.post("/assessments",json={"application_id":"absent"}).status_code==422


def test_docx_preserves_sections_and_tables(tmp_path):
    doc=Document();doc.add_heading("Integrations",1);doc.add_paragraph("DEPENDS_ON: Gateway")
    table=doc.add_table(rows=1,cols=2);table.cell(0,0).text="Capability";table.cell(0,1).text="Posting"
    path=tmp_path/"app.docx";doc.save(path)
    sections=extract_sections(path)
    assert "Gateway" in str(sections) and "Posting" in str(sections)
    assert all(s["page"] is None for s in sections)


def test_pdf_page_provenance(client):
    # Small hand-built PDF with text; verifies the real pypdf extraction path.
    objects=[b"<< /Type /Catalog /Pages 2 0 R >>",b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
             b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
             b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    stream=b"BT /F1 12 Tf 50 700 Td (DEPENDS_ON: PDF Gateway) Tj ET"
    objects.append(b"<< /Length "+str(len(stream)).encode()+b" >>\nstream\n"+stream+b"\nendstream")
    pdf=bytearray(b"%PDF-1.4\n");offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(pdf));pdf.extend(f"{i} 0 obj\n".encode()+obj+b"\nendobj\n")
    start=len(pdf);pdf.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets[1:]:pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(f"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF".encode())
    body=upload(client,name="sample.pdf",text=bytes(pdf))
    chunks=client.get(f"/documents/{body['document']['id']}/chunks").json()["chunks"]
    assert chunks[0]["page"]==1 and "PDF Gateway" in chunks[0]["text"]


def test_untrusted_quotes_are_rejected(settings,monkeypatch):
    from app.providers import ModelProvider
    settings.model_provider="ollama"
    provider=ModelProvider(settings)
    monkeypatch.setattr(provider,"generate_json",lambda *args:{"facts":[{"relation":"DEPENDS_ON","name":"Fake","quote":"fabricated text"}]})
    assert provider.facts("Real document text only.")==[]


def test_untrusted_citation_ids_are_rejected(settings,monkeypatch):
    from app.providers import ModelProvider
    settings.model_provider="ollama";provider=ModelProvider(settings)
    monkeypatch.setattr(provider,"generate_json",lambda *args:{"answer":"bad","chunk_ids":["invented"]})
    with pytest.raises(ValueError,match="unsupported citation"):
        provider.answer("question",{"passages":[{"chunk_id":"real"}],"facts":[]})


def test_unsupported_generated_answer_abstains(settings,monkeypatch):
    from app.providers import ModelProvider
    settings.model_provider="ollama";provider=ModelProvider(settings)
    monkeypatch.setattr(provider,"generate_json",lambda *args:{"answer":"invented cost","chunk_ids":[],"supported":False})
    result=provider.answer("What is the migration cost?",{"passages":[{"chunk_id":"real"}],"facts":[]})
    assert result["citations"]==[] and "does not establish" in result["answer"]
