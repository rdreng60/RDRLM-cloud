"""The HTTP surface the Next.js server talks to.

Runs the real FastAPI app against the real database, with only the model calls
stubbed. What is being checked here is the contract: the shared secret, the
actor, and — most of all — that a refused rule comes back as a 200 the
clinician can act on rather than an error that kills the page.
"""

import os
import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")

KEY = "test-engine-key"

OLD = "Insomnia. On medication. Low mood for 2 years."
NEW = "Insomnia. Stopped medication 3 days ago. Panic attacks."
FACTS = {
    OLD: {"chronic low mood", "insomnia"},
    NEW: {"chronic low mood", "insomnia", "panic attacks", "stopped medication"},
}


@pytest.fixture
def client(db, monkeypatch, oracle):
    """The app, wired to the scratch database, with a deterministic model."""
    from fastapi.testclient import TestClient
    import rdr_engine, main, llm_api

    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    monkeypatch.setattr(main, "API_KEY", KEY)

    oracle.facts = dict(FACTS)
    oracle.differences = ["insomnia", "panic attacks", "stopped medication"]
    monkeypatch.setattr(rdr_engine, "llm_check_condition", oracle.check)
    monkeypatch.setattr(rdr_engine, "llm_get_differentiating_conditions", oracle.diff)
    monkeypatch.setattr(rdr_engine, "llm_merge_summaries", oracle.merge)
    monkeypatch.setattr(main, "llm_merge_summaries", oracle.merge)
    monkeypatch.setattr(main, "llm_generate_summary", lambda t: f"summary of {t[:20]}")

    c = TestClient(TestClient(main.app).app)
    c.headers.update({"x-api-key": KEY, "x-actor": "rohit@x.com"})
    return c


def seed_root(db):
    with db.connect() as conn:
        db.insert_vertex(conn, "sangath", None, "root", ["chronic low mood"],
                         "moderate depression", OLD, "rohit@x.com", "old1.docx")
        conn.commit()


# --- the gate on the door -------------------------------------------------

def test_a_wrong_key_is_refused(client):
    r = client.get("/orgs/sangath/tree", headers={"x-api-key": "nope"})
    assert r.status_code == 401


def test_a_missing_actor_is_refused(client):
    r = client.get("/orgs/sangath/tree", headers={"x-actor": ""})
    assert r.status_code == 400


def test_health_needs_nothing(client):
    assert client.get("/health").json() == {"ok": True}


# --- the walk -------------------------------------------------------------

def test_an_empty_organisation_concludes_nothing(client):
    r = client.post("/orgs/sangath/interpret", json={"summary": NEW})
    assert r.status_code == 200
    body = r.json()
    assert body["tree"] == {} and body["root"] is None
    assert body["verdict_node"] is None and body["conclusion"] is None


def test_the_walk_returns_per_condition_detail(client, db):
    seed_root(db)
    body = client.post("/orgs/sangath/interpret",
                       json={"summary": NEW, "source_file": "new.docx"}).json()

    assert body["conclusion"] == "moderate depression"
    assert body["verdict_node"] == 0 and body["end_node"] == 0
    assert body["trace"] == [["0", True]]
    # Algorithm 3, visible: one entry per conjunct.
    assert body["detail"][0]["conditions"] == [
        {"condition": "chronic low mood", "result": True}
    ]


# --- Algorithm 5 ----------------------------------------------------------

def test_candidates_are_verified_before_they_are_offered(client, db):
    seed_root(db)
    body = client.post("/orgs/sangath/differences",
                       json={"summary": NEW, "verdict_node": 0}).json()

    # insomnia is true of the stored case, so it never reaches the clinician.
    assert body["kept"] == ["panic attacks", "stopped medication"]
    assert body["rejected"][0]["condition"] == "insomnia"
    assert body["rejected"][0]["reason"] == "true_of_stored"
    assert body["stored_cases"] == [OLD]


# --- Algorithms 6 + 7 -----------------------------------------------------

