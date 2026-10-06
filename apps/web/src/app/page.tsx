import {
  ChartNoAxesColumn,
  Lightbulb,
  MessagesSquare,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import { redirect } from "next/navigation";

import { auth, signIn, signInOptions } from "@/auth";
import { LogoMark } from "@/components/shell/logo";

const FEATURES: { icon: LucideIcon; title: string; text: string }[] = [
  {
    icon: ChartNoAxesColumn,
    title: "Research question fit",
    text: "Each question gets a verdict from measured checks: rows in scope, missing values, group sizes, power.",
  },
  {
    icon: Lightbulb,
    title: "Ranked insights",
    text: "Fixed statistical tests, corrected for multiple testing, ranked by effect size, not p-value alone.",
  },
  {
    icon: MessagesSquare,
    title: "Chat with your data",
    text: "Ask in plain language. Every number comes from a query you can open and check.",
  },
];

export default async function Home() {
  const session = await auth();
  if (session?.user) redirect("/projects");

  return (
    <main className="relative flex flex-1 flex-col overflow-hidden">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 -top-40 h-[32rem] bg-[radial-gradient(ellipse_at_top,var(--brand-soft),transparent_65%)]"
      />
      <div className="relative mx-auto grid w-full max-w-6xl flex-1 items-center gap-12 px-4 py-16 sm:px-6 lg:grid-cols-[1.1fr_1fr] lg:py-24">
        <div className="flex flex-col gap-8">
          <div className="flex items-center gap-2.5">
            <LogoMark className="h-9 w-9" />
            <span className="text-lg font-semibold tracking-tight">
              RQ Lens
            </span>
          </div>
          <div className="flex flex-col gap-4">
            <h1 className="text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
              Know what your data can answer,{" "}
              <span className="text-brand">before</span> you design the study.
            </h1>
            <p className="text-muted max-w-xl text-lg leading-relaxed">
              Upload a dataset and state your research questions. RQ Lens
              profiles every column, checks whether each question is answerable,
              and surfaces patterns worth testing, with the query behind every
              number.
            </p>
          </div>

          <div className="flex max-w-sm flex-col gap-2.5">
            {signInOptions.length === 0 && (
              <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
                No login provider is configured. Set AUTH_GOOGLE_ID and
                AUTH_GOOGLE_SECRET in .env.
              </p>
            )}
            {signInOptions.map((provider, i) => (
              <form
                key={provider.id}
                action={async () => {
                  "use server";
                  await signIn(provider.id, { redirectTo: "/projects" });
                }}
              >
                <button
                  className={`btn w-full py-2.5 ${i === 0 ? "btn-primary" : "btn-secondary"}`}
                >
                  Continue with {provider.name}
                </button>
              </form>
            ))}
            <p className="text-subtle flex items-center gap-1.5 text-xs">
              <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
              The AI sees schema and statistics, never your raw rows.
            </p>
          </div>
        </div>

        <PreviewCard />
      </div>

      <section className="border-line bg-surface relative border-t">
        <div className="mx-auto grid w-full max-w-6xl gap-6 px-4 py-12 sm:grid-cols-3 sm:px-6">
          {FEATURES.map(({ icon: Icon, title, text }) => (
            <div key={title} className="flex flex-col gap-2">
              <span className="bg-brand-soft text-brand-fg grid h-9 w-9 place-items-center rounded-lg">
                <Icon className="h-4.5 w-4.5" aria-hidden />
              </span>
              <h2 className="font-semibold tracking-tight">{title}</h2>
              <p className="text-muted text-sm leading-relaxed">{text}</p>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}

/** A static illustration of an assessed research question. */
function PreviewCard() {
  const checks: [string, string][] = [
    ["✓", "534 rows in scope; 534 have every mapped value"],
    ["✓", "2 groups of union membership: no (438), yes (96)"],
    ["!", "Causal wording: observational data shows association only"],
  ];
  return (
    <div aria-hidden className="relative mx-auto w-full max-w-md select-none">
      <div className="bg-brand-soft/60 absolute -inset-4 -z-10 rounded-3xl blur-2xl" />
      <div className="card shadow-pop flex flex-col gap-4 p-5">
        <div className="flex items-center gap-2">
          <span className="badge badge-warning">Partly answerable</span>
          <span className="text-subtle text-xs">causal question</span>
        </div>
        <p className="font-medium">
          Does union membership increase hourly wages?
        </p>
        <div className="bg-surface-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 rounded-lg p-3 text-xs">
          <span className="text-subtle">Outcome</span>
          <code>cps1985.wage</code>
          <span className="text-subtle">Explanatory</span>
          <code>cps1985.union</code>
        </div>
        <ul className="flex flex-col gap-2 text-sm">
          {checks.map(([icon, text]) => (
            <li key={text} className="flex gap-2">
              <span
                className={`mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full text-[10px] font-bold ${
                  icon === "✓"
                    ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
                    : "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200"
                }`}
              >
                {icon}
              </span>
              <span className="text-muted">{text}</span>
            </li>
          ))}
        </ul>
        <div className="border-line text-subtle flex items-center justify-between border-t pt-3 text-xs">
          <span>3 queries · all numbers traced</span>
          <span className="text-brand-fg dark:text-brand font-medium">
            Use suggested wording →
          </span>
        </div>
      </div>
    </div>
  );
}
