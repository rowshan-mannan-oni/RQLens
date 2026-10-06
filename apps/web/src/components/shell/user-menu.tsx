import { Gauge, LogOut } from "lucide-react";
import Link from "next/link";

import { signOut } from "@/auth";

export function UserMenu({
  email,
  name,
}: {
  email: string;
  name: string | null | undefined;
}) {
  const initial = (name || email).trim().charAt(0).toUpperCase();
  return (
    <details className="group relative">
      <summary
        aria-label="Account"
        className="hover:bg-surface-3 flex cursor-pointer list-none items-center gap-2 rounded-full p-0.5 select-none"
      >
        <span className="bg-brand-soft text-brand-fg grid h-8 w-8 place-items-center rounded-full text-sm font-semibold">
          {initial}
        </span>
      </summary>
      <div className="border-line bg-surface shadow-pop absolute right-0 z-20 mt-2 w-64 rounded-xl border p-2">
        <div className="px-2 py-1.5">
          {name && <p className="truncate text-sm font-medium">{name}</p>}
          <p className="text-muted truncate text-xs">{email}</p>
        </div>
        <div className="border-line my-1 border-t" />
        <Link href="/usage" className="btn btn-ghost w-full justify-start">
          <Gauge className="h-4 w-4" aria-hidden />
          Usage and limits
        </Link>
        <form
          action={async () => {
            "use server";
            await signOut({ redirectTo: "/" });
          }}
        >
          <button className="btn btn-ghost w-full justify-start">
            <LogOut className="h-4 w-4" aria-hidden />
            Sign out
          </button>
        </form>
      </div>
    </details>
  );
}
