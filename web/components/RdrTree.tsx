"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Node from "./Node";
import VerdictCard, { type Draft } from "./VerdictCard";
import {
  layout,
  rowOffsets,
  needsShift,
  xOf,
  edgeGeometry,
  NODE_W,
  NODE_H,
  CARD_W,
  type Heights,
  type LayoutMode,
} from "./layout";
import type { Tree } from "@/lib/engine";
import "./tree.css";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * The whole tree, as one React island.
 *
 * Ported from the Streamlit custom component. The drawing is deliberately
 * identical — same ladder geometry, same colours, same node anatomy — because
 * that is what clinicians have been reading. What changed is the plumbing: the
 * iframe bridge is gone, and Agree / Disagree / Save are ordinary callbacks
 * into server actions instead of messages posted to Python.
 */
export default function RdrTree({
  tree,
  root,
  trace,
  endNode,
  verdictNode,
  suggestions,
  freshNode,
  phase,
  phaseSeq,
  error,
  draft,
  busy,
  animate = true,
  onAgree,
  onDisagree,
  onSave,
}: {
  tree: Tree;
  root: string | null;
  trace: [string, boolean][];
  endNode: string | null;
  verdictNode: string | null;
  suggestions: string[];
  freshNode: string | null;
  phase: "verdict" | "fixing";
  phaseSeq: number;
  error: string;
  draft: Draft | null;
  busy: boolean;
  animate?: boolean;
  onAgree: () => void;
  onDisagree: () => void;
  onSave: (v: {
    conclusion: string;
    conditions: string[];
    manual: string[];
    side: "left" | "right";
  }) => void;
}) {
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [testing, setTesting] = useState<string | null>(null);
  const [walked, setWalked] = useState<string[]>([]);
  const [finished, setFinished] = useState(false);
  const [mode, setMode] = useState<"verdict" | "fixing" | "done">(phase);
  const [doneMessage, setDoneMessage] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [heights, setHeights] = useState<Heights>({});
  // Layout is a pure view preference, so it stays here in the browser.
  const [layoutMode, setLayoutMode] = useState<LayoutMode>("ladder");

  const traceKey = JSON.stringify(trace);

  // Replay the walk the engine already did. Every model call has already been
  // made on the server; this only paces the reveal so the clinician can follow
  // the reasoning.
  useEffect(() => {
    let cancelled = false;
    setMode(phase);
    setDoneMessage("");

    if (!trace.length) {
      setRevealed({});
      setWalked([]);
      setTesting(null);
      setFinished(true);
      return;
    }
    if (!animate) {
      setRevealed(Object.fromEntries(trace));
      setWalked(trace.map(([id]) => id));
      setTesting(null);
      setFinished(true);
      return;
    }

    const play = async () => {
      const seenIds: string[] = [];
      const results: Record<string, boolean> = {};
      setRevealed({});
      setWalked([]);
      setFinished(false);
      for (let i = 0; i < trace.length; i++) {
        const [id, was] = trace[i];
        if (cancelled) return;
        seenIds.push(id);
        setWalked([...seenIds]);
        setTesting(id);
        await sleep(600);
        if (cancelled) return;
        results[id] = was;
        setRevealed({ ...results });
        setTesting(null);
        await sleep(350);
      }
      if (!cancelled) setFinished(true);
    };
    play();
    return () => {
      cancelled = true;
    };
  }, [traceKey, animate]); // eslint-disable-line react-hooks/exhaustive-deps

  // The server moved the card: back to the fix form after a rejected save, or
  // back to the verdict. phaseSeq tells two consecutive rejections apart.
  useEffect(() => {
    setMode(phase);
    setDoneMessage("");
  }, [phase, phaseSeq]);

  const onMeasure = useCallback((id: string, h: number) => {
    setHeights((prev) => (prev[id] === h ? prev : { ...prev, [id]: h }));
  }, []);

  const toggle = useCallback(
    (id: string) => setExpanded((prev) => ({ ...prev, [id]: !prev[id] })),
    []
  );

  const pos = useMemo(
    () => (root ? layout(tree, root, layoutMode) : {}),
    [tree, root, layoutMode]
  );
  const { y: rowY, total: treeH } = useMemo(
    () => rowOffsets(pos, heights),
    [pos, heights]
  );

  const showCard = finished && endNode && pos[endNode];
  const cardH = mode === "fixing" ? 560 : 210;
  const shift = !!showCard && needsShift(pos, rowY, heights, endNode, cardH);
  const endCol = showCard ? pos[endNode!].col : -1;

  let width = 0;
  let height = treeH;
  for (const id of Object.keys(pos)) {
    width = Math.max(width, xOf(pos, id, endCol, shift) + NODE_W);
  }
  if (showCard) {
    width = Math.max(
      width,
      xOf(pos, endNode!, endCol, shift) + NODE_W + 24 + CARD_W
    );
    height = Math.max(height, rowY[pos[endNode!].row] - 4 + cardH);
  }

  const handleDisagree = () => {
    setMode("fixing");
    onDisagree();
  };

  const edges: React.ReactNode[] = [];
  for (const id of Object.keys(tree)) {
    if (!pos[id]) continue;
    const px = xOf(pos, id, endCol, shift);
    const pBottom = rowY[pos[id].row] + (heights[id] || NODE_H);
    for (const side of ["left", "right"] as const) {
      const kid = tree[id][side];
      if (!kid || !pos[kid]) continue;
      const isTrue = side === "right";
      const kx = xOf(pos, kid, endCol, shift);
      const kTop = rowY[pos[kid].row];
      const used = revealed[id] === isTrue && walked.includes(kid);
      // Path colour is deliberately not the app's primary: a red primary would
      // collide with the red "false" edges.
      const colour = used ? "var(--accent)" : isTrue ? "#16a34a" : "#dc2626";
      const faded = used ? 1 : walked.length ? 0.28 : 0.5;
      const { d, lx, ly } = edgeGeometry(layoutMode, px, pBottom, kx, kTop, isTrue);
      edges.push(
        <g key={`${id}-${side}`}>
          <path d={d} fill="none" stroke={colour} strokeWidth={used ? 2.5 : 1.2} opacity={faded} />
          <text x={lx} y={ly} fontSize="10.5" fill={colour} opacity={faded}>
            {isTrue ? "true" : "false"}
          </text>
        </g>
      );
    }
  }

  if (!root) {
    return (
      <div className="shell">
        <p className="empty-tree">
          The knowledge base is empty. Analyse a case and write the first rule.
        </p>
      </div>
    );
  }

  return (
    <div className="shell">
      <div className="toolbar">
        <div className="seg">
          <button
            className={layoutMode === "ladder" ? "on" : ""}
            onClick={() => setLayoutMode("ladder")}
          >
            Ladder
          </button>
          <button
            className={layoutMode === "pyramid" ? "on" : ""}
            onClick={() => setLayoutMode("pyramid")}
          >
            Pyramid
          </button>
        </div>
        <span className="seg-note">
          {layoutMode === "ladder"
            ? "one node per row; indent = how many exceptions deep"
            : "one row per depth level; parents centred over their children"}
        </span>
      </div>

      <div className="legend">
        <span>
          <i className="swatch solid" /> solid outline = confirmed by a clinician
        </span>
        <span>
          <i className="swatch dotted" /> dotted = proposed, awaiting your decision
        </span>
        <span>
          <i className="dash" style={{ borderColor: "#16a34a" }} /> true branch (a
          more specific exception)
        </span>
        <span>
          <i className="dash" style={{ borderColor: "#dc2626" }} /> false branch (the
          next alternative)
        </span>
        <span>
          <i className="dash" style={{ borderColor: "var(--accent)" }} /> path taken
        </span>
      </div>

      <div className="scroller">
        <div className="canvas" style={{ width, height: height + 20 }}>
          <svg className="wires">{edges}</svg>

          {Object.keys(tree).map((id) =>
            pos[id] ? (
              <Node
                key={id}
                id={id}
                node={tree[id]}
                x={xOf(pos, id, endCol, shift)}
                y={rowY[pos[id].row]}
                visited={walked.includes(id)}
                result={revealed[id]}
                testing={testing === id}
                isEnd={!!showCard && id === endNode}
                isVerdictSource={id === verdictNode}
                isFresh={id === freshNode}
                anyVisited={walked.length > 0}
                expanded={!!expanded[id]}
                onToggle={toggle}
                onMeasure={onMeasure}
              />
            ) : null
          )}

          {showCard && (
            <VerdictCard
              x={xOf(pos, endNode!, endCol, shift) + NODE_W + 24}
              y={rowY[pos[endNode!].row] - 4}
              endNode={endNode}
              verdictNode={verdictNode}
              conclusion={verdictNode ? (tree[verdictNode]?.conclusion ?? null) : null}
              suggestions={suggestions}
              mode={mode}
              busy={busy}
              doneMessage={doneMessage}
              error={error}
              draft={draft}
              draftKey={phaseSeq}
              onAgree={onAgree}
              onDisagree={handleDisagree}
              onSave={onSave}
            />
          )}
        </div>
      </div>
    </div>
  );
}
