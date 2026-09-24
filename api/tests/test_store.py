"""The Postgres layer: the part that replaces the pickled blob.

These need a real Postgres, because the thing being tested is a unique
constraint and a locked row — neither of which a fake would exercise. Point
TEST_DATABASE_URL at a scratch database:

    createdb rdr_test
    TEST_DATABASE_URL=postgresql://localhost/rdr_test python -m pytest api/tests

Without it they skip.
"""

import os
import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")


def seed(db, conn, oracle):
    """Root: chronic low mood -> moderate depression, holding one case."""
    return db.insert_vertex(
        conn, "sangath", None, "root", ["chronic low mood"],
        "moderate depression", "Insomnia. On medication. Low mood for 2 years.",
        "rohit@x.com", "old1.docx",
    )


# --- rows in, tree out ---------------------------------------------------

def test_a_saved_rule_comes_back_as_a_tree(db, conn, oracle):
    seed(db, conn, oracle)
    db.insert_vertex(
        conn, "sangath", 0, "right", ["panic attacks", "stopped medication"],
        "withdrawal reaction", "Panic attacks. Stopped medication.",
        "priya@x.com", "new.docx",
    )
    conn.commit()

    engine = db.load_engine(conn, "sangath", "rohit@x.com")

    assert engine.root.vertex.rule.conclusions == "moderate depression"
    assert engine.root.number == 0
    assert engine.root.right.number == 1
    assert engine.root.right.vertex.rule.condition_list() == [
        "panic attacks", "stopped medication",
    ]
    assert engine.root.left is None
    assert engine.last_vertex_number == 1


def test_the_stored_cases_survive_the_round_trip(db, conn, oracle):
    seed(db, conn, oracle)
    db.merge_case(conn, "sangath", 0, "merged profile text",
                  "Hypersomnia. Low mood for 4 years.", "priya@x.com", "old2.docx")
    conn.commit()

    engine = db.load_engine(conn, "sangath", "rohit@x.com")
    cases = engine.cases_of(engine.root)

    assert cases == [
        "Insomnia. On medication. Low mood for 2 years.",
        "Hypersomnia. Low mood for 4 years.",
    ]
    assert engine.root.vertex.summary == "merged profile text"


def test_the_algorithms_run_on_a_tree_loaded_from_rows(db, conn, oracle):
    """The point of keeping rdr_engine.py byte-identical."""
    seed(db, conn, oracle)
    db.merge_case(conn, "sangath", 0, "sleep disturbances and low mood",
                  "Insomnia. Low mood for 3 years.", "priya@x.com", "old3.docx")
    conn.commit()

    engine = db.load_engine(conn, "sangath", "rohit@x.com")
    oracle.facts = {
        "Insomnia. On medication. Low mood for 2 years.": {"chronic low mood", "insomnia"},
        "Insomnia. Low mood for 3 years.": {"chronic low mood", "insomnia"},
        "new case": {"chronic low mood", "insomnia", "panic attacks"},
    }

    # insomnia is true of both stored cases, so it cannot differentiate.
    ok, problem = engine.verify_conditions(
        ["insomnia"], "new case", engine.cases_of(engine.root)
    )
    assert ok is False and problem.reason == "true_of_stored"

    # the conjunction is not, so it can.
    ok, _ = engine.verify_conditions(
        ["insomnia", "panic attacks"], "new case", engine.cases_of(engine.root)
    )
    assert ok is True


# --- the headline fix ----------------------------------------------------

def test_two_clinicians_adding_to_different_branches_both_land(db, oracle):
    """What the pickled blob could not do.

    Rohit and Priya each load the tree, each add a rule to a different branch,
    and both rules are there. Under the old design the second save rewrote the
    whole tree and erased the first.
    """
    with db.connect() as setup:
        db.insert_vertex(setup, "sangath", None, "root", ["chronic low mood"],
                         "moderate depression", "case A", "rohit@x.com", "a.docx")
        setup.commit()

    # Two separate connections, as two separate requests would be.
    with db.connect() as rohit, db.connect() as priya:
        db.insert_vertex(rohit, "sangath", 0, "right", ["panic attacks"],
                         "withdrawal reaction", "case B", "rohit@x.com", "b.docx")
        rohit.commit()

        db.insert_vertex(priya, "sangath", 0, "left", ["acute grief"],
                         "bereavement", "case C", "priya@x.com", "c.docx")
        priya.commit()

    with db.connect() as conn:
        engine = db.load_engine(conn, "sangath", "rohit@x.com")

    assert engine.root.right.vertex.rule.conclusions == "withdrawal reaction"
    assert engine.root.left.vertex.rule.conclusions == "bereavement"
    assert {n.number for n in engine.walk()} == {0, 1, 2}


def test_two_clinicians_racing_for_the_same_slot_is_reported(db, oracle):
    """A real collision is an error, not a silent loss."""
    with db.connect() as setup:
        db.insert_vertex(setup, "sangath", None, "root", ["chronic low mood"],
                         "moderate depression", "case A", "rohit@x.com", "a.docx")
        setup.commit()

    with db.connect() as rohit:
        db.insert_vertex(rohit, "sangath", 0, "right", ["panic attacks"],
                         "withdrawal reaction", "case B", "rohit@x.com", "b.docx")
        rohit.commit()

    with db.connect() as priya:
        with pytest.raises(db.SlotTaken) as clash:
            db.insert_vertex(priya, "sangath", 0, "right", ["insomnia"],
                             "something else", "case C", "priya@x.com", "c.docx")
        assert "Someone else" in str(clash.value)

    with db.connect() as conn:
        engine = db.load_engine(conn, "sangath", "rohit@x.com")
    # Rohit's rule is untouched.
    assert engine.root.right.vertex.rule.conclusions == "withdrawal reaction"


