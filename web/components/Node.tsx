"use client";

import { useEffect, useRef, useState } from "react";
import { NODE_W } from "./layout";
import type { TreeNode } from "@/lib/engine";

// One React component per node in the tree.
//
// Outline carries the confirmation state, which is the thing a clinician needs
// at a glance:
//   dotted -> proposed, nobody has confirmed it yet
//   solid  -> a human agreed with this rule
export default function Node({
  id,
  node,
  x,
  y,
  visited,
  result,
  testing,
  isEnd,
  isVerdictSource,
  isFresh,
  anyVisited,
  expanded,
  onToggle,
  onMeasure,
}: {
  id: string;
  node: TreeNode;
  x: number;
  y: number;
  visited: boolean;
  result?: boolean;
  testing: boolean;
  isEnd: boolean;
  isVerdictSource: boolean;
  isFresh: boolean;
  anyVisited: boolean;
  expanded: boolean;
  onToggle: (id: string) => void;
  onMeasure: (id: string, h: number) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [showSummary, setShowSummary] = useState(false);

  // The layout needs the real height once a node expands, so report it upward.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const report = () => onMeasure(id, el.offsetHeight);
    report();
    const ro = new ResizeObserver(report);
    ro.observe(el);
    return () => ro.disconnect();
  }, [id, onMeasure, expanded]);

  const confirmed = node.status !== "pending";

  const cls = ["node"];
  cls.push(confirmed ? "confirmed" : "pending");
  if (visited || !anyVisited) cls.push("seen");
  if (visited) cls.push("onpath");
  if (testing) cls.push("testing");
  if (isEnd) cls.push("endnode");
  if (isVerdictSource && !isEnd) cls.push("verdictsrc");
  if (isFresh) cls.push("fresh", "seen");
  if (expanded || showSummary) cls.push("expanded");

  const n = node.conds.length;
  const summary = node.summary || "";
  // The cases stored at this node, one by one. The merged profile above is a
  // generalisation — it is what turned "insomnia" and "hypersomnia" into
  // "sleep disturbances" — so a clinician deciding whether a condition
  // distinguishes this node needs to read what it was actually tested against.
  const cases = node.cases || [];

  return (
    <div
      ref={ref}
      className={cls.join(" ")}
      style={{ left: x, top: y, width: NODE_W }}
    >
      {result !== undefined && (
        <div className={"stamp " + (result ? "yes" : "no")}>
          {result ? "✓" : "✗"}
        </div>
      )}

      <div className="n-head">
        <div className="n-if" title={node.short_if}>
          <b>IF</b>
          {node.short_if}
        </div>
        <div className="n-then" title={node.conclusion}>
          <b>THEN</b>
          {node.conclusion}
        </div>
        <div className="n-actions">
          <button className="n-more" onClick={() => onToggle(id)}>
            {expanded ? "▾ hide rule" : `▸ ${n} condition${n === 1 ? "" : "s"}`}
          </button>
          <button
            className="n-more n-sum-toggle"
            onClick={() => setShowSummary((s) => !s)}
            disabled={!summary && !cases.length}
            title={
              summary || cases.length
                ? "Every patient stored at this node: the merged profile, and each case on its own"
                : "No patient has been agreed onto this node yet"
            }
          >
            {!summary && !cases.length
              ? "no profile"
              : showSummary
                ? "▾ hide profile"
                : `▸ profile (${cases.length})`}
          </button>
        </div>
      </div>

      {expanded && (
        <div className="n-full">
          <p className="n-full-label">
            IF ALL OF THESE HOLD{confirmed ? "" : " (not yet confirmed)"}
          </p>
          <ol className="n-conds">
            {node.conds.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ol>
          <p className="n-full-label">THEN</p>
          <div className="n-full-concl">{node.conclusion}</div>
          <p className="n-meta">
            vertex #{node.number}
            {node.created_by ? ` · added by ${node.created_by}` : ""}
          </p>
        </div>
      )}

      {showSummary && (summary || cases.length > 0) && (
        <div className="n-summary">
          {summary && (
            <>
              <p className="n-full-label">
                EVERY AGREED PATIENT AT THIS NODE, MERGED
              </p>
              <div className="n-summary-text">{summary}</div>
            </>
          )}
          {cases.length > 0 && (
            <>
              <p className="n-full-label">
                THE {cases.length} CASE{cases.length === 1 ? "" : "S"} STORED
                HERE, AS WRITTEN
              </p>
              <ol className="n-cases">
                {cases.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ol>
            </>
          )}
        </div>
      )}
    </div>
  );
}
