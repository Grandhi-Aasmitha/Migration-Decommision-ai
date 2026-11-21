# Migration & Decommission AI

A React workspace and FastAPI API for uploading application evidence, exploring its knowledge graph, asking cited questions, and comparing migration targets through a resumable LangGraph workflow. Neo4j stores the production graph and vectors; SQLite stores metadata, job statuses, and assessment checkpoints.

**Users upload their own documents. The application starts empty and never loads test documents or example application facts automatically.** Existing user uploads remain available after restart.

## Docker Compose

Requires Docker Compose, about 6 GB free memory, and space for Ollama models.

```sh
git clone https://github.com/Grandhi-Aasmitha/Migration-Decommision-ai.git
cd Migration-Decommision-ai
cp .env.example .env
docker compose up --build -d
docker compose exec ollama ollama pull nomic-embed-text
docker compose exec ollama ollama pull llama3.2:3b
```

PowerShell: use `Copy-Item .env.example .env` instead of `cp`.

- Workspace: <http://localhost:8080>
- API docs: <http://localhost:8000/docs>
- Neo4j Browser: <http://localhost:7474> (`neo4j` and the local password from `.env`)

Open the workspace and upload your files. No seed command is needed. Download the models before processing ordinary prose in Ollama mode. Failed jobs report errors; re-upload the file to retry. Stop with `docker compose down`; named volumes preserve your files, graph, metadata, and checkpoints. Run one API process for this prototype.

## Local workspace

Requires Python 3.11+ and Node 22+. From the repository root:

```sh
python -m venv .venv
# PowerShell: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r backend/requirements.lock
cd frontend
npm ci
npm run build
cd ..
python scripts/run_local.py --demo --open-browser
```

UI and API run together at <http://127.0.0.1:5173/>; API docs are under `/api/docs`. If Windows blocks port 5173 or another server holds it, the launcher chooses a free localhost port and opens that URL. Keep the terminal open. Optional `--reload` enables development restarts; the default uses a single process. Rebuild React and refresh the page after frontend edits.

The launcher uses `data/user-uploads/`, initially empty, and preserves manually uploaded documents there. Older prototype data under `data/` is left intact and is not imported. Choose another workspace with `--data-dir /path/to/workspace`.

`--demo` explicitly selects an in-memory graph and extractive provider. It never uploads documents. All uploads produce document/passage/application connections. Demo domain extraction recognizes explicit lines such as `DEPENDS_ON: System name`, `HAS_CAPABILITY: Capability name`, and `MUST_MEET: Policy name`; it does not infer arbitrary relationships from prose. For natural-language extraction, configure Neo4j/Ollama using `.env.example`, pull the models, and launch without `--demo`.

Separate development servers are also supported:

```sh
python -m uvicorn app.main:create_app --factory --app-dir backend --host 127.0.0.1 --port 8000
# Another terminal:
cd frontend
npm run dev
```

Vite proxies `/api` to port 8000. Separate servers use regular `DATA_DIR`; the single-port launcher uses `--data-dir`.

## Upload and explore

1. Choose your PDF, DOCX, or UTF-8 TXT file; supply document type (`source_app`, `target`, `policy`, `nfr`), application ID, and version. Use distinct IDs for source and targets; `_shared` is reserved for cross-application policy/NFR documents.
2. Submit and follow queued/processing/ready or failed status. Files are capped at 15 MB and 500 chunks. OCR and encrypted PDFs are unsupported.
3. After processing, **Explore your knowledge graph** updates automatically. Filter by application/document, search nodes, zoom, and drag to pan. Select a node or relationship to inspect source passages and open the original upload.
4. Select an uploaded source application for document Q&A. Answers link to PDF pages or DOCX/TXT sections. Chat never starts assessments.
5. Click **Run assessment**, answer the priority clarification, and review documented matches, missing evidence, and policy/NFR checks. Source-only uploads report that target comparison is unavailable.

