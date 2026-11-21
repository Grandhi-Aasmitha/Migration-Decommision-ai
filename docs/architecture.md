# Implementation notes

## Inspect the graph

Run in Neo4j Browser after the sample loader completes:

```cypher
MATCH (d:Document)-[:HAS_CHUNK]->(c:Chunk)
RETURN d.filename, d.document_type, d.application_id, count(c) AS chunks;
```

```cypher
MATCH (a:Application {id:'ledger-core'})-[r:DEPENDS_ON]->(s:System)
RETURN a.id, s.name, r.document_id, r.chunk_id, r.page, r.section, r.quote;
```

```cypher
MATCH p=(d:Document)-[:HAS_CHUNK]->(:Chunk)-[:MENTIONS]->(e)
RETURN p LIMIT 100;
```

```cypher
SHOW INDEXES;
```

`chunk_embedding` and `chunk_text` should be ONLINE. The graph also contains a `CorpusConfig` node recording the embedding profile. The fixed domain labels and relationship types are allowlisted in code. Entity IDs normalize names; assertion IDs remain per chunk so contradictory or repeated document evidence retains distinct sources.

## Storage and recovery

`DATA_DIR/uploads/` holds original files, `metadata.sqlite` holds document/job/run metadata, and `checkpoints.sqlite` holds LangGraph state. Back up these paths together with the corresponding Neo4j database. Files and graph are committed before the job is marked ready. If processing crashes, the persisted job retries on startup with stable graph IDs. A failed upload can be retried by uploading identical bytes/metadata.

The embedding schema and graph are initialized lazily so the API can start and display failures when Neo4j is unavailable. `/health` reports graph connectivity separately from the process's availability. It does not assert that Ollama models are already downloaded; model availability is exercised at ingestion/query time.

Only one API process is supported. It has one ingestion worker and one assessment worker. The upload lock prevents duplicate in-process ingestion scheduling, and an atomic status claim rejects a second clarification submission. This is not a distributed lock or production task queue.

Assessment evidence is checkpointed before clarification, providing a stable review snapshot. New uploads do not retroactively alter a paused run's fact inventory. Start a new run to include newly uploaded evidence. The resume endpoint checks that its referenced evidence is ready, including after demo restoration. Active execution interrupted by a restart is reported failed; paused runs retain their checkpoint.

## Interfaces

- `ModelProvider`: Ollama embedding, constrained extraction, and cited answer generation; explicit deterministic demo implementation.
- `Neo4jGraph` / `MemoryGraph`: store, scoped hybrid search, graph facts, original chunk inspection.
- `RetrievalService.retrieve(question, application_id, document_types, top_k)`: normalized passages, connected facts, citations, shared by chat and assessments.
- `IngestionService`: durable job stages and idempotent transactional graph writes.
- `AssessmentService`: LangGraph gather/clarify/compare nodes, SQLite checkpoints, run statuses.

The production graph uses Neo4j; memory is only an explicit demo/test option. There is no unrestricted model-generated Cypher. A future official `neo4j-graphrag` adapter can replace internals behind these interfaces without changing the UI/API contracts; pin and test the package before enabling its experimental builder.
