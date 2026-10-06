"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import type { ActionState } from "@/components/confirm-dialog";
import { ApiError, apiFetch } from "@/lib/api";

// The API checks that the signed-in user owns the project, so the bound IDs need no extra
// checks here beyond being signed in.

async function requireUser() {
  const session = await auth();
  if (!session?.user) throw new Error("Unauthorized");
}

function message(e: ApiError): string {
  try {
    const body = JSON.parse(e.message);
    if (typeof body.detail === "string") return body.detail;
  } catch {}
  return `Something went wrong (${e.status}).`;
}

export async function setShareSamples(projectId: number, value: boolean) {
  await requireUser();
  await apiFetch(`/projects/${projectId}`, {
    method: "PATCH",
    body: JSON.stringify({ share_samples: value }),
  });
  revalidatePath(`/projects/${projectId}`);
}

export async function deleteDataset(
  projectId: number,
  datasetId: number,
  redirectToProject: boolean,
  _state: ActionState,
  _formData: FormData,
): Promise<ActionState> {
  await requireUser();
  try {
    await apiFetch(`/projects/${projectId}/datasets/${datasetId}`, {
      method: "DELETE",
    });
  } catch (e) {
    if (e instanceof ApiError) return { error: message(e) };
    throw e;
  }
  revalidatePath(`/projects/${projectId}`);
  if (redirectToProject) redirect(`/projects/${projectId}`);
  return { error: null };
}

export async function deleteProject(
  projectId: number,
  _state: ActionState,
  _formData: FormData,
): Promise<ActionState> {
  await requireUser();
  try {
    await apiFetch(`/projects/${projectId}`, { method: "DELETE" });
  } catch (e) {
    if (e instanceof ApiError) return { error: message(e) };
    throw e;
  }
  revalidatePath("/projects");
  redirect("/projects");
}
