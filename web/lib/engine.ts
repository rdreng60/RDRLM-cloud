import "server-only";

/**
 * The Python engine, over HTTP.
 *
 * The engine stays Python because that is where Algorithms 1-7 live, tested.
 * Only this server talks to it — never a browser — so it is protected by a
 * shared secret rather than by user auth, and the signed-in clinician's email
 * rides along as the actor that ends up in the event log.
 */

const BASE = process.env.ENGINE_URL ?? "http://127.0.0.1:8000";
const KEY = process.env.ENGINE_API_KEY ?? "";

export type TreeNode = {
  left: string | null;
  right: string | null;
  conds: string[];
  conclusion: string;
  short_if: string;
  summary: string;
  cases: string[];
  number: number;
  created_by: string | null;
  status: "confirmed" | "pending";
};

export type Tree = Record<string, TreeNode>;

export type ConditionResult = { condition: string; result: boolean };

export type Step = {
  number: number;
  result: boolean;
  conclusion: string;
  conditions: ConditionResult[];
};

export type Interpretation = {
  tree: Tree;
  root: string | null;
  trace: [string, boolean][];
  detail: Step[];
  end_node: number | null;
  verdict_node: number | null;
  conclusion: string | null;
};

export type Rejection = {
  condition: string;
  reason: "false_of_new" | "true_of_stored";
  case_index: number | null;
};

/** The model could not be reached, or its answer could not be read. */
export class EngineError extends Error {
  constructor(
    message: string,
    readonly operation?: string,
    readonly status?: number
  ) {
    super(message);
  }
}

async function call<T>(
  path: string,
  actor: string,
  init?: { method?: string; body?: unknown }
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method: init?.method ?? "GET",
      headers: {
        "content-type": "application/json",
        "x-api-key": KEY,
        "x-actor": actor,
      },
      body: init?.body ? JSON.stringify(init.body) : undefined,
      cache: "no-store",
    });
  } catch (cause) {
    throw new EngineError(
      "The engine is not reachable. Is the Python service running?"
    );
  }

  if (!res.ok) {
    let detail: unknown = await res.text();
    try {
      detail = JSON.parse(detail as string);
    } catch {
      /* plain text is fine */
    }
    const inner = (detail as { detail?: { detail?: string; operation?: string } })
      ?.detail;
    if (inner?.detail) {
      // A failed model call is never read as an answer: nothing was changed,
      // and no branch was taken on a guess.
      throw new EngineError(
        `The model could not be reached (${inner.operation ?? "unknown"}). ` +
          `Nothing has been changed. ${inner.detail}`,
        inner.operation,
        res.status
      );
    }
    throw new EngineError(
      typeof detail === "string" ? detail : JSON.stringify(detail),
      undefined,
      res.status
    );
  }

  return (await res.json()) as T;
}

export const engine = {
  summarize: (actor: string, transcript: string) =>
    call<{ summary: string }>("/summarize", actor, {
      method: "POST",
      body: { transcript },
    }),

  tree: (actor: string, org: string) =>
    call<{ tree: Tree; root: string | null; last_vertex_number: number }>(
      `/orgs/${org}/tree`,
      actor
    ),

  /** Algorithm 1, with Algorithm 3 inside it: one model call per conjunct. */
  interpret: (actor: string, org: string, summary: string, source_file: string) =>
    call<Interpretation>(`/orgs/${org}/interpret`, actor, {
      method: "POST",
      body: { summary, source_file },
    }),

  /** Algorithm 5: the model proposes, then every candidate is verified. */
  differences: (
    actor: string,
    org: string,
    summary: string,
    verdict_node: number | null,
    source_file: string
  ) =>
    call<{ kept: string[]; rejected: Rejection[]; stored_cases: string[] }>(
      `/orgs/${org}/differences`,
      actor,
      { method: "POST", body: { summary, verdict_node, source_file } }
    ),

  /** Algorithms 6 + 7 (the gate), then Algorithm 4 (where it goes). */
  addRule: (
    actor: string,
    org: string,
    body: {
      summary: string;
      source_file: string;
      end_node: number | null;
      verdict_node: number | null;
      conditions: string[];
      manual: string[];
      conclusion: string;
    }
  ) =>
    call<{ ok: boolean; problem?: string; stale?: boolean; number?: number; side?: string }>(
      `/orgs/${org}/rules`,
      actor,
      { method: "POST", body }
    ),

  agree: (
    actor: string,
    org: string,
    body: { summary: string; source_file: string; verdict_node: number }
  ) => call<{ ok: boolean }>(`/orgs/${org}/agree`, actor, { method: "POST", body }),

  undo: (actor: string, org: string) =>
    call<{ ok: boolean; message: string }>(`/orgs/${org}/undo`, actor, {
      method: "POST",
      body: {},
    }),

  events: (actor: string, org: string, limit = 200) =>
    call<{ events: EventRow[] }>(`/orgs/${org}/events?limit=${limit}`, actor),
};

export type EventRow = {
  at: string;
  action: string;
  source_file: string | null;
  true_vertex: number | null;
  eval_vertex: number | null;
  condition_type: string | null;
  actor: string | null;
  detail: string | null;
};
