import { MessageSquare, Plus, ShieldCheck, Trash2 } from "lucide-react";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { ChatView } from "@/components/chat/chat-view";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { ApiError, apiFetch } from "@/lib/api";
import { createChat, deleteChat } from "../actions";
import type { Chat, ChatDetail, Dataset, Project } from "@/lib/types";

export default async function ChatPage(
  props: PageProps<"/projects/[id]/chat/[chatId]">,
) {
  const session = await auth();
  if (!session?.user) redirect("/");
  const { id, chatId } = await props.params;

  let project: Project;
  let chats: Chat[];
  let detail: ChatDetail;
  let datasets: Dataset[];
  try {
    [project, chats, detail, datasets] = await Promise.all([
      apiFetch<Project>(`/projects/${id}`),
      apiFetch<Chat[]>(`/projects/${id}/chats`),
      apiFetch<ChatDetail>(`/projects/${id}/chats/${chatId}`),
      apiFetch<Dataset[]>(`/projects/${id}/datasets`),
    ]);
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 422))
      notFound();
    throw e;
  }
  const ready = datasets.filter((d) => d.status === "ready");

  return (
    <div className="grid gap-6 md:grid-cols-[15rem_minmax(0,1fr)]">
      <aside className="flex flex-col gap-3 text-sm md:sticky md:top-20 md:self-start">
        <form action={createChat.bind(null, project.id)}>
          <button className="btn btn-secondary w-full justify-start">
            <Plus className="h-4 w-4" aria-hidden />
            New chat
          </button>
        </form>
        <nav aria-label="Chats" className="flex flex-col gap-1">
          <p className="eyebrow px-2 pt-2 pb-1">Recent</p>
          <ul className="flex max-h-48 flex-col gap-0.5 overflow-y-auto md:max-h-[60vh]">
            {chats.map((c) => (
              <li key={c.id}>
                <Link
                  href={`/projects/${project.id}/chat/${c.id}`}
                  aria-current={c.id === detail.chat.id ? "page" : undefined}
                  className="text-muted hover:bg-surface-3 hover:text-fg aria-[current=page]:bg-brand-soft aria-[current=page]:text-brand-fg flex items-center gap-2 truncate rounded-lg px-2 py-1.5 transition-colors aria-[current=page]:font-medium"
                >
                  <MessageSquare
                    className="h-3.5 w-3.5 shrink-0 opacity-70"
                    aria-hidden
                  />
                  <span className="truncate">{c.title}</span>
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </aside>

      <section className="card flex min-w-0 flex-col">
        <header className="border-line flex items-start justify-between gap-4 border-b px-5 py-4">
          <div className="min-w-0">
            <h2 className="truncate font-semibold tracking-tight">
              {detail.chat.title}
            </h2>
            <p className="text-subtle mt-0.5 flex items-start gap-1.5 text-xs">
              <ShieldCheck className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
              <span>
                {ready.length === 0
                  ? "No datasets are ready yet."
                  : `Tables: ${ready.map((d) => d.table_name).join(", ")}. `}
                The AI sees the schema, column statistics
                {project.share_samples ? ", masked example values" : ""} and up
                to 50 rows of each query result; personal-data columns are
                masked.
              </span>
            </p>
          </div>
          <ConfirmDialog
            triggerLabel={
              <>
                <Trash2 className="h-3.5 w-3.5" aria-hidden />
                <span className="sr-only sm:not-sr-only">Delete</span>
              </>
            }
            triggerClassName="btn btn-sm btn-ghost"
            title={`Delete the chat “${detail.chat.title}”?`}
            confirmLabel="Delete chat"
            action={deleteChat.bind(null, project.id, detail.chat.id)}
          >
            <p>The questions and answers in this chat are removed.</p>
          </ConfirmDialog>
        </header>
        <div className="p-5">
          <ChatView
            key={detail.chat.id}
            projectId={project.id}
            chatId={detail.chat.id}
            initialMessages={detail.messages}
          />
        </div>
      </section>
    </div>
  );
}
