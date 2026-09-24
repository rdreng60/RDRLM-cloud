# RDRM-cloud

The RDR knowledge base as a deployed app: **Next.js on Vercel + a Python engine
+ Neon Postgres**, with Google sign-in and organisations.

A clinician opens a link, signs in with Google, and sees their organisation's
tree. Everyone in Sangath reads and adds to the same one.

```
RDRM-cloud/
├── web/        Next.js — sign-in, orgs, the tree UI        → Vercel
├── api/        FastAPI — Algorithms 1-7, unchanged         → Render / Cloud Run
├── db/         schema.sql
├── prompts/    unchanged
└── scripts/    orgadmin.py — orgs and the allow list
```

## Why it is split in two

`api/rdr_engine.py` is **byte-identical** to the Streamlit build. That is the
point: Algorithms 1-7 and their tests have one home, and moving the app to the
web did not mean re-deriving the paper in TypeScript. The Next.js server never
decides whether a condition holds; it asks the engine.

Only the Next.js server calls the engine — never a browser. It authenticates
with a shared secret and passes the signed-in clinician's email as the actor,
which is what lands in the event log.

---

## Setting it up

### 1. Neon — done

Database `neondb` on project `dawn-hat-97805122`. The schema is applied and one
organisation exists: **Sangath**, owned by `rohit.baluni@leptonsoftware.com`.
`web/.env.local` already has the connection string.

To rebuild it, or to set up a second environment:

```bash
cd web
npm run db:setup                                   # tables only
npm run db:setup -- --org sangath --name Sangath --owner you@gmail.com
```

That runs over Neon's HTTP driver, so it works on networks that block outbound
Postgres on port 5432. `python scripts/orgadmin.py init` does the same over an
ordinary connection.

### 2. Google sign-in — the one thing left

`AUTH_SECRET` and `ENGINE_API_KEY` are already generated in `web/.env.local`.
Only the Google client is missing.

1. [console.cloud.google.com](https://console.cloud.google.com) → pick or create
   a project → **APIs & Services → OAuth consent screen**. Choose **External**,
   give it a name and your email, and save. While it is in *Testing*, add every
   clinician's address under **Test users**, or press **Publish app** to lift
   that.
2. **Credentials → Create credentials → OAuth client ID → Web application**.
3. Authorised redirect URIs — add both:
   - `http://localhost:3000/api/auth/callback/google`
   - `https://YOUR-APP.vercel.app/api/auth/callback/google`
4. Paste the client ID and secret into `AUTH_GOOGLE_ID` and
   `AUTH_GOOGLE_SECRET` in `web/.env.local`.

That is the whole of it — `npm run dev`, press **Continue with Google**, and you
land in Sangath.

No domain restriction is set, so any Google account can *sign in*. Signing in is
not permission — see below.

### 3. The engine

Render, Railway or Cloud Run. Root directory `RDRM-cloud`, then:

```
build:  pip install -r api/requirements.txt
start:  uvicorn api.main:app --host 0.0.0.0 --port $PORT
env:    DATABASE_URL, API_KEY (Gemini), ENGINE_API_KEY
```

Not Vercel: a walk down a deep tree makes one model call per condition and will
outrun a serverless timeout.

### 4. The web app

```bash
cd web
cp .env.example .env.local     # fill it in
npm install && npm run dev
```

### 5. Vercel

Point Vercel at this repo with **root directory `web`**. Set the same variables
in *Settings → Environment Variables*:

| variable | value |
|---|---|
| `DATABASE_URL` | the Neon string from `web/.env.local` |
| `AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET` | from step 2 |
| `AUTH_SECRET` | copy from `web/.env.local` |
| `ENGINE_URL` | the engine's public URL, e.g. `https://rdr-engine.onrender.com` |
| `ENGINE_API_KEY` | copy from `web/.env.local`, must match the engine's |
| `SUPER_ADMINS` | your email |

Then add the deployed callback URL to the Google client, and set `ENGINE_URL`
in `web/.env.local` back to `http://127.0.0.1:8000` for local work.

Order matters slightly: deploy the **engine first**, so you know its URL.

---

## Adding an organisation, or an email to the allow list

Three ways, in order of how often you will want each.

**In the app** — the usual way. An owner opens **People** in the sidebar, types
an email, presses Add. That person can sign in immediately.

**The admin page** — `/admin`, for anyone listed in `SUPER_ADMINS`. Creates
organisations and edits any allow list. This is the bootstrap: the first
organisation has no owner yet, so somebody outside the members table has to be
able to make it.

```
SUPER_ADMINS="you@gmail.com,colleague@gmail.com"
```

**The command line** — for the very first setup, or scripting:

```bash
export DATABASE_URL='postgresql://...neon.tech/rdr?sslmode=require'

python scripts/orgadmin.py add-org sangath --name Sangath --owner you@gmail.com
python scripts/orgadmin.py add-member sangath priya@example.com
python scripts/orgadmin.py add-member sangath amit@example.com --role owner
python scripts/orgadmin.py remove-member sangath priya@example.com
python scripts/orgadmin.py list
python scripts/orgadmin.py list sangath
```

An **owner** can manage people; a **clinician** can read and add rules.

---

## How access actually works

Signing in establishes *who you are*. The `members` table decides *what you can
open*, and that check runs on the server in three places — the page, the server
action, and the engine call — before any rule is fetched. A link to `/sangath`
is not a way in, and neither is a hidden button becoming visible.

This holds because it is **one deployed app**: the database credential lives on
the server, and the browser never holds it. Running the app locally with a copy
of the credentials is a different situation, and there the members list is
organisation, not security.

---

## What changed against the Streamlit build

**The tree is rows, not a pickled blob.** This is the substantive change.
Adding a rule used to mean rewriting the whole tree, so two clinicians in one
organisation could not both add one — whoever saved second erased the other.
Now a rule is one `INSERT`:

- two people adding to different branches never touch each other;
- a genuine race for the same slot hits `unique (org_id, parent_id, side)` and
  the second person is told, rather than silently losing their work.

**The event log is rows.** It records the paper's vertex number rather than
`id(n)`, so `select count(*) from events where true_vertex = 3` answers "how
many times did this rule fire" — across sessions, which the CSV could not do.
It also records **who**, which was impossible before there was a signed-in user.

**The UI is the same drawing.** `RdrTree`, `Node` and `VerdictCard` are ported
from the Streamlit component with the same geometry, colours and node anatomy.
What went is the iframe bridge: Agree / Disagree / Save are server actions now.

Unchanged on purpose: the prompts, the algorithms, and evaluation temperature
(still 1.0 — that was left open in `rdr-spec-gaps.md` and is not closed here).

---

## Tests

```bash
# engine only — no database needed
python -m pytest api/tests -q

# including the Postgres layer
createdb rdr_test
TEST_DATABASE_URL=postgresql://localhost/rdr_test python -m pytest api/tests -q
```

87 tests. 59 are the engine's own, carried over unchanged. The rest cover the
database layer and the HTTP contract, including the two that matter most: two
clinicians writing to different branches both land, and a race for the same slot
is reported instead of lost.

The database tests use a real Postgres deliberately — what they check is a
unique constraint and a locked row, and a fake would exercise neither.
