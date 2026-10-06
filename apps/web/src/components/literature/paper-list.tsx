"use client";

import {
  AlertTriangle,
  FileText,
  Folder,
  LoaderCircle,
  Pencil,
  RotateCw,
  ScanText,
  Trash2,
} from "lucide-react";
import { useActionState, useId, useRef, useTransition } from "react";

import {
  deletePaper,
  reparsePaper,
  updatePaper,
} from "@/app/projects/[id]/literature/actions";
import type { ActionState } from "@/components/confirm-dialog";
import { formatBytes } from "@/lib/format";
import type { Paper } from "@/lib/types";

const STATUS: Record<Paper["status"], { label: string; className: string }> = {
  queued: { label: "Waiting", className: "badge-neutral" },
  parsing: { label: "Reading", className: "badge-brand" },
  ready: { label: "Ready", className: "badge-success" },
  needs_ocr: { label: "Needs OCR", className: "badge-warning" },
  failed: { label: "Failed", className: "badge-danger" },
};

export function PaperList({
  projectId,
  papers,
}: {
  projectId: number;
  papers: Paper[];
}) {
  const groups = new Map<string, Paper[]>();
  for (const p of papers) {
    const key = p.folder ?? "";
    groups.set(key, [...(groups.get(key) ?? []), p]);
  }
  return (
    <div className="card divide-line divide-y overflow-hidden">
      {[...groups.entries()].map(([folder, items]) => (
        <section key={folder || "-"}>
          {(groups.size > 1 || folder) && (
            <h3 className="bg-surface-2 text-muted flex items-center gap-1.5 px-4 py-2 text-xs font-medium">
              <Folder className="h-3.5 w-3.5" aria-hidden />
              {folder || "No folder"}
              <span className="text-subtle">· {items.length}</span>
            </h3>
          )}
          <ul className="divide-line divide-y">
            {items.map((p) => (
              <PaperRow key={p.id} projectId={projectId} paper={p} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function PaperRow({
  projectId,
  paper: p,
}: {
  projectId: number;
  paper: Paper;
}) {
  const [pending, start] = useTransition();
  const status = STATUS[p.status];
  const authors = p.authors_json ?? [];
  return (
    <li className="flex items-start gap-3 px-4 py-3">
      <span className="bg-surface-3 text-subtle mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg">
        {p.status === "needs_ocr" ? (
          <ScanText className="h-4 w-4" aria-hidden />
        ) : (
          <FileText className="h-4 w-4" aria-hidden />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <p
          className="truncate text-sm font-medium"
          title={p.title ?? p.filename}
        >
          {p.title ?? p.filename}
        </p>
        <p className="text-muted truncate text-xs">
          {authors.length > 0 &&
            `${authors.slice(0, 3).join(", ")}${authors.length > 3 ? " et al." : ""} · `}
          {p.year && `${p.year} · `}
          {p.title ? p.filename : formatBytes(p.size_bytes)}
          {p.page_count != null && ` · ${p.page_count} pages`}
          {p.passage_count != null && ` · ${p.passage_count} passages`}
        </p>
        {p.error && (
          <p className="mt-1 flex items-start gap-1 text-xs text-amber-700 dark:text-amber-400">
            <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
            {p.error}
          </p>
        )}
      </div>
      {p.ocr_pages_json && p.ocr_pages_json.length > 0 && (
        <span
          className="badge badge-neutral shrink-0"
          title={`Read with OCR: page${p.ocr_pages_json.length > 1 ? "s" : ""} ${p.ocr_pages_json.join(", ")}`}
        >
          OCR
        </span>
      )}
      <span className={`badge ${status.className} shrink-0`}>
        {(p.status === "queued" || p.status === "parsing") && (
          <LoaderCircle className="h-3 w-3 animate-spin" aria-hidden />
        )}
        {status.label}
      </span>
      <div className="flex shrink-0 items-center gap-1">
        {p.status === "ready" && (
          <MetadataDialog projectId={projectId} paper={p} />
        )}
        {(p.status === "failed" || p.status === "needs_ocr") && (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            title="Read the PDF again"
            aria-label={`Read ${p.filename} again`}
            disabled={pending}
            onClick={() =>
              start(async () => void (await reparsePaper(projectId, p.id)))
            }
          >
            <RotateCw className="h-4 w-4" aria-hidden />
          </button>
        )}
        <button
          type="button"
          className="btn btn-ghost btn-sm hover:text-red-600"
          title="Delete paper"
          aria-label={`Delete ${p.filename}`}
          disabled={pending}
          onClick={() => {
            if (
              confirm(
                `Delete "${p.title ?? p.filename}"? Its row is removed from every literature table.`,
              )
            )
              start(async () => void (await deletePaper(projectId, p.id)));
          }}
        >
          <Trash2 className="h-4 w-4" aria-hidden />
        </button>
      </div>
    </li>
  );
}

function MetadataDialog({
  projectId,
  paper: p,
}: {
  projectId: number;
  paper: Paper;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [state, action, pending] = useActionState(
    async (prev: ActionState, data: FormData) => {
      const res = await updatePaper(projectId, p.id, prev, data);
      if (!res.error) dialog.current?.close();
      return res;
    },
    { error: null },
  );
  const field = (name: string, label: string, value: string, hint?: string) => (
    <label className="flex flex-col gap-1">
      <span className="label">{label}</span>
      <input name={name} defaultValue={value} className="input" />
      {hint && <span className="text-subtle text-xs">{hint}</span>}
    </label>
  );
  return (
    <>
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        title="Correct title, authors and year"
        aria-label={`Edit details of ${p.filename}`}
        onClick={() => dialog.current?.showModal()}
      >
        <Pencil className="h-4 w-4" aria-hidden />
      </button>
      <dialog
        ref={dialog}
        aria-labelledby={titleId}
        className="border-line bg-surface text-fg shadow-pop m-auto w-[calc(100%-2rem)] max-w-lg rounded-2xl border p-0 backdrop:bg-black/40"
      >
        <form action={action} className="flex flex-col gap-3 p-6">
          <h2 id={titleId} className="text-lg font-semibold tracking-tight">
            Paper details
          </h2>
          <p className="text-muted text-sm">
            Read from the PDF. Your corrections are kept when the paper is read
            again, and fill the title, author and year columns.
          </p>
          {field("title", "Title", p.title ?? "")}
          {field(
            "authors",
            "Authors",
            (p.authors_json ?? []).join("; "),
            "Separate names with semicolons.",
          )}
          <div className="grid grid-cols-[6rem_1fr] gap-3">
            {field("year", "Year", p.year ? String(p.year) : "")}
            {field("venue", "Venue", p.venue ?? "")}
          </div>
          {field("doi", "DOI", p.doi ?? "")}
          {state.error && (
            <p role="alert" className="text-sm text-red-600">
              {state.error}
            </p>
          )}
          <div className="mt-2 flex justify-end gap-2">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => dialog.current?.close()}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={pending}
            >
              {pending ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      </dialog>
    </>
  );
}
