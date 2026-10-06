import type { NextRequest } from "next/server";

import { API_URL, apiAuthorization } from "@/lib/api";
import { isId } from "@/lib/proxy";

/** Download the dataset report (Markdown or PDF) as the signed-in user. */
export async function GET(
  req: NextRequest,
  ctx: RouteContext<"/api/projects/[id]/report">,
) {
  const { id } = await ctx.params;
  if (!isId(id)) return Response.json({ detail: "Not found" }, { status: 404 });
  const format =
    req.nextUrl.searchParams.get("format") === "pdf" ? "pdf" : "md";
  const authorization = await apiAuthorization();
  if (!authorization)
    return Response.json({ detail: "Not signed in" }, { status: 401 });

  const res = await fetch(`${API_URL}/projects/${id}/report?format=${format}`, {
    headers: { Authorization: authorization },
    cache: "no-store",
  });
  return new Response(res.body, {
    status: res.status,
    headers: {
      "Content-Type":
        res.headers.get("content-type") ?? "application/octet-stream",
      "Content-Disposition":
        res.headers.get("content-disposition") ??
        `attachment; filename="report.${format}"`,
    },
  });
}
