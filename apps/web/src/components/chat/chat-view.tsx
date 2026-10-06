"use client";

import { LoaderCircle, SendHorizontal, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import {
  AssistantMessage,
  StepLine,
} from "@/components/chat/assistant-message";
import type { AgentStep, ChatEvent, ChatMessage } from "@/lib/types";

const EXAMPLES = [
  "How many rows have a missing outcome?",
  "Does the average differ between groups?",
  "Show the number of records per month.",
  "Which columns are most strongly related?",
];

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
          <div className="flex flex-col items-center gap-4 py-8 text-center">
            <span className="bg-brand-soft text-brand-fg grid h-11 w-11 place-items-center rounded-2xl">
              <Sparkles className="h-5 w-5" aria-hidden />
            </span>
            <div>
              <p className="font-medium">Ask a question about your data</p>
              <p className="text-muted mt-1 text-sm">
                Every number in the answer comes from a query you can inspect.
              </p>
            </div>
            <div className="flex max-w-xl flex-wrap justify-center gap-2">
              {EXAMPLES.map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => setDraft(q)}
                  className="border-line bg-surface-2 text-muted hover:border-brand/50 hover:text-fg rounded-full border px-3 py-1.5 text-xs transition"
                >
                  {q}
                </button>
              ))}
            </div>
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
              className="text-muted flex flex-col gap-1.5 text-sm"
              aria-live="polite"
            >
              {pending.steps.map((s, i) => (
                <StepLine key={i} step={s} index={i + 1} />
              ))}
              <p className="flex items-center gap-2">
                <LoaderCircle
                  className="text-brand h-3.5 w-3.5 animate-spin"
                  aria-hidden
                />
                {pending.status}…
              </p>
            </div>
          </>
        )}
        <div ref={bottom} />
      </div>

      {error && (
        <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
          {error}
        </p>
      )}

      <form
        className="border-line bg-surface/95 sticky bottom-0 -mx-5 -mb-5 border-t px-5 py-4 backdrop-blur"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div className="border-line-strong bg-surface focus-within:border-brand flex items-end gap-2 rounded-xl border p-2 shadow-xs transition focus-within:ring-4 focus-within:ring-(--ring)">
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
            placeholder="Ask about your data… (Enter to send, Shift+Enter for a new line)"
            aria-label="Question"
            className="placeholder:text-subtle max-h-48 min-h-[2.75rem] flex-1 resize-none bg-transparent px-2 py-1.5 text-sm outline-none"
          />
          <button
            disabled={!!pending || !draft.trim()}
            className="btn btn-primary h-9 w-9 shrink-0 rounded-lg p-0"
            aria-label={pending ? "Working" : "Ask"}
          >
            {pending ? (
              <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <SendHorizontal className="h-4 w-4" aria-hidden />
            )}
          </button>
        </div>
      </form>
    </div>
  );
}

function UserBubble({ text, muted }: { text: string; muted?: boolean }) {
  return (
    <p
      className={`bg-brand ml-auto max-w-[85%] rounded-2xl rounded-br-md px-4 py-2.5 text-sm whitespace-pre-wrap text-white shadow-sm dark:text-[#0b0c0f] ${muted ? "opacity-70" : ""}`}
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
