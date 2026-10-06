"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** Re-render the server page every `ms` while `active` (e.g. a background job is running). */
export function AutoRefresh({
  active,
  ms = 2000,
}: {
  active: boolean;
  ms?: number;
}) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => router.refresh(), ms);
    return () => clearInterval(timer);
  }, [active, ms, router]);
  return null;
}
