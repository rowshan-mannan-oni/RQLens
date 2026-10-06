import { LoaderCircle, RefreshCw } from "lucide-react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { MappingEditor } from "@/components/rq/mapping-editor";
import {
  applyRewording,
  deleteQuestion,
  reassess,
  saveMapping,
} from "@/app/projects/[id]/rqs/actions";
import type {
  ColumnOption,
  RQAssessment,
  RQMapping,
  RQQuery,
  ResearchQuestion,
  RuleLevel,
  Verdict,
  ProjectComment,
} from "@/lib/types";
import { CommentsToggle } from "@/components/sharing/comments-toggle";

const VERDICT: Record<
  Verdict,
  { label: string; badge: string; accent: string }
> = {
  answerable: {
    label: "Answerable",
    badge: "badge-success",
    accent: "before:bg-emerald-500",
  },
  partial: {
    label: "Partly answerable",
    badge: "badge-warning",
    accent: "before:bg-amber-500",
  },
  not_answerable: {
    label: "Not answerable",
    badge: "badge-danger",
    accent: "before:bg-red-500",
  },
};

const LEVEL: Record<RuleLevel, { icon: string; label: string; cls: string }> = {
  fail: { icon: "✕", label: "Blocks", cls: "text-red-700 dark:text-red-400" },
  warn: {
    icon: "!",
    label: "Limits",
    cls: "text-amber-700 dark:text-amber-400",
  },
  info: { icon: "i", label: "Note", cls: "text-subtle" },
  pass: {
    icon: "✓",
    label: "Measured",
    cls: "text-emerald-700 dark:text-emerald-400",
  },
};

export function RQCard({
  projectId,
  rq,
  columns,
  comments,
  canModerate,
}: {
  projectId: number;
  rq: ResearchQuestion;
  columns: ColumnOption[];
  comments: ProjectComment[];
  canModerate: boolean;
}) {
  const a = rq.assessment;
  const working = rq.status === "queued" || rq.status === "running";
  return (
    <article
      id={`rq-${rq.id}`}
      className={`card relative flex flex-col gap-5 overflow-hidden p-5 pl-6 before:absolute before:inset-y-0 before:left-0 before:w-1 ${
        a && !working ? VERDICT[a.verdict].accent : "before:bg-line-strong"
      }`}
    >
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {a && !working && (
            <span className={`badge ${VERDICT[a.verdict].badge}`}>
              {VERDICT[a.verdict].label}
            </span>
          )}
          {working && (
            <span className="badge badge-brand">
              <LoaderCircle className="h-3 w-3 animate-spin" aria-hidden />
              {rq.status === "queued" ? "Waiting to assess" : "Assessing"}
            </span>
          )}
          {rq.parsed && (
            <span className="badge badge-neutral capitalize">
              {rq.parsed.type}
            </span>
          )}
        </div>
        <h3 className="text-lg leading-snug font-semibold tracking-tight">
          {rq.text}
        </h3>
        {rq.status === "failed" && (
          <p role="alert" className="text-sm text-red-700 dark:text-red-400">
            The assessment failed: {rq.error}
          </p>
        )}
        {rq.error && working && (
          <p className="text-subtle text-xs">{rq.error}</p>
        )}
      </header>

      {a && <AssessmentBody projectId={projectId} rq={rq} a={a} />}

      {rq.mapping && (
        <MappingSection
          projectId={projectId}
          rqId={rq.id}
          mapping={rq.mapping}
          columns={columns}
          editable={!working && rq.parsed !== null}
        />
      )}

      {a && <EvidenceSection a={a} />}

      <footer className="border-line bg-surface-2 -mx-5 -mb-5 -ml-6 flex flex-wrap items-center gap-2 border-t px-5 py-3 pl-6 text-xs">
        <form data-edit action={reassess.bind(null, projectId, rq.id, false)}>
          <button disabled={working} className="btn btn-secondary btn-sm">
            <RefreshCw className="h-3.5 w-3.5" aria-hidden />
            Re-assess
          </button>
        </form>
        <form data-edit action={reassess.bind(null, projectId, rq.id, true)}>
          <button
            disabled={working}
            title="Ask the AI to map the question to columns again"
            className="btn btn-secondary btn-sm"
          >
            Map again
          </button>
        </form>
        <ConfirmDialog
          triggerLabel="Delete"
          triggerClassName="btn btn-sm btn-ghost text-red-600 dark:text-red-400"
          title="Delete this research question?"
          confirmLabel="Delete"
          action={deleteQuestion.bind(null, projectId, rq.id)}
        >
          <p>Its assessments are deleted too. This cannot be undone.</p>
        </ConfirmDialog>
        <CommentsToggle
          projectId={projectId}
          rqId={rq.id}
          comments={comments}
          canModerate={canModerate}
        />
        {a && (
          <span className="text-subtle ml-auto" title={a.config_version}>
            Assessed {new Date(a.created_at).toLocaleString()}
          </span>
        )}
      </footer>
    </article>
  );
}