Graph nodes: Document, Chunk, Application, System, Capability, Policy. Edges: HAS_CHUNK, MENTIONS, DEPENDS_ON, HAS_CAPABILITY, MUST_MEET. Every edge retains document/chunk provenance; extracted assertions also retain their exact quote. Graph views include only processed uploads and default to 180 nodes; filters support focused exploration.

## Architecture and behavior

```text
React: manual uploads, graph explorer, Q&A, assessment
    |
FastAPI
    |-- ingestion worker -> extraction -> embeddings/facts -> Neo4j
    |-- graph projection -> stored passages/facts with provenance
    |-- shared GraphRAG retrieval -> chat and assessment evidence
    |-- LangGraph: gather -> clarify (interrupt) -> compare
    `-- SQLite: metadata, jobs, run statuses, checkpoints
```

Graph writes are transactional. File hash + application ID + type + version identify an upload, so identical uploads reuse their document/job. Different versions remain separate active evidence. PDF references use real page numbers; DOCX/TXT references use sections. Memory mode rebuilds its graph from saved user uploads after restart.

The shared retrieval service fuses full-text/vector rankings and follows fixed graph relationships, scoped by application/type and applicable `_shared` policies. Cypher is authored in code; model outputs never become queries. A scoped exact vector fill supports the small prototype corpus.

Ollama uses [embeddings](https://docs.ollama.com/api/embed) and [schema-constrained chat](https://docs.ollama.com/api/chat). Extracted quotes must occur in their source; generated citation IDs must belong to retrieved passages. The pinned Neo4j driver is used directly behind service interfaces rather than requiring an experimental graph builder.

LangGraph uses actual `interrupt()`/`Command(resume=...)` with SQLite checkpoints. Paused runs survive restart. Balanced capability/integration weights are 70/30; capability priority uses 90/10; integration priority uses 40/60. Missing source dimensions are excluded and weights renormalized. Ties or zero coverage do not establish a preferred target. Scores measure **documented coverage**, not readiness or compliance. Costs, policy/NFR validation, cutover, rollback, and decommission approval remain human review items.

## API

| Endpoint | Purpose |
| --- | --- |
| `POST /documents` | Multipart upload with metadata |
| `GET /documents` | Uploaded document library |
| `GET /ingestion-jobs/{id}` | Processing stage and errors |
| `GET /graph` | Nodes/edges/evidence; optional `application_id`, `document_id`, `max_nodes` (10–300) |
| `GET /documents/{id}/chunks` | Processed passages |
| `GET /documents/{id}/content` | Uploaded original |
| `POST /chat/messages` | Cited document Q&A |
| `POST /assessments` | Start assessment |
| `GET /assessments` | Run history |
| `GET /assessments/{id}` | Status, clarification, result |
| `POST /assessments/{id}/answers` | Resume paused run |
| `GET /health` | Graph connectivity and provider/demo mode |

## Verification

```sh
cd backend
python -m pytest -q
cd ../frontend
npm run build
npm audit --audit-level=high
```

CI starts disposable Neo4j for integration tests, then checks the React production build and dependency audit. Test documents live exclusively in `backend/tests/fixtures/documents/`, are excluded from the application image, and are never loaded by startup or served to users.

Tests cover empty startup, manual-upload graphs, provenance, graph filters/limits, deduplication, PDF/DOCX extraction, retry, unsupported model references, source-only behavior, and persistent clarification. Configure `NEO4J_TEST_URI`/`NEO4J_TEST_PASSWORD` only for a disposable database: integration tests clear its graph. Live Ollama inference requires downloaded models.

## Prototype boundaries

- Local, single-user operation with one API process. Authentication, tenant isolation, OCR, scanning, and production queue/deployment hardening are not included.
- Ingestion jobs recover. Active assessments interrupted by restart fail visibly; paused runs retain their checkpoints.
- Keep files, metadata, checkpoints, and Neo4j backups aligned. Changing embedding provider/model/dimensions requires a fresh graph and re-ingestion.
- Exact capability/integration names are conservative. Synonyms, conflicting versions, costs, migration plans, and policy/NFR evidence require review.

See [architecture notes](docs/architecture.md) and the [acceptance checklist](docs/acceptance.md).
