import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { Logo } from "@/components/shell/logo";
import { UserMenu } from "@/components/shell/user-menu";

export default async function ProjectsLayout({
  children,
}: LayoutProps<"/projects">) {
  const session = await auth();
  if (!session?.user?.email) redirect("/");
  return (
    <div className="flex min-h-full flex-col">
      <header className="border-line bg-surface/85 supports-[backdrop-filter]:bg-surface/70 sticky top-0 z-30 border-b backdrop-blur">
        <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
          <Logo />
          <UserMenu email={session.user.email} name={session.user.name} />
        </div>
      </header>
      <div className="flex flex-1 flex-col">{children}</div>
    </div>
  );
}
