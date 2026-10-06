"use client";

import { MessageSquare } from "lucide-react";
import { useState } from "react";

import { CommentThread } from "@/components/sharing/comment-thread";
import type { ProjectComment } from "@/lib/types";

/** A "Comments (n)" button that opens the item's thread below it. */
export function CommentsToggle({
  projectId,
  rqId,
  comments,
  canModerate,
}: {
  projectId: number;
  rqId: number;
  comments: ProjectComment[];
  canModerate: boolean;
}) {
  const open = comments.filter((c) => !c.resolved).length;
  const [shown, setShown] = useState(false);
  return (
    <>
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        aria-expanded={shown}
        onClick={() => setShown(!shown)}
      >
        <MessageSquare className="h-3.5 w-3.5" aria-hidden />
        Comments{open > 0 && <span className="badge badge-brand">{open}</span>}
      </button>
      {shown && (
        <div className="order-last basis-full pt-2">
          <CommentThread
            projectId={projectId}
            targetType="rq"
            targetId={rqId}
            comments={comments}
            canModerate={canModerate}
            placeholder="Comment on this question"
            compact
          />
        </div>
      )}
    </>
  );
}
