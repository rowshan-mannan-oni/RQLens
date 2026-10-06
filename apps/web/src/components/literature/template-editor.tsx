"use client";

import { ArrowDown, ArrowUp, Copy, Lock, Plus, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import {
  deleteTemplate,
  saveTemplate,
} from "@/app/projects/[id]/literature/actions";
import type { ColumnKind, ReviewTemplate, TemplateColumn } from "@/lib/types";

type Draft = {
  key: string | null; // user:<id> when editing a saved template
  name: string;
  description: string;
  columns: (TemplateColumn & { uid: number })[];
};

let uid = 0;
const blankColumn = (): Draft["columns"][number] => ({
  uid: ++uid,
  key: "",
  label: "",
  instructions: "",
  kind: "text",
  options: [],
  required: false,
  metadata: null,
});

function draftFrom(t: ReviewTemplate, copy: boolean): Draft {
  return {
    key: copy ? null : t.key,
    name: copy ? `${t.name} (copy)` : t.name,
    description: t.description,
    columns: t.columns.map((c) => ({ ...c, uid: ++uid })),
  };
}

export function TemplateEditor({
  projectId,
  templates,
}: {
  projectId: number;
  templates: ReviewTemplate[];
}) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>(() => {
    const own = templates.find((t) => !t.builtin);
    return own
      ? draftFrom(own, false)
      : { key: null, name: "", description: "", columns: [blankColumn()] };
  });

  const setColumn = (i: number, patch: Partial<TemplateColumn>) =>
    setDraft({
      ...draft,
      columns: draft.columns.map((c, j) => (j === i ? { ...c, ...patch } : c)),
    });
  const moveColumn = (i: number, d: -1 | 1) => {
    const cols = [...draft.columns];
    [cols[i], cols[i + d]] = [cols[i + d], cols[i]];
    setDraft({ ...draft, columns: cols });
  };

  function save() {
    setSaved(null);
    if (!draft.name.trim()) return setError("Give the template a name.");
    if (!draft.columns.length) return setError("Add at least one column.");
    const bad = draft.columns.find((c) => !c.label.trim());
    if (bad) return setError("Every column needs a label.");
    const cat = draft.columns.find(
      (c) => c.kind === "category" && c.options.length < 2,
    );
    if (cat) return setError(`"${cat.label}" needs at least two options.`);
    start(async () => {
      const res = await saveTemplate(projectId, draft.key, {
        name: draft.name.trim(),
        description: draft.description.trim(),
        columns: draft.columns.map(({ uid: _uid, ...c }) => ({
          ...c,
          // Keys come from labels; a saved column keeps its key.
          key: c.key,
        })),
      });
      setError(res.error);
      if (!res.error && res.key) {
        setDraft({ ...draft, key: res.key });
        setSaved("Saved. Use it when you create a table.");
        router.refresh();
      }
    });
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[16rem_minmax(0,1fr)]">
      <nav aria-label="Templates" className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <p className="eyebrow px-2">Your templates</p>
          {templates.filter((t) => !t.builtin).length === 0 && (
            <p className="text-subtle px-2 text-xs">None yet.</p>
          )}
          {templates
            .filter((t) => !t.builtin)
            .map((t) => (
              <button
                key={t.key}
                type="button"
                aria-current={draft.key === t.key ? "true" : undefined}
                onClick={() => {
                  setDraft(draftFrom(t, false));
                  setError(null);
                  setSaved(null);
                }}
                className="hover:bg-surface-3 aria-[current=true]:bg-brand-soft aria-[current=true]:text-brand-fg rounded-lg px-2 py-1.5 text-left text-sm"
              >
                {t.name}
              </button>
            ))}
          <button
            type="button"
            className="btn btn-secondary btn-sm mt-1"
            onClick={() => {
              setDraft({
                key: null,
                name: "",
                description: "",
                columns: [blankColumn()],
              });
              setError(null);
              setSaved(null);
            }}
          >
            <Plus className="h-3.5 w-3.5" aria-hidden />
            New template
          </button>
        </div>
        <div className="flex flex-col gap-1">
          <p className="eyebrow px-2">Built in</p>
          {templates
            .filter((t) => t.builtin)
            .map((t) => (
              <div
                key={t.key}
                className="flex items-center justify-between gap-2 px-2 py-1 text-sm"
              >
                <span className="text-muted flex min-w-0 items-center gap-1.5">
                  <Lock className="h-3 w-3 shrink-0" aria-hidden />
                  <span className="truncate">{t.name}</span>
                </span>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  title="Start a new template from this one"
                  onClick={() => {
                    setDraft(draftFrom(t, true));
                    setError(null);
                    setSaved(null);
                  }}
                >
                  <Copy className="h-3.5 w-3.5" aria-hidden />
                  Copy
                </button>
              </div>
            ))}
        </div>
      </nav>

      <div className="card flex flex-col gap-5 p-5">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1">
            <span className="label">Template name</span>
            <input
              className="input"
              value={draft.name}
              maxLength={200}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="label">Description</span>
            <input
              className="input"
              value={draft.description}
              maxLength={2000}
              onChange={(e) =>
                setDraft({ ...draft, description: e.target.value })
              }
            />
          </label>
        </div>

        <ol className="flex flex-col gap-3">
          {draft.columns.map((c, i) => (
            <li key={c.uid} className="card-muted flex flex-col gap-3 p-4">
              <div className="flex items-center gap-2">
                <span className="text-subtle w-6 text-xs tabular-nums">
                  {i + 1}.
                </span>
                <input
                  className="input flex-1"
                  placeholder="Column label, e.g. Sample size"
                  value={c.label}
                  maxLength={120}
                  aria-label={`Column ${i + 1} label`}
                  onChange={(e) => setColumn(i, { label: e.target.value })}
                />
                <select
                  className="input w-36"
                  value={c.kind}
                  aria-label={`Column ${i + 1} kind`}
                  onChange={(e) =>
                    setColumn(i, { kind: e.target.value as ColumnKind })
                  }
                >
                  <option value="text">Text</option>
                  <option value="list">List</option>
                  <option value="number">Number</option>
                  <option value="category">Category</option>
                </select>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  disabled={i === 0}
                  onClick={() => moveColumn(i, -1)}
                  aria-label="Move up"
                >
                  <ArrowUp className="h-3.5 w-3.5" aria-hidden />
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  disabled={i === draft.columns.length - 1}
                  onClick={() => moveColumn(i, 1)}
                  aria-label="Move down"
                >
                  <ArrowDown className="h-3.5 w-3.5" aria-hidden />
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm hover:text-red-600"
                  onClick={() =>
                    setDraft({
                      ...draft,
                      columns: draft.columns.filter((_, j) => j !== i),
                    })
                  }
                  aria-label="Remove column"
                >
                  <Trash2 className="h-3.5 w-3.5" aria-hidden />
                </button>
              </div>
              <textarea
                className="input text-sm"
                rows={2}
                placeholder="Instructions for the AI: what to extract, and when to answer not found."
                value={c.instructions}
                maxLength={2000}
                aria-label={`Column ${i + 1} instructions`}
                onChange={(e) => setColumn(i, { instructions: e.target.value })}
              />
              {c.kind === "category" && (
                <label className="flex flex-col gap-1">
                  <span className="text-muted text-xs">
                    Options, one per line
                  </span>
                  <textarea
                    className="input text-sm"
                    rows={3}
                    value={c.options.join("\n")}
                    onChange={(e) =>
                      setColumn(i, {
                        options: e.target.value.split("\n"),
                      })
                    }
                    onBlur={(e) =>
                      setColumn(i, {
                        options: e.target.value
                          .split("\n")
                          .map((o) => o.trim())
                          .filter(Boolean),
                      })
                    }
                  />
                </label>
              )}
              <div className="text-muted flex flex-wrap items-center gap-4 text-xs">
                <label className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={c.required}
                    onChange={(e) =>
                      setColumn(i, { required: e.target.checked })
                    }
                  />
                  Required
                </label>
                <label className="flex items-center gap-1.5">
                  Fill from the PDF&rsquo;s details:
                  <select
                    className="input w-auto py-0.5 text-xs"
                    value={c.metadata ?? ""}
                    onChange={(e) =>
                      setColumn(i, {
                        metadata: (e.target.value ||
                          null) as TemplateColumn["metadata"],
                      })
                    }
                  >
                    <option value="">No (AI extracts it)</option>
                    <option value="title">Title</option>
                    <option value="authors">Authors</option>
                    <option value="year">Year</option>
                    <option value="venue">Venue</option>
                    <option value="doi">DOI</option>
                  </select>
                </label>
              </div>
            </li>
          ))}
        </ol>

        <button
          type="button"
          className="btn btn-secondary w-fit"
          onClick={() =>
            setDraft({ ...draft, columns: [...draft.columns, blankColumn()] })
          }
        >
          <Plus className="h-4 w-4" aria-hidden />
          Add column
        </button>

        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
        {saved && (
          <p
            role="status"
            className="text-sm text-emerald-700 dark:text-emerald-400"
          >
            {saved}
          </p>
        )}
        <div className="border-line flex flex-wrap items-center gap-2 border-t pt-4">
          <button
            type="button"
            className="btn btn-primary"
            disabled={pending}
            onClick={save}
          >
            {pending ? "Saving…" : draft.key ? "Save changes" : "Save template"}
          </button>
          {draft.key && (
            <button
              type="button"
              className="btn btn-danger"
              disabled={pending}
              onClick={() => {
                if (
                  !confirm(
                    `Delete the template "${draft.name}"? Tables made from it keep their columns.`,
                  )
                )
                  return;
                start(async () => {
                  const res = await deleteTemplate(projectId, draft.key!);
                  setError(res.error);
                  if (!res.error) {
                    setDraft({
                      key: null,
                      name: "",
                      description: "",
                      columns: [blankColumn()],
                    });
                    router.refresh();
                  }
                });
              }}
            >
              Delete template
            </button>
          )}
          <p className="text-subtle ml-auto text-xs">
            Tables keep their own copy of the columns, so editing a template
            does not change existing tables.
          </p>
        </div>
      </div>
    </div>
  );
}
