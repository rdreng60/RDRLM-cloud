"""Postgres in place of the pickle.

`rdr_engine.py` is copied here byte-for-byte from the Streamlit build: the
algorithms are the same code, with the same tests behind them. Everything that
used to write a pickle or a CSV is replaced here instead, by subclassing rather
than by editing the engine.

The shape of the change:

    before                          now
    ------------------------------  --------------------------------------
    one pickled blob per org        one row per vertex
    save = rewrite the whole tree   save = INSERT one row
    two clinicians -> one loses     two clinicians -> both rules land
    log = a CSV string              log = rows that join on vertex number
"""

import json
import os
from contextlib import contextmanager
from typing import Dict, List, Optional, Tuple

import psycopg
from psycopg.rows import dict_row

from rdr_engine import RDREngine, Node, Rule, Vertex, LLMError

def database_url() -> str:
    """Read at call time, not at import: the process may be configured after
    this module is loaded, and tests point it somewhere else."""
    return os.environ.get("DATABASE_URL", "")


@contextmanager
def connect():
    url = database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    with psycopg.connect(url, row_factory=dict_row) as conn:
        yield conn


class DbEngine(RDREngine):
    """An RDREngine whose bookkeeping goes to Postgres.

    Only the three logging methods are overridden. Every algorithm — interpret,
    evaluate_rule, find_differences, verify_conditions, attach — is inherited
    unchanged, which is the point: the paper's implementation has one home.
    """

    def __init__(self, org_id: str, actor: str = "system"):
        self.org_id = org_id
        self.actor = actor
        self.pending_events: List[dict] = []
        self.root: Optional[Node] = None
        self.history = []
        self.last_vertex_number = -1
        # deliberately not calling super().__init__: it creates the CSV log.

    # --- logging, redirected ------------------------------------------------

    def _init_log(self):
        """No CSV. Events are rows."""

    def _log_event(self, action, file_path, n_true, n_eval, rev_triggered,
                   cond_type="N/A"):
        self.pending_events.append({
            "action": action,
            "source_file": file_path,
            "true_vertex": self.node_number(n_true),
            "eval_vertex": self.node_number(n_eval),
            "revision": rev_triggered if isinstance(rev_triggered, bool) else None,
            "condition_type": cond_type,
            "actor": self.actor,
            "detail": None,
        })

    def log_llm_error(self, source_file: str, error: LLMError):
        self.pending_events.append({
            "action": "LLM_ERROR",
            "source_file": source_file,
            "true_vertex": None,
            "eval_vertex": None,
            "revision": False,
            "condition_type": getattr(error, "operation", "unknown"),
            "actor": self.actor,
            "detail": str(getattr(error, "detail", error))[:500],
        })


# --- loading a tree -------------------------------------------------------

def load_engine(conn, org_id: str, actor: str = "system") -> DbEngine:
    """Rows -> the in-memory tree the algorithms walk.

    Read in one query. The engine then behaves exactly as it does in the
    Streamlit build, because it is the same class.
    """
    engine = DbEngine(org_id, actor)

    with conn.cursor() as cur:
        cur.execute(
            """
            select v.id, v.number, v.parent_id, v.side, v.conditions,
                   v.conclusion, v.summary, v.created_by, v.created_at,
                   coalesce(
                     (select json_agg(c.summary order by c.added_at, c.id)
                      from vertex_cases c where c.vertex_id = v.id),
                     '[]'::json
                   ) as cases
              from vertices v
             where v.org_id = %s
             order by v.number
            """,
            (org_id,),
        )
        rows = cur.fetchall()

        cur.execute(
            "select last_vertex_number from orgs where id = %s", (org_id,)
        )
        org = cur.fetchone()

    engine.last_vertex_number = org["last_vertex_number"] if org else -1

    by_id: Dict[int, Node] = {}
    for row in rows:
        conditions = row["conditions"]
        if not isinstance(conditions, str):
            conditions = json.dumps(conditions)
        node = Node(Vertex(
            Rule(conditions, row["conclusion"]),
            row["summary"] or "",
            cases=list(row["cases"] or []),
        ))
        node.number = row["number"]
        node.db_id = row["id"]
        node.created_by = row["created_by"]
        by_id[row["id"]] = node

    for row in rows:
        node = by_id[row["id"]]
        if row["side"] == "root":
            engine.root = node
        else:
            parent = by_id.get(row["parent_id"])
            if parent is not None:
                setattr(parent, row["side"], node)

    return engine


# --- writing -------------------------------------------------------------