function AssessmentBody({
  projectId,
  rq,
  a,
}: {
  projectId: number;
  rq: ResearchQuestion;
  a: RQAssessment;
}) {
  return (
    <div className="flex flex-col gap-3 text-sm">
      {a.explanation && <p>{a.explanation}</p>}
      {a.explained_by === "rules" && (
        <p className="text-subtle text-xs">
          The AI was unavailable, so this explanation lists the rule results
          directly.
        </p>
      )}
      {a.grounding && !a.grounding.ok && (
        <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          <span className="font-medium">Check these numbers:</span>{" "}
          {a.grounding.unsupported.join(", ")} do not appear in the measured
          checks.
        </p>
      )}
      {a.rewording && a.rewording !== rq.text && (
        <div className="bg-surface-2 flex flex-col gap-2 rounded-md p-3">
          <p>
            <span className="font-medium">A version the data can answer: </span>
            {a.rewording}
          </p>
          <form
            action={applyRewording.bind(null, projectId, rq.id, a.rewording)}
          >
            <button className="btn btn-secondary btn-sm">
              Use this wording
            </button>
          </form>
        </div>
      )}
      {a.suggested_method && (
        <p>
          <span className="font-medium">Suggested method: </span>
          {a.suggested_method}
        </p>
      )}
      {a.threats.length > 0 && (
        <div>
          <p className="font-medium">Threats to validity</p>
          <ul className="ml-5 list-disc">
            {a.threats.map((t, i) => (
              <li key={i}>{t}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function MappingSection({
  projectId,
  rqId,
  mapping,
  columns,
  editable,
}: {
  projectId: number;
  rqId: number;
  mapping: RQMapping;
  columns: ColumnOption[];
  editable: boolean;
}) {
  return (
    <section className="flex flex-col gap-2 text-sm">
      <h4 className="font-medium">How the question maps to the data</h4>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-subtle">
            <tr>
              <th className="py-1 pr-3 font-normal">Concept</th>
              <th className="py-1 pr-3 font-normal">Role</th>
              <th className="py-1 pr-3 font-normal">Measured by</th>
              <th className="py-1 pr-3 font-normal">Match</th>
              <th className="py-1 font-normal">Why</th>
            </tr>
          </thead>
          <tbody>
            {mapping.constructs.map((c) => {
              const cand =
                c.status === "rejected" ? undefined : c.candidates[0];
              return (
                <tr key={c.name} className="border-line border-t align-top">
                  <td className="py-1.5 pr-3 font-medium">{c.name}</td>
                  <td className="py-1.5 pr-3">{c.role}</td>
                  <td className="py-1.5 pr-3">
                    {cand ? (
                      <code>
                        {cand.expression
                          ? cand.expression
                          : `${cand.table}.${cand.column}`}
                      </code>
                    ) : (
                      <span className="text-red-700 dark:text-red-400">
                        No column (gap)
                      </span>
                    )}
                    {c.status === "confirmed" && (
                      <span className="text-subtle ml-1">· confirmed</span>
                    )}
                  </td>
                  <td className="py-1.5 pr-3">{cand?.match ?? "—"}</td>
                  <td className="text-muted py-1.5">{cand?.justification}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {(mapping.population_filter || mapping.time_column) && (
        <p className="text-muted text-xs">
          {mapping.population_filter && (
            <>
              Population: <code>{mapping.population_filter}</code>.{" "}
            </>
          )}
          {mapping.time_column && (
            <>
              Period: <code>{mapping.time_column}</code> from{" "}
              {mapping.time_start ?? "the start"} to{" "}
              {mapping.time_end ?? "the end"}.
            </>
          )}
        </p>
      )}
      {mapping.notes && <p className="text-muted text-xs">{mapping.notes}</p>}
      {editable && (
        <MappingEditor
          mapping={mapping}
          columns={columns}
          save={saveMapping.bind(null, projectId, rqId)}
        />
      )}
    </section>
  );
}

function EvidenceSection({ a }: { a: RQAssessment }) {
  const queries = new Map(a.queries.map((q) => [q.id, q]));
  const items = [
    ...a.rules.map((r) => ({ ...r, key: `r-${r.rule}-${r.message}` })),
    ...a.facts.map((f) => ({
      rule: f.fact,
      level: "pass" as const,
      message: f.message,
      query_id: f.query_id,
      key: `f-${f.fact}`,
    })),
  ];
  return (
    <details className="group card text-sm">
      <summary className="hover:bg-surface-2 cursor-pointer list-none px-3 py-2 font-medium select-none">
        <span className="inline-block transition-transform group-open:rotate-90">
          ▸
        </span>{" "}
        Evidence
        <span className="text-subtle ml-2 font-normal">
          {a.rules.length} check result{a.rules.length === 1 ? "" : "s"} ·{" "}
          {a.queries.length} quer{a.queries.length === 1 ? "y" : "ies"}
          {a.grounding?.ok && a.grounding.checked > 0 && (
            <> · all {a.grounding.checked} numbers traced</>
          )}
        </span>
      </summary>
      <ul className="border-line flex flex-col gap-3 border-t p-3">
        {items.map((item) => {
          const q =
            item.query_id != null ? queries.get(item.query_id) : undefined;
          return (
            <li key={item.key} className="flex flex-col gap-1">
              <p>
                <span
                  className={`mr-1 font-mono font-bold ${LEVEL[item.level].cls}`}
                  aria-label={LEVEL[item.level].label}
                  title={LEVEL[item.level].label}
                >
                  {LEVEL[item.level].icon}
                </span>
                {item.message}
              </p>
              {q && <QueryLine query={q} />}
            </li>
          );
        })}
        {a.problems.length > 0 && (
          <li className="text-subtle text-xs">
            Mapping fixes: {a.problems.join(" ")}
          </li>
        )}
      </ul>
    </details>
  );
}

function QueryLine({ query }: { query: RQQuery }) {
  return (
    <details className="ml-5 text-xs">
      <summary className="text-subtle cursor-pointer">
        Query #{query.id}
        {query.duration_ms != null && <> · {query.duration_ms} ms</>}
      </summary>
      <pre className="code-block mt-1">{query.sql}</pre>
      {query.result_preview_json && (
        <table className="mt-1">
          <thead>
            <tr>
              {query.result_preview_json.columns.map((c) => (
                <th key={c} className="text-subtle pr-3 text-left font-normal">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {query.result_preview_json.rows.slice(0, 10).map((row, i) => (
              <tr key={i}>
                {row.map((v, j) => (
                  <td key={j} className="pr-3 font-mono">
                    {v === null ? "∅" : String(v)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </details>
  );
}
