"""Gap 7 — llm_verify_manual_condition always returned true.
Gap 9 — a failed API call was read as "condition false".

These run against llm_api itself, with a stand-in for `model`, so the reply
parsing and the error handling are exercised for real.
"""

import pytest
import llm_api
from llm_api import LLMError


# --- Gap 7 --------------------------------------------------------------

def test_the_always_true_duplicate_is_gone():
    """`return 'TRUE'` returned the literal string, which is always truthy.

    Its caller at app.py:408 checked the reference summary, so every manual
    condition was rejected with "Differentiation Failed" and manual entry was
    unusable. The function duplicated llm_check_condition and is deleted in
    favour of it.
    """
    assert not hasattr(llm_api, "llm_verify_manual_condition")


def test_false_really_means_false(fake_model):
    fake_model(replies=["FALSE"])
    assert llm_check("any summary", "insomnia") is False


def test_true_means_true(fake_model):
    fake_model(replies=["TRUE"])
    assert llm_check("any summary", "insomnia") is True


def test_the_reply_is_read_case_insensitively_and_trimmed(fake_model):
    fake_model(replies=["  true\n"])
    assert llm_check("s", "c") is True


def llm_check(summary, condition):
    return llm_api.llm_check_condition(summary, condition)


# --- Gap 9: a failed call is not an answer ------------------------------

def test_a_failed_condition_check_raises_instead_of_answering_false(fake_model):
    fake_model(raises=TimeoutError("deadline exceeded"))

    with pytest.raises(LLMError) as excinfo:
        llm_api.llm_check_condition("summary", "insomnia")

    assert excinfo.value.operation == "condition check"
    assert "TimeoutError" in excinfo.value.detail


def test_a_quota_error_is_distinguishable_from_a_genuine_false(fake_model):
    fake_model(raises=RuntimeError("429 quota exceeded"))
    with pytest.raises(LLMError):
        llm_api.llm_check_condition("summary", "insomnia")


def test_a_failed_difference_call_raises(fake_model):
    fake_model(raises=ConnectionError("reset by peer"))
    with pytest.raises(LLMError):
        llm_api.llm_get_differentiating_conditions("new", "ref")


def test_an_unparseable_reply_is_not_no_differences_found(fake_model):
    fake_model(replies=["I'm sorry, I can't help with that."])

    with pytest.raises(LLMError) as excinfo:
        llm_api.llm_get_differentiating_conditions("new", "ref")

    assert "not JSON" in excinfo.value.detail


def test_a_non_list_reply_is_refused(fake_model):
    fake_model(replies=['{"condition": "insomnia"}'])
    with pytest.raises(LLMError):
        llm_api.llm_get_differentiating_conditions("new", "ref")


def test_a_genuinely_empty_list_is_still_an_empty_list(fake_model):
    """"no differences found" must remain expressible."""
    fake_model(replies=["[]"])
    assert llm_api.llm_get_differentiating_conditions("new", "ref") == []


def test_a_fenced_json_block_is_still_unwrapped(fake_model):
    fake_model(replies=['```json\n["insomnia", "panic attacks"]\n```'])
    assert llm_api.llm_get_differentiating_conditions("new", "ref") == [
        "insomnia",
        "panic attacks",
    ]


def test_blank_candidates_are_dropped(fake_model):
    fake_model(replies=['["insomnia", "  ", ""]'])
    assert llm_api.llm_get_differentiating_conditions("n", "r") == ["insomnia"]


# --- Gap 9, seen from the engine ---------------------------------------

def test_the_walk_stops_rather_than_branching_on_an_outage(engine, oracle):
    """A left branch taken on an error would place every later rule wrongly."""
    node = engine.new_node(["chronic low mood"], "moderate depression", "seed")
    engine.attach(node, None, None, "seed.docx")
    oracle.fail_check_on = {"chronic low mood"}

    with pytest.raises(LLMError):
        engine.interpret("some patient")

    # Nothing was attached, nothing was decided.
    assert engine.root is node and node.left is None and node.right is None


def test_the_failure_is_recorded_in_the_event_log(engine, oracle, isolated_storage):
    import csv

    try:
        raise LLMError("condition check", "simulated outage")
    except LLMError as err:
        engine.log_llm_error("case_12.docx", err)

    rows = list(csv.reader(open(isolated_storage / "rdr_event_log.csv")))
    entry = [r for r in rows if r and r[2] == "LLM_ERROR"]
    assert len(entry) == 1
    assert entry[0][3] == "case_12.docx"
    assert "simulated outage" in entry[0][4]
    assert entry[0][7] == "condition check"
    # The column count is unchanged, so existing readers of the CSV still work.
    assert len(entry[0]) == len(rows[0])
