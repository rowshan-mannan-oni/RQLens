import {
  ArrowRight,
  ChartNoAxesColumn,
  Database,
  Download,
  FileText,
  Lightbulb,
  Link2,
  MessagesSquare,
  Rows3,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";

import { AutoRefresh } from "@/components/auto-refresh";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { DatasetList } from "@/components/dataset-list";
import { UploadForm } from "@/components/upload-form";
import { apiFetch } from "@/lib/api";
import { formatInt, formatPct } from "@/lib/format";
import { deleteProject, setShareSamples } from "./actions";
import type {
  Dataset,
  Insights,
  Project,
  Relationship,
  ProjectComment,
  ResearchQuestions,
} from "@/lib/types";
import { CommentThread } from "@/components/sharing/comment-thread";

export default async function ProjectPage(props: PageProps<"/projects/[id]">) {
  const { id } = await props.params;
  // The layout already checked that the project exists and belongs to the user.
  const [project, datasets, joins, rqs, insights, comments] = await Promise.all(
    [
      apiFetch<Project>(`/projects/${id}`),
      apiFetch<Dataset[]>(`/projects/${id}/datasets`),
      apiFetch<Relationship[]>(`/projects/${id}/relationships`),
      apiFetch<ResearchQuestions>(`/projects/${id}/rqs`),
      apiFetch<Insights>(`/projects/${id}/insights`),
      apiFetch<ProjectComment[]>(`/projects/${id}/comments`),
    ],
  );
  const projectComments = comments.filter((c) => c.target_type === "project");
  const elsewhere = comments.filter(
    (c) => c.target_type !== "project" && !c.resolved,
  );
  const elsewhereHref = (c: ProjectComment) =>
    c.target_type === "rq"
      ? `/projects/${id}/rqs#rq-${c.target_id}`
      : c.target_type === "insight"
        ? `/projects/${id}/insights`
        : `/projects/${id}/literature`;
  const elsewhereLabel = {
    rq: "Research question",
    cell: "Literature table",
    insight: "Insight",
    paper: "Paper",
    project: "Project",
  };
  const working = datasets.some(
    (d) => d.status !== "ready" && d.status !== "failed",
  );
  const ready = datasets.filter((d) => d.status === "ready");
  const rows = ready.reduce((n, d) => n + (d.row_count ?? 0), 0);
  const columns = ready.reduce((n, d) => n + (d.column_count ?? 0), 0);
  const verdicts = { answerable: 0, partial: 0, not_answerable: 0 };
  for (const q of rqs.questions)
    if (q.assessment && q.status === "done") verdicts[q.assessment.verdict]++;
  const findings = insights.insights.filter(
    (i) => i.status === "finding",
  ).length;

  return (
    <div className="flex flex-col gap-8">
      <AutoRefresh active={working} />

      <dl className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Tile
          icon={Database}
          label="Datasets"
          value={formatInt(ready.length)}
          note={
            datasets.length > ready.length
              ? `${datasets.length - ready.length} processing or failed`
              : "ready"
          }
        />
        <Tile
          icon={Rows3}
          label="Rows"
          value={formatInt(rows)}
          note={`${formatInt(columns)} columns in total`}
        />
        <Tile
          icon={ChartNoAxesColumn}
          label="Research questions"
          value={formatInt(rqs.questions.length)}
          note={
            rqs.questions.length
              ? `${verdicts.answerable} answerable · ${verdicts.partial} partly · ${verdicts.not_answerable} not`
              : "none yet"
          }
        />
        <Tile
          icon={Lightbulb}
          label="Findings"
          value={formatInt(findings)}
          note={
            insights.run?.status === "done"
              ? `from ${insights.run.planned} analyses`
              : "not generated yet"
          }
        />
      </dl>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="flex min-w-0 flex-col gap-8">
          <section className="flex flex-col gap-4">
            <div>
              <h2 className="section-title">Datasets</h2>
              <p className="lead">
                Each file becomes a table. SPSS and Stata variable labels fill
                the data dictionary. Profiles run in the background.
              </p>
            </div>
            <UploadForm projectId={project.id} />
            {datasets.length > 0 && (
              <DatasetList projectId={project.id} datasets={datasets} />
            )}
          </section>

          {joins.length > 0 && (
            <section className="flex flex-col gap-4">
              <div>
                <h2 className="section-title">Possible joins</h2>
                <p className="lead">
                  Column pairs that share values. Coverage is the share of each
                  side&apos;s distinct values found on the other side.
                </p>
              </div>
              <ul className="card divide-line divide-y">
                {joins.map((j) => (
                  <li key={j.id} className="flex gap-3 p-4">
                    <span className="bg-surface-3 text-muted mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-md">
                      <Link2 className="h-3.5 w-3.5" aria-hidden />
                    </span>
                    <div className="min-w-0 text-sm">
                      <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
                        <code className="text-muted">{j.left.table_name}.</code>
                        <span className="font-medium">
                          {j.left.column_label}
                        </span>
                        <span className="text-subtle">↔</span>
                        <code className="text-muted">
                          {j.right.table_name}.
                        </code>
                        <span className="font-medium">
                          {j.right.column_label}
                        </span>
                        <span className="badge badge-neutral ml-1">
                          {j.cardinality}
                        </span>
                        {j.name_match && (
                          <span className="badge badge-brand">names match</span>
                        )}
                      </p>
                      <p className="text-subtle mt-1 text-xs">
                        {formatInt(j.shared_values)} shared values ·{" "}
                        {formatPct(j.left.coverage, 0)} of {j.left.column_label}{" "}
                        found · {formatPct(j.right.coverage, 0)} of{" "}
                        {j.right.column_label} found
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>

        <aside className="flex flex-col gap-4">
          <section
            aria-label="Discussion"
            className="card flex flex-col gap-3 p-4"
          >
            <p className="eyebrow">Discussion</p>
            {elsewhere.length > 0 && (
              <ul className="flex flex-col gap-1.5 text-xs">
                {elsewhere.slice(-5).map((c) => (
                  <li key={c.id}>
                    <a
                      href={elsewhereHref(c)}
                      className="hover:text-fg text-muted"
                    >
                      <span className="text-fg font-medium">{c.author}</span> on{" "}
                      {elsewhereLabel[c.target_type].toLowerCase()}:{" "}
                      {c.body.length > 80
                        ? `${c.body.slice(0, 80)}\u2026`
                        : c.body}
                    </a>
                  </li>
                ))}
              </ul>
            )}
            <CommentThread
              projectId={project.id}
              targetType="project"
              targetId={null}
              comments={projectComments}
              canModerate={project.role !== "viewer"}
              placeholder="Write to everyone on the project"
              compact
            />
          </section>
          {ready.length > 0 && (
            <nav aria-label="Next steps" className="card divide-line divide-y">
              <p className="eyebrow px-4 pt-4 pb-2">Next steps</p>
              <NextStep
                href={`/projects/${project.id}/rqs`}
                icon={ChartNoAxesColumn}
                title="Check your research questions"
                text="See which questions the data can answer."
              />
              <NextStep
                href={`/projects/${project.id}/insights`}
                icon={Lightbulb}
                title="Generate insights"
                text="Ranked patterns, each with its test and query."
              />
              <NextStep
                href={`/projects/${project.id}/chat`}
                icon={MessagesSquare}
                title="Chat with your data"
                text="Ask questions; see the SQL behind every answer."
              />
            </nav>
          )}

          {ready.length > 0 && (
            <div className="card flex flex-col gap-3 p-4">
              <div className="flex items-center gap-2">
                <FileText className="text-brand h-4 w-4" aria-hidden />
                <h2 className="text-sm font-semibold">Dataset report</h2>
              </div>
              <p className="text-muted text-sm">
                A draft of your paper&apos;s data section: dictionary, quality
                warnings, research-question fit and top insights.
              </p>
              <div className="flex gap-2">
                <a
                  href={`/api/projects/${project.id}/report?format=pdf`}
                  className="btn btn-secondary btn-sm"
                  download
                >
                  <Download className="h-3.5 w-3.5" aria-hidden />
                  PDF
                </a>
                <a
                  href={`/api/projects/${project.id}/report?format=md`}
                  className="btn btn-secondary btn-sm"
                  download
                >
                  <Download className="h-3.5 w-3.5" aria-hidden />
                  Markdown
                </a>
              </div>
            </div>
          )}

          <form
            data-edit
            action={setShareSamples.bind(
              null,
              project.id,
              !project.share_samples,
            )}
            className="card flex flex-col gap-3 p-4"
          >
            <div className="flex items-center gap-2">
              <ShieldCheck className="text-brand h-4 w-4" aria-hidden />
              <h2 className="text-sm font-semibold">What the AI sees</h2>
            </div>
            <p className="text-muted text-sm">
              {project.share_samples
                ? "Column statistics and a few masked example values, never full rows. Personal-data columns are never shown."
                : "Only column names and aggregate statistics. No example values."}
            </p>
            <button className="btn btn-secondary btn-sm self-start">
              {project.share_samples
                ? "Stop sharing example values"
                : "Share example values"}
            </button>
          </form>

          {project.role === "owner" && (
            <div className="card-muted flex flex-col gap-2 p-4">
              <h2 className="text-sm font-semibold">Delete project</h2>
              <p className="text-muted text-xs">
                Removes every dataset, upload, profile, query log and AI call
                log in this project.
              </p>
              <ConfirmDialog
                triggerLabel="Delete project"
                triggerClassName="btn btn-sm btn-danger self-start"
                title={`Delete the project “${project.title}”?`}
                confirmLabel="Delete project"
                action={deleteProject.bind(null, project.id)}
              >
                <p>
                  This permanently removes all {datasets.length} dataset
                  {datasets.length === 1 ? "" : "s"}, uploaded files, profiles,
                  descriptions, query logs and AI call logs in this project.
                </p>
                <p className="mt-2 font-medium">This cannot be undone.</p>
              </ConfirmDialog>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

function Tile({
  icon: Icon,
  label,
  value,
  note,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  note: string;
}) {
  return (
    <div className="card flex flex-col gap-1 p-4">
      <dt className="text-muted flex items-center gap-1.5 text-xs font-medium">
        <Icon className="text-subtle h-3.5 w-3.5" aria-hidden />
        {label}
      </dt>
      <dd className="text-2xl font-semibold tracking-tight tabular-nums">
        {value}
      </dd>
      <dd className="text-subtle truncate text-xs">{note}</dd>
    </div>
  );
}

function NextStep({
  href,
  icon: Icon,
  title,
  text,
}: {
  href: string;
  icon: LucideIcon;
  title: string;
  text: string;
}) {
  return (
    <Link
      href={href}
      className="group hover:bg-surface-2 flex items-center gap-3 px-4 py-3 transition-colors last:rounded-b-xl first-of-type:rounded-t-xl"
    >
      <span className="bg-brand-soft text-brand-fg grid h-8 w-8 shrink-0 place-items-center rounded-lg">
        <Icon className="h-4 w-4" aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium">{title}</span>
        <span className="text-muted block text-xs">{text}</span>
      </span>
      <ArrowRight
        className="text-subtle group-hover:text-brand h-4 w-4 transition group-hover:translate-x-0.5"
        aria-hidden
      />
    </Link>
  );
}
