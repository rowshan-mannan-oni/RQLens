"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import type { ActionState } from "@/components/confirm-dialog";
import { ApiError, apiFetch } from "@/lib/api";
import type { Chat } from "@/lib/types";

async function requireUser() {
  const session = await auth();
  if (!session?.user) throw new Error("Unauthorized");
}

export async function createChat(projectId: number) {
  await requireUser();
  const chat = await apiFetch<Chat>(`/projects/${projectId}/chats`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  redirect(`/projects/${projectId}/chat/${chat.id}`);
}

export async function deleteChat(
  projectId: number,
  chatId: number,
  _state: ActionState,
  _formData: FormData,
): Promise<ActionState> {
  await requireUser();
  try {
    await apiFetch(`/projects/${projectId}/chats/${chatId}`, {
      method: "DELETE",
    });
  } catch (e) {
    if (e instanceof ApiError)
      return { error: `Could not delete (${e.status}).` };
    throw e;
  }
  revalidatePath(`/projects/${projectId}/chat`);
  redirect(`/projects/${projectId}/chat`);
}
