"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import {
  AssistantMessage,
  StepLine,
} from "@/components/chat/assistant-message";
import type { AgentStep, ChatEvent, ChatMessage } from "@/lib/types";

type Pending = {
  question: string;
  accepted: boolean; // saved by the API and added to `messages`
  status: string;
  steps: AgentStep[];
};

export function ChatView({
  projectId,
  chatId,
  initialMessages,
}: {
  projectId: number;
  chatId: number;
  initialMessages: ChatMessage[];
}) {
  const router = useRouter();
  const [messages, setMessages] = useState(initialMessages);
  const [pending, setPending] = useState<Pending | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [messages.length, pending?.steps.length]);

  async function ask(question: string) {
    setError(null);
    setPending({ question, accepted: false, status: "Sending", steps: [] });
    try {
      const res = await fetch(
        `/api/projects/${projectId}/chats/${chatId}/messages`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: question }),
        },
      );
      if (!res.ok || !res.body) {
        const body = await res.json().catch(() => null);
        throw new Error(
          typeof body?.detail === "string"
            ? body.detail
            : `The request failed (${res.status}).`,
        );
      }
      let done = false;
      for await (const event of readEvents(res.body)) {
        if (event.type === "accepted") {
          setMessages((m) => [
            ...m,
            {
              id: event.user_message_id,
              role: "user",
              content: question,
              created_at: new Date().toISOString(),
              kind: null,
              charts: [],
              steps: [],
              queries: [],
              grounding: null,
              usage: null,
              stopped: null,
            },
          ]);
          setDraft("");
          setPending((p) => p && { ...p, accepted: true });
        } else if (event.type === "status") {
          setPending((p) => p && { ...p, status: event.text });
        } else if (event.type === "step") {
          setPending((p) => p && { ...p, steps: [...p.steps, event.step] });
        } else if (event.type === "done") {
          done = true;
          setMessages((m) => [...m, event.message]);
        }
      }
      if (!done)
        throw new Error(
          "The connection closed before the answer arrived. Reload the page to see it once it is saved.",
        );
      router.refresh(); // the chat title in the sidebar may have changed
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(null);
    }
  }

  function submit() {
    const q = draft.trim();
    if (q && !pending) void ask(q);
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="flex flex-col gap-6">
        {messages.length === 0 && !pending && (
          <div className="rounded-lg border border-dashed border-zinc-300 p-4 text-sm text-zinc-600 dark:border-zinc-700 dark:text-zinc-400">
            <p className="font-medium text-zinc-900 dark:text-zinc-100">
              Ask a question about your data.
            </p>
            <p className="mt-1">
              For example: “How many rows have a missing outcome?”, “Does the
              average score differ between groups?” or “Show the number of
              records per month.” Every number in the answer comes from a query
              you can inspect.
            </p>
          </div>
        )}
        {messages.map((m) =>
          m.role === "user" ? (
            <UserBubble key={m.id} text={m.content} />
          ) : (
            <AssistantMessage key={m.id} message={m} />
          ),
        )}
        {pending && (
          <>
            {!pending.accepted && <UserBubble text={pending.question} muted />}
            <div
              className="flex flex-col gap-1.5 text-sm text-zinc-600 dark:text-zinc-400"
              aria-live="polite"
            >
              {pending.steps.map((s, i) => (
                <StepLine key={i} step={s} index={i + 1} />
              ))}
              <p className="flex items-center gap-2">
                <span className="inline-block size-2 animate-pulse rounded-full bg-[var(--chart-1)]" />
                {pending.status}…
              </p>
            </div>
          </>
        )}
        <div ref={bottom} />
      </div>

      {error && (
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-300">
          {error}
        </p>
      )}

      <form
        className="sticky bottom-0 flex items-end gap-2 bg-[var(--background)] py-3"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          rows={2}
          maxLength={4000}
          placeholder="Ask about your data…"
          aria-label="Question"
          className="min-h-[2.75rem] flex-1 resize-y rounded-md border border-zinc-300 bg-transparent px-3 py-2 text-sm dark:border-zinc-700"
        />
        <button
          disabled={!!pending || !draft.trim()}
          className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-40 dark:bg-zinc-100 dark:text-zinc-900"
        >
          {pending ? "Working…" : "Ask"}
        </button>
      </form>
    </div>
  );
}

function UserBubble({ text, muted }: { text: string; muted?: boolean }) {
  return (
    <p
      className={`ml-auto max-w-[85%] rounded-lg bg-zinc-100 px-3 py-2 text-sm whitespace-pre-wrap dark:bg-zinc-800 ${muted ? "opacity-70" : ""}`}
    >
      {text}
    </p>
  );
}

/** Parse a server-sent event stream of `data: {json}` lines. */
async function* readEvents(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<ChatEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let end: number;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const data = chunk
        .split("\n")
        .filter((l) => l.startsWith("data: "))
        .map((l) => l.slice(6))
        .join("\n");
      if (data) yield JSON.parse(data) as ChatEvent;
    }
  }
}
