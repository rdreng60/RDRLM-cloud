"""Gaps 5 + 6 — conditions must be verified against the stored cases.

This is the worked example from rdr-spec-gaps.md, run end to end.

Node N: IF ["chronic low mood"] THEN moderate depression, holding three cases.
Old1 says insomnia, Old2 says hypersomnia, so the merge generalises insomnia
away into "sleep disturbances" and the clinician never sees it. The proposal
step therefore offers "insomnia" as a difference, and the save step used to let
it through because the conditions came from checkboxes.
"""

import json
import pytest


OLD1 = "Insomnia. On medication. Low mood for 2 years."
OLD2 = "Hypersomnia. Low mood for 4 years. Socially withdrawn."
OLD3 = "Insomnia. Low mood for 3 years. On medication."
MERGED = "persistent low mood over several years and sleep disturbances"
NEW = "Insomnia. Stopped medication 3 days ago. Panic attacks."
LATER = "Insomnia. Low mood for 3 years. On medication."

FACTS = {
    OLD1: {"chronic low mood", "insomnia"},
    OLD2: {"chronic low mood", "hypersomnia"},
    OLD3: {"chronic low mood", "insomnia"},
    MERGED: {"chronic low mood", "sleep disturbances"},
    NEW: {"insomnia", "panic attacks", "stopped medication"},
    LATER: {"chronic low mood", "insomnia"},
}


@pytest.fixture
def node_n(engine, oracle):
    oracle.facts = dict(FACTS)
    oracle.differences = ["insomnia", "panic attacks", "stopped medication"]
    node = engine.new_node(["chronic low mood"], "moderate depression", OLD1)
    node.vertex.summary = MERGED
    node.vertex.cases = [OLD1, OLD2, OLD3]
    engine.attach(node, None, None, "old1.docx")
    return node


# --- Gap 5: the proposal ------------------------------------------------

def test_candidates_are_checked_against_every_stored_case(engine, oracle, node_n):
    rejected = []
    kept = engine.find_differences(NEW, node_n, rejected=rejected)

    # insomnia is true of Old1 and Old3, so it does not distinguish anything.
    assert kept == ["panic attacks", "stopped medication"]
    assert [r.condition for r in rejected] == ["insomnia"]
    assert rejected[0].reason == "true_of_stored"
    assert rejected[0].case_index == 0          # Old1


def test_every_stored_case_is_actually_consulted(engine, oracle, node_n):
    engine.find_differences(NEW, node_n)
    for case in (OLD1, OLD2, OLD3):
        assert any(c == case for c, _ in oracle.checks), f"{case} never tested"


def test_a_candidate_false_of_the_new_case_is_dropped(engine, oracle, node_n):
    oracle.differences = ["panic attacks", "hypersomnia"]
    rejected = []
    kept = engine.find_differences(NEW, node_n, rejected=rejected)

    assert kept == ["panic attacks"]
    assert rejected[0].condition == "hypersomnia"
    assert rejected[0].reason == "false_of_new"


def test_the_proposal_sees_the_cases_not_only_the_merged_paragraph(engine, oracle, node_n):
    engine.find_differences(NEW, node_n)
    _, reference = oracle.diff_calls[0]
    for case in (OLD1, OLD2, OLD3):
        assert case in reference
    assert "Case 1:" in reference


def test_nothing_survives_when_the_model_returns_nothing(engine, oracle, node_n):
    oracle.differences = []
    assert engine.find_differences(NEW, node_n) == []


# --- Gap 6: the save gate ------------------------------------------------

def test_a_checkbox_condition_is_verified_too(engine, oracle, node_n):
    """The old code only checked hand-typed conditions. Origin is irrelevant."""
    ok, problem = engine.verify_conditions(["insomnia"], NEW, engine.cases_of(node_n))

    assert ok is False
    assert problem.reason == "true_of_stored"
    assert problem.case_index == 0


