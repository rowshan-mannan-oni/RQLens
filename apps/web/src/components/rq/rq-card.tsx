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
} from "@/lib/types";

const VERDICT: Record<Verdict, { label: string; cls: string }> = {
  answerable: {
    label: "Answerable",
    cls: "bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300",
  },
  partial: {
    label: "Partly answerable",
    cls: "bg-amber-50 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200",
  },
  not_answerable: {
    label: "Not answerable",
    cls: "bg-red-50 text-red-800 dark:bg-red-950/40 dark:text-red-300",
  },
};

const LEVEL: Record<RuleLevel, { icon: string; label: string; cls: string }> = {
  fail: { icon: "✕", label: "Blocks", cls: "text-red-700 dark:text-red-400" },
  warn: {
    icon: "!",
    label: "Limits",
    cls: "text-amber-700 dark:text-amber-400",
  },
  info: { icon: "i", label: "Note", cls: "text-zinc-500" },
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
}: {
  projectId: number;
  rq: ResearchQuestion;
  columns: ColumnOption[];
}) {
  const a = rq.assessment;
  const working = rq.status === "queued" || rq.status === "running";
  return (
    <article className="flex flex-col gap-4 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {a && !working && (
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium ${VERDICT[a.verdict].cls}`}
            >
              {VERDICT[a.verdict].label}
            </span>
          )}
          {working && (
            <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
              {rq.status === "queued" ? "Waiting to assess…" : "Assessing…"}
            </span>
          )}
          {rq.parsed && (
            <span className="text-xs text-zinc-500">
              {rq.parsed.type} question
            </span>
          )}
        </div>
        <h3 className="font-medium">{rq.text}</h3>
        {rq.status === "failed" && (
          <p role="alert" className="text-sm text-red-700 dark:text-red-400">
            The assessment failed: {rq.error}
          </p>
        )}
        {rq.error && working && (
          <p className="text-xs text-zinc-500">{rq.error}</p>
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

      <footer className="flex flex-wrap items-center gap-2 border-t border-zinc-200 pt-3 text-xs dark:border-zinc-800">
        <form action={reassess.bind(null, projectId, rq.id, false)}>
          <button
            disabled={working}
            className="rounded-md border border-zinc-300 px-2 py-1 hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            Re-assess
          </button>
        </form>
        <form action={reassess.bind(null, projectId, rq.id, true)}>
          <button
            disabled={working}
            title="Ask the AI to map the question to columns again"
            className="rounded-md border border-zinc-300 px-2 py-1 hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            Map again
          </button>
        </form>
        <ConfirmDialog
          triggerLabel="Delete"
          title="Delete this research question?"
          confirmLabel="Delete"
          action={deleteQuestion.bind(null, projectId, rq.id)}
        >
          <p>Its assessments are deleted too. This cannot be undone.</p>
        </ConfirmDialog>
        {a && (
          <span className="ml-auto text-zinc-500" title={a.config_version}>
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
        <p className="text-xs text-zinc-500">
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
        <div className="flex flex-col gap-2 rounded-md bg-zinc-50 p-3 dark:bg-zinc-900">
          <p>
            <span className="font-medium">A version the data can answer: </span>
            {a.rewording}
          </p>
          <form
            action={applyRewording.bind(null, projectId, rq.id, a.rewording)}
          >
            <button className="rounded-md border border-zinc-300 px-2 py-1 text-xs hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800">
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
          <thead className="text-zinc-500">
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
                <tr
                  key={c.name}
                  className="border-t border-zinc-100 align-top dark:border-zinc-800"
                >
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
                      <span className="ml-1 text-zinc-500">· confirmed</span>
                    )}
                  </td>
                  <td className="py-1.5 pr-3">{cand?.match ?? "—"}</td>
                  <td className="py-1.5 text-zinc-600 dark:text-zinc-400">
                    {cand?.justification}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {(mapping.population_filter || mapping.time_column) && (
        <p className="text-xs text-zinc-600 dark:text-zinc-400">
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
      {mapping.notes && (
        <p className="text-xs text-zinc-600 dark:text-zinc-400">
          {mapping.notes}
        </p>
      )}
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
    <details className="group rounded-lg border border-zinc-200 text-sm dark:border-zinc-800">
      <summary className="cursor-pointer list-none px-3 py-2 font-medium select-none hover:bg-zinc-50 dark:hover:bg-zinc-900">
        <span className="inline-block transition-transform group-open:rotate-90">
          ▸
        </span>{" "}
        Evidence
        <span className="ml-2 font-normal text-zinc-500">
          {a.rules.length} check result{a.rules.length === 1 ? "" : "s"} ·{" "}
          {a.queries.length} quer{a.queries.length === 1 ? "y" : "ies"}
          {a.grounding?.ok && a.grounding.checked > 0 && (
            <> · all {a.grounding.checked} numbers traced</>
          )}
        </span>
      </summary>
      <ul className="flex flex-col gap-3 border-t border-zinc-200 p-3 dark:border-zinc-800">
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
          <li className="text-xs text-zinc-500">
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
      <summary className="cursor-pointer text-zinc-500">
        Query #{query.id}
        {query.duration_ms != null && <> · {query.duration_ms} ms</>}
      </summary>
      <pre className="mt-1 overflow-x-auto rounded bg-zinc-50 p-2 whitespace-pre-wrap dark:bg-zinc-900">
        {query.sql}
      </pre>
      {query.result_preview_json && (
        <table className="mt-1">
          <thead>
            <tr>
              {query.result_preview_json.columns.map((c) => (
                <th
                  key={c}
                  className="pr-3 text-left font-normal text-zinc-500"
                >
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
