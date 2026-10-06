import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { ApiError, apiFetch } from "@/lib/api";
import { createChat } from "./actions";
import type { Chat, Project } from "@/lib/types";

/** Opens the most recent chat, or offers to start the first one. */
export default async function ChatIndexPage(
  props: PageProps<"/projects/[id]/chat">,
) {
  const session = await auth();
  if (!session?.user) redirect("/");
  const { id } = await props.params;

  let project: Project;
  let chats: Chat[];
  try {
    [project, chats] = await Promise.all([
      apiFetch<Project>(`/projects/${id}`),
      apiFetch<Chat[]>(`/projects/${id}/chats`),
    ]);
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 422))
      notFound();
    throw e;
  }
  if (chats.length > 0) redirect(`/projects/${id}/chat/${chats[0].id}`);

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-10">
      <Link
        href={`/projects/${project.id}`}
        className="text-sm text-zinc-500 hover:underline"
      >
        ← {project.title}
      </Link>
      <h1 className="text-2xl font-semibold tracking-tight">Chat</h1>
      <p className="text-zinc-600 dark:text-zinc-400">
        Ask questions about the datasets in this project. The assistant answers
        by running read-only queries and statistical tests, and shows each one.
      </p>
      <form action={createChat.bind(null, project.id)}>
        <button className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white dark:bg-zinc-100 dark:text-zinc-900">
          Start a chat
        </button>
      </form>
    </main>
  );
}
