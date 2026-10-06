import "server-only";

import { API_URL, apiAuthorization } from "@/lib/api";

/**
 * Stream a POST body to the API as the signed-in user and stream the response back. Used by
 * route handlers for uploads (Server Actions cap request bodies at 1 MB) and for chat answers,
 * which arrive as server-sent events.
 */
export async function proxyPost(req: Request, path: string) {
  const authorization = await apiAuthorization();
  if (!authorization) {
    return Response.json({ detail: "Not signed in" }, { status: 401 });
  }

  const headers = new Headers({ Authorization: authorization });
  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("Content-Type", contentType);
  const length = req.headers.get("content-length");
  if (length) headers.set("Content-Length", length);

  const res = await fetch(`${API_URL}${path}`, {
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
      "Cache-Control": res.headers.get("cache-control") ?? "no-store",
    },
  });
}

export function isId(value: string): boolean {
  return /^\d+$/.test(value);
}
