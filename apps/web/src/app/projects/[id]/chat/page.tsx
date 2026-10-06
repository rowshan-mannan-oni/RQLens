import { MessagesSquare, Plus } from "lucide-react";
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
    <div className="card mx-auto flex max-w-xl flex-col items-center gap-3 px-6 py-12 text-center">
      <span className="bg-brand-soft text-brand-fg grid h-12 w-12 place-items-center rounded-2xl">
        <MessagesSquare className="h-6 w-6" aria-hidden />
      </span>
      <h2 className="text-xl font-semibold tracking-tight">
        Chat with your data
      </h2>
      <p className="lead max-w-md">
        Ask questions about the datasets in this project. The assistant answers
        by running read-only queries and statistical tests, and shows each one.
      </p>
      <form action={createChat.bind(null, project.id)} className="mt-2">
        <button className="btn btn-primary">
          <Plus className="h-4 w-4" aria-hidden />
          Start a chat
        </button>
      </form>
    </div>
  );
}
