"use server";

import { revalidatePath } from "next/cache";
import { auth } from "@/auth";
import {
  addMember,
  createOrg,
  isSuperAdmin,
  membershipIn,
  removeMember,
  type Role,
} from "./orgs";
import { normalizeEmail } from "./db";

/**
 * A server action is a public endpoint with a friendly face. Every one of these
 * re-checks who is calling and what they are allowed to do — being able to see
 * a button is never the thing that grants permission.
 */
async function requireOwner(orgId: string) {
  const session = await auth();
  const email = normalizeEmail(session?.user?.email);
  if (!email) throw new Error("Not signed in.");
  if (isSuperAdmin(email)) return email;
  const membership = await membershipIn(email, orgId);
  if (!membership || membership.role !== "owner") {
    throw new Error("Only an owner of this organisation can change its members.");
  }
  return email;
}

async function requireSuperAdmin() {
  const session = await auth();
  const email = normalizeEmail(session?.user?.email);
  if (!isSuperAdmin(email)) {
    throw new Error("Only a super admin can create organisations.");
  }
  return email;
}

export type ActionResult = { ok: boolean; message: string };

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export async function addMemberAction(
  orgId: string,
  formData: FormData
): Promise<ActionResult> {
  try {
    const me = await requireOwner(orgId);
    const email = normalizeEmail(String(formData.get("email") ?? ""));
    const role = (String(formData.get("role") ?? "clinician") as Role);
    if (!EMAIL.test(email)) {
      return { ok: false, message: `"${email}" does not look like an email address.` };
    }
    await addMember(orgId, email, role === "owner" ? "owner" : "clinician", me);
    revalidatePath(`/${orgId}/members`);
    revalidatePath("/admin");
    return { ok: true, message: `${email} can now sign in to this organisation.` };
  } catch (e) {
    return { ok: false, message: (e as Error).message };
  }
}

export async function removeMemberAction(
  orgId: string,
  email: string
): Promise<ActionResult> {
  try {
    const me = await requireOwner(orgId);
    if (normalizeEmail(email) === me && !isSuperAdmin(me)) {
      return { ok: false, message: "You cannot remove yourself — ask another owner." };
    }
    await removeMember(orgId, email);
    revalidatePath(`/${orgId}/members`);
    revalidatePath("/admin");
    return { ok: true, message: `${email} no longer has access.` };
  } catch (e) {
    return { ok: false, message: (e as Error).message };
  }
}

export async function createOrgAction(formData: FormData): Promise<ActionResult> {
  try {
    const me = await requireSuperAdmin();
    const rawId = String(formData.get("orgId") ?? "").trim();
    const name = String(formData.get("name") ?? "").trim() || rawId;
    const owner = normalizeEmail(String(formData.get("owner") ?? "")) || me;
    if (!rawId) return { ok: false, message: "Give the organisation an id." };
    if (!EMAIL.test(owner)) {
      return { ok: false, message: `"${owner}" does not look like an email address.` };
    }
    const id = await createOrg(rawId, name, owner);
    revalidatePath("/admin");
    revalidatePath("/orgs");
    return { ok: true, message: `Created ${name} (${id}), owned by ${owner}.` };
  } catch (e) {
    return { ok: false, message: (e as Error).message };
  }
}
