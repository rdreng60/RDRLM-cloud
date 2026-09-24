#!/usr/bin/env python3
"""Organisations and the allow list, from the command line.

    export DATABASE_URL='postgresql://...neon.tech/rdr?sslmode=require'

    python scripts/orgadmin.py init
    python scripts/orgadmin.py add-org sangath --name Sangath --owner you@gmail.com
    python scripts/orgadmin.py add-member sangath priya@example.com
    python scripts/orgadmin.py add-member sangath amit@example.com --role owner
    python scripts/orgadmin.py remove-member sangath priya@example.com
    python scripts/orgadmin.py list
    python scripts/orgadmin.py list sangath

Nobody can sign in to an organisation they are not a member of, so this file is
the allow list. An owner can do the same things from the Members page in the
app; this is here for the first organisation, when there is no owner yet.
"""

import argparse
import os
import pathlib
import sys

import psycopg
from psycopg.rows import dict_row

HERE = pathlib.Path(__file__).resolve().parent
SCHEMA = HERE.parent / "db" / "schema.sql"


def connect():
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set. Copy it from the Neon console.")
    return psycopg.connect(url, row_factory=dict_row)


def norm(email: str) -> str:
    """Emails are compared lowercased, everywhere, or membership silently fails."""
    return email.strip().lower()


def cmd_init(args, conn):
    with conn.cursor() as cur:
        cur.execute(SCHEMA.read_text())
    conn.commit()
    print(f"schema applied from {SCHEMA}")


def cmd_add_org(args, conn):
    org_id = args.org.strip().lower()
    name = args.name or args.org
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into orgs (id, name) values (%s, %s)
            on conflict (id) do update set name = excluded.name
            """,
            (org_id, name),
        )
        if args.owner:
            cur.execute(
                """
                insert into members (org_id, email, role, added_by)
                values (%s, %s, 'owner', 'cli')
                on conflict (org_id, email) do update set role = 'owner'
                """,
                (org_id, norm(args.owner)),
            )
    conn.commit()
    print(f"organisation '{name}' ready (id: {org_id})")
    if args.owner:
        print(f"  owner: {norm(args.owner)}")


def cmd_add_member(args, conn):
    org_id = args.org.strip().lower()
    email = norm(args.email)
    with conn.cursor() as cur:
        cur.execute("select 1 from orgs where id = %s", (org_id,))
        if cur.fetchone() is None:
            sys.exit(f"no organisation '{org_id}'. Run add-org first.")
        cur.execute(
            """
            insert into members (org_id, email, role, added_by)
            values (%s, %s, %s, 'cli')
            on conflict (org_id, email) do update set role = excluded.role
            """,
            (org_id, email, args.role),
        )
    conn.commit()
    print(f"{email} is now a {args.role} of {org_id}")


def cmd_remove_member(args, conn):
    org_id = args.org.strip().lower()
    email = norm(args.email)
    with conn.cursor() as cur:
        cur.execute(
            "delete from members where org_id = %s and email = %s",
            (org_id, email),
        )
        gone = cur.rowcount
    conn.commit()
    print(f"removed {email} from {org_id}" if gone else f"{email} was not in {org_id}")


def cmd_list(args, conn):
    with conn.cursor() as cur:
        if args.org:
            org_id = args.org.strip().lower()
            cur.execute("select * from orgs where id = %s", (org_id,))
            org = cur.fetchone()
            if not org:
                sys.exit(f"no organisation '{org_id}'")
            cur.execute(
                "select email, role, added_at from members where org_id = %s"
                " order by role, email",
                (org_id,),
            )
            print(f"{org['name']}  ({org['id']})")
            print(f"  last vertex number: {org['last_vertex_number']}")
            for m in cur.fetchall():
                print(f"  {m['role']:<10} {m['email']}")
            return

        cur.execute(
            """
            select o.id, o.name,
                   (select count(*) from members m where m.org_id = o.id) as people,
                   (select count(*) from vertices v where v.org_id = o.id) as rules
              from orgs o order by o.name
            """
        )
        rows = cur.fetchall()
        if not rows:
            print("no organisations yet — try add-org")
            return
        print(f"{'id':<20} {'name':<24} {'people':>6} {'rules':>6}")
        for r in rows:
            print(f"{r['id']:<20} {r['name']:<24} {r['people']:>6} {r['rules']:>6}")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create the tables").set_defaults(fn=cmd_init)

    p = sub.add_parser("add-org", help="create an organisation")
    p.add_argument("org")
    p.add_argument("--name")
    p.add_argument("--owner", help="email of the first owner")
    p.set_defaults(fn=cmd_add_org)

    p = sub.add_parser("add-member", help="put an email on the allow list")
    p.add_argument("org")
    p.add_argument("email")
    p.add_argument("--role", choices=["clinician", "owner"], default="clinician")
    p.set_defaults(fn=cmd_add_member)

    p = sub.add_parser("remove-member", help="take an email off the allow list")
    p.add_argument("org")
    p.add_argument("email")
    p.set_defaults(fn=cmd_remove_member)

    p = sub.add_parser("list", help="show organisations, or one organisation's people")
    p.add_argument("org", nargs="?")
    p.set_defaults(fn=cmd_list)

    args = parser.parse_args()
    with connect() as conn:
        args.fn(args, conn)


if __name__ == "__main__":
    main()
