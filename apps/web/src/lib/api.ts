import "server-only";

import { SignJWT } from "jose";

import { auth } from "@/auth";

export const API_URL = process.env.API_URL_INTERNAL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Short-lived token the FastAPI backend accepts (see apps/api/auth.py). */
async function apiToken(email: string, name: string | null): Promise<string> {
  const secret = process.env.API_JWT_SECRET;
  if (!secret) throw new Error("API_JWT_SECRET is not set");
  return new SignJWT({ email, name })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuer("rq-lens-web")
    .setAudience("rq-lens-api")
    .setIssuedAt()
    .setExpirationTime("5m")
    .sign(new TextEncoder().encode(secret));
}

/** Authorization header for the signed-in user, or null when signed out. */
export async function apiAuthorization(): Promise<string | null> {
  const session = await auth();
  const email = session?.user?.email;
  if (!email) return null;
  return `Bearer ${await apiToken(email, session.user?.name ?? null)}`;
}

/** Call the API as the signed-in user. Server-side only. */
export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const authorization = await apiAuthorization();
  if (!authorization) throw new ApiError(401, "Not signed in");

  const headers = new Headers(init.headers);
  headers.set("Authorization", authorization);
  if (init.body) headers.set("Content-Type", "application/json");

  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return (await res.json()) as T;
}
