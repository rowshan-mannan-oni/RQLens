import type { NextRequest } from "next/server";

import { isId, proxyPost } from "@/lib/proxy";

/** Upload one PDF (with its folder path when part of a folder upload). */
export async function POST(
  req: NextRequest,
  ctx: RouteContext<"/api/projects/[id]/papers">,
) {
  const { id } = await ctx.params;
  if (!isId(id)) return Response.json({ detail: "Not found" }, { status: 404 });
  return proxyPost(req, `/projects/${id}/papers`);
}
