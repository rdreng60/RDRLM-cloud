import Link from "next/link";
import { redirect } from "next/navigation";
import { auth, signOut } from "@/auth";
import { orgsFor, isSuperAdmin, allOrgs } from "@/lib/orgs";

/** Which knowledge base? Only shown when there is more than one to choose. */
export default async function Orgs() {
  const session = await auth();
  const email = session?.user?.email;
  if (!email) redirect("/signin");

  const admin = isSuperAdmin(email);
  const mine = await orgsFor(email);
  const listed = admin ? await allOrgs() : mine;

  if (!listed.length && !admin) redirect("/no-access");

  const mineIds = new Set(mine.map((m) => m.orgId));

  return (
    <main className="min-h-screen px-6 py-14">
      <div className="mx-auto w-full max-w-[720px]">
        <h1 className="text-xl font-semibold tracking-tight">
          Your organisations
        </h1>
        <p className="note mt-1.5">
          Signed in as {email}. Everyone in an organisation reads and adds to the
          same tree.
        </p>

        <div className="mt-7 flex flex-col gap-3">
          {listed.map((o) => (
            <Link
              key={o.orgId}
              href={`/${o.orgId}`}
              className="surface px-5 py-4 flex items-center justify-between hover:border-[var(--accent)] transition-colors"
            >
              <div>
                <div className="font-medium">{o.name}</div>
                <div className="note mt-0.5">
                  {o.rules} rule{o.rules === 1 ? "" : "s"} · {o.people}{" "}
                  {o.people === 1 ? "person" : "people"}
                  {admin && !mineIds.has(o.orgId) ? " · (admin view)" : ""}
                </div>
              </div>
              <span className="note">open →</span>
            </Link>
          ))}
          {!listed.length && (
            <p className="note">
              No organisations exist yet. Create the first one below.
            </p>
          )}
        </div>

        <div className="mt-8 flex gap-3">
          {admin && (
            <Link href="/admin" className="btn-base">
              Manage organisations
            </Link>
          )}
          <form
            action={async () => {
              "use server";
              await signOut({ redirectTo: "/signin" });
            }}
          >
            <button className="btn-base">Sign out</button>
          </form>
        </div>
      </div>
    </main>
  );
}
