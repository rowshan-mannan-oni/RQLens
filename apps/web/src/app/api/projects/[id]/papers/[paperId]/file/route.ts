import { isId } from "@/lib/proxy";
import { proxyGet } from "@/lib/proxy-get";

/** The paper's PDF, for the reader. */
export async function GET(
  _req: Request,
  ctx: RouteContext<"/api/projects/[id]/papers/[paperId]/file">,
) {
  const { id, paperId } = await ctx.params;
  if (!isId(id) || !isId(paperId))
    return Response.json({ detail: "Not found" }, { status: 404 });
  return proxyGet(`/projects/${id}/papers/${paperId}/file`, "application/pdf");
}
