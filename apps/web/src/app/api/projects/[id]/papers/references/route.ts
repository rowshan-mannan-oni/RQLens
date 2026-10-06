import type { NextRequest } from "next/server";

import { isId, proxyPost } from "@/lib/proxy";

/** Import a BibTeX or RIS file. */
export async function POST(
  req: NextRequest,
  ctx: RouteContext<"/api/projects/[id]/papers/references">,
) {
  const { id } = await ctx.params;
  if (!isId(id)) return Response.json({ detail: "Not found" }, { status: 404 });
  return proxyPost(req, `/projects/${id}/papers/references`);
}
