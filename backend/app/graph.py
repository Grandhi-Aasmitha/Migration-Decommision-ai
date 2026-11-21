"""Fixed Cypher only. User questions and model outputs never become executable Cypher."""
import threading

from neo4j import GraphDatabase

from .extraction import stable_id
from .providers import terms

LABELS = {"DEPENDS_ON": "System", "HAS_CAPABILITY": "Capability", "MUST_MEET": "Policy"}


def in_scope(chunk, applications, types):
    return chunk["document_type"] in types and (
        chunk["application_id"] in applications or
        (chunk["application_id"] == "_shared" and chunk["document_type"] in {"policy", "nfr"}))


def fuse(keyword, vector, top_k):
    scores, items = {}, {}
    for ranking in (keyword, vector):
        for rank, item in enumerate(ranking, 1):
            scores[item["id"]] = scores.get(item["id"], 0) + 1 / (60 + rank)
            items[item["id"]] = item
    return [{**items[k], "score": scores[k]} for k in sorted(scores, key=scores.get, reverse=True)[:top_k]]


class MemoryGraph:
    """Ephemeral demo/test adapter; production evidence is never stored in SQLite."""
    def __init__(self, settings):
        self.documents, self.chunks = {}, {}
        self.lock = threading.RLock()

    def health(self):
        return True

    def close(self):
        pass

    def write(self, document, chunks):
        with self.lock:
            self.documents[document["id"]] = document
            self.chunks = {k: v for k, v in self.chunks.items() if v["document_id"] != document["id"]}
            self.chunks.update({c["id"]: c for c in chunks})

    def search(self, question, embedding, applications, types, top_k):
        with self.lock:
            chunks = [c.copy() for c in self.chunks.values() if in_scope(c, applications, types)]
        query = set(terms(question))
        keyword = sorted(chunks, key=lambda c: len(query & set(terms(c["text"]))), reverse=True)
        keyword = [c for c in keyword if query & set(terms(c["text"]))]
        vector = sorted(chunks, key=lambda c: sum(a*b for a, b in zip(embedding, c["embedding"])), reverse=True)
        return fuse(keyword, vector, top_k)

    def facts(self, chunk_ids):
        with self.lock:
            return [{**fact, "chunk_id": c["id"], "document_id": c["document_id"],
                     "application_id": c["application_id"], "page": c["page"], "section": c["section"]}
                    for c in self.chunks.values() if c["id"] in chunk_ids for fact in c["facts"]]

    def application_facts(self, application_id, document_type):
        with self.lock:
            ids = [c["id"] for c in self.chunks.values()
                   if c["application_id"] == application_id and c["document_type"] == document_type]
        return self.facts(ids)

    def document_chunks(self, document_id):
        with self.lock:
            return [{k: v for k, v in c.items() if k not in {"embedding", "facts"}}
                    for c in self.chunks.values() if c["document_id"] == document_id]


