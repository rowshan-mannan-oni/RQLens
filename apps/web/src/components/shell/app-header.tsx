import Link from "next/link";

import { Logo } from "@/components/shell/logo";
import { UserMenu } from "@/components/shell/user-menu";

export function AppHeader({
  email,
  name,
}: {
  email: string;
  name: string | null | undefined;
}) {
  return (
    <header className="border-line bg-surface/85 supports-[backdrop-filter]:bg-surface/70 sticky top-0 z-30 border-b backdrop-blur">
      <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <div className="flex items-center gap-6">
          <Logo />
          <nav aria-label="Main" className="hidden items-center gap-1 sm:flex">
            <Link href="/projects" className="btn btn-ghost btn-sm">
              Projects
            </Link>
            <Link href="/usage" className="btn btn-ghost btn-sm">
              Usage
            </Link>
          </nav>
        </div>
        <UserMenu email={email} name={name} />
      </div>
    </header>
  );
}
