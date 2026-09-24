"use client";

import { useEffect, useState } from "react";
import { CARD_W } from "./layout";

export type Draft = { conclusion: string; picked: string[]; manual: string };

// Sits immediately beside the node the run stopped on. Agree / Disagree live
// here rather than at the bottom of the page, so the clinician answers the
// question right where the reasoning ended.
export default function VerdictCard({
  x,
  y,
  endNode,
  verdictNode,
  conclusion,
  suggestions,
  mode,
  busy,
  doneMessage,
  error,
  draft,
  draftKey,
  onAgree,
  onDisagree,
  onSave,
}: {
  x: number;
  y: number;
  endNode: string | null;
  verdictNode: string | null;
  conclusion: string | null;
  suggestions: string[];
  mode: "verdict" | "fixing" | "done";
  busy: boolean;
  doneMessage: string;
  error: string;
  draft: Draft | null;
  draftKey: number;
  onAgree: () => void;
  onDisagree: () => void;
  onSave: (v: {
    conclusion: string;
    conditions: string[];
    manual: string[];
    side: "left" | "right";
  }) => void;
}) {
  const [newConclusion, setNewConclusion] = useState(draft?.conclusion ?? "");
  const [picked, setPicked] = useState<string[]>(draft?.picked ?? []);
  const [manual, setManual] = useState(draft?.manual ?? "");
  const [localError, setLocalError] = useState("");

  // A rejected save comes back with the same entries still in the boxes, so the
  // clinician edits their choice rather than retyping it.
  useEffect(() => {
    if (!draft) return;
    setNewConclusion(draft.conclusion || "");
    setPicked(draft.picked || []);
    setManual(draft.manual || "");
    setLocalError("");
  }, [draftKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const shown = localError || error || "";

  const toggle = (c: string) =>
    setPicked((p) => (p.includes(c) ? p.filter((x) => x !== c) : [...p, c]));

  // Algorithm 4: when the run stopped on the same node that produced the
  // conclusion the new rule is a refinement (right), otherwise it is the next
  // alternative (left). The engine decides this for real; this only labels the
  // button so the clinician knows what they are about to do.
  const side: "left" | "right" = endNode === verdictNode ? "right" : "left";

  const save = () => {
    const manualList = manual
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    const conditions = [...picked, ...manualList];
    if (!newConclusion.trim() || conditions.length === 0) {
      setLocalError("Give a conclusion and at least one condition.");
      return;
    }
    setLocalError("");
    onSave({
      conclusion: newConclusion.trim(),
      conditions,
      manual: manualList,
      side,
    });
  };

  return (
    <div className="card" style={{ left: x, top: y, width: CARD_W }}>
      <h3>CONCLUSION</h3>
      <p className="verdict">{conclusion || "No conclusion"}</p>
      <p className="from">
        {!verdictNode
          ? "the tree produced nothing for this transcript"
          : verdictNode === endNode
            ? "from this node — run stopped here"
            : `from vertex #${verdictNode} (last rule that was true); run stopped at this node`}
      </p>

      {mode === "verdict" && (
        <div className="row">
          <button className="btn agree" onClick={onAgree} disabled={busy || !verdictNode}>
            Agree
          </button>
          <button className="btn reject" onClick={onDisagree} disabled={busy}>
            Disagree
          </button>
        </div>
      )}

      {mode === "fixing" && (
        <div className="fix">
          <p>CORRECT CONCLUSION</p>
          <input
            type="text"
            value={newConclusion}
            placeholder="e.g. Client is likely to remit"
            onChange={(e) => setNewConclusion(e.target.value)}
          />

          {suggestions.length > 0 && <p>WHAT MAKES THIS CASE DIFFERENT</p>}
          {suggestions.map((c, i) => (
            <label className="cond" key={i}>
              <input
                type="checkbox"
                checked={picked.includes(c)}
                onChange={() => toggle(c)}
              />
              <span>{c}</span>
            </label>
          ))}

          <p style={{ marginTop: 10 }}>OR TYPE YOUR OWN, ONE PER LINE</p>
          <textarea
            rows={3}
            value={manual}
            placeholder={"Client reports suicidal ideation\nSleep disturbance present"}
            onChange={(e) => setManual(e.target.value)}
          />

          {shown && <div className="err">{shown}</div>}

          <button className="btn primary wide" onClick={save} disabled={busy}>
            {busy
              ? "Checking against every stored case…"
              : `Save as ${side} child of #${endNode}`}
          </button>
        </div>
      )}

      {mode === "done" && (
        <div className="fix">
          <span className="done">{doneMessage}</span>
        </div>
      )}
    </div>
  );
}
