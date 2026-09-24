import { redirect } from "next/navigation";
import { auth, signOut } from "@/auth";
import { orgsFor } from "@/lib/orgs";

/** Signed in, but on nobody's allow list yet. */
export default async function NoAccess() {
  const session = await auth();
  const email = session?.user?.email;
  if (!email) redirect("/signin");
  if ((await orgsFor(email)).length) redirect("/");

  return (
    <main className="min-h-screen grid place-items-center px-6 py-16">
      <div className="w-full max-w-[460px] surface p-8 text-center">
        <div className="text-3xl mb-3">🔑</div>
        <h1 className="text-lg font-semibold">You are signed in, but not yet invited</h1>
        <p className="note mt-3">
          You are signed in as <strong className="text-[var(--foreground)]">{email}</strong>,
          and that address is not in any organisation.
        </p>
        <p className="note mt-3">
          Ask whoever runs your organisation to add this exact address. If you
          have more than one Google account, make sure it is the one they were
          given.
        </p>
        <form
          className="mt-6"
          action={async () => {
            "use server";
            await signOut({ redirectTo: "/signin" });
          }}
        >
          <button className="btn-base w-full">Sign out and try another account</button>
        </form>
      </div>
    </main>
  );
}
