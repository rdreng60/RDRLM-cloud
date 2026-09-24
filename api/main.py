"""The RDR engine as an HTTP service.

Only the Next.js server calls this — never a browser. It authenticates with a
shared secret and passes the signed-in clinician's email as the actor, which is
what ends up in the event log.

Every route is a thin wrapper around a method of RDREngine. Nothing here decides
whether a condition holds, filters a candidate, or chooses where a vertex goes:
that is all in rdr_engine.py, unchanged from the Streamlit build.
"""

import os
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import store
from llm_api import LLMError, llm_generate_summary, llm_merge_summaries

API_KEY = os.environ.get("ENGINE_API_KEY", "")

app = FastAPI(title="RDR engine", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o],
    allow_methods=["*"],
    allow_headers=["*"],
)


def caller(
    x_api_key: str = Header(default=""),
    x_actor: str = Header(default=""),
) -> str:
    """The shared secret, and who the Next.js server says is signed in."""
    if not API_KEY:
        raise HTTPException(500, "ENGINE_API_KEY is not configured")
    if x_api_key != API_KEY:
        raise HTTPException(401, "bad api key")
    if not x_actor:
        raise HTTPException(400, "missing X-Actor")
    return x_actor.strip().lower()


# --- payloads -------------------------------------------------------------

class Transcript(BaseModel):
    transcript: str


class CaseIn(BaseModel):
    summary: str
    source_file: str = "Unknown"


class DifferencesIn(CaseIn):
    verdict_node: Optional[int] = None


class AgreeIn(CaseIn):
    verdict_node: int


class RuleIn(CaseIn):
    end_node: Optional[int] = None
    verdict_node: Optional[int] = None
    conditions: List[str] = Field(default_factory=list)
    manual: List[str] = Field(default_factory=list)
    conclusion: str


# --- routes ---------------------------------------------------------------

@app.get("/health")
def health():
    return {"ok": True}


@app.post("/summarize")
def summarize(body: Transcript, actor: str = Depends(caller)):
    """Raw transcript text in, Clinical Prototype Summary out."""
    return {"summary": llm_generate_summary(body.transcript)}


@app.get("/orgs/{org_id}/tree")
def get_tree(org_id: str, actor: str = Depends(caller)):
    with store.connect() as conn:
        engine = store.load_engine(conn, org_id, actor)
        return {
            "tree": store.tree_payload(engine),
            "root": str(engine.root.number) if engine.root else None,
            "last_vertex_number": engine.last_vertex_number,
        }


@app.post("/orgs/{org_id}/interpret")
def interpret(org_id: str, body: CaseIn, actor: str = Depends(caller)):
    """Algorithm 1, with Algorithm 3 inside it: one call per conjunct."""
    with store.connect() as conn:
        engine = store.load_engine(conn, org_id, actor)
        trace, detail = [], []
        try:
            n1, n2 = engine.interpret(body.summary, trace=trace, detail=detail)
        except LLMError as err:
            engine.log_llm_error(body.source_file, err)
            store.log_events(conn, org_id, engine.pending_events)
            conn.commit()
            raise HTTPException(502, {
                "error": "llm",
                "operation": err.operation,
                "detail": err.detail,
            })

        return {
            "tree": store.tree_payload(engine),
            "root": str(engine.root.number) if engine.root else None,
            # ids the component draws with: the paper's vertex numbers
            "trace": [[str(d["number"]), d["result"]] for d in detail],
            "detail": [
                {
                    "number": d["number"],
                    "result": d["result"],
                    "conclusion": d["conclusion"],
                    "conditions": [
                        {"condition": c, "result": ok} for c, ok in d["conditions"]
                    ],
                }
                for d in detail
            ],
            "end_node": engine.node_number(n1),
            "verdict_node": engine.node_number(n2),
            "conclusion": n2.vertex.rule.conclusions if n2 else None,
        }


