# rdr_engine.py
#
# The algorithms of the paper (Srinivasan, *RDR*, Algs 1-7) live HERE, as
# functions, not inside Streamlit button callbacks. Gap 3.
#
# One real difficulty had to be worked around: the paper's rdr() runs start to
# finish in one go, while a human oracle answers across several page reloads, so
# a single function cannot sit and wait in the middle. The split used here is
# the one the gap note proposes -- every pure step is a method on RDREngine:
#
#     evaluate_condition   Alg 3, one conjunct          lambda.Evaluate(x, c_i)
#     evaluate_rule        Alg 3, the hard AND
#     interpret            Alg 1, the walk
#     cases_of             the X stored at a vertex
#     exists_satisfied     Alg 7, ExistsSatisfied(D', X)
#     find_differences     Alg 5, propose THEN verify
#     verify_conditions    Algs 6+7, the gate a chosen set D' must pass
#     attach               Alg 4/6, where the new vertex goes
#     merge_case           the agreement path
#
# `revise()` composes them into the paper's loop for any oracle that can answer
# without a page reload (a script, a test, a batch run). app.py calls the very
# same methods in the same order across reloads. Nothing about *how a condition
# is checked* is written twice, and every step above is testable on its own.

import sys
import os
import pickle
import logging
import json
import csv
import datetime
from typing import Optional, List, Tuple, Dict, Any, Sequence

# Import updated API functions
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

try:
    from llm_api import (
        llm_check_condition, 
        llm_get_differentiating_conditions, 
        llm_generate_summary, 
        llm_merge_summaries,
        LLMError,
    )
except ImportError:
    from app.llm_api import (
        llm_check_condition, 
        llm_get_differentiating_conditions, 
        llm_generate_summary, 
        llm_merge_summaries,
        LLMError,
    )
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
#Path configuration
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
STORAGE_DIR = os.path.join(CURRENT_DIR, '..','storage')
TREE_STORAGE_FILE = os.path.join(STORAGE_DIR, "rdr_tree_summary.pkl")
LOG_FILE = os.path.join(STORAGE_DIR, "rdr_event_log.csv")


def parse_conditions(raw) -> List[str]:
    """The stored condition blob as the list of conjuncts it stands for.

    Storage is unchanged -- still the JSON string app.py has always written --
    but nothing downstream is allowed to treat it as one opaque condition again
    (Gap 4). A tree pickled before this change, whose conditions are a bare
    string, still reads back as a one-element conjunction.
    """
    if isinstance(raw, (list, tuple)):
        return [str(c) for c in raw]
    if raw is None:
        return []
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return [str(raw)]
    if isinstance(parsed, list):
        return [str(c) for c in parsed]
    return [str(parsed)]


class Rule:
    def __init__(self, conditions: str, conclusions: str):
        self.conditions = conditions
        self.conclusions = conclusions

    def condition_list(self) -> List[str]:
        """C = c1 AND c2 AND ... AND ck, as the list of ci."""
        return parse_conditions(self.conditions)

class Vertex:
    def __init__(self, rule: Rule, summary: str, cases: Optional[Sequence[str]] = None):
        self.rule = rule
        self.summary: str = summary 
        # X: the cases stored at this vertex, kept one by one.
        #
        # `summary` is the merged group profile and stays exactly what it was --
        # it is what the clinician reads on the node. But Algs 5 and 7 test a
        # condition against *every stored case*, and a merge generalises the
        # conflicting details away ("insomnia" + "hypersomnia" -> "sleep
        # disturbances"), so the paragraph cannot answer that question. Gaps 5+6.
        self.cases: List[str] = list(cases) if cases is not None else (
            [summary] if summary else []
        )

class Node:
    def __init__(self, vertex: Vertex):
        self.vertex = vertex
        self.left: Optional[Node] = None
        self.right: Optional[Node] = None
        # The paper's vertex table index: V[0] is the root, V[1] the next, and
        # `s` is the number of the last vertex added. Assigned by the engine
        # when the node is attached, and it is what the log records. Gap 10.
        self.number: Optional[int] = None