def insert_vertex(conn, org_id: str, parent_number: Optional[int], side: str,
                  conditions: List[str], conclusion: str, case_summary: str,
                  actor: str, source_file: str) -> dict:
    """Add one rule. One INSERT, inside one transaction.

    Two clinicians adding rules to different branches do not collide at all.
    Two racing for the *same* slot hit the unique constraint, and the second is
    told what happened instead of quietly erasing the first — which is what the
    pickled blob did.
    """
    with conn.cursor() as cur:
        # Lock the org row: `last_vertex_number` is the paper's `s`, and two
        # concurrent inserts must not be handed the same number.
        cur.execute(
            "select last_vertex_number from orgs where id = %s for update",
            (org_id,),
        )
        org = cur.fetchone()
        if org is None:
            raise LookupError(f"no such organisation: {org_id}")
        number = org["last_vertex_number"] + 1

        parent_id = None
        if parent_number is not None:
            cur.execute(
                "select id from vertices where org_id = %s and number = %s",
                (org_id, parent_number),
            )
            parent = cur.fetchone()
            if parent is None:
                raise LookupError(f"no vertex {parent_number} in {org_id}")
            parent_id = parent["id"]

        try:
            cur.execute(
                """
                insert into vertices
                    (org_id, number, parent_id, side, conditions, conclusion,
                     summary, created_by)
                values (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                returning id, number
                """,
                (org_id, number, parent_id, side, json.dumps(conditions),
                 conclusion, case_summary, actor),
            )
        except psycopg.errors.UniqueViolation as exc:
            conn.rollback()
            raise SlotTaken(
                "Someone else added a rule in that position while you were "
                "working. Re-run the case to see the tree as it is now."
            ) from exc

        vertex = cur.fetchone()

        cur.execute(
            "update orgs set last_vertex_number = %s where id = %s",
            (number, org_id),
        )
        cur.execute(
            """
            insert into vertex_cases (vertex_id, summary, source_file, added_by)
            values (%s, %s, %s, %s)
            """,
            (vertex["id"], case_summary, source_file, actor),
        )

    return {"id": vertex["id"], "number": vertex["number"], "side": side}


class SlotTaken(RuntimeError):
    """Another clinician got to this branch first."""


def merge_case(conn, org_id: str, number: int, merged_summary: str,
               case_summary: str, actor: str, source_file: str):
    """Agreement: the case joins the vertex's profile and its case list."""
    with conn.cursor() as cur:
        cur.execute(
            """
            update vertices set summary = %s
             where org_id = %s and number = %s
            returning id
            """,
            (merged_summary, org_id, number),
        )
        vertex = cur.fetchone()
        if vertex is None:
            raise LookupError(f"no vertex {number} in {org_id}")

        cur.execute(
            """
            insert into vertex_cases (vertex_id, summary, source_file, added_by)
            values (%s, %s, %s, %s)
            """,
            (vertex["id"], case_summary, source_file, actor),
        )


def undo_last(conn, org_id: str, actor: str) -> Tuple[bool, str]:
    """Remove the most recently added vertex, if it is still a leaf.

    Its number is not given back: `last_vertex_number` only ever counts up, so
    a number means the same thing in every session and the event rows stay
    comparable.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, number, conclusion from vertices
             where org_id = %s order by number desc limit 1
            """,
            (org_id,),
        )
        last = cur.fetchone()
        if last is None:
            return False, "No rules to undo."

        cur.execute(
            "select count(*) as n from vertices where parent_id = %s",
            (last["id"],),
        )
        if cur.fetchone()["n"]:
            return False, (
                "The last rule has exceptions hanging off it. Remove those "
                "first."
            )

        cur.execute("delete from vertices where id = %s", (last["id"],))
        log_events(conn, org_id, [{
            "action": "UNDO",
            "source_file": None,
            "true_vertex": last["number"],
            "eval_vertex": None,
            "revision": False,
            "condition_type": "N/A",
            "actor": actor,
            "detail": last["conclusion"][:200],
        }])
    return True, f"Removed vertex #{last['number']}."


def log_events(conn, org_id: str, events: List[dict]):
    if not events:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into events
                (org_id, action, source_file, true_vertex, eval_vertex,
                 revision, condition_type, actor, detail)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (org_id, e["action"], e.get("source_file"),
                 e.get("true_vertex"), e.get("eval_vertex"),
                 e.get("revision"), e.get("condition_type"),
                 e.get("actor"), e.get("detail"))
                for e in events
            ],
        )


# --- reading, for the screen ---------------------------------------------

def tree_payload(engine: DbEngine) -> dict:
    """The tree as the React component draws it.

    Node ids are the paper's vertex numbers as strings, so what is on screen,
    what is in `vertices` and what is in `events` all name a rule the same way.
    """
    out = {}

    def walk(node):
        if node is None:
            return
        conds = node.vertex.rule.condition_list()
        out[str(node.number)] = {
            "left": str(node.left.number) if node.left else None,
            "right": str(node.right.number) if node.right else None,
            "conds": conds,
            "conclusion": node.vertex.rule.conclusions,
            "short_if": short_label(conds),
            "summary": node.vertex.summary or "",
            "cases": list(getattr(node.vertex, "cases", []) or []),
            "number": node.number,
            "created_by": getattr(node, "created_by", None),
            "status": "confirmed",
        }
        walk(node.left)
        walk(node.right)

    walk(engine.root)
    return out


_LEAD_INS = (
    "in the new patient summary, ", "the new patient summary indicates ",
    "the new patient summary ", "the client's ", "the client ", "client's ",
    "client ", "the therapist's ", "the therapist ", "therapist's ",
    "therapist ", "the patient ", "patient ",
)


def short_label(conds, limit=40):
    """A one-line gist for the node box; the full text lives in the panel."""
    if not conds:
        return "(no conditions)"
    text = " ".join(str(conds[0]).split())
    lowered = text.lower()
    for lead in _LEAD_INS:
        if lowered.startswith(lead):
            text = text[len(lead):]
            break
    if text:
        text = text[0].upper() + text[1:]
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def recent_events(conn, org_id: str, limit: int = 200) -> List[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select at, action, source_file, true_vertex, eval_vertex,
                   condition_type, actor, detail
              from events where org_id = %s
             order by at desc limit %s
            """,
            (org_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]
