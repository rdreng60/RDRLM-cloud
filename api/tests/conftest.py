"""Shared fixtures.

Two levels of stand-in are used, deliberately:

  * `oracle` replaces the two LLM entry points *inside the engine*, so the
    algorithms are tested on their own logic with deterministic answers;
  * `fake_model` replaces `llm_api.model`, so llm_api's own error handling and
    reply parsing are tested for real.

Nothing here talks to the network, and no test writes into the real storage/.
"""

import os
import pathlib
import sys
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
API = os.path.dirname(HERE)          # .../RDRM-cloud/api
ROOT = os.path.dirname(API)          # .../RDRM-cloud
for p in (ROOT, API):
    if p not in sys.path:
        sys.path.insert(0, p)

# llm_api raises at import time without a key. Nothing is ever sent to it.
os.environ.setdefault("API_KEY", "test-key-not-used")


class Oracle:
    """A deterministic model.

    `facts[case]` is the set of conditions that are TRUE of that case. Every
    check is recorded in call order, so a test can assert not just the answer
    but how many questions were asked and which ones.
    """

    def __init__(self, facts=None, differences=None):
        self.facts = {k: set(v) for k, v in (facts or {}).items()}
        self.differences = list(differences) if differences is not None else []
        self.checks = []        # (case, condition) in the order they were asked
        self.diff_calls = []    # (new_summary, reference_text)
        self.merges = []
        self.fail_check_on = set()   # conditions whose check raises
        self.fail_diff = False

    # --- the two entry points the engine uses ---
    def check(self, case, condition):
        self.checks.append((case, condition))
        if condition in self.fail_check_on:
            from llm_api import LLMError
            raise LLMError("condition check", "simulated outage")
        return condition in self.facts.get(case, set())

    def diff(self, new_summary, reference_text):
        self.diff_calls.append((new_summary, reference_text))
        if self.fail_diff:
            from llm_api import LLMError
            raise LLMError("difference extraction", "simulated outage")
        return list(self.differences)

    def merge(self, old, new):
        self.merges.append((old, new))
        return f"{old} + {new}" if old else new

    # --- convenience for assertions ---
    def conditions_asked(self):
        return [c for _, c in self.checks]

    def asked(self, case, condition):
        return (case, condition) in self.checks

    def reset_calls(self):
        self.checks.clear()
        self.diff_calls.clear()
        self.merges.clear()


@pytest.fixture
def isolated_storage(tmp_path, monkeypatch):
    """Point the engine's tree file and event log at a temp directory."""
    import rdr_engine

    storage = tmp_path / "storage"
    storage.mkdir()
    monkeypatch.setattr(rdr_engine, "STORAGE_DIR", str(storage))
    monkeypatch.setattr(rdr_engine, "LOG_FILE", str(storage / "rdr_event_log.csv"))
    monkeypatch.setattr(
        rdr_engine, "TREE_STORAGE_FILE", str(storage / "rdr_tree_summary.pkl")
    )
    return storage


@pytest.fixture
def oracle(monkeypatch, isolated_storage):
    """Install a deterministic Oracle in place of the engine's LLM calls."""
    import rdr_engine

    o = Oracle()
    monkeypatch.setattr(rdr_engine, "llm_check_condition", o.check)
    monkeypatch.setattr(rdr_engine, "llm_get_differentiating_conditions", o.diff)
    monkeypatch.setattr(rdr_engine, "llm_merge_summaries", o.merge)
    return o


@pytest.fixture
def engine(oracle):
    import rdr_engine
    return rdr_engine.RDREngine()


class FakeResponse:
    def __init__(self, text):
        self._text = text

    @property
    def text(self):
        if isinstance(self._text, Exception):
            raise self._text
        return self._text


class FakeModel:
    """Stands in for `llm_api.model`. Replies come from a queue or a callable."""

    def __init__(self, replies=None, raises=None):
        self.replies = list(replies or [])
        self.raises = raises
        self.calls = []

    def generate_content(self, prompt, generation_config=None):
        self.calls.append((prompt, generation_config))
        if self.raises is not None:
            raise self.raises
        if not self.replies:
            raise AssertionError("FakeModel ran out of scripted replies")
        return FakeResponse(self.replies.pop(0))


@pytest.fixture
def fake_model(monkeypatch):
    import llm_api

    def install(replies=None, raises=None):
        m = FakeModel(replies=replies, raises=raises)
        monkeypatch.setattr(llm_api, "model", m)
        return m

    return install


# --- the Postgres layer ---------------------------------------------------
#
# These need a real database, because what is being tested is a unique
# constraint and a locked row — neither of which a fake would exercise:
#
#     createdb rdr_test
#     TEST_DATABASE_URL=postgresql://localhost/rdr_test python -m pytest api/tests
#
# Without TEST_DATABASE_URL the database tests skip and the rest still run.

TEST_DB = os.environ.get("TEST_DATABASE_URL", "")
SCHEMA = pathlib.Path(__file__).resolve().parents[2] / "db" / "schema.sql"


@pytest.fixture
def db(monkeypatch):
    """A clean database, with one empty organisation in it."""
    if not TEST_DB:
        pytest.skip("TEST_DATABASE_URL not set")

    import psycopg
    from psycopg.rows import dict_row
    import store

    monkeypatch.setenv("DATABASE_URL", TEST_DB)

    with psycopg.connect(TEST_DB, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA.read_text())
            cur.execute(
                "truncate events, vertex_cases, vertices, members, orgs "
                "restart identity cascade"
            )
            cur.execute("insert into orgs (id, name) values ('sangath', 'Sangath')")
        conn.commit()

    return store


@pytest.fixture
def conn(db):
    with db.connect() as c:
        yield c
