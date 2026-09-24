"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import RdrTree from "./RdrTree";
import type { Draft } from "./VerdictCard";
import type { Tree, Step, Rejection } from "@/lib/engine";
import {
  agreeAction,
  analyzeAction,
  differencesAction,
  refreshTreeAction,
  saveRuleAction,
  undoAction,
  type CaseState,
} from "@/app/[org]/actions";

/**
 * One case, from upload to decision.
 *
 * The order is the paper's, and the same one the Streamlit build used:
 *
 *   Analyze  -> interpret            (Algorithms 1 + 3)
 *   Disagree -> find_differences     (Algorithm 5: propose, then verify)
 *   Save     -> verify_conditions    (Algorithms 6 + 7) then attach
 *   Agree    -> merge_case
 *
 * Nothing in this file decides whether a condition holds or where a rule goes.
 * It decides which screen you are on.
 */
export default function Workspace({
  orgId,
  orgName,
  role,
  me,
  initialTree,
  initialRoot,
}: {
  orgId: string;
  orgName: string;
  role: "owner" | "clinician";
  me: string;
  initialTree: Tree;
  initialRoot: string | null;
}) {
  const [tree, setTree] = useState<Tree>(initialTree);
  const [root, setRoot] = useState<string | null>(initialRoot);
  const [kase, setKase] = useState<CaseState | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [rejected, setRejected] = useState<Rejection[]>([]);
  const [phase, setPhase] = useState<"verdict" | "fixing">("verdict");
  const [phaseSeq, setPhaseSeq] = useState(0);
  const [cardError, setCardError] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [freshNode, setFreshNode] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ kind: "ok" | "bad"; text: string } | null>(null);
  const [showDetail, setShowDetail] = useState(false);
  const [pending, start] = useTransition();

  /** A decision has been taken; put the card away so it cannot be taken twice. */
  const closeCase = () => {
    setKase(null);
    setSuggestions([]);
    setRejected([]);
    setPhase("verdict");
    setCardError("");
    setDraft(null);
    setPhaseSeq((n) => n + 1);
  };

  const analyze = (form: FormData) =>
    start(async () => {
      setBanner(null);
      const out = await analyzeAction(orgId, form);
      if (!out.ok) return setBanner({ kind: "bad", text: out.error });
      setKase(out.data);
      setTree(out.data.tree);
      setRoot(out.data.root);
      setSuggestions([]);
      setRejected([]);
      setPhase("verdict");
      setCardError("");
      setDraft(null);
      setFreshNode(null);
      setPhaseSeq((n) => n + 1);
    });

  const onAgree = () => {
    if (!kase || kase.verdict_node === null) return;
    start(async () => {
      const out = await agreeAction(orgId, kase.summary, kase.verdict_node!, kase.sourceFile);
      if (!out.ok) return setBanner({ kind: "bad", text: out.error });
      setTree(out.data.tree);
      setRoot(out.data.root);
      setFreshNode(String(kase.verdict_node));
      closeCase();
      setBanner({ kind: "ok", text: "Agreed — this case merged into that rule's profile." });
    });
  };

  const onDisagree = () => {
    if (!kase) return;
    start(async () => {
      const out = await differencesAction(orgId, kase.summary, kase.verdict_node, kase.sourceFile);
      if (!out.ok) {
        // No suggestions, and the card says why rather than looking as though
        // the model found no differences.
        setSuggestions([]);
        setRejected([]);
        setCardError(out.error);
      } else {
        setSuggestions(out.data.kept);
        setRejected(out.data.rejected);
        setCardError("");
      }
      setPhase("fixing");
      setPhaseSeq((n) => n + 1);
    });
  };

  const onSave = (v: {
    conclusion: string;
    conditions: string[];
    manual: string[];
    side: "left" | "right";
  }) => {
    if (!kase) return;
    const asDraft: Draft = {
      conclusion: v.conclusion,
      picked: v.conditions.filter((c) => !v.manual.includes(c)),
      manual: v.manual.join("\n"),
    };
    start(async () => {
      const out = await saveRuleAction(orgId, {
        summary: kase.summary,
        sourceFile: kase.sourceFile,
        endNode: kase.end_node,
        verdictNode: kase.verdict_node,
        conditions: v.conditions,
        manual: v.manual,
        conclusion: v.conclusion,
      });

      if (!out.ok) {
        setCardError(out.error);
        setDraft(asDraft);
        setPhase("fixing");
        setPhaseSeq((n) => n + 1);
        return;
      }

      setTree(out.data.tree);
      setRoot(out.data.root);

      if (!out.data.saved) {
        // The repeat-until: back to the form with the reason and the entries
        // still in the boxes, rather than a dead end.
        setCardError(out.data.problem ?? "Those conditions cannot be used.");
        setDraft(asDraft);
        setPhase("fixing");
        setPhaseSeq((n) => n + 1);
        if (out.data.stale) {
          setBanner({
            kind: "bad",
            text: "Someone else changed the tree while you were working. Re-run the case.",
          });
        }
        return;
      }

      setFreshNode(out.data.number != null ? String(out.data.number) : null);
      closeCase();
      setBanner({ kind: "ok", text: `New rule saved as vertex #${out.data.number}.` });
    });
  };

  const undo = () =>
    start(async () => {
      const out = await undoAction(orgId);
      if (!out.ok) return setBanner({ kind: "bad", text: out.error });
      setTree(out.data.tree);
      setRoot(out.data.root);
      setFreshNode(null);
      closeCase();
      setBanner({ kind: "ok", text: out.data.message });
    });

  const refresh = () =>
    start(async () => {
      const out = await refreshTreeAction(orgId);
      if (!out.ok) return setBanner({ kind: "bad", text: out.error });
      setTree(out.data.tree);
      setRoot(out.data.root);
      setBanner({ kind: "ok", text: "Tree reloaded." });
    });

  const openCase = kase !== null;
  const ruleCount = Object.keys(tree).length;

  return (
    <div className="flex min-h-screen">
      {/* ---------------- sidebar: the Streamlit one, rebuilt ---------------- */}
      <aside className="w-[280px] shrink-0 border-r border-[var(--border)] px-5 py-6 flex flex-col gap-6">
        <div>
          <div className="text-[11px] uppercase tracking-wider text-[var(--muted)]">
            Organisation
          </div>
          <div className="text-[15px] font-medium mt-1">{orgName}</div>
          <div className="note mt-0.5">
            {ruleCount} rule{ruleCount === 1 ? "" : "s"}
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <div className="text-[11px] uppercase tracking-wider text-[var(--muted)]">
            Tree controls
          </div>
          <button className="btn-base text-left" onClick={undo} disabled={pending}>
            ↩︎ Undo last rule
          </button>
          <button className="btn-base text-left" onClick={refresh} disabled={pending}>
            ⟳ Reload tree
          </button>
          <p className="note">
            Everyone here works on this one tree, so reload if a colleague has
            been adding rules.
          </p>
        </div>

        <div className="flex flex-col gap-2">
          <div className="text-[11px] uppercase tracking-wider text-[var(--muted)]">
            This organisation
          </div>
          <Link href={`/${orgId}/log`} className="btn-base text-left">
            📄 Event log
          </Link>
          {role === "owner" && (
            <Link href={`/${orgId}/members`} className="btn-base text-left">
              👥 People
            </Link>
          )}
          <Link href="/orgs" className="btn-base text-left">
            ⇄ Switch organisation
          </Link>
        </div>

        <div className="mt-auto">
          <div className="note">{me}</div>
          <form action="/api/auth/signout" method="post" className="mt-2">
            <button className="btn-base w-full text-[12px]">Sign out</button>
          </form>
        </div>
      </aside>

      {/* ---------------- main ---------------- */}
      <main className="flex-1 px-8 py-8 min-w-0">
        <h1 className="text-xl font-semibold tracking-tight">
          🧠 Clinical RDR Knowledge Base
        </h1>

        {banner && (
          <div
            className="surface mt-4 px-4 py-3 text-[13px]"
            style={{
              borderColor: banner.kind === "ok" ? "var(--good)" : "var(--bad)",
            }}
          >
            {banner.text}
          </div>
        )}

        <section className="mt-7">
          <h2 className="text-[15px] font-medium">Input transcript</h2>
          <form action={analyze} className="mt-3 flex flex-wrap items-center gap-3">
            <input
              type="file"
              name="file"
              accept=".docx"
              required
              className="field max-w-[380px] file:mr-3 file:rounded file:border-0 file:bg-[var(--panel)] file:px-3 file:py-1.5 file:text-[var(--foreground)]"
            />
            <button className="btn-base" disabled={pending}>
              {pending ? "Working…" : "Analyse case"}
            </button>
          </form>
        </section>

        {kase && (
          <section className="mt-8 grid gap-6 lg:grid-cols-2">
            <div>
              <h2 className="text-[15px] font-medium">📄 Clinical summary</h2>
              <div className="surface mt-2 p-4 text-[13px] leading-relaxed whitespace-pre-wrap">
                {kase.summary}
              </div>
            </div>
            <div>
              <h2 className="text-[15px] font-medium">🤖 System conclusion</h2>
              <div className="surface mt-2 p-4">
                {kase.conclusion ? (
                  <>
                    <div
                      className="text-[14px] font-medium"
                      style={{ color: "var(--good)" }}
                    >
                      {kase.conclusion}
                    </div>
                    <div className="note mt-2">
                      from vertex #{kase.verdict_node} · {kase.detail.length} rule
                      {kase.detail.length === 1 ? "" : "s"} tested
                    </div>
                  </>
                ) : (
                  <div className="text-[13px]" style={{ color: "var(--muted)" }}>
                    No conclusion — no rule was true for this case.
                  </div>
                )}
              </div>
            </div>
          </section>
        )}

        {kase && kase.detail.length > 0 && (
          <section className="mt-6">
            <button className="btn-base" onClick={() => setShowDetail((s) => !s)}>
              {showDetail ? "▾" : "▸"} How each rule was evaluated, condition by condition
            </button>
            {showDetail && (
              <div className="surface mt-3 p-4">
                <p className="note">
                  Algorithm 3: one model call per condition, a hard AND, stopping
                  at the first FALSE. A rule with untested conditions below its
                  first FALSE is correct — the conjunction was already decided.
                </p>
                <div className="mt-4 flex flex-col gap-4">
                  {kase.detail.map((step: Step) => (
                    <div key={step.number}>
                      <div className="text-[13px]">
                        <strong>
                          vertex #{step.number} → {step.result ? "✅ TRUE" : "❌ FALSE"}
                        </strong>{" "}
                        <span className="note">THEN {step.conclusion}</span>
                      </div>
                      <ul className="mt-1.5 ml-4 flex flex-col gap-1">
                        {step.conditions.map((c, i) => (
                          <li key={i} className="text-[12.5px]">
                            {c.result ? "✅" : "❌"} {c.condition}
                          </li>
                        ))}
                      </ul>
                      {step.conditions.length <
                        (tree[String(step.number)]?.conds.length ?? 0) && (
                        <p className="note ml-4 mt-1">
                          {(tree[String(step.number)]?.conds.length ?? 0) -
                            step.conditions.length}{" "}
                          further condition(s) not tested — the AND was already
                          false.
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>
        )}

        {/* The first rule has no node for the card to sit beside. */}
        {openCase && root === null && (
          <FirstRule
            busy={pending}
            error={cardError}
            onSave={(conclusion, conditions) =>
              onSave({ conclusion, conditions, manual: conditions, side: "right" })
            }
          />
        )}

        <section className="mt-9">
          <h2 className="text-[15px] font-medium">Knowledge base</h2>
          <div className="mt-3">
            <RdrTree
              tree={tree}
              root={root}
              trace={openCase ? kase!.trace : []}
              endNode={openCase && kase!.end_node !== null ? String(kase!.end_node) : null}
              verdictNode={
                openCase && kase!.verdict_node !== null ? String(kase!.verdict_node) : null
              }
              suggestions={suggestions}
              freshNode={freshNode}
              phase={phase}
              phaseSeq={phaseSeq}
              error={cardError}
              draft={draft}
              busy={pending}
              onAgree={onAgree}
              onDisagree={onDisagree}
              onSave={onSave}
            />
          </div>

          {rejected.length > 0 && (
            <div className="surface mt-4 p-4">
              <div className="text-[13px] font-medium">
                🧹 Candidates Algorithm 5 discarded
              </div>
              <p className="note mt-1">
                The model proposed these; the engine checked each one against
                this case and against every case already stored at that node.
                Only the survivors are offered as checkboxes.
              </p>
              <ul className="mt-3 flex flex-col gap-1.5">
                {rejected.map((r, i) => (
                  <li key={i} className="text-[12.5px]">
                    ❌ <strong>{r.condition}</strong>{" "}
                    {r.reason === "false_of_new"
                      ? "— not true of this patient."
                      : `— also true of stored case ${(r.case_index ?? 0) + 1} at that node, so it does not distinguish them.`}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

/** The very first rule in an empty organisation. */
function FirstRule({
  busy,
  error,
  onSave,
}: {
  busy: boolean;
  error: string;
  onSave: (conclusion: string, conditions: string[]) => void;
}) {
  const [conclusion, setConclusion] = useState("");
  const [conditions, setConditions] = useState("");

  return (
    <section className="surface mt-8 p-6 max-w-[620px]">
      <h2 className="text-[15px] font-medium">The first rule</h2>
      <p className="note mt-1">
        This knowledge base is empty, so this case becomes the root of the tree.
      </p>
      <input
        className="field mt-4"
        placeholder="Conclusion for this case"
        value={conclusion}
        onChange={(e) => setConclusion(e.target.value)}
      />
      <textarea
        className="field mt-3"
        rows={4}
        placeholder={"Conditions, one per line\nChronic low mood\nSleep disturbance present"}
        value={conditions}
        onChange={(e) => setConditions(e.target.value)}
      />
      {error && (
        <p className="mt-2 text-[12.5px]" style={{ color: "var(--bad)" }}>
          {error}
        </p>
      )}
      <button
        className="btn-base mt-3"
        disabled={busy}
        onClick={() =>
          onSave(
            conclusion.trim(),
            conditions
              .split("\n")
              .map((c) => c.trim())
              .filter(Boolean)
          )
        }
      >
        {busy ? "Checking…" : "Save the first rule"}
      </button>
    </section>
  );
}