class Neo4jGraph:
    def __init__(self, settings):
        self.settings = settings
        self.driver = GraphDatabase.driver(settings.neo4j_uri,
                                           auth=(settings.neo4j_user, settings.neo4j_password))
        self.initialized = False
        self.init_lock = threading.Lock()

    def query(self, query, **params):
        records, _, _ = self.driver.execute_query(query, parameters_=params,
                                                  database_=self.settings.neo4j_database)
        return [record.data() for record in records]

    def health(self):
        self.driver.verify_connectivity()
        return True

    def close(self):
        self.driver.close()

    def initialize(self):
        with self.init_lock:
            if self.initialized:
                return
            for label in ["Document", "Chunk", "Application", "System", "Capability", "Policy"]:
                self.query(f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE")
            self.query("CREATE FULLTEXT INDEX chunk_text IF NOT EXISTS FOR (c:Chunk) ON EACH [c.text]")
            dimensions = self.settings.embedding_dimensions
            self.query(f"""CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS
                FOR (c:Chunk) ON (c.embedding) OPTIONS {{indexConfig: {{
                `vector.dimensions`: {dimensions}, `vector.similarity_function`: 'cosine'}}}}""")
            result = self.query("""MERGE (p:CorpusConfig {id:'embedding'})
                ON CREATE SET p.profile=$profile RETURN p.profile AS profile""",
                                profile=self.settings.embedding_key)
            if result[0]["profile"] != self.settings.embedding_key:
                raise ValueError("Embedding profile changed. Use a fresh Neo4j database and re-ingest the corpus.")
            self.query("CALL db.awaitIndexes(60)")
            self.initialized = True

    def write(self, document, chunks):
        self.initialize()

        def transaction(tx):
            tx.run("MATCH (:Application)-[r]->() WHERE r.document_id=$id DELETE r", id=document["id"]).consume()
            tx.run("MATCH (d:Document {id:$id})-[:HAS_CHUNK]->(c:Chunk) DETACH DELETE c",
                   id=document["id"]).consume()
            props = {k: document[k] for k in ["id", "filename", "application_id", "document_type", "version", "hash"]}
            tx.run("MERGE (d:Document {id:$props.id}) SET d += $props, d.status='ready'", props=props).consume()
            for chunk in chunks:
                props = {k: v for k, v in chunk.items() if k != "facts"}
                tx.run("""MATCH (d:Document {id:$doc})
                    MERGE (c:Chunk {id:$props.id}) SET c += $props
                    MERGE (d)-[:HAS_CHUNK]->(c)
                    MERGE (a:Application {id:$app}) SET a.name=$app
                    MERGE (c)-[:MENTIONS]->(a)""",
                       doc=document["id"], props=props, app=document["application_id"]).consume()
                for fact in chunk["facts"]:
                    relation, label = fact["relation"], LABELS[fact["relation"]]
                    tx.run(f"""MATCH (c:Chunk {{id:$chunk}}), (a:Application {{id:$app}})
                        MERGE (e:{label} {{id:$entity}}) SET e.name=$name
                        MERGE (c)-[:MENTIONS]->(e)
                        MERGE (a)-[r:{relation} {{id:$fact}}]->(e)
                        SET r.document_id=$doc, r.chunk_id=$chunk, r.quote=$quote,
                            r.page=$page, r.section=$section""",
                           chunk=chunk["id"], app=chunk["application_id"],
                           entity=stable_id(label, fact["name"].casefold().strip()),
                           name=fact["name"], fact=stable_id(chunk["id"], relation, fact["name"]),
                           doc=document["id"], quote=fact["quote"], page=chunk["page"], section=chunk["section"]).consume()

        with self.driver.session(database=self.settings.neo4j_database) as session:
            session.execute_write(transaction)

    def search(self, question, embedding, applications, types, top_k):
        self.initialize()
        params = {"apps": applications, "types": types, "embedding": embedding,
                  "candidates": max(100, top_k * 20), "limit": top_k * 3}
        scope = """node.document_type IN $types AND (node.application_id IN $apps
            OR (node.application_id='_shared' AND node.document_type IN ['policy','nfr']))"""
        vector = self.query(f"""CALL db.index.vector.queryNodes('chunk_embedding', $candidates, $embedding)
            YIELD node, score WHERE {scope} RETURN properties(node) AS chunk, score
            ORDER BY score DESC LIMIT $limit""", **params)
        # ANN filtering can underfill a scope. Exact scoped fill is affordable for this small prototype.
        if len(vector) < top_k:
            vector = self.query(f"""MATCH (node:Chunk) WHERE {scope}
                RETURN properties(node) AS chunk, vector.similarity.cosine(node.embedding,$embedding) AS score
                ORDER BY score DESC LIMIT $limit""", **params)
        words = terms(question)[:40]
        keyword = self.query(f"""CALL db.index.fulltext.queryNodes('chunk_text',$text)
            YIELD node, score WHERE {scope} RETURN properties(node) AS chunk, score
            ORDER BY score DESC LIMIT $limit""", **params, text=" OR ".join(words)) if words else []
        return fuse([r["chunk"] for r in keyword], [r["chunk"] for r in vector], top_k)

    def facts(self, chunk_ids):
        # Two graph hops: retrieved chunk -> mentioned application -> asserted entity.
        return self.query("""MATCH (c:Chunk)-[:MENTIONS]->(a:Application)-[r]->(e)
            WHERE c.id IN $ids AND r.chunk_id=c.id
            AND type(r) IN ['DEPENDS_ON','HAS_CAPABILITY','MUST_MEET']
            RETURN DISTINCT type(r) AS relation, e.name AS name, r.quote AS quote,
              c.id AS chunk_id, c.document_id AS document_id, a.id AS application_id,
              c.page AS page, c.section AS section""", ids=chunk_ids)

    def application_facts(self, application_id, document_type):
        return self.query("""MATCH (a:Application {id:$app})-[r]->(e),
            (c:Chunk {id:r.chunk_id}) WHERE c.document_type=$type
            AND type(r) IN ['DEPENDS_ON','HAS_CAPABILITY','MUST_MEET']
            RETURN type(r) AS relation, e.name AS name, r.quote AS quote,
              c.id AS chunk_id, c.document_id AS document_id, a.id AS application_id,
              c.page AS page, c.section AS section""", app=application_id, type=document_type)

    def document_chunks(self, document_id):
        return [r["chunk"] for r in self.query("""MATCH (d:Document {id:$id})-[:HAS_CHUNK]->(c)
            RETURN c {.id,.document_id,.text,.page,.section,.offset,.application_id,.document_type} AS chunk
            ORDER BY c.section, c.offset""", id=document_id)]
