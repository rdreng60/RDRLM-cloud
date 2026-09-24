"""Gap 4 — the condition list must be a hard AND, one call per conjunct (Alg 3).

Before: the whole JSON array was dropped into a prompt written for a single
condition, so one word came back for the entire rule and there was no telling
which question had been answered.
"""

import json
import pytest


RULE = ["insomnia", "stopped medication", "panic attacks"]
PATIENT = "Insomnia. Low mood for 3 years. On medication."


def test_one_call_per_condition_not_one_for_the_list(engine, oracle):
    oracle.facts = {PATIENT: {"insomnia"}}

    check = engine.evaluate_rule(PATIENT, json.dumps(RULE))

    assert check.holds is False
    # The paper's loop: ask about conjuncts one at a time, never about the list.
    assert oracle.conditions_asked() == ["insomnia", "stopped medication"]
    assert json.dumps(RULE) not in oracle.conditions_asked()


def test_stops_at_the_first_false(engine, oracle):
    oracle.facts = {PATIENT: {"insomnia"}}

    check = engine.evaluate_rule(PATIENT, json.dumps(RULE))

    assert check.results == [("insomnia", True), ("stopped medication", False)]
    assert check.failed_on == "stopped medication"
    # The third conjunct is never asked: the AND is already decided.
    assert "panic attacks" not in oracle.conditions_asked()


def test_all_true_means_the_rule_holds(engine, oracle):
    case = "Insomnia. Stopped medication 3 days ago. Panic attacks."
    oracle.facts = {case: set(RULE)}

    check = engine.evaluate_rule(case, json.dumps(RULE))

    assert check.holds is True
    assert [c for c, _ in check.results] == RULE
    assert check.failed_on is None


def test_a_single_true_conjunct_is_not_enough(engine, oracle):
    """'is the main one true?' and 'are all three true?' now differ."""
    oracle.facts = {PATIENT: {"insomnia", "panic attacks"}}
    assert engine.evaluate_rule(PATIENT, json.dumps(RULE)).holds is False


def test_legacy_bare_string_condition_still_reads_as_one_conjunct(engine, oracle):
    oracle.facts = {PATIENT: {"chronic low mood"}}
    check = engine.evaluate_rule(PATIENT, "chronic low mood")
    assert check.holds is True
    assert oracle.conditions_asked() == ["chronic low mood"]


def test_trace_records_every_condition_not_just_the_node(engine, oracle):
    """There is now a per-condition record, which the old trace never had."""
    oracle.facts = {PATIENT: {"insomnia"}}
    node = engine.new_node(RULE, "withdrawal reaction", "seed")
    engine.attach(node, None, None, "case.docx")

    trace, detail = [], []
    engine.interpret(PATIENT, trace=trace, detail=detail)

    assert trace == [["Root", False]]          # unchanged node-level shape
    assert detail[0]["node"] == "Root"
    assert detail[0]["result"] is False
    assert detail[0]["conditions"] == [
        ("insomnia", True),
        ("stopped medication", False),
    ]


def test_a_wrong_true_would_put_the_next_rule_in_the_wrong_place(engine, oracle):
    """Why Gap 4 compounds: the branch decides where revision attaches.

    Same tree, same case, and the only difference is whether the rule is
    evaluated as a conjunction or waved through as one blob.
    """
    root = engine.new_node(RULE, "withdrawal reaction", "seed")
    engine.attach(root, None, None, "seed.docx")
    oracle.facts = {PATIENT: {"insomnia"}}

    # Per-condition (Alg 3): the rule is FALSE, the walk goes left, and nothing
    # was ever true, so there is no conclusion to be an exception to.
    n1, n2 = engine.interpret(PATIENT)
    assert (n1, n2) == (root, None)

    new = engine.new_node(["chronic low mood"], "moderate depression", PATIENT)
    side = engine.attach(new, n1, n2, "new.docx")
    assert side == "LEFT"
    assert root.left is new and root.right is None

    # What the blob answer would have done: a single TRUE for the whole array
    # makes the walk stop on the node it just confirmed, so n1 is n2 and the
    # new rule is attached as a RIGHT child — a permanent exception hung off a
    # rule that was never actually satisfied.
    engine.undo_last_addition()
    assert root.left is None
    wrong = engine.new_node(["chronic low mood"], "moderate depression", PATIENT)
    wrong_side = engine.attach(wrong, root, root, "new.docx")
    assert wrong_side == "RIGHT"
    assert root.right is wrong
