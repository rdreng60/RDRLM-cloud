import { neon } from "@neondatabase/serverless";
import { Pool } from "pg";

/**
 * One query interface, two drivers.
 *
 * In production the database is Neon and the driver is its HTTP one, which is
 * what serverless wants: every Vercel invocation is its own short-lived
 * process, so a connection pool would be a liability rather than a saving.
 *
 * Anywhere else — a local Postgres, a self-hosted one — that HTTP endpoint does
 * not exist, so an ordinary TCP pool is used instead. The call site cannot tell
 * the difference: both are tagged templates returning rows, and both pass
 * values as real query parameters rather than by string interpolation.
 */

type Row = Record<string, unknown>;
export type Sql = (
  strings: TemplateStringsArray,
  ...values: unknown[]
) => Promise<Row[]>;

const url = process.env.DATABASE_URL ?? "";
const isNeon = /\.neon\.tech(?::|\/|$)/.test(url);

function localSql(connectionString: string): Sql {
  // One pool per process, reused across requests in `next dev`'s hot reloads.
  const globalForPg = globalThis as unknown as { __rdrPool?: Pool };
  const pool =
    globalForPg.__rdrPool ?? (globalForPg.__rdrPool = new Pool({ connectionString }));

  return async (strings, ...values) => {
    // `select ... where email = ${x}` -> `select ... where email = $1`
    const text = strings.reduce(
      (acc, part, i) => acc + part + (i < values.length ? `$${i + 1}` : ""),
      ""
    );
    const result = await pool.query(text, values);
    return result.rows as Row[];
  };
}

export const sql: Sql = isNeon
  ? (neon(url) as unknown as Sql)
  : localSql(url || "postgresql://localhost/postgres");

/** Emails are compared lowercased, everywhere, or membership silently fails. */
export function normalizeEmail(email: string | null | undefined): string {
  return (email ?? "").trim().toLowerCase();
}
