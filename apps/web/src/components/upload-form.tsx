"use client";

import { FileSpreadsheet, UploadCloud } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

const MAX_BYTES = 500 * 1024 * 1024;

type Item = {
  key: string;
  name: string;
  state: "waiting" | "uploading" | "done" | "error";
  progress: number;
  error?: string;
};

const ACCEPTED = [
  ".csv",
  ".tsv",
  ".txt",
  ".xlsx",
  ".xlsm",
  ".sav",
  ".zsav",
  ".por",
  ".dta",
  ".parquet",
  ".pq",
];

function check(file: File): string | undefined {
  const name = file.name.toLowerCase();
  if (name.endsWith(".xls"))
    return "Old Excel files (.xls) are not supported. Save it as .xlsx and upload again.";
  if (!ACCEPTED.some((ext) => name.endsWith(ext)))
    return "Upload CSV, Excel (.xlsx), SPSS (.sav), Stata (.dta) or Parquet files.";
  if (file.size > MAX_BYTES) return "The file is larger than 500 MB.";
  if (file.size === 0) return "The file is empty.";
}

/** Upload one file with progress; resolves to an error message or undefined. */
function send(
  projectId: number,
  file: File,
  onProgress: (share: number) => void,
): Promise<string | undefined> {
  return new Promise((resolve) => {
    const body = new FormData();
    body.append("file", file);
    // XMLHttpRequest rather than fetch, for upload progress events.
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/projects/${projectId}/datasets`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) return resolve(undefined);
      let detail = `Upload failed (${xhr.status}).`;
      try {
        detail = JSON.parse(xhr.responseText).detail ?? detail;
      } catch {}
      resolve(detail);
    };
    xhr.onerror = () => resolve("Upload failed: network error.");
    xhr.send(body);
  });
}

export function UploadForm({ projectId }: { projectId: number }) {
  const router = useRouter();
  const [items, setItems] = useState<Item[]>([]);
  const [dragging, setDragging] = useState(false);
  const busy = items.some(
    (i) => i.state === "waiting" || i.state === "uploading",
  );

  function update(key: string, patch: Partial<Item>) {
    setItems((all) => all.map((i) => (i.key === key ? { ...i, ...patch } : i)));
  }

  async function uploadAll(files: File[]) {
    const batch = files.map((file, n) => ({
      file,
      item: {
        key: `${Date.now()}-${n}-${file.name}`,
        name: file.name,
        state: "waiting",
        progress: 0,
        error: check(file),
      } satisfies Item as Item,
    }));
    for (const b of batch) if (b.item.error) b.item.state = "error";
    // Keep earlier errors visible; drop finished uploads from earlier batches.
    setItems((all) => [
      ...all.filter((i) => i.state === "error"),
      ...batch.map((b) => b.item),
    ]);

    // One at a time: the server profiles files in order anyway, and a single
    // upload at a time keeps progress readable on slow connections.
    for (const { file, item } of batch) {
      if (item.state === "error") continue;
      update(item.key, { state: "uploading" });
      const error = await send(projectId, file, (progress) =>
        update(item.key, { progress }),
      );
      update(
        item.key,
        error ? { state: "error", error } : { state: "done", progress: 1 },
      );
      if (!error) router.refresh();
    }
  }

  return (
    <div data-edit className="flex flex-col gap-3">
      <label
        htmlFor="csv-upload"
        onDragOver={(e) => {
          e.preventDefault();
          if (!busy) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const files = Array.from(e.dataTransfer.files ?? []);
          if (!busy && files.length) void uploadAll(files);
        }}
        data-dragging={dragging || undefined}
        className="group border-line-strong bg-surface hover:border-brand/60 hover:bg-brand-soft/30 data-[dragging]:border-brand data-[dragging]:bg-brand-soft/50 flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed px-6 py-8 text-center transition"
      >
        <span className="bg-brand-soft text-brand-fg grid h-10 w-10 place-items-center rounded-full transition group-hover:scale-105">
          <UploadCloud className="h-5 w-5" aria-hidden />
        </span>
        <span className="text-sm font-medium">
          {busy ? "Uploading…" : "Drop data files here, or click to choose"}
        </span>
        <span className="text-subtle text-xs">
          CSV, Excel, SPSS, Stata or Parquet · up to 500 MB each · every file
          becomes its own table
        </span>
        <input
          id="csv-upload"
          type="file"
          accept={ACCEPTED.join(",")}
          multiple
          disabled={busy}
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            e.target.value = "";
            if (files.length) void uploadAll(files);
          }}
          className="sr-only"
        />
      </label>

      {items.length > 0 && (
        <ul className="card divide-line flex flex-col divide-y">
          {items.map((i) => (
            <li key={i.key} className="flex flex-col gap-1.5 px-4 py-3 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="flex min-w-0 items-center gap-2">
                  <FileSpreadsheet
                    className="text-subtle h-4 w-4 shrink-0"
                    aria-hidden
                  />
                  <span className="truncate">{i.name}</span>
                </span>
                <span
                  className={`shrink-0 text-xs font-medium ${
                    i.state === "error"
                      ? "text-red-600 dark:text-red-400"
                      : i.state === "done"
                        ? "text-emerald-600 dark:text-emerald-400"
                        : "text-subtle"
                  }`}
                >
                  {i.state === "waiting" && "Waiting"}
                  {i.state === "uploading" &&
                    `${Math.round(i.progress * 100)}%`}
                  {i.state === "done" && "Uploaded"}
                  {i.state === "error" && "Failed"}
                </span>
              </div>
              {i.state === "uploading" && (
                <div
                  role="progressbar"
                  aria-label={`Uploading ${i.name}`}
                  aria-valuenow={Math.round(i.progress * 100)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  className="bg-surface-3 h-1.5 overflow-hidden rounded-full"
                >
                  <div
                    className="bg-brand h-full rounded-full transition-[width]"
                    style={{ width: `${i.progress * 100}%` }}
                  />
                </div>
              )}
              {i.error && (
                <p className="text-xs text-red-600 dark:text-red-400">
                  {i.error}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
