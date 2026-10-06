"use client";

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

function check(file: File): string | undefined {
  if (!file.name.toLowerCase().endsWith(".csv"))
    return "Only .csv files are accepted.";
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
    <div className="flex flex-col gap-2 rounded-lg border border-dashed border-zinc-300 p-4 dark:border-zinc-700">
      <label className="text-sm font-medium" htmlFor="csv-upload">
        Upload CSV files
      </label>
      <input
        id="csv-upload"
        type="file"
        accept=".csv,text/csv"
        multiple
        disabled={busy}
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          e.target.value = "";
          if (files.length) void uploadAll(files);
        }}
        className="text-sm file:mr-3 file:rounded-md file:border-0 file:bg-zinc-900 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-white hover:file:bg-zinc-700 dark:file:bg-zinc-100 dark:file:text-zinc-900"
      />
      <p className="text-xs text-zinc-500">
        Select one or more files, up to 500 MB each. Each file becomes its own
        table.
      </p>

      {items.length > 0 && (
        <ul className="mt-1 flex flex-col gap-2">
          {items.map((i) => (
            <li key={i.key} className="text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="truncate">{i.name}</span>
                <span
                  className={`shrink-0 text-xs ${i.state === "error" ? "text-red-600" : "text-zinc-500"}`}
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
                  className="mt-1 h-1.5 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800"
                >
                  <div
                    className="h-full bg-zinc-900 transition-[width] dark:bg-zinc-100"
                    style={{ width: `${i.progress * 100}%` }}
                  />
                </div>
              )}
              {i.error && <p className="text-xs text-red-600">{i.error}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
