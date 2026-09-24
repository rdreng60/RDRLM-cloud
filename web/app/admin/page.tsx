import Link from "next/link";
import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { allOrgs, isSuperAdmin, membersOf } from "@/lib/orgs";
import { addMemberAction, removeMemberAction } from "@/lib/actions";
import MemberPanel from "@/components/MemberPanel";
import NewOrgForm from "@/components/NewOrgForm";

/**
 * Making a new organisation, and editing anyone's allow list.
 *
 * Restricted to the addresses in SUPER_ADMINS. That list is the bootstrap: the
 * first organisation has no owner yet, so somebody outside the members table
 * has to be able to create it.
 */
export default async function Admin() {
  const session = await auth();
  const email = session?.user?.email;
  if (!email) redirect("/signin");
  if (!isSuperAdmin(email)) redirect("/");

  const orgs = await allOrgs();
  const withMembers = await Promise.all(
    orgs.map(async (o) => ({ org: o, members: await membersOf(o.orgId) }))
  );

  return (
    <main className="min-h-screen px-6 py-14">
      <div className="mx-auto w-full max-w-[760px]">
        <div className="flex items-baseline justify-between">
          <h1 className="text-xl font-semibold tracking-tight">Organisations</h1>
          <Link href="/orgs" className="note hover:text-[var(--foreground)]">
            ← back
          </Link>
        </div>
        <p className="note mt-1.5">
          Signed in as {email}, a super admin. You can create organisations and
          change any allow list.
        </p>

        <div className="mt-7">
          <NewOrgForm defaultOwner={email} />
        </div>

        <div className="mt-8 flex flex-col gap-6">
          {withMembers.map(({ org, members }) => (
            <MemberPanel
              key={org.orgId}
              orgId={org.orgId}
              orgName={`${org.name} (${org.rules} rule${org.rules === 1 ? "" : "s"})`}
              members={members}
              me={email}
              add={addMemberAction}
              remove={removeMemberAction}
            />
          ))}
          {!withMembers.length && (
            <p className="note">No organisations yet — create the first one above.</p>
          )}
        </div>
      </div>
    </main>
  );
}
