"use client";

import { BookMarked, FileText, LoaderCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { clearReferences } from "@/app/projects/[id]/literature/actions";
import type { ReferenceEntry } from "@/lib/types";

type Result = { entries: number; matched: number; updated_papers: number };

/** Import a BibTeX or RIS export (Zotero, Mendeley, EndNote) to fill paper details. */
export function ReferenceImport({
  projectId,
  entries,
}: {
  projectId: number;
  entries: ReferenceEntry[];
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const waiting = entries.filter((e) => e.paper_id == null);
  const matched = entries.length - waiting.length;

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    const body = new FormData();
    body.append("file", file);
    const res = await fetch(`/api/projects/${projectId}/papers/references`, {
      method: "POST",
      body,
    });
    const data = await res.json().catch(() => ({}));
    setBusy(false);
    if (!res.ok)
      return setError(data.detail ?? `Import failed (${res.status}).`);
    setResult(data);
    router.refresh();
  }

  return (
    <div data-edit className="card flex flex-col gap-3 p-5">
      <h3 className="flex items-center gap-2 font-semibold">
        <BookMarked className="text-brand h-4 w-4" aria-hidden />
        Reference library
      </h3>
      <p className="text-muted text-xs leading-relaxed">
        Import a BibTeX or RIS export from Zotero, Mendeley or EndNote. Papers
        get their exact title, authors, year, venue and citation key; entries
        whose PDF is not uploaded yet are matched when it is.
      </p>
      <label
        className={`btn btn-secondary btn-sm cursor-pointer ${busy ? "pointer-events-none opacity-50" : ""}`}
      >
        {busy ? (
          <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden />
        ) : (
          <FileText className="h-3.5 w-3.5" aria-hidden />
        )}
        {busy ? "Importing…" : "Import .bib or .ris"}
        <input
          type="file"
          accept=".bib,.bibtex,.ris,.txt"
          className="sr-only"
          disabled={busy}
          onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (f) void upload(f);
          }}
        />
      </label>
      {error && (
        <p role="alert" className="text-xs text-red-600">
          {error}
        </p>
      )}
      {result && (
        <p
          role="status"
          className="text-xs text-emerald-700 dark:text-emerald-400"
        >
          {result.entries} entries read; {result.matched} matched to papers,{" "}
          {result.updated_papers} paper{result.updated_papers === 1 ? "" : "s"}{" "}
          updated.
        </p>
      )}
      {entries.length > 0 && (
        <div className="text-muted flex flex-col gap-2 text-xs">
          <p>
            {entries.length} entries · {matched} matched
            {waiting.length > 0 && ` · ${waiting.length} waiting for a PDF`}
          </p>
          {waiting.length > 0 && (
            <details>
              <summary className="link cursor-pointer">
                Show papers to upload
              </summary>
              <ul className="mt-2 flex max-h-56 flex-col gap-1.5 overflow-y-auto">
                {waiting.map((e) => (
                  <li key={e.id} className="leading-snug">
                    <span className="text-fg">{e.title ?? e.cite_key}</span>
                    {e.year && ` (${e.year})`}
                    {e.files_json?.length ? (
                      <span className="text-subtle block font-mono text-[11px]">
                        {e.files_json.join(", ")}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </details>
          )}
          <button
            type="button"
            className="link w-fit"
            disabled={pending}
            onClick={() => {
              if (
                confirm(
                  "Forget the imported entries? Details already copied to papers stay.",
                )
              )
                start(async () => {
                  const res = await clearReferences(projectId);
                  setError(res.error);
                  setResult(null);
                });
            }}
          >
            Forget imported entries
          </button>
        </div>
      )}
    </div>
  );
}
