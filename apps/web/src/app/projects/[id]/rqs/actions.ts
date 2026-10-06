"use server";

import { revalidatePath } from "next/cache";

import { auth } from "@/auth";
import type { ActionState } from "@/components/confirm-dialog";
import { ApiError, apiFetch } from "@/lib/api";
import type { RQMapping } from "@/lib/types";

// The API checks that the signed-in user owns the project and question.

async function requireUser() {
  const session = await auth();
  if (!session?.user) throw new Error("Unauthorized");
}

function message(e: ApiError): string {
  try {
    const { detail } = JSON.parse(e.message);
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail?.problems)) return detail.problems.join(" ");
    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
  } catch {}
  return `Something went wrong (${e.status}).`;
}

const path = (projectId: number) => `/projects/${projectId}/rqs`;

async function call(
  projectId: number,
  url: string,
  init: RequestInit,
): Promise<ActionState> {
  await requireUser();
  try {
    await apiFetch(url, init);
  } catch (e) {
    if (e instanceof ApiError) return { error: message(e) };
    throw e;
  }
  revalidatePath(path(projectId));
  return { error: null };
}

export async function addQuestion(
  projectId: number,
  _state: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const text = String(formData.get("text") ?? "").trim();
  if (text.length < 5)
    return { error: "Write a question of at least 5 characters." };
  return call(projectId, path(projectId), {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export async function updateText(
  projectId: number,
  rqId: number,
  text: string,
): Promise<ActionState> {
  return call(projectId, `${path(projectId)}/${rqId}`, {
    method: "PATCH",
    body: JSON.stringify({ text }),
  });
}

export async function saveMapping(
  projectId: number,
  rqId: number,
  mapping: RQMapping,
): Promise<ActionState> {
  return call(projectId, `${path(projectId)}/${rqId}/mapping`, {
    method: "PUT",
    body: JSON.stringify(mapping),
  });
}

export async function reassess(
  projectId: number,
  rqId: number,
  remap: boolean,
) {
  await call(projectId, `${path(projectId)}/${rqId}/assess`, {
    method: "POST",
    body: JSON.stringify({ remap }),
  });
}

export async function deleteQuestion(
  projectId: number,
  rqId: number,
  _state: ActionState,
  _formData: FormData,
): Promise<ActionState> {
  return call(projectId, `${path(projectId)}/${rqId}`, { method: "DELETE" });
}

export async function requestSuggestions(projectId: number) {
  await call(projectId, `${path(projectId)}/suggestions`, { method: "POST" });
}

export async function addSuggestion(projectId: number, text: string) {
  await call(projectId, path(projectId), {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export async function applyRewording(
  projectId: number,
  rqId: number,
  text: string,
) {
  await updateText(projectId, rqId, text);
}
