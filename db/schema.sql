-- RDR knowledge base — schema
--
-- Two things this replaces, and why:
--
-- 1. The tree was a pickled Python object base64'd into one Firestore field.
--    Adding a rule meant rewriting the whole blob, so two clinicians in the
--    same organisation could not both add one — whoever saved second erased
--    the other. Here a rule is one row, so two people adding to different
--    branches never touch each other. The unique constraint on
--    (org_id, parent_id, side) makes a genuine collision an error instead of
--    a silent loss.
--
-- 2. The event log was the whole CSV as one string, and it recorded id(n) —
--    a memory address — so rows could not be joined across sessions. Here the
--    paper's vertex number is a real column, and every event names an actor.

create table if not exists orgs (
  id                  text primary key,            -- slug: 'sangath'
  name                text        not null,        -- display: 'Sangath'
  -- The paper's `s`: the number of the last vertex added. Kept here rather
  -- than derived from max(number) so that a number is never reused after an
  -- undo, which is what makes log rows comparable across sessions.
  last_vertex_number  integer     not null default -1,
  created_at          timestamptz not null default now()
);

create table if not exists members (
  org_id    text        not null references orgs(id) on delete cascade,
  email     text        not null,                  -- always stored lowercased
  role      text        not null default 'clinician'
                        check (role in ('owner', 'clinician')),
  added_by  text,
  added_at  timestamptz not null default now(),
  primary key (org_id, email)
);

-- "which organisations is this person in?" — asked on every sign-in.
create index if not exists members_email_idx on members (email);

create table if not exists vertices (
  id          bigserial   primary key,
  org_id      text        not null references orgs(id) on delete cascade,
  -- The paper's V index. Unique within an organisation, never reused.
  number      integer     not null,
  parent_id   bigint      references vertices(id) on delete cascade,
  side        text        not null check (side in ('root', 'left', 'right')),
  -- C = c1 AND c2 AND ... AND ck, as a JSON array of strings. Algorithm 3
  -- evaluates them one at a time; this is only how they are stored.
  conditions  jsonb       not null,
  conclusion  text        not null,
  -- The merged group profile: what a clinician reads on the node.
  summary     text        not null default '',
  created_by  text        not null,
  created_at  timestamptz not null default now(),

  unique (org_id, number),
  -- One rule per slot. Two clinicians racing for the same branch: the first
  -- wins, the second is told, and neither is silently overwritten. NULLS NOT
  -- DISTINCT also makes this enforce one root per organisation.
  unique nulls not distinct (org_id, parent_id, side)
);

create index if not exists vertices_org_idx on vertices (org_id);
create index if not exists vertices_parent_idx on vertices (parent_id);

-- X: the cases stored at a vertex, each one whole.
--
-- The merged `summary` above is a generalisation — it is what turns "insomnia"
-- and "hypersomnia" into "sleep disturbances". Algorithms 5 and 7 test a
-- condition against every stored case, so those cases have to survive
-- separately or the check has nothing real to run against.
create table if not exists vertex_cases (
  id           bigserial   primary key,
  vertex_id    bigint      not null references vertices(id) on delete cascade,
  summary      text        not null,
  source_file  text,
  added_by     text        not null,
  added_at     timestamptz not null default now()
);

create index if not exists vertex_cases_vertex_idx on vertex_cases (vertex_id);

create table if not exists events (
  id              bigserial   primary key,
  org_id          text        not null references orgs(id) on delete cascade,
  at              timestamptz not null default now(),
  action          text        not null,   -- ADD_RULE | MERGE_AGREEMENT | UNDO
                                          -- | FLUSH_TREE | LLM_ERROR
  source_file     text,
  -- The paper's vertex numbers, so these rows join to `vertices` and to each
  -- other. "How many times did this node fire?" is now one query.
  true_vertex     integer,
  eval_vertex     integer,
  revision        boolean,
  condition_type  text,
  -- Who did it. Impossible to record before there was a signed-in user.
  actor           text,
  detail          text
);

create index if not exists events_org_at_idx on events (org_id, at desc);
create index if not exists events_true_vertex_idx on events (org_id, true_vertex);
