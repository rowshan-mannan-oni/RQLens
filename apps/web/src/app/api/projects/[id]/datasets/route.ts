import type { NextRequest } from "next/server";

import { API_URL, apiAuthorization } from "@/lib/api";

// Streams the multipart upload to the API. A route handler is used instead of a Server
// Action because actions cap request bodies at 1 MB.
export async function POST(
  req: NextRequest,
  ctx: RouteContext<"/api/projects/[id]/datasets">,
) {
  const authorization = await apiAuthorization();
  if (!authorization) {
    return Response.json({ detail: "Not signed in" }, { status: 401 });
  }
  const { id } = await ctx.params;
  if (!/^\d+$/.test(id)) {
    return Response.json({ detail: "Not found" }, { status: 404 });
  }

  const headers = new Headers({ Authorization: authorization });
  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("Content-Type", contentType);
  const length = req.headers.get("content-length");
  if (length) headers.set("Content-Length", length);

  const res = await fetch(`${API_URL}/projects/${id}/datasets`, {
    method: "POST",
    headers,
    body: req.body,
    // Required by Node's fetch when the body is a stream.
    duplex: "half",
  } as RequestInit & { duplex: "half" });

  return new Response(res.body, {
    status: res.status,
    headers: {
      "Content-Type": res.headers.get("content-type") ?? "application/json",
    },
  });
}
