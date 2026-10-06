import type { NextRequest } from "next/server";

import { isId, proxyPost } from "@/lib/proxy";

export async function POST(
  req: NextRequest,
  ctx: RouteContext<"/api/projects/[id]/datasets/[datasetId]/dictionary">,
) {
  const { id, datasetId } = await ctx.params;
  if (!isId(id) || !isId(datasetId)) {
    return Response.json({ detail: "Not found" }, { status: 404 });
  }
  return proxyPost(req, `/projects/${id}/datasets/${datasetId}/dictionary`);
}