def test_one_root_per_organisation(db, oracle):
    with db.connect() as conn:
        db.insert_vertex(conn, "sangath", None, "root", ["a"], "A", "x",
                         "rohit@x.com", "a.docx")
        conn.commit()
    with db.connect() as conn:
        with pytest.raises(db.SlotTaken):
            db.insert_vertex(conn, "sangath", None, "root", ["b"], "B", "y",
                             "priya@x.com", "b.docx")


# --- numbering (the paper's `s`) -----------------------------------------

def test_numbers_start_at_zero_and_count_up(db, conn, oracle):
    a = seed(db, conn, oracle)
    b = db.insert_vertex(conn, "sangath", 0, "right", ["x"], "B", "case",
                         "rohit@x.com", "b.docx")
    conn.commit()
    assert (a["number"], b["number"]) == (0, 1)


def test_a_number_is_never_reused_after_an_undo(db, conn, oracle):
    seed(db, conn, oracle)
    db.insert_vertex(conn, "sangath", 0, "right", ["x"], "B", "case",
                     "rohit@x.com", "b.docx")
    conn.commit()

    ok, message = db.undo_last(conn, "sangath", "rohit@x.com")
    conn.commit()
    assert ok and "#1" in message

    c = db.insert_vertex(conn, "sangath", 0, "right", ["y"], "C", "case",
                         "rohit@x.com", "c.docx")
    conn.commit()
    assert c["number"] == 2, "an undone vertex's number must not come back"


def test_undo_refuses_to_orphan_children(db, conn, oracle):
    seed(db, conn, oracle)
    db.insert_vertex(conn, "sangath", 0, "right", ["x"], "B", "case",
                     "rohit@x.com", "b.docx")
    db.insert_vertex(conn, "sangath", 1, "right", ["y"], "C", "case",
                     "rohit@x.com", "c.docx")
    conn.commit()

    # The most recent is #2, a leaf, so that one goes.
    ok, _ = db.undo_last(conn, "sangath", "rohit@x.com")
    assert ok
    conn.commit()

    engine = db.load_engine(conn, "sangath", "rohit@x.com")
    assert engine.root.right.number == 1
    assert engine.root.right.right is None


def test_undo_on_an_empty_tree_says_so(db, conn, oracle):
    ok, message = db.undo_last(conn, "sangath", "rohit@x.com")
    assert ok is False and "No rules" in message


# --- events --------------------------------------------------------------

def test_events_name_the_vertex_and_the_person(db, conn, oracle):
    seed(db, conn, oracle)
    db.log_events(conn, "sangath", [{
        "action": "MERGE_AGREEMENT", "source_file": "x.docx", "true_vertex": 0,
        "eval_vertex": 0, "revision": False, "condition_type": "N/A",
        "actor": "priya@x.com", "detail": None,
    }])
    conn.commit()

    rows = db.recent_events(conn, "sangath")
    assert rows[0]["actor"] == "priya@x.com"
    assert rows[0]["true_vertex"] == 0

    # The three questions the old CSV could not answer, as one query each.
    with conn.cursor() as cur:
        cur.execute(
            "select count(*) as n from events where org_id=%s and true_vertex=%s",
            ("sangath", 0),
        )
        assert cur.fetchone()["n"] == 1


def test_the_engines_own_log_calls_become_rows(db, conn, oracle):
    """add_node_to_tree calls _log_event; the subclass turns that into a row."""
    engine = db.load_engine(conn, "sangath", "priya@x.com")
    node = engine.new_node(["a"], "A", "case")
    engine.attach(node, None, None, "a.docx", "MANUAL")

    assert engine.pending_events[0]["action"] == "ADD_RULE"
    assert engine.pending_events[0]["actor"] == "priya@x.com"

    db.log_events(conn, "sangath", engine.pending_events)
    conn.commit()
    assert db.recent_events(conn, "sangath")[0]["action"] == "ADD_RULE"


# --- what the screen gets ------------------------------------------------

def test_tree_payload_is_keyed_by_vertex_number(db, conn, oracle):
    seed(db, conn, oracle)
    db.insert_vertex(conn, "sangath", 0, "right", ["panic attacks"],
                     "withdrawal reaction", "case B", "priya@x.com", "b.docx")
    conn.commit()

    payload = db.tree_payload(db.load_engine(conn, "sangath", "rohit@x.com"))

    assert set(payload) == {"0", "1"}
    assert payload["0"]["right"] == "1"
    assert payload["0"]["left"] is None
    assert payload["1"]["number"] == 1
    assert payload["1"]["created_by"] == "priya@x.com"
    assert payload["0"]["cases"] == ["Insomnia. On medication. Low mood for 2 years."]
    assert payload["0"]["short_if"] == "Chronic low mood"


def test_organisations_cannot_see_each_other(db, conn, oracle):
    seed(db, conn, oracle)
    with conn.cursor() as cur:
        cur.execute("insert into orgs (id, name) values ('other', 'Other')")
    db.insert_vertex(conn, "other", None, "root", ["different"], "Different",
                     "their case", "someone@else.com", "z.docx")
    conn.commit()

    sangath = db.load_engine(conn, "sangath", "rohit@x.com")
    other = db.load_engine(conn, "other", "someone@else.com")

    assert sangath.root.vertex.rule.conclusions == "moderate depression"
    assert other.root.vertex.rule.conclusions == "Different"
    # Numbering is per organisation, so both start at 0.
    assert sangath.root.number == 0 and other.root.number == 0
