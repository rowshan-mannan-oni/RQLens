import { ArrowRight, BadgeCheck, Quote, Table2 } from "lucide-react";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { auth } from "@/auth";
import { AutoRefresh } from "@/components/auto-refresh";
import { NewTableForm } from "@/components/literature/new-table-form";
import { PaperList } from "@/components/literature/paper-list";
import { PaperUpload } from "@/components/literature/paper-upload";
import { ApiError, apiFetch } from "@/lib/api";
import type { Paper, ReviewTableSummary, ReviewTemplate } from "@/lib/types";
import { createTable } from "./actions";

export default async function LiteraturePage(
  props: PageProps<"/projects/[id]/literature">,
) {
  const session = await auth();
  if (!session?.user) redirect("/");
  const { id } = await props.params;

  let papers: Paper[];
  let tables: ReviewTableSummary[];
  let templates: ReviewTemplate[];
  try {
    [papers, tables, templates] = await Promise.all([
      apiFetch<Paper[]>(`/projects/${id}/papers`),
      apiFetch<ReviewTableSummary[]>(`/projects/${id}/review-tables`),
      apiFetch<ReviewTemplate[]>(`/templates`),
    ]);
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 422))
      notFound();
    throw e;
  }
  const projectId = Number(id);
  const reading = papers.some(
    (p) => p.status === "queued" || p.status === "parsing",
  );
  const ready = papers.filter((p) => p.status === "ready").length;
  const templateName = new Map(templates.map((t) => [t.key, t.name]));

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <AutoRefresh active={reading} ms={2500} />
      <div className="flex min-w-0 flex-col gap-8">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">
            Literature review
          </h2>
          <p className="lead mt-1 max-w-3xl">
            Upload your papers and the AI fills a review table, one row per
            paper. Every value cites the sentences it came from: click a
            citation to open the PDF at that page with the sentence highlighted.
            Citations are checked against the paper, and anything that fails the
            check is marked unverified.
          </p>
        </div>

        {tables.length > 0 && (
          <section className="flex flex-col gap-3">
            <h3 className="section-title">Tables</h3>
            <ul className="grid gap-3 sm:grid-cols-2">
              {tables.map((t) => (
                <li key={t.id}>
                  <Link
                    href={`/projects/${projectId}/literature/${t.id}`}
                    className="card group hover:border-brand/50 flex items-center gap-3 p-4 transition"
                  >
                    <span className="bg-brand-soft text-brand-fg grid h-9 w-9 shrink-0 place-items-center rounded-lg">
                      <Table2 className="h-4 w-4" aria-hidden />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">
                        {t.name}
                      </span>
                      <span className="text-muted block truncate text-xs">
                        {templateName.get(t.template_key) ?? "Custom template"}{" "}
                        · {ready} paper{ready === 1 ? "" : "s"}
                      </span>
                    </span>
                    <ArrowRight
                      className="text-subtle group-hover:text-brand h-4 w-4 transition group-hover:translate-x-0.5"
                      aria-hidden
                    />
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="flex flex-col gap-3">
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="section-title">Papers</h3>
            {papers.length > 0 && (
              <span className="text-muted text-xs">
                {ready} of {papers.length} ready
              </span>
            )}
          </div>
          <PaperUpload projectId={projectId} />
          {papers.length > 0 && (
            <PaperList projectId={projectId} papers={papers} />
          )}
        </section>
      </div>

      <aside className="flex flex-col gap-4">
        <div className="card flex flex-col gap-3 p-5">
          <h3 className="font-semibold">New table</h3>
          <NewTableForm
            projectId={projectId}
            templates={templates}
            action={createTable.bind(null, projectId)}
          />
          {papers.length === 0 && (
            <p className="text-subtle text-xs">
              You can create a table now; papers you upload later are added to
              it automatically.
            </p>
          )}
        </div>
        <div className="card-muted flex flex-col gap-3 p-5 text-sm">
          <p className="flex items-start gap-2">
            <Quote className="text-brand mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <span className="text-muted">
              The AI may only cite sentences it was shown, and must quote them.
              A check compares every quote and number with the cited sentence.
            </span>
          </p>
          <p className="flex items-start gap-2">
            <BadgeCheck
              className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600"
              aria-hidden
            />
            <span className="text-muted">
              Title, authors and year come from the PDF itself. You can correct
              them, and your edits in the table are never overwritten.
            </span>
          </p>
        </div>
      </aside>
    </div>
  );
}
