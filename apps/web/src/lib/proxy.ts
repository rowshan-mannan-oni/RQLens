import "server-only";

import { API_URL, apiAuthorization } from "@/lib/api";

/**
 * Stream a multipart upload to the API as the signed-in user. Used by route handlers
 * because Server Actions cap request bodies at 1 MB.
 */
export async function proxyUpload(req: Request, path: string) {
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
    },
  });
}

export function isId(value: string): boolean {
  return /^\d+$/.test(value);
}
