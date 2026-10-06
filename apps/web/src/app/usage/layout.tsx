import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { AppHeader } from "@/components/shell/app-header";

export default async function UsageLayout({ children }: LayoutProps<"/usage">) {
  const session = await auth();
  if (!session?.user?.email) redirect("/");
  return (
    <div className="flex min-h-full flex-col">
      <AppHeader email={session.user.email} name={session.user.name} />
      <div className="flex flex-1 flex-col">{children}</div>
    </div>
  );
}