def test_the_conjunction_is_tested_whole_not_condition_by_condition(engine, oracle, node_n):
    """The legal rule that the old per-condition filter refused.

    insomnia AND panic attacks: against Old1 that is yes AND no = FALSE, so no
    stored case matches and the rule is legal. Only the whole conjunction has to
    be false of the stored cases.
    """
    ok, problem = engine.verify_conditions(
        ["insomnia", "panic attacks"], NEW, engine.cases_of(node_n)
    )

    assert ok is True, "a legal combination was blocked"
    assert problem is None


def test_a_condition_false_of_the_new_case_is_refused(engine, oracle, node_n):
    ok, problem = engine.verify_conditions(
        ["panic attacks", "hypersomnia"], NEW, engine.cases_of(node_n)
    )
    assert ok is False
    assert problem.reason == "false_of_new"
    assert problem.condition == "hypersomnia"


def test_exists_satisfied_reports_which_case(engine, oracle, node_n):
    cases = engine.cases_of(node_n)
    assert engine.exists_satisfied(["insomnia"], cases) == 0
    assert engine.exists_satisfied(["hypersomnia"], cases) == 1
    assert engine.exists_satisfied(["insomnia", "panic attacks"], cases) is None
    assert engine.exists_satisfied(["panic attacks"], cases) is None


def test_the_empty_set_is_not_a_rule(engine, oracle, node_n):
    ok, problem = engine.verify_conditions([], NEW, engine.cases_of(node_n))
    assert ok is False
    assert problem.reason == "empty"


def test_the_wrong_rule_from_the_worked_example_cannot_be_saved(engine, oracle, node_n):
    """The whole point: the later patient must not get 'withdrawal reaction'.

    IF ["insomnia"] THEN withdrawal reaction, hung right of N, made every
    insomnia patient on that branch a withdrawal case. It is now refused at the
    gate, so the tree never acquires it.
    """
    ok, _ = engine.verify_conditions(["insomnia"], NEW, engine.cases_of(node_n))
    assert ok is False

    # Nothing was attached, so the later patient still lands on N's conclusion.
    n1, n2 = engine.interpret(LATER)
    assert n2 is node_n
    assert n2.vertex.rule.conclusions == "moderate depression"


def test_the_legal_rule_does_save_and_behaves(engine, oracle, node_n):
    conditions = ["insomnia", "panic attacks"]
    ok, _ = engine.verify_conditions(conditions, NEW, engine.cases_of(node_n))
    assert ok

    n1, n2 = engine.interpret(NEW)
    new_node = engine.new_node(conditions, "withdrawal reaction", NEW)
    engine.attach(new_node, n1, n2, "new.docx")

    # The new case now reaches the new conclusion...
    assert engine.interpret(NEW)[1] is new_node
    # ...and the plain-depression patient does not.
    assert engine.interpret(LATER)[1] is node_n


def test_cases_survive_a_merge(engine, oracle, node_n):
    """Agreement adds to X as well as to the paragraph.

    The merged paragraph is what the clinician reads; the case list is what
    Algorithms 5 and 7 are run against, so it must keep growing.
    """
    before = list(engine.cases_of(node_n))
    engine.merge_case(node_n, LATER, "later.docx")

    assert engine.cases_of(node_n) == before + [LATER]
    assert node_n.vertex.summary != MERGED     # the profile was merged too


def test_a_legacy_vertex_without_a_case_list_falls_back_to_its_summary(engine, oracle):
    import rdr_engine

    vertex = rdr_engine.Vertex(
        rdr_engine.Rule(json.dumps(["chronic low mood"]), "moderate depression"),
        MERGED,
    )
    del vertex.cases                     # as an old pickle would unpickle
    node = rdr_engine.Node(vertex)
    oracle.facts = dict(FACTS)

    assert engine.cases_of(node) == [MERGED]
    ok, _ = engine.verify_conditions(["chronic low mood"], OLD1, engine.cases_of(node))
    assert ok is False                   # still checked against something
