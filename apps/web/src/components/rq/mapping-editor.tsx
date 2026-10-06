"use client";

import { useState, useTransition } from "react";

import type { ActionState } from "@/components/confirm-dialog";
import type {
  Candidate,
  ColumnOption,
  MappedConstruct,
  MatchType,
  RQMapping,
} from "@/lib/types";

const GAP = "gap";

/** Choose a column (or "no column fits") for each construct, then re-assess. */
export function MappingEditor({
  mapping,
  columns,
  save,
}: {
  mapping: RQMapping;
  columns: ColumnOption[];
  save: (mapping: RQMapping) => Promise<ActionState>;
}) {
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState(() =>
    mapping.constructs.map((c) => initialChoice(c)),
  );
  const [match, setMatch] = useState<MatchType[]>(() =>
    mapping.constructs.map((c) => c.candidates[0]?.match ?? "direct"),
  );
  const [population, setPopulation] = useState(mapping.population_filter ?? "");
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  if (!open)
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="btn btn-secondary btn-sm w-fit"
      >
        Edit mapping
      </button>
    );

  function build(): RQMapping {
    return {
      ...mapping,
      population_filter: population.trim() || null,
      constructs: mapping.constructs.map((c, i) =>
        applyChoice(c, choice[i], match[i]),
      ),
    };
  }

  return (
    <form
      className="border-line flex flex-col gap-3 rounded-md border p-3 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        setError(null);
        start(async () => {
          const result = await save(build());
          if (result.error) setError(result.error);
          else setOpen(false);
        });
      }}
    >
      {mapping.constructs.map((c, i) => (
        <fieldset key={c.name} className="flex flex-col gap-1">
          <legend className="font-medium">
            {c.name} <span className="text-subtle font-normal">({c.role})</span>
          </legend>
          <div className="flex flex-wrap gap-2">
            <select
              aria-label={`Column for ${c.name}`}
              value={choice[i]}
              onChange={(e) =>
                setChoice(choice.map((v, j) => (j === i ? e.target.value : v)))
              }
              className="border-line-strong bg-surface min-w-0 flex-1 rounded-md border px-2 py-1"
            >
              {c.candidates.map((cand, k) => (
                <option key={k} value={`cand:${k}`}>
                  Suggested: {describe(cand)}
                </option>
              ))}
              <optgroup label="All columns">
                {columns.map((o) => (
                  <option
                    key={`${o.table}.${o.column}`}
                    value={`col:${o.table}.${o.column}`}
                  >
                    {o.table}.{o.label}
                    {o.type ? ` (${o.type})` : ""}
                  </option>
                ))}
              </optgroup>
              <option value={GAP}>No column measures this (gap)</option>
            </select>
            {choice[i] !== GAP && !isExpression(c, choice[i]) && (
              <select
                aria-label={`Match type for ${c.name}`}
                value={match[i]}
                onChange={(e) =>
                  setMatch(
                    match.map((v, j) =>
                      j === i ? (e.target.value as MatchType) : v,
                    ),
                  )
                }
                className="border-line-strong bg-surface rounded-md border px-2 py-1"
              >
                <option value="direct">direct</option>
                <option value="proxy">proxy</option>
              </select>
            )}
          </div>
        </fieldset>
      ))}
      <label className="flex flex-col gap-1">
        <span className="font-medium">
          Population filter{" "}
          <span className="text-subtle font-normal">
            (SQL condition, empty for all rows)
          </span>
        </span>
        <input
          value={population}
          onChange={(e) => setPopulation(e.target.value)}
          placeholder={`species = 'Gentoo'`}
          className="border-line-strong bg-surface rounded-md border px-2 py-1 font-mono text-xs"
        />
      </label>
      {error && (
        <p role="alert" className="text-red-700 dark:text-red-400">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <button disabled={pending} className="btn btn-primary btn-sm">
          {pending ? "Saving…" : "Save and re-assess"}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="border-line-strong rounded-md border px-3 py-1.5 text-xs"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

function initialChoice(c: MappedConstruct): string {
  if (c.status === "rejected" || c.candidates.length === 0) return GAP;
  return "cand:0";
}

function isExpression(c: MappedConstruct, value: string): boolean {
  return (
    value.startsWith("cand:") &&
    !!c.candidates[Number(value.slice(5))]?.expression
  );
}

function describe(c: Candidate): string {
  return c.expression
    ? `${c.table}: ${c.expression}`
    : `${c.table}.${c.column}`;
}

function applyChoice(
  c: MappedConstruct,
  value: string,
  match: MatchType,
): MappedConstruct {
  if (value === GAP) return { ...c, status: "rejected" };
  if (value.startsWith("cand:")) {
    const k = Number(value.slice(5));
    const original = c.candidates[k];
    // An expression is always a derived value; only plain columns can be direct or proxy.
    const picked = {
      ...original,
      match: original.expression ? "derivable" : match,
    } as Candidate;
    const rest = c.candidates.filter((_, j) => j !== k);
    return { ...c, status: "confirmed", candidates: [picked, ...rest] };
  }
  const [table, ...columnParts] = value.slice(4).split(".");
  const candidate: Candidate = {
    table,
    column: columnParts.join("."),
    expression: null,
    match,
    kind: null,
    justification: "Chosen by the researcher.",
  };
  return {
    ...c,
    status: "confirmed",
    candidates: [candidate, ...c.candidates].slice(0, 3),
  };
}
