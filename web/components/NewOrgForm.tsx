"use client";

import { useState, useTransition } from "react";
import { createOrgAction, type ActionResult } from "@/lib/actions";

/** One form, three fields: the whole "add a new org" path. */
export default function NewOrgForm({ defaultOwner }: { defaultOwner: string }) {
  const [result, setResult] = useState<ActionResult | null>(null);
  const [pending, start] = useTransition();

  return (
    <div className="surface p-6">
      <h2 className="font-medium">New organisation</h2>
      <p className="note mt-1">
        The id is what appears in the address bar, so keep it short and
        lowercase — <code>sangath</code> gives <code>/sangath</code>.
      </p>

      <form
        className="mt-4 flex flex-wrap gap-2"
        action={(form) =>
          start(async () => {
            const r = await createOrgAction(form);
            setResult(r);
            if (r.ok) (document.getElementById("new-org") as HTMLFormElement)?.reset();
          })
        }
        id="new-org"
      >
        <input name="orgId" required placeholder="sangath" className="field w-[160px]" />
        <input name="name" placeholder="Sangath" className="field w-[200px]" />
        <input
          name="owner"
          type="email"
          defaultValue={defaultOwner}
          placeholder="first owner's email"
          className="field flex-1 min-w-[240px]"
        />
        <button className="btn-base" disabled={pending}>
          {pending ? "Creating…" : "Create"}
        </button>
      </form>

      {result && (
        <p
          className="mt-3 text-[12.5px]"
          style={{ color: result.ok ? "var(--good)" : "var(--bad)" }}
        >
          {result.message}
        </p>
      )}
    </div>
  );
}
