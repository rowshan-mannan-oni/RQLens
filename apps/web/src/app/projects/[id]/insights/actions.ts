"use server";

import { revalidatePath } from "next/cache";

import { auth } from "@/auth";
import { ApiError, apiFetch } from "@/lib/api";

export async function generateInsights(projectId: number) {
  const session = await auth();
  if (!session?.user) throw new Error("Unauthorized");
  try {
    await apiFetch(`/projects/${projectId}/insights`, { method: "POST" });
  } catch (e) {
    // 409: already running or no data; the page shows the current state either way.
    if (!(e instanceof ApiError && e.status === 409)) throw e;
  }
  revalidatePath(`/projects/${projectId}/insights`);
}
