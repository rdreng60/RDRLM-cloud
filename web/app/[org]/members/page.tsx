import Link from "next/link";
import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { membershipIn, membersOf } from "@/lib/orgs";
import { addMemberAction, removeMemberAction } from "@/lib/actions";
import MemberPanel from "@/components/MemberPanel";

/** An owner's view of their own organisation's allow list. */
export default async function Members({
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
  if (membership.role !== "owner") redirect(`/${org}`);

  const members = await membersOf(org);

  return (
    <main className="min-h-screen px-6 py-14">
      <div className="mx-auto w-full max-w-[720px]">
        <div className="flex items-baseline justify-between">
          <h1 className="text-xl font-semibold tracking-tight">
            {membership.name} · people
          </h1>
          <Link href={`/${org}`} className="note hover:text-[var(--foreground)]">
            ← back to the tree
          </Link>
        </div>

        <div className="mt-7">
          <MemberPanel
            orgId={org}
            orgName={membership.name}
            members={members}
            me={email.toLowerCase()}
            add={addMemberAction}
            remove={removeMemberAction}
          />
        </div>
      </div>
    </main>
  );
}
