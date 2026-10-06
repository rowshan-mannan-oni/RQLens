"use client";

import { Check, MessageSquare, RotateCcw, Trash2 } from "lucide-react";
import { useState, useTransition } from "react";

import {
  addComment,
  deleteComment,
  resolveComment,
} from "@/app/projects/[id]/sharing-actions";
import type { CommentTarget, ProjectComment } from "@/lib/types";

function when(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** A comment thread on the project or one of its items. Everyone on the project can comment. */
export function CommentThread({
  projectId,
  targetType,
  targetId,
  comments,
  canModerate,
  placeholder = "Add a comment",
  compact,
}: {
  projectId: number;
  targetType: CommentTarget;
  targetId: number | null;
  comments: ProjectComment[];
  canModerate: boolean; // editors and the owner resolve anyone's comments
  placeholder?: string;
  compact?: boolean;
}) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [showResolved, setShowResolved] = useState(false);
  const [pending, start] = useTransition();
  const open = comments.filter((c) => !c.resolved);
  const resolved = comments.filter((c) => c.resolved);
  const shown = showResolved ? comments : open;

  const run = (fn: () => Promise<{ error: string | null }>) =>
    start(async () => setError((await fn()).error));

  return (
    <div className="flex flex-col gap-3">
      {shown.length > 0 && (
        <ul className="flex flex-col gap-2.5">
          {shown.map((c) => (
            <li
              key={c.id}
              className={`group/c flex flex-col gap-0.5 text-sm ${c.resolved ? "opacity-60" : ""}`}
            >
              <div className="flex items-baseline gap-2">
                <span className="font-medium">{c.author}</span>
                <span className="text-subtle text-xs">
                  {when(c.created_at)}
                  {c.edited_at && " · edited"}
                  {c.resolved && " · resolved"}
                </span>
                <span className="ml-auto flex gap-0.5 opacity-0 transition group-focus-within/c:opacity-100 group-hover/c:opacity-100">
                  {(c.mine || canModerate) && (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm px-1.5"
                      disabled={pending}
                      title={c.resolved ? "Reopen" : "Resolve"}
                      aria-label={
                        c.resolved ? "Reopen comment" : "Resolve comment"
                      }
                      onClick={() =>
                        run(() => resolveComment(projectId, c.id, !c.resolved))
                      }
                    >
                      {c.resolved ? (
                        <RotateCcw className="h-3.5 w-3.5" aria-hidden />
                      ) : (
                        <Check className="h-3.5 w-3.5" aria-hidden />
                      )}
                    </button>
                  )}
                  {c.mine && (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm px-1.5 hover:text-red-600"
                      disabled={pending}
                      aria-label="Delete comment"
                      onClick={() => {
                        if (confirm("Delete this comment?"))
                          run(() => deleteComment(projectId, c.id));
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" aria-hidden />
                    </button>
                  )}
                </span>
              </div>
              <p className="text-muted whitespace-pre-wrap">{c.body}</p>
            </li>
          ))}
        </ul>
      )}
      {resolved.length > 0 && (
        <button
          type="button"
          className="link w-fit text-xs"
          onClick={() => setShowResolved(!showResolved)}
        >
          {showResolved
            ? "Hide resolved"
            : `Show ${resolved.length} resolved comment${resolved.length === 1 ? "" : "s"}`}
        </button>
      )}
      <form
        className="flex flex-col gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          const body = text.trim();
          if (!body) return;
          start(async () => {
            const res = await addComment(projectId, targetType, targetId, body);
            setError(res.error);
            if (!res.error) setText("");
          });
        }}
      >
        <textarea
          className="input text-sm"
          rows={compact ? 2 : 3}
          maxLength={5000}
          placeholder={placeholder}
          value={text}
          onChange={(e) => setText(e.target.value)}
          aria-label={placeholder}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey))
              e.currentTarget.form?.requestSubmit();
          }}
        />
        <div className="flex items-center gap-2">
          <button
            type="submit"
            className="btn btn-secondary btn-sm"
            disabled={pending || !text.trim()}
          >
            <MessageSquare className="h-3.5 w-3.5" aria-hidden />
            Comment
          </button>
          {error && (
            <p role="alert" className="text-xs text-red-600">
              {error}
            </p>
          )}
        </div>
      </form>
    </div>
  );
}
