import { sql, normalizeEmail } from "./db";

export type Role = "owner" | "clinician";

export type Membership = {
  orgId: string;
  name: string;
  role: Role;
  rules: number;
  people: number;
};

/**
 * Anyone listed here can create organisations and manage any allow list.
 *
 * This is the bootstrap: the very first organisation has no owner yet, so
 * somebody has to be able to make one. Set it in the environment, comma
 * separated:  SUPER_ADMINS="you@gmail.com,colleague@gmail.com"
 */
export function isSuperAdmin(email: string | null | undefined): boolean {
  const me = normalizeEmail(email);
  if (!me) return false;
  return (process.env.SUPER_ADMINS ?? "")
    .split(",")
    .map((e) => e.trim().toLowerCase())
    .filter(Boolean)
    .includes(me);
}

/** Every organisation this email belongs to. The allow list, asked from the other end. */
export async function orgsFor(email: string): Promise<Membership[]> {
  const me = normalizeEmail(email);
  if (!me) return [];
  const rows = await sql`
    select o.id, o.name, m.role,
           (select count(*)::int from vertices v where v.org_id = o.id) as rules,
           (select count(*)::int from members p where p.org_id = o.id) as people
      from members m
      join orgs o on o.id = m.org_id
     where m.email = ${me}
     order by o.name
  `;
  return rows.map((r) => ({
    orgId: r.id as string,
    name: r.name as string,
    role: r.role as Role,
    rules: r.rules as number,
    people: r.people as number,
  }));
}

/**
 * This person's standing in this organisation, or null if they are not in it.
 *
 * Every page and every action calls this before doing anything. It runs on the
 * server, and the browser never holds a database credential, so it is a real
 * gate rather than a hidden menu item.
 */
export async function membershipIn(
  email: string,
  orgId: string
): Promise<Membership | null> {
  const me = normalizeEmail(email);
  if (!me || !orgId) return null;

  if (isSuperAdmin(me)) {
    const found = await sql`select id, name from orgs where id = ${orgId}`;
    if (found.length) {
      return {
        orgId: found[0].id as string,
        name: found[0].name as string,
        role: "owner",
        rules: 0,
        people: 0,
      };
    }
    return null;
  }

  const rows = await sql`
    select o.id, o.name, m.role
      from members m join orgs o on o.id = m.org_id
     where m.email = ${me} and m.org_id = ${orgId}
  `;
  if (!rows.length) return null;
  return {
    orgId: rows[0].id as string,
    name: rows[0].name as string,
    role: rows[0].role as Role,
    rules: 0,
    people: 0,
  };
}

export type Member = { email: string; role: Role; addedBy: string | null; addedAt: string };

export async function membersOf(orgId: string): Promise<Member[]> {
  const rows = await sql`
    select email, role, added_by, added_at
      from members where org_id = ${orgId}
     order by role, email
  `;
  return rows.map((r) => ({
    email: r.email as string,
    role: r.role as Role,
    addedBy: r.added_by as string | null,
    addedAt: new Date(r.added_at as string).toISOString(),
  }));
}

export async function addMember(
  orgId: string,
  email: string,
  role: Role,
  addedBy: string
) {
  await sql`
    insert into members (org_id, email, role, added_by)
    values (${orgId}, ${normalizeEmail(email)}, ${role}, ${normalizeEmail(addedBy)})
    on conflict (org_id, email) do update set role = excluded.role
  `;
}

export async function removeMember(orgId: string, email: string) {
  await sql`
    delete from members where org_id = ${orgId} and email = ${normalizeEmail(email)}
  `;
}

export async function allOrgs(): Promise<Membership[]> {
  const rows = await sql`
    select o.id, o.name,
           (select count(*)::int from vertices v where v.org_id = o.id) as rules,
           (select count(*)::int from members m where m.org_id = o.id) as people
      from orgs o order by o.name
  `;
  return rows.map((r) => ({
    orgId: r.id as string,
    name: r.name as string,
    role: "owner" as Role,
    rules: r.rules as number,
    people: r.people as number,
  }));
}

/** Create an organisation and give it its first owner. */
export async function createOrg(orgId: string, name: string, owner: string) {
  const id = orgId.trim().toLowerCase().replace(/[^a-z0-9-]+/g, "-");
  if (!id) throw new Error("An organisation needs an id.");
  await sql`
    insert into orgs (id, name) values (${id}, ${name.trim() || id})
    on conflict (id) do update set name = excluded.name
  `;
  await sql`
    insert into members (org_id, email, role, added_by)
    values (${id}, ${normalizeEmail(owner)}, 'owner', ${normalizeEmail(owner)})
    on conflict (org_id, email) do update set role = 'owner'
  `;
  return id;
}
