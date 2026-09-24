// Ported unchanged from the Streamlit component, with types added. The
// geometry is the thing a clinician reads the tree by, so it is deliberately
// the same drawing in both builds.
//
export type LayoutMode = "ladder" | "pyramid"
export type Positions = Record<string, { col: number; row: number }>
export type Heights = Record<string, number>
type Tree = Record<string, { left: string | null; right: string | null }>

// Ladder layout.
//
//   false  -> straight down, same column     (try the next alternative)
//   true   -> indent one column to the right (a more specific exception)
//
// A node's column is just how many exceptions deep it sits.
//
// Node heights are NOT fixed: expanding a node to show its full conditions
// makes it taller, and every row below has to move down. So rows are placed by
// accumulating measured heights rather than multiplying by a constant.

export const NODE_W = 236
export const NODE_H = 74 // collapsed height; expanded nodes are measured
export const ROW_GAP = 44
export const COL_W = 262
export const CARD_W = 250
export const CARD_GAP = 296
export const HEADER_H = 74 // the IF/THEN block, unchanged when expanded

// LADDER: row = reading order (every node gets its own row),
//         col = how many exceptions deep.
export function ladderLayout(tree: Tree, root: string): Positions {
  const pos: Positions = {}
  let row = 0
  const walk = (id: string, col: number) => {
    const n = tree[id]
    if (!n) return
    pos[id] = { col, row: row++ }
    if (n.right) walk(n.right, col + 1)
    if (n.left) walk(n.left, col)
  }
  walk(root, 0)
  return pos
}

// PYRAMID: row = depth in the tree (siblings share a row),
//          col = centred over the children below.
//
// Children are placed first, then the parent takes the midpoint between them.
// A node with only one child sits directly above it, so a long unbranched
// chain stays vertical instead of drifting sideways.
export function pyramidLayout(tree: Tree, root: string): Positions {
  const pos: Positions = {}
  let nextLeaf = 0

  const walk = (id: string, depth: number): number | null => {
    const n = tree[id]
    if (!n) return null
    const lx = n.left ? walk(n.left, depth + 1) : null
    const rx = n.right ? walk(n.right, depth + 1) : null

    let col: number
    if (lx === null && rx === null) col = nextLeaf++      // leaf: take the next slot
    else if (lx !== null && rx !== null) col = (lx + rx) / 2 // two kids: sit between them
    // one kid: sit right above it. Reaching here means exactly one of the two
    // is non-null, which TypeScript cannot see from the branches above.
    else col = (lx !== null ? lx : rx) as number

    pos[id] = { col, row: depth }
    return col
  }
  walk(root, 0)

  // Shift everything so the leftmost node starts at column 0.
  const min = Math.min(...Object.values(pos).map((p) => p.col))
  for (const id of Object.keys(pos)) pos[id].col -= min
  return pos
}

export function layout(tree: Tree, root: string, mode: LayoutMode): Positions {
  return mode === "pyramid" ? pyramidLayout(tree, root) : ladderLayout(tree, root)
}

// y position of every row, given whatever heights the nodes actually measured.
export function rowOffsets(pos: Positions, heights: Heights) {
  const tallest: number[] = []
  for (const id of Object.keys(pos)) {
    const r = pos[id].row
    tallest[r] = Math.max(tallest[r] || NODE_H, heights[id] || NODE_H)
  }
  const y: number[] = []
  let acc = 0
  for (let r = 0; r < tallest.length; r++) {
    y[r] = acc
    acc += (tallest[r] || NODE_H) + ROW_GAP
  }
  return { y, total: acc }
}

export function needsShift(pos: Positions, rowY: number[], heights: Heights, endNode: string | null, cardH: number): boolean {
  if (!endNode || !pos[endNode]) return false
  const top = rowY[pos[endNode].row] - 4
  const bottom = top + cardH
  const endCol = pos[endNode].col
  return Object.keys(pos).some((id) => {
    if (pos[id].col <= endCol) return false
    const y = rowY[pos[id].row]
    return y < bottom && y + (heights[id] || NODE_H) > top
  })
}

export function xOf(pos: Positions, id: string, endCol: number, shift: boolean): number {
  return pos[id].col * COL_W + (shift && pos[id].col > endCol ? CARD_GAP : 0)
}

// Where an edge is drawn depends on the layout, so both shapes live here.
//
//   ladder  – false drops straight down the left gutter;
//             true steps out sideways into the child's left edge.
//   pyramid – the classic square connector: down out of the parent's middle,
//             across, then down into the top of the child.
//
// Either way the edge lands on the child's header, which stays 74px tall
// however far the node is expanded.
export function edgeGeometry(mode: LayoutMode, px: number, pBottom: number, kx: number, kTop: number, isTrue: boolean) {
  if (mode === "pyramid") {
    const from = px + NODE_W / 2
    const to = kx + NODE_W / 2
    const mid = kTop - 20
    return {
      d: `M ${from} ${pBottom} V ${mid} H ${to} V ${kTop}`,
      lx: to + (isTrue ? 8 : -34),
      ly: kTop - 7,
    }
  }
  const sx = isTrue ? px + 26 + 16 : px + 26
  return {
    d: isTrue
      ? `M ${sx} ${pBottom} V ${kTop + HEADER_H / 2} H ${kx}`
      : `M ${sx} ${pBottom} V ${kTop}`,
    lx: sx + 6,
    ly: isTrue ? pBottom + 14 : pBottom + 30,
  }
}