@app.post("/orgs/{org_id}/differences")
def differences(org_id: str, body: DifferencesIn, actor: str = Depends(caller)):
    """Algorithm 5: the model proposes, then every candidate is verified."""
    with store.connect() as conn:
        engine = store.load_engine(conn, org_id, actor)
        node = find(engine, body.verdict_node)
        rejected = []
        try:
            kept = engine.find_differences(body.summary, node, rejected=rejected)
        except LLMError as err:
            engine.log_llm_error(body.source_file, err)
            store.log_events(conn, org_id, engine.pending_events)
            conn.commit()
            raise HTTPException(502, {
                "error": "llm",
                "operation": err.operation,
                "detail": err.detail,
            })

        return {
            "kept": kept,
            "rejected": [
                {
                    "condition": r.condition,
                    "reason": r.reason,
                    "case_index": r.case_index,
                }
                for r in rejected
            ],
            "stored_cases": engine.cases_of(node),
        }


@app.post("/orgs/{org_id}/rules")
def add_rule(org_id: str, body: RuleIn, actor: str = Depends(caller)):
    """Algorithms 6 + 7 (the gate), then Algorithm 4 (where it goes).

    A rejection is a 200 with ok=false, not an error: the clinician is meant to
    choose again, which is the paper's repeat-until.
    """
    conditions = [c.strip() for c in body.conditions if c.strip()]
    if not conditions or not body.conclusion.strip():
        return {"ok": False, "problem": "Give a conclusion and at least one condition."}

    with store.connect() as conn:
        engine = store.load_engine(conn, org_id, actor)
        verdict = find(engine, body.verdict_node)
        end = find(engine, body.end_node)

        try:
            ok, problem = engine.verify_conditions(
                conditions, body.summary, engine.cases_of(verdict)
            )
        except LLMError as err:
            engine.log_llm_error(body.source_file, err)
            store.log_events(conn, org_id, engine.pending_events)
            conn.commit()
            raise HTTPException(502, {
                "error": "llm",
                "operation": err.operation,
                "detail": err.detail,
            })

        if not ok:
            return {"ok": False, "problem": engine.describe_rejection(problem)}

        # Algorithm 4, decided by the engine as it always was.
        if engine.root is None:
            side, parent_number = "root", None
        elif end is verdict:
            side, parent_number = "right", engine.node_number(end)
        else:
            side, parent_number = "left", engine.node_number(end)

        try:
            result = store.insert_vertex(
                conn, org_id, parent_number, side, conditions,
                body.conclusion.strip(), body.summary, actor, body.source_file,
            )
        except store.SlotTaken as clash:
            return {"ok": False, "problem": str(clash), "stale": True}

        store.log_events(conn, org_id, [{
            "action": "ADD_RULE",
            "source_file": body.source_file,
            "true_vertex": engine.node_number(verdict),
            "eval_vertex": engine.node_number(end),
            "revision": True,
            "condition_type": "MANUAL" if body.manual else "AI_GENERATED",
            "actor": actor,
            "detail": body.conclusion.strip()[:200],
        }])
        conn.commit()

    return {"ok": True, **result}


@app.post("/orgs/{org_id}/agree")
def agree(org_id: str, body: AgreeIn, actor: str = Depends(caller)):
    """The case joins the vertex's merged profile and its stored case list."""
    with store.connect() as conn:
        engine = store.load_engine(conn, org_id, actor)
        node = find(engine, body.verdict_node)
        if node is None:
            raise HTTPException(404, "no such vertex")

        merged = llm_merge_summaries(node.vertex.summary, body.summary)
        store.merge_case(conn, org_id, body.verdict_node, merged, body.summary,
                         actor, body.source_file)
        store.log_events(conn, org_id, [{
            "action": "MERGE_AGREEMENT",
            "source_file": body.source_file,
            "true_vertex": body.verdict_node,
            "eval_vertex": body.verdict_node,
            "revision": False,
            "condition_type": "N/A",
            "actor": actor,
            "detail": None,
        }])
        conn.commit()
    return {"ok": True}


@app.post("/orgs/{org_id}/undo")
def undo(org_id: str, actor: str = Depends(caller)):
    with store.connect() as conn:
        ok, message = store.undo_last(conn, org_id, actor)
        conn.commit()
    return {"ok": ok, "message": message}


@app.get("/orgs/{org_id}/events")
def events(org_id: str, limit: int = 200, actor: str = Depends(caller)):
    with store.connect() as conn:
        return {"events": store.recent_events(conn, org_id, limit)}


def find(engine, number: Optional[int]):
    """The node with this vertex number, or None."""
    if number is None:
        return None
    for node in engine.walk():
        if node.number == number:
            return node
    return None
