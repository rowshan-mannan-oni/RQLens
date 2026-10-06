import type { NextRequest } from "next/server";

import { isId, proxyPost } from "@/lib/proxy";

/** Ask a question; the answer streams back as server-sent events. */
export async function POST(
  req: NextRequest,
  ctx: RouteContext<"/api/projects/[id]/chats/[chatId]/messages">,
) {
  const { id, chatId } = await ctx.params;
  if (!isId(id) || !isId(chatId))
    return Response.json({ detail: "Not found" }, { status: 404 });
  return proxyPost(req, `/projects/${id}/chats/${chatId}/messages`);
}
