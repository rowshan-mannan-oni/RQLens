"use server";

import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { ApiError, apiFetch } from "@/lib/api";

export type CombineState = { error: string | null };

function detail(e: ApiError): string {
  try {
    const body = JSON.parse(e.message);
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail
        .map((d: { msg?: string }) => d.msg?.replace(/^Value error, /, ""))
        .join(" ");
    }
  } catch {}
  return `Could not create the dataset (${e.status}).`;
}

export async function createCombined(
  projectId: number,
  datasetIds: number[],
  _prev: CombineState,
  formData: FormData,
): Promise<CombineState> {
  const session = await auth();
  if (!session?.user) throw new Error("Unauthorized");

  const mode = formData.get("mode");
  const name = String(formData.get("name") ?? "").trim();
  const payload =
    mode === "join"
      ? {
          name,
          mode,
          left: {
            dataset_id: Number(formData.get("left_dataset")),
            column: String(formData.get("left_column") ?? ""),
          },
          right: {
            dataset_id: Number(formData.get("right_dataset")),
            column: String(formData.get("right_column") ?? ""),
          },
          how: formData.get("how") === "inner" ? "inner" : "left",
        }
      : { name, mode: "stack", dataset_ids: datasetIds };

  try {
    await apiFetch(`/projects/${projectId}/combined`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  } catch (e) {
    if (e instanceof ApiError) return { error: detail(e) };
    throw e;
  }
  redirect(`/projects/${projectId}`);
}
