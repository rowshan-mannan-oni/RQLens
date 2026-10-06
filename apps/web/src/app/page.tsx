import { redirect } from "next/navigation";

import { auth, signIn, signInOptions } from "@/auth";

export default async function Home() {
  const session = await auth();
  if (session?.user) redirect("/projects");

  return (
    <main className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center gap-8 px-4 py-16">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">RQ Lens</h1>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          Upload a dataset, state your research questions, and find out whether
          the data can answer them.
        </p>
      </div>

      <div className="flex flex-col gap-3">
        {signInOptions.length === 0 && (
          <p className="text-sm text-red-600">
            No login provider is configured. Set AUTH_GOOGLE_ID and
            AUTH_GOOGLE_SECRET in .env.
          </p>
        )}
        {signInOptions.map((provider) => (
          <form
            key={provider.id}
            action={async () => {
              "use server";
              await signIn(provider.id, { redirectTo: "/projects" });
            }}
          >
            <button className="w-full rounded-md border border-zinc-300 px-4 py-2.5 font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900">
              Continue with {provider.name}
            </button>
          </form>
        ))}
      </div>
    </main>
  );
}
