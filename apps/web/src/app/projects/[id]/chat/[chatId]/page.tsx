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
    <main className="mx-auto grid w-full max-w-6xl gap-6 px-4 py-6 md:grid-cols-[14rem_minmax(0,1fr)]">
      <aside className="flex flex-col gap-3 text-sm">
        <Link
          href={`/projects/${project.id}`}
          className="text-zinc-500 hover:underline"
        >
          ← {project.title}
        </Link>
        <form action={createChat.bind(null, project.id)}>
          <button className="w-full rounded-md border border-zinc-300 px-3 py-1.5 text-left font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800">
            + New chat
          </button>
        </form>
        <nav aria-label="Chats">
          <ul className="flex max-h-48 flex-col gap-0.5 overflow-y-auto md:max-h-none">
            {chats.map((c) => (
              <li key={c.id}>
                <Link
                  href={`/projects/${project.id}/chat/${c.id}`}
                  aria-current={c.id === detail.chat.id ? "page" : undefined}
                  className="block truncate rounded-md px-2 py-1 hover:bg-zinc-100 aria-[current=page]:bg-zinc-100 aria-[current=page]:font-medium dark:hover:bg-zinc-800 dark:aria-[current=page]:bg-zinc-800"
                >
                  {c.title}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </aside>

      <section className="flex min-w-0 flex-col gap-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="truncate text-xl font-semibold tracking-tight">
              {detail.chat.title}
            </h1>
            <p className="text-xs text-zinc-500">
              {ready.length === 0
                ? "No datasets are ready yet."
                : `Tables: ${ready.map((d) => d.table_name).join(", ")}`}
              {" · "}The AI sees the schema, column statistics,
              {project.share_samples ? " masked example values" : ""} and up to
              50 rows of each query result; personal-data columns are masked.
            </p>
          </div>
          <ConfirmDialog
            triggerLabel="Delete chat"
            title={`Delete the chat “${detail.chat.title}”?`}
            confirmLabel="Delete chat"
            action={deleteChat.bind(null, project.id, detail.chat.id)}
          >
            <p>The questions and answers in this chat are removed.</p>
          </ConfirmDialog>
        </div>
        <ChatView
          key={detail.chat.id}
          projectId={project.id}
          chatId={detail.chat.id}
          initialMessages={detail.messages}
        />
      </section>
    </main>
  );
}
