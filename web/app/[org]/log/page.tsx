import Link from "next/link";
import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { membershipIn } from "@/lib/orgs";
import { engine, type EventRow } from "@/lib/engine";

/**
 * The event log, as rows rather than a downloaded CSV.
 *
 * Two columns here were impossible before: `vertex` is the paper's number
 * rather than a memory address, so rows can be counted and joined across
 * sessions; and `who` exists at all only because there is now a signed-in user.
 */
export default async function LogPage({
  params,
}: {
  params: Promise<{ org: string }>;
}) {
  const { org } = await params;
  const session = await auth();
  const email = session?.user?.email;
  if (!email) redirect("/signin");

  const membership = await membershipIn(email, org);
  if (!membership) redirect("/no-access");

  let rows: EventRow[] = [];
  let error: string | null = null;
  try {
    rows = (await engine.events(email.toLowerCase(), org, 300)).events;
  } catch (e) {
    error = (e as Error).message;
  }

  return (
    <main className="min-h-screen px-6 py-14">
      <div className="mx-auto w-full max-w-[1000px]">
        <div className="flex items-baseline justify-between">
          <h1 className="text-xl font-semibold tracking-tight">
            {membership.name} · event log
          </h1>
          <Link href={`/${org}`} className="note hover:text-[var(--foreground)]">
            ← back to the tree
          </Link>
        </div>

        {error && (
          <p className="mt-4 text-[13px]" style={{ color: "var(--bad)" }}>
            {error}
          </p>
        )}

        <div className="surface mt-6 overflow-x-auto">
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="text-left text-[var(--muted)]">
                <th className="px-4 py-3 font-medium">when</th>
                <th className="px-4 py-3 font-medium">what</th>
                <th className="px-4 py-3 font-medium">who</th>
                <th className="px-4 py-3 font-medium">vertex</th>
                <th className="px-4 py-3 font-medium">transcript</th>
                <th className="px-4 py-3 font-medium">detail</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-t border-[var(--border)]">
                  <td className="px-4 py-2.5 whitespace-nowrap text-[var(--muted)]">
                    {new Date(r.at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2.5 whitespace-nowrap">{r.action}</td>
                  <td className="px-4 py-2.5 whitespace-nowrap">{r.actor ?? "—"}</td>
                  <td className="px-4 py-2.5 whitespace-nowrap">
                    {r.true_vertex !== null ? `#${r.true_vertex}` : "—"}
                  </td>
                  <td className="px-4 py-2.5">{r.source_file ?? "—"}</td>
                  <td className="px-4 py-2.5 text-[var(--muted)]">
                    {r.detail ?? r.condition_type ?? ""}
                  </td>
                </tr>
              ))}
              {!rows.length && !error && (
                <tr>
                  <td className="px-4 py-6 note" colSpan={6}>
                    Nothing recorded yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <p className="note mt-4">
          Every row names a vertex by the number the paper gives it, so these
          rows join to the tree and to each other — across sessions, which the
          old CSV could not do.
        </p>
      </div>
    </main>
  );
}
