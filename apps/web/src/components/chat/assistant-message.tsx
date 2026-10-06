import { AnswerChart } from "@/components/chat/answer-chart";
import { Markdown } from "@/components/chat/markdown";
import { formatInt } from "@/lib/format";
import type { AgentStep, ChatMessage, ChatQuery } from "@/lib/types";

const STOPPED: Record<string, string> = {
  tool_calls: "the limit on steps per question",
  sql_errors: "three failed queries",
  tokens: "the token budget per question",
  time: "the time limit per question",
};

export function AssistantMessage({ message }: { message: ChatMessage }) {
  const { kind, grounding, stopped } = message;
  return (
    <div className="flex flex-col gap-3">
      {kind === "clarification" && <Badge tone="info">Needs your input</Badge>}
      {kind === "cannot_answer" && (
        <Badge tone="info">The data cannot answer this</Badge>
      )}
      {kind === "error" && <Badge tone="error">No answer</Badge>}

      <Markdown text={message.content} />

      {message.charts.map((c) => (
        <AnswerChart key={c.id} chart={c} />
      ))}

      {grounding && !grounding.ok && (
        <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          <span aria-hidden>⚠ </span>
          <span className="font-medium">Check these numbers:</span>{" "}
          {grounding.unsupported.join(", ")} could not be traced to any query
          result.
        </p>
      )}
      {stopped && (
        <p className="text-muted text-sm">
          Stopped early after {STOPPED[stopped] ?? stopped}.
        </p>
      )}

      {(message.steps.length > 0 || message.queries.length > 0) && (
        <HowComputed message={message} />
      )}
    </div>
  );
}

function Badge({
  tone,
  children,
}: {
  tone: "info" | "error";
  children: React.ReactNode;
}) {
  const cls =
    tone === "error"
      ? "bg-red-50 text-red-800 dark:bg-red-950/40 dark:text-red-300"
      : "bg-surface-3 text-muted";
  return (
    <span
      className={`w-fit rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}
    >
      {children}
    </span>
  );
}

function HowComputed({ message }: { message: ChatMessage }) {
  const { grounding, usage } = message;
  const queries = new Map(message.queries.map((q) => [q.id, q]));
  const shown = new Set<number>();
  return (
    <details className="group card text-sm">
      <summary className="hover:bg-surface-2 cursor-pointer list-none px-3 py-2 font-medium select-none">
        <span className="inline-block transition-transform group-open:rotate-90">
          ▸
        </span>{" "}
        How this was computed
        <span className="text-subtle ml-2 font-normal">
          {message.queries.length} quer
          {message.queries.length === 1 ? "y" : "ies"}
          {grounding && grounding.checked > 0 && grounding.ok && (
            <> · all {grounding.checked} numbers traced to results</>
          )}
        </span>
      </summary>
      <ol className="border-line flex flex-col gap-3 border-t p-3">
        {message.steps.map((s, i) => {
          const q = s.query_id != null ? queries.get(s.query_id) : undefined;
          if (q) shown.add(q.id);
          return (
            <li key={i} className="flex flex-col gap-1.5">
              <StepLine step={s} index={i + 1} />
              {q && <QueryBlock query={q} />}
            </li>
          );
        })}
        {message.queries
          .filter((q) => !shown.has(q.id))
          .map((q) => (
            <li key={q.id}>
              <QueryBlock query={q} />
            </li>
          ))}
      </ol>
      {usage && (
        <p className="border-line text-subtle border-t px-3 py-2 text-xs">
          {usage.llm_calls} AI calls · {usage.tool_calls} tool calls ·{" "}
          {formatInt(usage.tokens)} tokens ·{" "}
          {(usage.duration_ms / 1000).toFixed(1)} s
          {Number(usage.cost_usd) > 0 && (
            <> · ${Number(usage.cost_usd).toFixed(4)}</>
          )}
          {usage.grounding_retries > 0 && (
            <> · answer rewritten once to fix numbers</>
          )}
        </p>
      )}
    </details>
  );
}

export function StepLine({ step, index }: { step: AgentStep; index?: number }) {
  return (
    <div>
      <p className={step.error ? "text-red-700 dark:text-red-400" : undefined}>
        {index != null && <span className="text-subtle">{index}. </span>}
        {step.summary}
        {step.error && <span className="text-xs"> — {step.error}</span>}
      </p>
      {step.result && <StatResult result={step.result} />}
    </div>
  );
}

function StatResult({ result }: { result: Record<string, unknown> }) {
  const fmt = (v: unknown) =>
    typeof v === "number" ? v.toPrecision(4).replace(/\.?0+$/, "") : String(v);
  const groups = (result.groups as Record<string, unknown>[] | undefined) ?? [];
  return (
    <div className="bg-surface-2 mt-1 rounded-md px-3 py-2 text-xs">
      <p>
        <span className="font-medium">{String(result.test)}</span> ·{" "}
        {String(result.statistic_name)} = {fmt(result.statistic)} · p ={" "}
        {fmt(result.p_value)} · {String(result.effect_size_name)} ={" "}
        {fmt(result.effect_size)} · n = {formatInt(result.n as number)}
      </p>
      {groups.length > 0 && (
        <p className="text-muted">
          {groups
            .map(
              (g) =>
                `${String(g.group)}: n ${formatInt(g.n as number)}, median ${fmt(g.median)}`,
            )
            .join(" · ")}
        </p>
      )}
      {result.note ? <p className="text-muted">{String(result.note)}</p> : null}
    </div>
  );
}

function QueryBlock({ query }: { query: ChatQuery }) {
  return (
    <div className="flex flex-col gap-1.5">
      <pre className="code-block">
        <span className="text-subtle">-- query {query.id}</span>
        {"\n"}
        {query.sql}
      </pre>
      {query.error ? (
        <p className="text-xs text-red-700 dark:text-red-400">{query.error}</p>
      ) : (
        <>
          {query.columns.length > 0 && (
            <div className="border-line max-h-72 overflow-auto rounded-md border">
              <table className="w-full text-xs">
                <thead className="bg-surface sticky top-0">
                  <tr>
                    {query.columns.map((c) => (
                      <th
                        key={c}
                        className="border-line border-b px-2 py-1 text-left font-medium"
                      >
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {query.rows.map((r, i) => (
                    <tr key={i} className="odd:bg-surface-2">
                      {r.map((v, j) => (
                        <td key={j} className="px-2 py-1 tabular-nums">
                          {v == null ? "–" : String(v)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-subtle text-xs">
            {query.row_count != null && (
              <>
                {query.rows.length < query.row_count
                  ? `First ${query.rows.length} of ${formatInt(query.row_count)} rows`
                  : `${formatInt(query.row_count)} row${query.row_count === 1 ? "" : "s"}`}
              </>
            )}
            {query.duration_ms != null && <> · {query.duration_ms} ms</>}
          </p>
        </>
      )}
    </div>
  );
}
