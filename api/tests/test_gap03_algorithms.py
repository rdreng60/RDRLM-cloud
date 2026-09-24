"""Gap 3 — the algorithms must be in the engine, not in the Streamlit buttons.

`revise()` was `pass`; the real work sat between a pickle write and an
st.error call, so a script could not call it and a test could not check it.
Every test in this file is the proof that it now can: none of them import
Streamlit, and none of them press a button.
"""

import json
import pickle
import pytest


class ScriptedClinician:
    """An oracle that answers without a page reload.

    `picks` is the list of condition sets it will choose, in order — so a test
    can make the first choice illegal and check that it is asked again.
    """

    def __init__(self, agree=False, conclusion="withdrawal reaction", picks=None):
        self.agree = agree
        self.conclusion = conclusion
        self.picks = list(picks or [])
        self.problems = []
        self.seen_candidates = []

    def agrees(self, conclusion, node):
        return self.agree

    def correct_conclusion(self, conclusion):
        return self.conclusion

    def select(self, candidates, attempt, problem):
        self.seen_candidates.append(list(candidates))
        self.problems.append(problem)
        return self.picks[min(attempt - 1, len(self.picks) - 1)]


OLD = "Insomnia. Low mood for 2 years. On medication."
NEW = "Insomnia. Stopped medication 3 days ago. Panic attacks."
# As in the worked example: the new case lands on N — "chronic low mood" reads
# as true of it — and the clinician refutes the conclusion that N draws.
FACTS = {
    OLD: {"chronic low mood", "insomnia"},
    NEW: {"chronic low mood", "insomnia", "panic attacks", "stopped medication"},
}


@pytest.fixture
def seeded(engine, oracle):
    oracle.facts = dict(FACTS)
    oracle.differences = ["insomnia", "panic attacks", "stopped medication"]
    root = engine.new_node(["chronic low mood"], "moderate depression", OLD)
    engine.attach(root, None, None, "old.docx")
    return root


def test_the_whole_loop_runs_from_a_script(engine, oracle, seeded):
    clinician = ScriptedClinician(picks=[["panic attacks"]])

    result = engine.revise(NEW, clinician, "new.docx")

    assert result["action"] == "added"
    # The run stopped on the node that produced the conclusion, so the new rule
    # is an exception to it: a right child (Algorithm 4).
    assert result["side"] == "RIGHT"
    assert seeded.right is result["node"]
    assert result["node"].vertex.rule.conclusions == "withdrawal reaction"


def test_agreement_merges_instead_of_adding(engine, oracle, seeded):
    clinician = ScriptedClinician(agree=True)
    case = "Low mood for years."
    oracle.facts[case] = {"chronic low mood"}

    result = engine.revise(case, clinician, "agree.docx")

    assert result["action"] == "merged"
    assert case in engine.cases_of(seeded)
    assert seeded.left is None and seeded.right is None


def test_an_illegal_choice_sends_the_clinician_round_again(engine, oracle, seeded):
    """The repeat-until of Algorithms 6 + 7, in place of st.stop().

    First pick is insomnia, which is true of the stored case. The old code
    killed the page; the loop now asks for another selection and says why.
    """
    clinician = ScriptedClinician(picks=[["insomnia"], ["panic attacks"]])

    result = engine.revise(NEW, clinician, "new.docx")

    assert result["action"] == "added"
    assert result["attempts"] == 2
    assert clinician.problems[0] is None            # nothing wrong to report yet
    assert clinician.problems[1].reason == "true_of_stored"
    assert result["conditions"] == ["panic attacks"]


def test_a_clinician_who_never_finds_a_legal_set_leaves_the_tree_alone(engine, oracle, seeded):
    clinician = ScriptedClinician(picks=[["insomnia"]])

    result = engine.revise(NEW, clinician, "new.docx", max_attempts=3)

    assert result["action"] == "abandoned"
    assert result["problem"].reason == "true_of_stored"
    assert seeded.left is None and seeded.right is None


def test_the_candidates_offered_are_already_verified(engine, oracle, seeded):
    clinician = ScriptedClinician(picks=[["panic attacks"]])
    engine.revise(NEW, clinician, "new.docx")

    # insomnia never reaches the clinician: Algorithm 5 filtered it.
    assert clinician.seen_candidates[0] == ["panic attacks", "stopped medication"]


def test_the_same_cases_twice_build_the_same_tree(engine, oracle, seeded):
    """'running the same cases twice is not guaranteed to build the same tree'."""
    import rdr_engine

    def build():
        e = rdr_engine.RDREngine()
        root = e.new_node(["chronic low mood"], "moderate depression", OLD)
        e.attach(root, None, None, "old.docx")
        e.revise(NEW, ScriptedClinician(picks=[["panic attacks"]]), "new.docx")
        return e

    def shape(e):
        def walk(n, path="Root"):
            if n is None:
                return []
            return (
                [(path, n.number, n.vertex.rule.conditions, n.vertex.rule.conclusions)]
                + walk(n.left, path + "L")
                + walk(n.right, path + "R")
            )
        return walk(e.root)

    assert shape(build()) == shape(build())


def test_the_engine_pickles_and_keeps_working(engine, oracle, seeded):
    engine.revise(NEW, ScriptedClinician(picks=[["panic attacks"]]), "new.docx")
    revived = pickle.loads(pickle.dumps(engine))

    n1, n2 = revived.interpret(NEW)
    assert n2.vertex.rule.conclusions == "withdrawal reaction"


def test_attachment_side_is_decided_in_one_place(engine, oracle):
    """Algorithm 4: root, right for a refinement, left for an alternative."""
    oracle.facts = {"x": {"c1"}}

    first = engine.new_node(["c1"], "first", "x")
    assert engine.attach(first, None, None, "a.docx") == "ROOT"

    # run stopped on the node that produced the conclusion -> exception to it
    refinement = engine.new_node(["c2"], "second", "x")
    assert engine.attach(refinement, first, first, "b.docx") == "RIGHT"

    # run stopped somewhere the conclusion did not come from -> next alternative
    alternative = engine.new_node(["c3"], "third", "x")
    assert engine.attach(alternative, refinement, first, "c.docx") == "LEFT"


def test_interpret_returns_the_two_nodes_the_paper_names(engine, oracle):
    oracle.facts = {"case": {"c1", "c3"}}
    root = engine.new_node(["c1"], "A", "s")
    engine.attach(root, None, None, "a.docx")
    right = engine.new_node(["c2"], "B", "s")
    engine.attach(right, root, root, "b.docx")
    left_of_right = engine.new_node(["c3"], "C", "s")
    engine.attach(left_of_right, right, root, "c.docx")

    trace = []
    n1, n2 = engine.interpret("case", trace=trace)

    assert n1 is left_of_right       # last vertex evaluated
    assert n2 is left_of_right       # last vertex that was true
    assert trace == [["Root", True], ["RootR", False], ["RootRL", True]]


def test_an_empty_tree_concludes_nothing(engine, oracle):
    assert engine.interpret("anything") == (None, None)


def test_path_ids_and_node_objects_round_trip(engine, oracle):
    oracle.facts = {"x": {"c1"}}
    root = engine.new_node(["c1"], "A", "x")
    engine.attach(root, None, None, "a.docx")
    kid = engine.new_node(["c2"], "B", "x")
    engine.attach(kid, root, root, "b.docx")

    assert engine.path_of(kid) == "RootR"
    assert engine.node_at("RootR") is kid
    assert engine.node_at("RootL") is None
    assert engine.node_at(None) is None
    assert engine.path_of(None) is None
