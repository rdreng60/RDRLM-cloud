import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { membershipIn } from "@/lib/orgs";
import { engine } from "@/lib/engine";
import Workspace from "@/components/Workspace";

/**
 * One organisation's knowledge base.
 *
 * Membership is checked here, on the server, before a single rule is fetched.
 * A link to /sangath is not a way in.
 */
export default async function OrgPage({
  params,
}: {
  params: Promise<{ org: string }>;
}) {
  const { org } = await params;
  const session = await auth();
  const email = session?.user?.email;
  if (!email) redirect(`/signin?callbackUrl=/${org}`);

  const membership = await membershipIn(email, org);
  if (!membership) redirect("/no-access");

  let tree = {};
  let root: string | null = null;
  let offline: string | null = null;
  try {
    const fetched = await engine.tree(email.toLowerCase(), org);
    tree = fetched.tree;
    root = fetched.root;
  } catch (e) {
    offline = (e as Error).message;
  }

  return (
    <>
      {offline && (
        <div
          className="px-8 py-3 text-[13px]"
          style={{ background: "var(--panel)", color: "var(--bad)" }}
        >
          {offline}
        </div>
      )}
      <Workspace
        orgId={org}
        orgName={membership.name}
        role={membership.role}
        me={email.toLowerCase()}
        initialTree={tree}
        initialRoot={root}
      />
    </>
  );
}
