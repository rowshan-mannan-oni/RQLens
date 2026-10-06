"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { apiFetch } from "@/lib/api";

export async function createProject(formData: FormData) {
  const session = await auth();
  if (!session?.user) throw new Error("Unauthorized");

  const title = String(formData.get("title") ?? "").trim();
  const topic = String(formData.get("topic") ?? "").trim() || null;
  if (!title) return;

  await apiFetch("/projects", {
    method: "POST",
    body: JSON.stringify({ title, topic }),
  });
  revalidatePath("/projects");
}

export async function createSampleProject() {
  const session = await auth();
  if (!session?.user) throw new Error("Unauthorized");
  const project = await apiFetch<{ id: number }>("/projects/sample", {
    method: "POST",
  });
  redirect(`/projects/${project.id}`);
}