class RuleCheck:
    """What evaluate_rule found, conjunct by conjunct.

    `results` is [(condition, True/False), ...] in the order they were tested,
    stopping at the first FALSE the way Algorithm 3 does. So it also records
    which question was answered, which a single node-level TRUE never could.
    """

    def __init__(self, holds: bool, results: List[Tuple[str, bool]]):
        self.holds = holds
        self.results = results

    @property
    def failed_on(self) -> Optional[str]:
        for cond, ok in self.results:
            if not ok:
                return cond
        return None

    def __bool__(self):
        return self.holds


class Rejection:
    """Why a candidate condition or a chosen set D' was not allowed through."""

    def __init__(self, condition: str, reason: str, case_index: Optional[int] = None):
        self.condition = condition
        self.reason = reason          # "false_of_new" | "true_of_stored"
        self.case_index = case_index  # which stored case, when that is the reason

    def __repr__(self):
        return f"<Rejection {self.condition!r} {self.reason} case={self.case_index}>"


class RDREngine:
    def __init__(self):
        self.root: Optional[Node] = None
        # Stack: [(parent_node, side, new_node, source_file)]
        self.history: List[Tuple[Optional[Node], str, Node, str]] = []
        # The paper's `s`: the number of the last vertex added. Counts up and is
        # never reused, so a node's number means the same thing in every session.
        self.last_vertex_number: int = -1
        self._init_log()

    def _init_log(self):
        """Initialize the CSV log with headers."""
        if not os.path.exists(STORAGE_DIR):
            os.makedirs(STORAGE_DIR)
            
        file_exists = os.path.exists(LOG_FILE)
        is_empty = False
        if file_exists:
            is_empty = os.stat(LOG_FILE).st_size == 0
            
        if not file_exists or is_empty:
            try:
                with open(LOG_FILE, mode='w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    # Added 'Condition_Type' column
                    writer.writerow([
                        "Date",
                        "Time",
                        "Action", 
                        "File_Path", 
                        "Last_True_Node", 
                        "Last_Eval_Node", 
                        "Revision_Triggered",
                        "Condition_Type" # New Column
                    ])
            except Exception as e:
                logging.error(f"Failed to init log file: {e}")

    # --- vertex numbering (Gap 10) ---------------------------------------

    def _next_vertex_number(self) -> int:
        """The paper's `s`, incremented. Survives pickling and restarts."""
        if not isinstance(getattr(self, "last_vertex_number", None), int):
            # A tree pickled before nodes were numbered. Number what is already
            # there in traversal order first, so no two vertices share a number.
            self.last_vertex_number = -1
            for node in self.walk():
                if not isinstance(getattr(node, "number", None), int):
                    self.last_vertex_number += 1
                    node.number = self.last_vertex_number
                else:
                    self.last_vertex_number = max(
                        self.last_vertex_number, node.number
                    )
        self.last_vertex_number += 1
        return self.last_vertex_number

    def walk(self):
        """Every node in the tree, root first."""
        stack = [self.root]
        while stack:
            node = stack.pop()
            if node is None:
                continue
            yield node
            stack.append(node.right)
            stack.append(node.left)

    def node_number(self, node: Optional[Node]) -> Optional[int]:
        if node is None:
            return None
        return getattr(node, "number", None)

    def path_of(self, target: Optional[Node]) -> Optional[str]:
        """Path id ("RootLR") for a node object, or None if it is not in the tree."""
        if target is None:
            return None

        def walk(node, path="Root"):
            if node is None:
                return None
            if node is target:
                return path
            return walk(node.left, path + "L") or walk(node.right, path + "R")

        return walk(self.root)

    def node_at(self, path: Optional[str]) -> Optional[Node]:
        """The node a path id points at, or None. The inverse of path_of."""
        if not path or not path.startswith("Root"):
            return None
        node = self.root
        for step in path[len("Root"):]:
            if node is None:
                return None
            node = node.left if step == "L" else node.right
        return node

    def _log_event(self, action, file_path, n_true: Optional[Node], n_eval: Optional[Node], rev_triggered, cond_type="N/A"):
        """Internal helper to append to the CSV log."""
        try:
            now = datetime.datetime.now()
            date_str = now.strftime("%Y-%m-%d")
            time_str = now.strftime("%H:%M:%S")
            
            def node_str(n):
                if not n: return "None"
                # The vertex's number, not id(n). id() is the object's address
                # in RAM during one run: it changes on restart, so rows could
                # not be joined across sessions and no node could be counted.
                # Gap 10.
                number = getattr(n, "number", None)
                tag = f"#{number}" if isinstance(number, int) else "#?"
                return f"[{tag}] {n.vertex.rule.conclusions[:30]}..."

            with open(LOG_FILE, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    date_str,
                    time_str,
                    action,
                    file_path,
                    node_str(n_true),
                    node_str(n_eval),
                    str(rev_triggered),
                    cond_type # Write condition type
                ])
        except Exception as e:
            logging.error(f"Logging failed: {e}")

    def log_llm_error(self, source_file: str, error: "LLMError"):
        """Record that a call to the oracle failed (Gap 9).

        Columns are unchanged; the detail rides in Last_True_Node and the
        operation in Condition_Type, so old readers of the CSV keep working.
        """
        try:
            now = datetime.datetime.now()
            with open(LOG_FILE, mode='a', newline='', encoding='utf-8') as f:
                csv.writer(f).writerow([
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%H:%M:%S"),
                    "LLM_ERROR",
                    source_file,
                    str(getattr(error, "detail", error))[:200],
                    "None",
                    "False",
                    getattr(error, "operation", "unknown"),
                ])
        except Exception as e:
            logging.error(f"Logging failed: {e}")

    # --- ALGORITHM 3: evaluating a rule ----------------------------------

    def evaluate_condition(self, case_summary: str, condition: str) -> bool:
        """lambda.Evaluate(x, c): one condition, one call, one answer.

        The single place a condition is ever checked. Traversal, proposal
        filtering and the save gate all come through here, so there is one
        definition of "is this condition true of this case" instead of three.
        """
        return llm_check_condition(case_summary, str(condition))

    def evaluate_rule(self, case_summary: str, conditions) -> RuleCheck:
        """Algorithm 3. C = c1 AND c2 AND ... AND ck.

        Loops over the conjuncts, one call each, and returns false on the first
        miss -- a hard AND. Gap 4: the list used to be handed to the model whole,
        as a JSON array dropped into a prompt written for a single condition, so
        one word came back for the entire rule and there was no telling which
        question it had answered.
        """
        conds = parse_conditions(conditions)
        results: List[Tuple[str, bool]] = []
        for cond in conds:
            ok = self.evaluate_condition(case_summary, cond)
            results.append((cond, bool(ok)))
            if not ok:
                return RuleCheck(False, results)   # first miss stops the loop
        # An empty condition list is vacuously true, as an empty conjunction is.
        return RuleCheck(True, results)

    # --- ALGORITHM 1: the walk -------------------------------------------

    def interpret(self, current_patient_summary: str, trace: Optional[list] = None,
                  detail: Optional[list] = None) -> Tuple[Optional[Node], Optional[Node]]:
        """Walk the tree for one summary.

        Pass a list as `trace` to also record the walk as
        [["Root", True], ["RootR", False], ...] — the path ids match the ones
        used for storage/summaries filenames. Purely optional; leaving it out
        keeps the original behaviour.

        Pass a list as `detail` to additionally record, per node visited,
        which conjunct gave which answer:
            {"node": "Root", "number": 0, "result": False,
             "conditions": [("insomnia", True), ("stopped medication", False)]}
        """
        last_tried_node: Optional[Node] = None
        last_true_node: Optional[Node] = None
        current_node: Optional[Node] = self.root
        path = "Root"

        while current_node:
            last_tried_node = current_node
            condition = current_node.vertex.rule.conditions
            check = self.evaluate_rule(current_patient_summary, condition)
            is_true = check.holds

            if trace is not None:
                trace.append([path, bool(is_true)])
            if detail is not None:
                detail.append({
                    "node": path,
                    "number": self.node_number(current_node),
                    "result": bool(is_true),
                    "conclusion": current_node.vertex.rule.conclusions,
                    "conditions": list(check.results),
                })

            if is_true:
                last_true_node = current_node
                current_node = current_node.right
                path += "R"
            else:
                current_node = current_node.left
                path += "L"

        return (last_tried_node, last_true_node)

    # --- the cases stored at a vertex ------------------------------------

    def cases_of(self, node: Optional[Node]) -> List[str]:
        """X: the stored cases at a vertex, each one whole.

        Falls back to the merged profile for a vertex pickled before cases were
        kept separately, so an old tree still gets checked against something
        rather than against nothing.
        """
        if node is None:
            return []
        vertex = getattr(node, "vertex", None)
        cases = getattr(vertex, "cases", None)
        if isinstance(cases, list) and cases:
            return [c for c in cases if isinstance(c, str) and c.strip()]
        summary = getattr(vertex, "summary", "")
        return [summary] if isinstance(summary, str) and summary.strip() else []

    def reference_text(self, node: Optional[Node]) -> str:
        """What the proposal call is shown as "the reference group".

        The stored cases, listed, rather than only the merged paragraph -- a
        merge generalises away exactly the details a differentiating condition
        turns on. The verification below does not depend on this: it tests every
        case separately either way. Gap 5.
        """
        cases = self.cases_of(node)
        if not cases:
            return ""
        if len(cases) == 1:
            return cases[0]
        return "\n\n".join(f"Case {i + 1}: {c}" for i, c in enumerate(cases))

    # --- ALGORITHM 7: ExistsSatisfied ------------------------------------

    def exists_satisfied(self, conditions, cases: Sequence[str]) -> Optional[int]:
        """Does the conjunction D' hold for ANY stored case?

        Returns the index of the first case it holds for, or None. The whole
        conjunction is tested against each case, not one condition at a time:
        individual conjuncts are allowed to be true of a stored case, it is only
        the AND of them that must not be. Gap 6.
        """
        conds = parse_conditions(conditions)
        if not conds:
            return None
        for i, case in enumerate(cases):
            if self.evaluate_rule(case, conds).holds:
                return i
        return None

    # --- ALGORITHM 5: propose, then verify -------------------------------

    def find_differences(self, new_case: str, node: Optional[Node],
                         rejected: Optional[list] = None) -> List[str]:
        """Algorithm 5. Ask the model for candidates, then check each one.

        A candidate c is kept only if it is true of the new case x AND false of
        every stored case x' in X. Previously the model's list was used as-is:
        one warm call, output straight onto the screen as checkboxes, nothing
        verified against anything. Gap 5.

        Pass a list as `rejected` to receive the discarded candidates as
        Rejection objects, so the clinician can be shown what was filtered and
        why rather than a silently shortened list.
        """
        stored = self.cases_of(node)
        candidates = llm_get_differentiating_conditions(
            new_case, self.reference_text(node)
        )

        kept: List[str] = []
        seen = set()
        for cand in candidates:
            cand = str(cand).strip()
            if not cand or cand in seen:
                continue
            seen.add(cand)

            if not self.evaluate_condition(new_case, cand):
                if rejected is not None:
                    rejected.append(Rejection(cand, "false_of_new"))
                continue

            hit = None
            for i, case in enumerate(stored):
                if self.evaluate_condition(case, cand):
                    hit = i
                    break
            if hit is not None:
                if rejected is not None:
                    rejected.append(Rejection(cand, "true_of_stored", hit))
                continue

            kept.append(cand)
        return kept

    # --- ALGORITHMS 6 + 7: the gate a chosen set must pass ---------------

    def verify_conditions(self, conditions, new_case: str,
                          cases: Sequence[str]) -> Tuple[bool, Optional[Rejection]]:
        """repeat ... until lambda.Evaluate(D', x) AND NOT ExistsSatisfied(D', X).

        The single gate every saved rule passes, whatever the conditions came
        from. Three things were wrong before (Gap 6):

          - the check sat inside `if manual_conditions:`, so a rule built from
            AI-suggested checkboxes was saved with no checks at all;
          - hand-typed conditions were tested one at a time, so a legal
            combination was refused because one of its parts was true of a
            stored case;
          - a failure called st.stop(), killing the page instead of letting the
            clinician choose again.

        The first two are fixed here. The third is fixed by returning the
        problem instead of raising: revise() loops, and app.py re-opens the form
        with the message and whatever the clinician had already typed.
        """
        conds = parse_conditions(conditions)
        if not conds:
            return False, Rejection("", "empty")

        # lambda.Evaluate(D', x): the conjunction must hold for the new case.
        check = self.evaluate_rule(new_case, conds)
        if not check.holds:
            return False, Rejection(check.failed_on or "", "false_of_new")

        # NOT ExistsSatisfied(D', X): no stored case may satisfy the whole thing.
        hit = self.exists_satisfied(conds, cases)
        if hit is not None:
            return False, Rejection(" AND ".join(conds), "true_of_stored", hit)

        return True, None

    def describe_rejection(self, rejection: Optional[Rejection]) -> str:
        """The rejection as a sentence for the clinician."""
        if rejection is None:
            return ""
        if rejection.reason == "empty":
            return "Give at least one condition."
        if rejection.reason == "false_of_new":
            return (
                f"'{rejection.condition}' is FALSE for the current patient, so "
                "the rule would not fire for this case. Choose again."
            )
        if rejection.reason == "true_of_stored":
            where = (
                f"stored case {rejection.case_index + 1}"
                if rejection.case_index is not None
                else "a stored case"
            )
            return (
                f"All of these hold together for {where} at this node, so the "
                "rule would also fire for a patient already filed here. Add a "
                "further condition, or choose a different set."
            )
        return "Those conditions cannot be used. Choose again."

    # --- MANAGEMENT METHODS ---

    def add_node_to_tree(self, parent_node: Optional[Node], new_node: Node, side: str, source_file: str = "Unknown", last_eval_node: Optional[Node] = None, last_true_node: Optional[Node] = None, condition_type: str = "Unknown"):
        """
        Adds a node, tracks it for undo, and logs the event with condition type.
        """
        if not hasattr(self, 'history'):
            self.history = []

        # Number the vertex the moment it joins the tree, before anything is
        # logged about it (Gap 10).
        if not isinstance(getattr(new_node, "number", None), int):
            new_node.number = self._next_vertex_number()

        if side == "ROOT":
            self.root = new_node
            self.history.append((None, "ROOT", new_node, source_file))
            logging.info("ROOT node added.")
        elif side == "RIGHT" and parent_node:
            parent_node.right = new_node
            self.history.append((parent_node, "RIGHT", new_node, source_file))
            logging.info(f"Node added to RIGHT of {parent_node.vertex.rule.conclusions[:15]}...")
        elif side == "LEFT" and parent_node:
            parent_node.left = new_node
            self.history.append((parent_node, "LEFT", new_node, source_file))
            logging.info(f"Node added to LEFT of {parent_node.vertex.rule.conclusions[:15]}...")

        # Log with Condition Type
        self._log_event("ADD_RULE", source_file, last_true_node, last_eval_node, True, condition_type)

    def attach(self, new_node: Node, last_eval_node: Optional[Node],
               last_true_node: Optional[Node], source_file: str = "Unknown",
               condition_type: str = "Unknown") -> str:
        """Algorithm 4/6: where the new vertex goes, decided in one place.

        Empty tree      -> it becomes the root.
        Run ended on the node that produced the conclusion (n1 == n2)
                        -> right child: a more specific exception to that rule.
        Otherwise       -> left child of where the run stopped: the next
                           alternative to try.
        """
        if self.root is None:
            side = "ROOT"
            parent = None
        elif last_eval_node is last_true_node:
            side = "RIGHT"
            parent = last_eval_node
        else:
            side = "LEFT"
            parent = last_eval_node
        self.add_node_to_tree(
            parent, new_node, side, source_file,
            last_eval_node, last_true_node, condition_type,
        )
        return side

    def new_node(self, conditions: Sequence[str], conclusion: str,
                 case_summary: str) -> Node:
        """Build an unattached vertex for a case. Storage format unchanged."""
        rule = Rule(json.dumps([str(c) for c in conditions]), conclusion)
        return Node(Vertex(rule, case_summary, cases=[case_summary]))

    def merge_case(self, node: Node, case_summary: str, source_file: str = "Unknown"):
        """The agreement path: the case joins this vertex's X and its profile.

        The merged paragraph is what the clinician reads; the case list is what
        Algs 5 and 7 test against. Both are kept.
        """
        node.vertex.summary = llm_merge_summaries(node.vertex.summary, case_summary)
        cases = getattr(node.vertex, "cases", None)
        if not isinstance(cases, list):
            node.vertex.cases = []
        node.vertex.cases.append(case_summary)
        return node.vertex.summary

    def log_merge(self, source_file: str, last_eval_node: Optional[Node], last_true_node: Optional[Node]):
        """Logs a Merge event (Revision Triggered = False)."""
        self._log_event("MERGE_AGREEMENT", source_file, last_true_node, last_eval_node, False, "N/A")

    def undo_last_addition(self) -> Tuple[bool, str]:
        if not hasattr(self, 'history'):
            self.history = []
        
        if not self.history:
            return False, "No history to undo."

        item = self.history.pop()
        # Handle tuple size variation
        if len(item) == 4:
            parent, direction, node_to_remove, source_file = item
        else:
            parent, direction, node_to_remove = item
            source_file = "Unknown"

        if direction == "ROOT":
            self.root = None
            self._log_event("UNDO", source_file, None, None, "Reversed", "N/A")
            return True, "Root node removed. Tree is empty."
        
        if direction == "RIGHT":
            if parent.right == node_to_remove:
                parent.right = None
                self._log_event("UNDO", source_file, None, None, "Reversed", "N/A")
                return True, "Last specific rule (Right) removed."
            else:
                return False, "Tree structure mismatch during undo."
        
        if direction == "LEFT":
            if parent.left == node_to_remove:
                parent.left = None
                self._log_event("UNDO", source_file, None, None, "Reversed", "N/A")
                return True, "Last alternative rule (Left) removed."
            else:
                return False, "Tree structure mismatch during undo."
        
        return False, "Unknown error."

    def flush_tree(self):
        self._log_event("FLUSH_TREE", "N/A", None, None, "N/A", "N/A")
        self.root = None
        self.history = []
        self.last_vertex_number = -1
        if os.path.exists(TREE_STORAGE_FILE):
            try:
                os.remove(TREE_STORAGE_FILE)
                logging.warning(f"Deleted tree storage file: {TREE_STORAGE_FILE}")
            except Exception as e:
                logging.error(f"Failed to delete tree storage file: {e}")
        else:
            logging.info("Flush requested but no storage file found.")

    # --- the paper's loop, for an oracle that answers without a page reload ---

    def revise(self, case_summary: str, oracle, source_file: str = "Unknown",
               max_attempts: int = 10) -> Dict[str, Any]:
        """Algorithms 1 + 4 + 5 + 6 + 7, composed.

        `oracle` is anything with:
            agrees(conclusion, node)          -> bool
            correct_conclusion(conclusion)    -> str
            select(candidates, attempt, problem) -> list[str]

        `select` is called again, with the previous problem, whenever the chosen
        set fails the Alg 6/7 gate -- the repeat-until, rather than the old
        st.stop(). Returns a dict describing what happened, so a script or a
        test can assert on it.
        """
        trace: List[list] = []
        detail: List[dict] = []
        n1, n2 = self.interpret(case_summary, trace=trace, detail=detail)
        conclusion = n2.vertex.rule.conclusions if n2 else None

        outcome: Dict[str, Any] = {
            "trace": trace,
            "detail": detail,
            "last_eval_node": n1,
            "last_true_node": n2,
            "conclusion": conclusion,
        }

        if n2 is not None and oracle.agrees(conclusion, n2):
            self.merge_case(n2, case_summary, source_file)
            self.log_merge(source_file, n1, n2)
            outcome["action"] = "merged"
            return outcome

        new_conclusion = oracle.correct_conclusion(conclusion)
        rejected: List[Rejection] = []
        candidates = self.find_differences(case_summary, n2, rejected=rejected)
        outcome["candidates"] = candidates
        outcome["rejected_candidates"] = rejected

        stored = self.cases_of(n2)
        problem = None
        chosen: List[str] = []
        attempts = 0
        while attempts < max_attempts:
            attempts += 1
            chosen = list(oracle.select(candidates, attempts, problem))
            ok, problem = self.verify_conditions(chosen, case_summary, stored)
            if ok:
                break
        else:
            outcome["action"] = "abandoned"
            outcome["problem"] = problem
            return outcome

        if problem is not None:
            outcome["action"] = "abandoned"
            outcome["problem"] = problem
            return outcome

        node = self.new_node(chosen, new_conclusion, case_summary)
        side = self.attach(node, n1, n2, source_file,
                           condition_type="AI_GENERATED"
                           if all(c in candidates for c in chosen) else "MANUAL")
        outcome["action"] = "added"
        outcome["side"] = side
        outcome["node"] = node
        outcome["conditions"] = chosen
        outcome["attempts"] = attempts
        return outcome

# --- Persistence Helpers ---

def load_tree() -> RDREngine:
    if os.path.exists(TREE_STORAGE_FILE):
        try:
            with open(TREE_STORAGE_FILE, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass
    return RDREngine()

def save_tree(engine):
    with open(TREE_STORAGE_FILE, "wb") as f:
        pickle.dump(engine, f)
