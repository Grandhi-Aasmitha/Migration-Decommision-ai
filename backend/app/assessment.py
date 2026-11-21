import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

logger = logging.getLogger(__name__)


class State(TypedDict, total=False):
    id: str
    application_id: str
    target_ids: list[str]
    objective: str | None
    evidence: dict
    result: dict


def norm(name):
    return " ".join(name.casefold().split())


class AssessmentService:
    def __init__(self, db, retrieval, checkpoint_path):
        self.db, self.retrieval = db, retrieval
        self.connection = sqlite3.connect(checkpoint_path, check_same_thread=False)
        self.checkpointer = SqliteSaver(self.connection)
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="assessment")
        graph = StateGraph(State)
        graph.add_node("gather", self.gather)
        graph.add_node("clarify", self.clarify)
        graph.add_node("compare", self.compare)
        graph.add_edge(START, "gather")
        graph.add_edge("gather", "clarify")
        graph.add_edge("clarify", "compare")
        graph.add_edge("compare", END)
        self.graph = graph.compile(checkpointer=self.checkpointer)

    def step(self, state, label):
        record = self.db.get("assessments", state["id"])
        self.db.save("assessments", {**record, "step": label})

    def gather(self, state):
        self.step(state, "Gathering source, target, and policy evidence")
        evidence = {}
        for app in [state["application_id"], *state["target_ids"]]:
            document_type = "source_app" if app == state["application_id"] else "target"
            evidence[app] = self.retrieval.retrieve(
                "capabilities dependencies integrations security policy performance availability",
                app, [document_type, "policy", "nfr"], 12)
            # Exhaustive scoped facts prevent top-k retrieval from truncating the comparison rubric.
            evidence[app]["all_facts"] = self.retrieval.all_facts(app, document_type)
        return {"evidence": evidence}

    def clarify(self, state):
        if not state["target_ids"] or state.get("objective"):
            return {}
        self.step(state, "Waiting for assessment priority")
        answer = interrupt({"question": "Which priority should guide the target comparison?",
                            "choices": [{"value": "balanced", "label": "Balance capabilities and integrations"},
                                        {"value": "capabilities", "label": "Prioritize capability coverage"},
                                        {"value": "integrations", "label": "Prioritize existing integrations"}]})
        return {"objective": answer["objective"]}

    def compare(self, state):
        self.step(state, "Comparing documented capabilities and dependencies")
        source = state["evidence"][state["application_id"]]
        if not state["target_ids"]:
            return {"result": {"summary": "Target comparison is not yet possible. Upload at least one target document.",
                               "candidates": [], "citations": source["passages"],
                               "gaps": ["No target documents are ready."], "recommendation": None,
                               "objective": state.get("objective"), "draft": True}}
        weights = {"balanced": (0.7, 0.3), "capabilities": (0.9, 0.1), "integrations": (0.4, 0.6)}
        objective = state.get("objective") or "balanced"
        wc, wi = weights[objective]
        source_facts = source["all_facts"]
        source_sets = {rel: {norm(f["name"]): f["name"] for f in source_facts if f["relation"] == rel}
                       for rel in ["HAS_CAPABILITY", "DEPENDS_ON", "MUST_MEET"]}
        candidates, citations = [], {}
        for bundle in state["evidence"].values():
            for p in bundle["passages"]:
                citations[p["chunk_id"]] = p
        # Include citations for all rubric facts, including those beyond retrieval's top-k.
        for bundle in state["evidence"].values():
            for fact in bundle["all_facts"]:
                if fact["chunk_id"] not in citations:
                    chunks = self.retrieval.graph.document_chunks(fact["document_id"])
                    chunk = next(c for c in chunks if c["id"] == fact["chunk_id"])
                    citations[fact["chunk_id"]] = self.retrieval.citation(chunk)
        for target_id in state["target_ids"]:
            bundle = state["evidence"][target_id]
            target_facts = bundle["all_facts"]
            sets = {rel: {norm(f["name"]) for f in target_facts if f["relation"] == rel}
                    for rel in source_sets}
            coverage, matches, gaps = {}, {}, []
            for rel, required in source_sets.items():
                matches[rel] = [name for key, name in required.items() if key in sets[rel]]
                missing = [name for key, name in required.items() if key not in sets[rel]]
                coverage[rel] = len(matches[rel]) / len(required) if required else None
                gaps.extend(f"No matching target evidence for {rel}: {name}" for name in missing)
            available_weights = [(wc, coverage["HAS_CAPABILITY"]), (wi, coverage["DEPENDS_ON"])]
            denominator = sum(w for w, value in available_weights if value is not None)
            score = (round(100 * sum(w * value for w, value in available_weights if value is not None) / denominator)
                     if denominator else None)
            candidates.append({"application_id": target_id, "coverage_score": score,
                               "matches": matches, "gaps": gaps,
                               "facts": target_facts, "citations": bundle["passages"]})
        candidates.sort(key=lambda c: c["coverage_score"] if c["coverage_score"] is not None else -1, reverse=True)
        gaps = ["Policy and NFR obligations require explicit validation; name matches do not prove compliance.",
                "Migration effort, costs, data retention, cutover, rollback, and decommission approval remain unverified.",
                "Capability names use exact, case-insensitive matching; synonyms need reviewer reconciliation."]
        if not source_sets["HAS_CAPABILITY"]:
            gaps.append("No source capabilities were extracted. Add stronger source evidence before deciding.")
        if not any(p["document_type"] in {"policy", "nfr"} for p in citations.values()):
            gaps.append("No relevant policy/NFR passages were retrieved.")
        top = candidates[0]
        tied = len(candidates) > 1 and candidates[1]["coverage_score"] == top["coverage_score"]
        recommendation = top["application_id"] if top["coverage_score"] is not None and top["coverage_score"] > 0 and not tied else None
        summary = (f"{recommendation} has the strongest documented coverage for the {objective} priority. "
                   "Review the gaps before making a migration decision." if recommendation else
                   "The available evidence does not establish a single preferred target.")
        return {"result": {"summary": summary, "recommendation": recommendation,
                           "objective": objective, "draft": True, "candidates": candidates,
                           "gaps": gaps, "source_facts": source_facts,
                           "rubric": {"capability_weight": wc, "integration_weight": wi,
                                      "meaning": "Percentage of source facts also documented for the target; not migration readiness. Missing source dimensions are excluded and weights renormalized."},
                           "citations": list(citations.values())}}

    def submit(self, record, answer=None):
        self.pool.submit(self.run, record, answer)

    def run(self, record, answer=None):
        config = {"configurable": {"thread_id": record["id"]}}
        try:
            with self.lock:
                initial = {"id": record["id"], **record["request"]}
                self.graph.invoke(Command(resume=answer) if answer else initial, config=config)
                snapshot = self.graph.get_state(config)
                current = self.db.get("assessments", record["id"])
                if snapshot.next:
                    questions = [i.value for task in snapshot.tasks for i in task.interrupts]
                    self.db.save("assessments", {**current, "status": "paused",
                                                "step": "Awaiting clarification", "question": questions[0]})
                else:
                    self.db.save("assessments", {**current, "status": "completed", "step": "Draft ready",
                                                "question": None, "result": snapshot.values["result"]})
        except Exception:
            logger.exception("Assessment failed: %s", record["id"])
            current = self.db.get("assessments", record["id"])
            self.db.save("assessments", {**current, "status": "failed", "step": "Failed",
                                        "error": "Assessment failed. Check service availability and API logs, then start a new run."})

    def recover(self):
        for record in self.db.list("assessments"):
            if record["status"] == "running":
                self.db.save("assessments", {**record, "status": "failed", "step": "Interrupted by restart",
                                            "error": "Start a new run. Paused runs can still be resumed."})

    def close(self):
        self.pool.shutdown(wait=True)
        self.connection.close()
