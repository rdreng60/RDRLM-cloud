"use client";

import { useState, useTransition } from "react";
import type { Member, Role } from "@/lib/orgs";
import type { ActionResult } from "@/lib/actions";

/**
 * The allow list, as a screen.
 *
 * Adding somebody is one field and one button, because it is the thing you do
 * most often and the thing a new clinician is blocked on.
 */
export default function MemberPanel({
  orgId,
  orgName,
  members,
  me,
  add,
  remove,
}: {
  orgId: string;
  orgName: string;
  members: Member[];
  me: string;
  add: (orgId: string, form: FormData) => Promise<ActionResult>;
  remove: (orgId: string, email: string) => Promise<ActionResult>;
}) {
  const [result, setResult] = useState<ActionResult | null>(null);
  const [pending, start] = useTransition();

  return (
    <div className="surface p-6">
      <h2 className="font-medium">Who can open {orgName}</h2>
      <p className="note mt-1">
        Anyone on this list can sign in with Google and add to this tree. Anyone
        not on it sees nothing, whatever link they are sent.
      </p>

      <form
        className="mt-5 flex flex-wrap gap-2"
        action={(form) =>
          start(async () => {
            const r = await add(orgId, form);
            setResult(r);
          })
        }
      >
        <input
          name="email"
          type="email"
          required
          placeholder="clinician@example.com"
          className="field flex-1 min-w-[240px]"
        />
        <select name="role" className="field w-[150px]" defaultValue="clinician">
          <option value="clinician">clinician</option>
          <option value="owner">owner</option>
        </select>
        <button className="btn-base" disabled={pending}>
          {pending ? "Adding…" : "Add"}
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

      <ul className="mt-6 flex flex-col divide-y divide-[var(--border)]">
        {members.map((m) => (
          <li key={m.email} className="flex items-center justify-between py-2.5">
            <div>
              <span className="text-[13px]">{m.email}</span>
              {m.email === me && <span className="note"> · you</span>}
              <div className="note">
                {m.role}
                {m.addedBy ? ` · added by ${m.addedBy}` : ""}
              </div>
            </div>
            <button
              className="btn-base !px-3 !py-1.5 !text-[12px]"
              disabled={pending || m.email === me}
              title={m.email === me ? "You cannot remove yourself" : "Remove access"}
              onClick={() =>
                start(async () => {
                  const r = await remove(orgId, m.email);
                  setResult(r);
                })
              }
            >
              Remove
            </button>
          </li>
        ))}
        {!members.length && <li className="note py-3">Nobody yet.</li>}
      </ul>
    </div>
  );
}
