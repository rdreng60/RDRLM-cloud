"""Gap 10 — the log recorded memory addresses, not node numbers.

`id(n)` is where the object happened to sit in RAM during one run. Restart the
app, load the pickle, and the same node gets a different number, so no row in
rdr_event_log.csv could be joined to any row from another session.
"""

import csv
import pickle
import pytest


def rows(storage):
    with open(storage / "rdr_event_log.csv", newline="") as f:
        return [r for r in csv.reader(f) if r and r[0] != "Date"]


def test_vertices_are_numbered_from_zero_like_the_papers_table(engine, oracle):
    oracle.facts = {"a": {"c1"}, "b": {"c1", "c2"}}
    root = engine.new_node(["c1"], "first", "a")
    engine.attach(root, None, None, "a.docx")
    child = engine.new_node(["c2"], "second", "b")
    engine.attach(child, root, root, "b.docx")

    assert root.number == 0
    assert child.number == 1
    assert engine.last_vertex_number == 1     # the paper's `s`


def test_the_log_records_the_number_not_the_address(engine, oracle, isolated_storage):
    oracle.facts = {"a": {"c1"}}
    root = engine.new_node(["c1"], "moderate depression", "a")
    engine.attach(root, None, None, "case_12.docx")
    child = engine.new_node(["c2"], "withdrawal reaction", "b")
    engine.attach(child, root, root, "case_13.docx")

    cell = rows(isolated_storage)[-1][4]      # Last_True_Node
    assert cell.startswith("[#0]")
    assert str(id(root)) not in cell


def test_the_number_survives_a_restart(engine, oracle, isolated_storage, tmp_path):
    """The whole point: rows from two sessions can be joined."""
    oracle.facts = {"a": {"c1"}, "b": {"c2"}}
    root = engine.new_node(["c1"], "first", "a")
    engine.attach(root, None, None, "a.docx")
    child = engine.new_node(["c2"], "second", "b")
    engine.attach(child, root, root, "b.docx")

    before = [(n.number, id(n)) for n in engine.walk()]

    blob = pickle.dumps(engine)
    revived = pickle.loads(blob)
    after = [(n.number, id(n)) for n in revived.walk()]

    assert [n for n, _ in before] == [n for n, _ in after]      # numbers hold
    assert [a for _, a in before] != [a for _, a in after]      # addresses do not


def test_numbering_continues_after_a_reload(engine, oracle):
    oracle.facts = {"a": {"c1"}, "b": {"c2"}, "c": {"c3"}}
    root = engine.new_node(["c1"], "first", "a")
    engine.attach(root, None, None, "a.docx")

    revived = pickle.loads(pickle.dumps(engine))
    nxt = revived.new_node(["c2"], "second", "b")
    revived.attach(nxt, revived.root, revived.root, "b.docx")

    assert nxt.number == 1, "a reloaded engine must not reuse a number"


def test_numbers_are_never_reused_after_an_undo(engine, oracle):
    oracle.facts = {"a": {"c1"}, "b": {"c2"}, "c": {"c3"}}
    root = engine.new_node(["c1"], "first", "a")
    engine.attach(root, None, None, "a.docx")
    second = engine.new_node(["c2"], "second", "b")
    engine.attach(second, root, root, "b.docx")
    engine.undo_last_addition()

    third = engine.new_node(["c3"], "third", "c")
    engine.attach(third, root, root, "c.docx")

    assert third.number == 2, "an undone vertex's number must not come back"


def test_a_tree_pickled_before_numbering_gets_numbered_on_demand(engine, oracle):
    """Old pickles have no `number` and no `last_vertex_number`."""
    oracle.facts = {"a": {"c1"}, "b": {"c2"}}
    root = engine.new_node(["c1"], "first", "a")
    engine.attach(root, None, None, "a.docx")
    child = engine.new_node(["c2"], "second", "b")
    engine.attach(child, root, root, "b.docx")

    for n in engine.walk():
        del n.number
    del engine.last_vertex_number

    fresh = engine.new_node(["c3"], "third", "c")
    engine.attach(fresh, root, child, "c.docx")

    numbers = sorted(n.number for n in engine.walk())
    assert numbers == [0, 1, 2], "every vertex must end up with a distinct number"


def test_counting_how_often_a_node_fired_is_answerable(engine, oracle, isolated_storage):
    """The three questions the gap note says the log could not answer."""
    oracle.facts = {"a": {"c1"}, "b": {"c1"}, "c": {"c1"}}
    root = engine.new_node(["c1"], "moderate depression", "a")
    engine.attach(root, None, None, "a.docx")

    for f in ("b.docx", "c.docx"):
        n1, n2 = engine.interpret("b")
        engine.log_merge(f, n1, n2)

    hits = [r for r in rows(isolated_storage) if r[4].startswith("[#0]")]
    assert len(hits) == 2          # "how many times did this node fire?"
    assert all(r[2] == "MERGE_AGREEMENT" for r in hits)