def test_a_refused_rule_is_a_200_the_clinician_can_act_on(client, db):
    """Not a 4xx, not a crash: the paper's repeat-until needs a way back."""
    seed_root(db)
    r = client.post("/orgs/sangath/rules", json={
        "summary": NEW, "source_file": "new.docx", "end_node": 0,
        "verdict_node": 0, "conditions": ["insomnia"], "manual": [],
        "conclusion": "withdrawal reaction",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "already filed here" in body["problem"]

    # Nothing was written.
    assert client.get("/orgs/sangath/tree").json()["tree"].keys() == {"0"}


def test_a_verified_rule_is_saved_and_numbered(client, db):
    seed_root(db)
    body = client.post("/orgs/sangath/rules", json={
        "summary": NEW, "source_file": "new.docx", "end_node": 0,
        "verdict_node": 0, "conditions": ["insomnia", "panic attacks"],
        "manual": [], "conclusion": "withdrawal reaction",
    }).json()

    assert body["ok"] is True
    assert body["number"] == 1 and body["side"] == "right"

    tree = client.get("/orgs/sangath/tree").json()["tree"]
    assert tree["0"]["right"] == "1"
    assert tree["1"]["conclusion"] == "withdrawal reaction"
    assert tree["1"]["created_by"] == "rohit@x.com"


def test_an_empty_rule_is_refused_without_touching_the_model(client, db):
    seed_root(db)
    body = client.post("/orgs/sangath/rules", json={
        "summary": NEW, "source_file": "x", "end_node": 0, "verdict_node": 0,
        "conditions": [], "manual": [], "conclusion": "",
    }).json()
    assert body["ok"] is False


def test_the_first_rule_becomes_the_root(client):
    body = client.post("/orgs/sangath/rules", json={
        "summary": NEW, "source_file": "first.docx", "end_node": None,
        "verdict_node": None, "conditions": ["chronic low mood"],
        "manual": ["chronic low mood"], "conclusion": "moderate depression",
    }).json()
    assert body["ok"] is True and body["side"] == "root" and body["number"] == 0


# --- agreement ------------------------------------------------------------

def test_agreeing_adds_the_case_to_the_node(client, db):
    seed_root(db)
    assert client.post("/orgs/sangath/agree", json={
        "summary": NEW, "source_file": "new.docx", "verdict_node": 0,
    }).json() == {"ok": True}

    node = client.get("/orgs/sangath/tree").json()["tree"]["0"]
    assert node["cases"] == [OLD, NEW]
    assert NEW in node["summary"]      # the stub merge concatenates


# --- failures are not answers --------------------------------------------

def test_a_model_outage_during_the_walk_is_a_502_not_a_false(client, db, oracle):
    seed_root(db)
    oracle.fail_check_on = {"chronic low mood"}

    r = client.post("/orgs/sangath/interpret",
                    json={"summary": NEW, "source_file": "new.docx"})
    assert r.status_code == 502

    # and it is on the record
    actions = [e["action"] for e in client.get("/orgs/sangath/events").json()["events"]]
    assert "LLM_ERROR" in actions


def test_undo_over_http(client, db):
    seed_root(db)
    client.post("/orgs/sangath/rules", json={
        "summary": NEW, "source_file": "new.docx", "end_node": 0,
        "verdict_node": 0, "conditions": ["panic attacks"], "manual": [],
        "conclusion": "withdrawal reaction",
    })
    assert client.post("/orgs/sangath/undo").json()["ok"] is True
    assert set(client.get("/orgs/sangath/tree").json()["tree"]) == {"0"}


def test_the_event_log_names_who_did_what(client, db):
    seed_root(db)
    client.post("/orgs/sangath/rules",
                headers={"x-actor": "priya@x.com"},
                json={"summary": NEW, "source_file": "new.docx", "end_node": 0,
                      "verdict_node": 0, "conditions": ["panic attacks"],
                      "manual": [], "conclusion": "withdrawal reaction"})

    rows = client.get("/orgs/sangath/events").json()["events"]
    added = [e for e in rows if e["action"] == "ADD_RULE"][0]
    assert added["actor"] == "priya@x.com"
    assert added["true_vertex"] == 0
