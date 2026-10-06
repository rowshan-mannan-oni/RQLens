import "server-only";

import { API_URL, apiAuthorization } from "@/lib/api";

/** Forward a GET to the API as the signed-in user and stream the response back. */
export async function proxyGet(path: string, fallbackType: string) {
  const authorization = await apiAuthorization();
  if (!authorization)
    return Response.json({ detail: "Not signed in" }, { status: 401 });
  const res = await fetch(`${API_URL}${path}`, {
    headers: { Authorization: authorization },
    cache: "no-store",
  });
  const headers = new Headers({
    "Content-Type": res.headers.get("content-type") ?? fallbackType,
    "Cache-Control": "private, no-store",
  });
  const disposition = res.headers.get("content-disposition");
  if (disposition) headers.set("Content-Disposition", disposition);
  const length = res.headers.get("content-length");
  if (length) headers.set("Content-Length", length);
  return new Response(res.body, { status: res.status, headers });
}
