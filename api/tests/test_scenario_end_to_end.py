"""A whole clinic's worth of cases, driven through the engine in one script.

This is the thing Gap 3 said was impossible: "A script cannot call it, a test
cannot check it, and running the same cases twice is not guaranteed to build the
same tree."
"""

import pickle
import pytest


# --- a small world -------------------------------------------------------

CASES = {
    "c1": ("case1.docx", {"chronic low mood", "insomnia", "on medication"}),
    "c2": ("case2.docx", {"chronic low mood", "hypersomnia", "socially withdrawn"}),
    "c3": ("case3.docx", {"chronic low mood", "insomnia", "on medication"}),
    "c4": ("case4.docx", {"chronic low mood", "insomnia", "stopped medication",
                          "panic attacks"}),
    "c5": ("case5.docx", {"chronic low mood", "insomnia", "on medication"}),
}


class Clinician:
    """Agrees unless the case is in `refutes`, then dictates the fix."""

    def __init__(self, refutes):
        self.refutes = refutes      # case -> (conclusion, chosen conditions)
        self.case = None

    def agrees(self, conclusion, node):
        return self.case not in self.refutes

    def correct_conclusion(self, conclusion):
        return self.refutes[self.case][0]

    def select(self, candidates, attempt, problem):
        return self.refutes[self.case][1]


def run_clinic(engine, oracle, clinician, order):
    for name in order:
        source, _ = CASES[name]
        clinician.case = name
        if engine.root is None:
            node = engine.new_node(["chronic low mood"], "moderate depression", name)
            engine.attach(node, None, None, source)
            continue
        engine.revise(name, clinician, source)
    return engine


@pytest.fixture
def world(oracle):
    oracle.facts = {name: facts for name, (_, facts) in CASES.items()}
    oracle.differences = [
        "insomnia", "panic attacks", "stopped medication", "socially withdrawn",
    ]
    return oracle


def test_five_cases_build_one_correct_tree(engine, world):
    clinician = Clinician({
        "c4": ("withdrawal reaction", ["panic attacks", "stopped medication"]),
    })
    run_clinic(engine, world, clinician, ["c1", "c2", "c3", "c4", "c5"])

    # c1 seeded the root; c2 and c3 agreed and merged into it; c4 was refuted
    # and became an exception; c5 is plain depression again.
    assert engine.root.vertex.rule.conclusions == "moderate depression"
    assert engine.root.right is not None
    assert engine.root.right.vertex.rule.conclusions == "withdrawal reaction"
    assert engine.root.left is None

    assert engine.interpret("c5")[1] is engine.root
    assert engine.interpret("c4")[1] is engine.root.right


def test_the_insomnia_trap_is_refused_even_if_the_clinician_ticks_it(engine, world):
    """The failure the gap note walks through, attempted deliberately.

    The clinician ticks 'insomnia', which is true of the new case and looks
    right on screen because the merged paragraph only says 'sleep disturbances'.
    It is true of c1 and c3, which are already filed at the node, so the rule is
    refused and the trap never enters the tree.
    """
    clinician = Clinician({"c4": ("withdrawal reaction", ["insomnia"])})
    run_clinic(engine, world, clinician, ["c1", "c2", "c3"])

    clinician.case = "c4"
    result = engine.revise("c4", clinician, "case4.docx", max_attempts=2)

    assert result["action"] == "abandoned"
    assert result["problem"].reason == "true_of_stored"
    assert engine.root.right is None

    # And the later plain-depression patient is still answered correctly.
    assert engine.interpret("c5")[1].vertex.rule.conclusions == "moderate depression"


def test_the_same_cases_in_the_same_order_give_the_same_tree(engine, world):
    import rdr_engine

    def build():
        e = rdr_engine.RDREngine()
        c = Clinician({"c4": ("withdrawal reaction", ["panic attacks"])})
        run_clinic(e, world, c, ["c1", "c2", "c3", "c4", "c5"])
        return shape(e)

    def shape(e):
        def walk(n, path="Root"):
            if n is None:
                return []
            return ([(path, n.number, n.vertex.rule.conditions,
                      n.vertex.rule.conclusions, tuple(e.cases_of(n)))]
                    + walk(n.left, path + "L") + walk(n.right, path + "R"))
        return walk(e.root)

    assert build() == build()


def test_the_tree_survives_being_saved_and_loaded_mid_clinic(engine, world):
    clinician = Clinician({"c4": ("withdrawal reaction", ["panic attacks"])})
    run_clinic(engine, world, clinician, ["c1", "c2", "c3"])

    revived = pickle.loads(pickle.dumps(engine))
    clinician.case = "c4"
    result = revived.revise("c4", clinician, "case4.docx")

    assert result["action"] == "added"
    assert result["node"].number == 1        # numbering continued, not restarted
    assert revived.interpret("c4")[1] is result["node"]


def test_when_no_rule_fires_there_is_no_stored_case_to_exclude(engine, world):
    """Which X the gate uses, pinned deliberately.

    X is the case set of the vertex whose conclusion was refuted. If nothing was
    ever true there is no such vertex, so there is nothing for the new rule to
    be false of — and the cases filed at the node the walk stopped on cannot
    reach the new left child anyway, because they satisfy that node's rule.
    """
    node = engine.new_node(["chronic low mood"], "moderate depression", "c1")
    engine.attach(node, None, None, "case1.docx")
    world.facts["stranger"] = {"acute grief"}

    n1, n2 = engine.interpret("stranger")
    assert (n1, n2) == (node, None)
    assert engine.cases_of(n2) == []

    ok, problem = engine.verify_conditions(["acute grief"], "stranger", engine.cases_of(n2))
    assert ok is True and problem is None

    new = engine.new_node(["acute grief"], "bereavement", "stranger")
    assert engine.attach(new, n1, n2, "stranger.docx") == "LEFT"
    # The cases filed at the root still reach the root's own conclusion.
    assert engine.interpret("c1")[1] is node


def test_an_agreed_case_joins_the_set_the_next_rule_is_tested_against(engine, world):
    """Gaps 5 and 6 depend on X growing, so this is the link between them."""
    clinician = Clinician({})
    run_clinic(engine, world, clinician, ["c1", "c2", "c3"])

    assert engine.cases_of(engine.root) == ["c1", "c2", "c3"]

    rejected = []
    kept = engine.find_differences("c4", engine.root, rejected=rejected)
    assert "insomnia" not in kept
    assert "socially withdrawn" not in kept        # true of c2
    assert set(kept) == {"panic attacks", "stopped medication"}
