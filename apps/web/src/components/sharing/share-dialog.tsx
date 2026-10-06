"use client";

import { Copy, LogOut, Trash2, Users } from "lucide-react";
import { useRef, useState, useTransition } from "react";

import {
  addMember,
  changeRole,
  leaveProject,
  listMembers,
  removeMember,
} from "@/app/projects/[id]/sharing-actions";
import type { Member } from "@/lib/types";

const ROLE_HELP = {
  viewer: "Reads everything and comments",
  editor: "Also uploads data, edits questions and tables, runs the AI",
};

export function ShareDialog({
  projectId,
  role,
  myEmail,
}: {
  projectId: number;
  role: "owner" | "editor" | "viewer";
  myEmail: string | null;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [members, setMembers] = useState<Member[] | null>(null);
  const [email, setEmail] = useState("");
  const [newRole, setNewRole] = useState<"viewer" | "editor">("viewer");
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [pending, start] = useTransition();
  const owner = role === "owner";

  const reload = async () => {
    const res = await listMembers(projectId);
    setError(res.error);
    if (res.data) setMembers(res.data);
  };

  return (
    <>
      <button
        type="button"
        className="btn btn-secondary btn-sm"
        onClick={() => {
          dialog.current?.showModal();
          start(reload);
        }}
      >
        <Users className="h-3.5 w-3.5" aria-hidden />
        {owner ? "Share" : "People"}
      </button>
      <dialog
        ref={dialog}
        onClick={(e) => {
          if (e.target === dialog.current) dialog.current.close();
        }}
        className="border-line bg-surface text-fg shadow-pop m-auto w-[calc(100%-2rem)] max-w-lg rounded-2xl border p-0 backdrop:bg-black/40"
      >
        <div className="flex flex-col gap-4 p-6">
          <h2 className="text-lg font-semibold tracking-tight">
            {owner ? "Share this project" : "People on this project"}
          </h2>
          {owner && (
            <form
              className="flex flex-col gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                start(async () => {
                  const res = await addMember(projectId, email, newRole);
                  setError(res.error);
                  if (!res.error) {
                    setEmail("");
                    await reload();
                  }
                });
              }}
            >
              <div className="flex gap-2">
                <input
                  type="email"
                  required
                  className="input flex-1"
                  placeholder="colleague@university.edu"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  aria-label="Email to share with"
                />
                <select
                  className="input w-28"
                  value={newRole}
                  onChange={(e) =>
                    setNewRole(e.target.value as "viewer" | "editor")
                  }
                  aria-label="Role"
                >
                  <option value="viewer">Viewer</option>
                  <option value="editor">Editor</option>
                </select>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={pending}
                >
                  Add
                </button>
              </div>
              <p className="text-subtle text-xs">{ROLE_HELP[newRole]}.</p>
            </form>
          )}
          {error && (
            <p role="alert" className="text-sm text-red-600">
              {error}
            </p>
          )}
          <ul className="divide-line flex flex-col divide-y text-sm">
            {(members ?? []).map((m) => (
              <li
                key={m.id ?? "owner"}
                className="flex items-center gap-3 py-2.5"
              >
                <span className="bg-brand-soft text-brand-fg grid h-8 w-8 shrink-0 place-items-center rounded-full text-xs font-semibold uppercase">
                  {(m.name ?? m.email).slice(0, 1)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">
                    {m.name ?? m.email}
                    {m.email === myEmail && " (you)"}
                  </span>
                  <span className="text-muted block truncate text-xs">
                    {m.email}
                    {!m.joined && " · has not signed in yet"}
                  </span>
                </span>
                {m.role === "owner" || !owner || m.id == null ? (
                  <span className="badge badge-neutral capitalize">
                    {m.role}
                  </span>
                ) : (
                  <select
                    className="input w-24 py-1 text-xs"
                    value={m.role}
                    aria-label={`Role of ${m.email}`}
                    onChange={(e) =>
                      start(async () => {
                        const res = await changeRole(
                          projectId,
                          m.id!,
                          e.target.value as "viewer" | "editor",
                        );
                        setError(res.error);
                        await reload();
                      })
                    }
                  >
                    <option value="viewer">Viewer</option>
                    <option value="editor">Editor</option>
                  </select>
                )}
                {owner && m.id != null && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm hover:text-red-600"
                    aria-label={`Remove ${m.email}`}
                    disabled={pending}
                    onClick={() =>
                      start(async () => {
                        const res = await removeMember(projectId, m.id!);
                        setError(res.error);
                        await reload();
                      })
                    }
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden />
                  </button>
                )}
                {!owner && m.email === myEmail && m.id != null && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm hover:text-red-600"
                    disabled={pending}
                    onClick={() => {
                      if (confirm("Leave this project? Your comments stay."))
                        start(async () => {
                          const res = await leaveProject(projectId, m.id!);
                          setError(res.error);
                        });
                    }}
                  >
                    <LogOut className="h-3.5 w-3.5" aria-hidden />
                    Leave
                  </button>
                )}
              </li>
            ))}
            {members === null && (
              <li className="text-subtle py-3 text-sm">Loading&hellip;</li>
            )}
          </ul>
          {owner && (
            <div className="card-muted flex flex-col gap-2 p-3 text-xs">
              <p className="text-muted">
                No email is sent. Send people the project link; they sign in
                with the address you added.
              </p>
              <button
                type="button"
                className="btn btn-secondary btn-sm w-fit"
                onClick={async () => {
                  await navigator.clipboard.writeText(
                    `${window.location.origin}/projects/${projectId}`,
                  );
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1500);
                }}
              >
                <Copy className="h-3.5 w-3.5" aria-hidden />
                {copied ? "Copied" : "Copy project link"}
              </button>
              <p className="text-subtle">
                AI used by editors counts against your monthly limit.
              </p>
            </div>
          )}
          <div className="flex justify-end">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => dialog.current?.close()}
            >
              Done
            </button>
          </div>
        </div>
      </dialog>
    </>
  );
}
