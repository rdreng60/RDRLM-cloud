/**
 * Create the tables, and optionally the first organisation.
 *
 *   npm run db:setup
 *   npm run db:setup -- --org sangath --name Sangath --owner you@gmail.com
 *
 * Uses the Neon HTTP driver, so it works from anywhere the app itself works —
 * including networks that block outbound Postgres on 5432. `scripts/orgadmin.py`
 * does the same over a normal connection if you prefer Python.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { neon } from "@neondatabase/serverless";

const here = dirname(fileURLToPath(import.meta.url));
const schemaPath = resolve(here, "../../db/schema.sql");

const url = process.env.DATABASE_URL;
if (!url) {
  console.error("DATABASE_URL is not set. Put it in web/.env.local first.");
  process.exit(1);
}

const args = process.argv.slice(2);
const flag = (name) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : undefined;
};

const sql = neon(url);

// Split on semicolons that end a statement. The schema is plain DDL with no
// function bodies, so this is safe here; anything fancier belongs in a real
// migration tool.
const statements = readFileSync(schemaPath, "utf8")
  .split(/;\s*$/m)
  .map((s) => s.trim())
  .filter((s) => s && !s.split("\n").every((l) => l.trim().startsWith("--")));

for (const statement of statements) {
  await sql.query(statement);
}
console.log(`applied ${statements.length} statements from db/schema.sql`);

const org = flag("org");
if (org) {
  const id = org.trim().toLowerCase();
  const name = flag("name") ?? org;
  const owner = (flag("owner") ?? "").trim().toLowerCase();
  if (!owner) {
    console.error("--org also needs --owner you@example.com");
    process.exit(1);
  }
  await sql.query(
    `insert into orgs (id, name) values ($1, $2)
       on conflict (id) do update set name = excluded.name`,
    [id, name]
  );
  await sql.query(
    `insert into members (org_id, email, role, added_by)
     values ($1, $2, 'owner', 'setup')
       on conflict (org_id, email) do update set role = 'owner'`,
    [id, owner]
  );
  console.log(`organisation "${name}" (${id}) ready, owned by ${owner}`);
}

const rows = await sql.query(
  `select o.id, o.name,
          (select count(*)::int from members m where m.org_id = o.id) as people,
          (select count(*)::int from vertices v where v.org_id = o.id) as rules
     from orgs o order by o.name`
);
console.table(rows);
