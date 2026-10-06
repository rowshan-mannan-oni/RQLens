import type { NextRequest } from "next/server";

import { isId } from "@/lib/proxy";
import { proxyGet } from "@/lib/proxy-get";

const FORMATS = new Set(["csv", "xlsx", "md", "bib"]);

/** Download a literature table as CSV, Excel, Markdown or BibTeX. */
export async function GET(
  req: NextRequest,
  ctx: RouteContext<"/api/projects/[id]/review-tables/[tableId]/export">,
) {
  const { id, tableId } = await ctx.params;
  if (!isId(id) || !isId(tableId))
    return Response.json({ detail: "Not found" }, { status: 404 });
  const requested = req.nextUrl.searchParams.get("format") ?? "csv";
  const format = FORMATS.has(requested) ? requested : "csv";
  return proxyGet(
    `/projects/${id}/review-tables/${tableId}/export?format=${format}`,
    "application/octet-stream",
  );
}
