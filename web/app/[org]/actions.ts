"use server";

import mammoth from "mammoth";
import { auth } from "@/auth";
import { membershipIn } from "@/lib/orgs";
import { normalizeEmail } from "@/lib/db";
import { engine, EngineError, type Interpretation, type Rejection } from "@/lib/engine";

/**
 * Everything the workspace can do, each one re-checking membership first.
 *
 * These are the same engine methods the Streamlit build called, in the same
 * order — interpret, then find_differences, then verify_conditions, then
 * attach. What changed is only where they are called from.
 */

async function actor(orgId: string): Promise<string> {
  const session = await auth();
  const email = normalizeEmail(session?.user?.email);
  if (!email) throw new Error("Not signed in.");
  const membership = await membershipIn(email, orgId);
  if (!membership) throw new Error("You are not a member of this organisation.");
  return email;
}

export type CaseState = Interpretation & {
  summary: string;
  sourceFile: string;
};

export type Outcome<T> = { ok: true; data: T } | { ok: false; error: string };

function failed(e: unknown): { ok: false; error: string } {
  if (e instanceof EngineError) return { ok: false, error: e.message };
  return { ok: false, error: (e as Error).message ?? "Something went wrong." };
}

/** Upload → summary → walk the tree. */
export async function analyzeAction(
  orgId: string,
  formData: FormData
): Promise<Outcome<CaseState>> {
  try {
    const me = await actor(orgId);
    const file = formData.get("file");
    if (!(file instanceof File) || !file.size) {
      return { ok: false, error: "Choose a .docx transcript first." };
    }

    const buffer = Buffer.from(await file.arrayBuffer());
    let transcript: string;
    try {
      transcript = (await mammoth.extractRawText({ buffer })).value.trim();
    } catch {
      return { ok: false, error: "That file could not be read as a .docx." };
    }
    if (!transcript) {
      return { ok: false, error: "That transcript appears to be empty." };
    }

    const { summary } = await engine.summarize(me, transcript);
    if (!summary.trim()) {
      return { ok: false, error: "The summary came back empty. Try again." };
    }

    const interpretation = await engine.interpret(me, orgId, summary, file.name);
    return {
      ok: true,
      data: { ...interpretation, summary, sourceFile: file.name },
    };
  } catch (e) {
    return failed(e);
  }
}

/** Algorithm 5, run only when the clinician actually disagrees. */
export async function differencesAction(
  orgId: string,
  summary: string,
  verdictNode: number | null,
  sourceFile: string
): Promise<Outcome<{ kept: string[]; rejected: Rejection[] }>> {
  try {
    const me = await actor(orgId);
    const out = await engine.differences(me, orgId, summary, verdictNode, sourceFile);
    return { ok: true, data: { kept: out.kept, rejected: out.rejected } };
  } catch (e) {
    return failed(e);
  }
}

export async function agreeAction(
  orgId: string,
  summary: string,
  verdictNode: number,
  sourceFile: string
): Promise<Outcome<{ tree: CaseState["tree"]; root: string | null }>> {
  try {
    const me = await actor(orgId);
    await engine.agree(me, orgId, { summary, verdict_node: verdictNode, source_file: sourceFile });
    const fresh = await engine.tree(me, orgId);
    return { ok: true, data: { tree: fresh.tree, root: fresh.root } };
  } catch (e) {
    return failed(e);
  }
}

/**
 * Algorithms 6 + 7, then attachment.
 *
 * A rejection is not an error: `ok` comes back true with a `problem`, and the
 * card re-opens so the clinician can choose again. That is the paper's
 * repeat-until, and it is why nothing here throws on a refused rule.
 */
export async function saveRuleAction(
  orgId: string,
  body: {
    summary: string;
    sourceFile: string;
    endNode: number | null;
    verdictNode: number | null;
    conditions: string[];
    manual: string[];
    conclusion: string;
  }
): Promise<
  Outcome<{
    saved: boolean;
    problem?: string;
    stale?: boolean;
    number?: number;
    tree: CaseState["tree"];
    root: string | null;
  }>
> {
  try {
    const me = await actor(orgId);
    const result = await engine.addRule(me, orgId, {
      summary: body.summary,
      source_file: body.sourceFile,
      end_node: body.endNode,
      verdict_node: body.verdictNode,
      conditions: body.conditions,
      manual: body.manual,
      conclusion: body.conclusion,
    });

    const fresh = await engine.tree(me, orgId);
    return {
      ok: true,
      data: {
        saved: !!result.ok,
        problem: result.problem,
        stale: result.stale,
        number: result.number,
        tree: fresh.tree,
        root: fresh.root,
      },
    };
  } catch (e) {
    return failed(e);
  }
}

export async function undoAction(
  orgId: string
): Promise<Outcome<{ message: string; tree: CaseState["tree"]; root: string | null }>> {
  try {
    const me = await actor(orgId);
    const out = await engine.undo(me, orgId);
    const fresh = await engine.tree(me, orgId);
    return {
      ok: true,
      data: { message: out.message, tree: fresh.tree, root: fresh.root },
    };
  } catch (e) {
    return failed(e);
  }
}

export async function refreshTreeAction(
  orgId: string
): Promise<Outcome<{ tree: CaseState["tree"]; root: string | null }>> {
  try {
    const me = await actor(orgId);
    const fresh = await engine.tree(me, orgId);
    return { ok: true, data: { tree: fresh.tree, root: fresh.root } };
  } catch (e) {
    return failed(e);
  }
}
