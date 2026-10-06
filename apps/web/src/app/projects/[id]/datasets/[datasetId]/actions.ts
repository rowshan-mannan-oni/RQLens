"use server";

import { revalidatePath } from "next/cache";

import { auth } from "@/auth";
import { apiFetch } from "@/lib/api";

// The API checks that the signed-in user owns the project, so the bound IDs need no extra
// checks here beyond being signed in.

export async function updateDescription(
  projectId: number,
  datasetId: number,
  columnId: number,
  formData: FormData,
) {
  const session = await auth();
  if (!session?.user) throw new Error("Unauthorized");

  const clear = formData.get("intent") === "clear";
  const description = clear
    ? null
    : String(formData.get("description") ?? "").trim() || null;
  await apiFetch(
    `/projects/${projectId}/datasets/${datasetId}/columns/${columnId}`,
    { method: "PATCH", body: JSON.stringify({ description }) },
  );
  revalidatePath(`/projects/${projectId}/datasets/${datasetId}`);
}

export async function redescribe(projectId: number, datasetId: number) {
  const session = await auth();
  if (!session?.user) throw new Error("Unauthorized");

  await apiFetch(`/projects/${projectId}/datasets/${datasetId}/describe`, {
    method: "POST",
  });
  revalidatePath(`/projects/${projectId}/datasets/${datasetId}`);
}
