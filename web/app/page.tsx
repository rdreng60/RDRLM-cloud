import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { orgsFor, isSuperAdmin } from "@/lib/orgs";

/**
 * The front door. Signing in tells us who you are; the members table decides
 * where you land.
 */
export default async function Home() {
  const session = await auth();
  const email = session?.user?.email;
  if (!email) redirect("/signin");

  const mine = await orgsFor(email);
  if (mine.length === 1 && !isSuperAdmin(email)) redirect(`/${mine[0].orgId}`);
  if (mine.length === 0 && !isSuperAdmin(email)) redirect("/no-access");
  redirect("/orgs");
}
