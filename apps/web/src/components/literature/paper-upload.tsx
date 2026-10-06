"use client";

import { FileText, FolderOpen, UploadCloud } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

const MAX_BYTES = 50 * 1024 * 1024;
const PARALLEL = 3;

type Item = {
  key: string;
  name: string;
  folder: string;
  state: "waiting" | "uploading" | "done" | "skipped" | "error";
  progress: number;
  message?: string;
};

type Picked = { file: File; folder: string };

function check(file: File): string | undefined {
  if (!file.name.toLowerCase().endsWith(".pdf")) return "Not a PDF.";
  if (file.size > MAX_BYTES) return "The file is larger than 50 MB.";
  if (file.size === 0) return "The file is empty.";
}

function dirname(path: string): string {
  const parts = path.split("/").filter(Boolean);
  return parts.slice(0, -1).join("/");
}

/** Upload one PDF with progress. Resolves to [state, message]. */
function send(
  projectId: number,
  { file, folder }: Picked,
  onProgress: (share: number) => void,
): Promise<[Item["state"], string | undefined]> {
  return new Promise((resolve) => {
    const body = new FormData();
    body.append("file", file);
    if (folder) body.append("folder", folder);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/projects/${projectId}/papers`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300)
        return resolve(["done", undefined]);
      let detail = `Upload failed (${xhr.status}).`;
      try {
        detail = JSON.parse(xhr.responseText).detail ?? detail;
      } catch {}
      resolve([xhr.status === 409 ? "skipped" : "error", detail]);
    };
    xhr.onerror = () => resolve(["error", "Upload failed: network error."]);
    xhr.send(body);
  });
}

/** Every file inside a dropped folder, with its path relative to the drop. */
async function readEntry(entry: FileSystemEntry): Promise<Picked[]> {
  if (entry.isFile) {
    const file = await new Promise<File>((ok, fail) =>
      (entry as FileSystemFileEntry).file(ok, fail),
    );
    return [{ file, folder: dirname(entry.fullPath) }];
  }
  if (!entry.isDirectory) return [];
  const reader = (entry as FileSystemDirectoryEntry).createReader();
  const children: FileSystemEntry[] = [];
  // readEntries returns at most ~100 entries per call; read until empty.
  for (;;) {
    const batch = await new Promise<FileSystemEntry[]>((ok, fail) =>
      reader.readEntries(ok, fail),
    );
    if (!batch.length) break;
    children.push(...batch);
  }
  const nested = await Promise.all(children.map(readEntry));
  return nested.flat();
}

export function PaperUpload({ projectId }: { projectId: number }) {
  const router = useRouter();
  const [items, setItems] = useState<Item[]>([]);
  const [dragging, setDragging] = useState(false);
  const busy = items.some(
    (i) => i.state === "waiting" || i.state === "uploading",
  );
  const done = items.filter((i) => i.state === "done").length;
  const ignored = items.filter((i) => i.state === "skipped").length;

  function update(key: string, patch: Partial<Item>) {
    setItems((all) => all.map((i) => (i.key === key ? { ...i, ...patch } : i)));
  }

  async function uploadAll(picked: Picked[]) {
    // A folder can hold other files too; only PDFs are uploaded.
    const pdfs = picked.filter((p) =>
      p.file.name.toLowerCase().endsWith(".pdf"),
    );
    const stamp = Date.now();
    const batch = pdfs.map((p, n) => {
      const error = check(p.file);
      const item: Item = {
        key: `${stamp}-${n}`,
        name: p.file.name,
        folder: p.folder,
        state: error ? "error" : "waiting",
        progress: 0,
        message: error,
      };
      return { picked: p, item };
    });
    if (!batch.length) {
      setItems((all) => [
        ...all,
        {
          key: `${stamp}-none`,
          name: "No PDF files found",
          folder: "",
          state: "error",
          progress: 0,
          message: "Choose PDF files, or a folder that contains them.",
        },
      ]);
      return;
    }
    setItems((all) => [
      ...all.filter((i) => i.state === "error"),
      ...batch.map((b) => b.item),
    ]);

    const queue = batch.filter((b) => b.item.state === "waiting");
    let refreshed = 0;
    async function worker() {
      for (let b = queue.shift(); b; b = queue.shift()) {
        update(b.item.key, { state: "uploading" });
        const [state, message] = await send(projectId, b.picked, (progress) =>
          update(b.item.key, { progress }),
        );
        update(b.item.key, { state, message, progress: 1 });
        // Refresh now and then so new papers appear without one refresh per file.
        if (state === "done" && Date.now() - refreshed > 1500) {
          refreshed = Date.now();
          router.refresh();
        }
      }
    }
    await Promise.all(Array.from({ length: PARALLEL }, worker));
    router.refresh();
  }

  return (
    <div className="flex flex-col gap-3">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!busy) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={async (e) => {
          e.preventDefault();
          setDragging(false);
          if (busy) return;
          const entries = Array.from(e.dataTransfer.items ?? [])
            .map((i) => i.webkitGetAsEntry?.())
            .filter((x): x is FileSystemEntry => Boolean(x));
          const picked = entries.length
            ? (await Promise.all(entries.map(readEntry))).flat()
            : Array.from(e.dataTransfer.files ?? []).map((file) => ({
                file,
                folder: "",
              }));
          if (picked.length) void uploadAll(picked);
        }}
        data-dragging={dragging || undefined}
        className="border-line-strong bg-surface data-[dragging]:border-brand data-[dragging]:bg-brand-soft/50 flex flex-col items-center gap-3 rounded-xl border-2 border-dashed px-6 py-8 text-center transition"
      >
        <span className="bg-brand-soft text-brand-fg grid h-10 w-10 place-items-center rounded-full">
          <UploadCloud className="h-5 w-5" aria-hidden />
        </span>
        <span className="text-sm font-medium">
          {busy
            ? `Uploading… ${done} of ${items.length}`
            : "Drop PDFs or a whole folder here"}
        </span>
        <div className="flex flex-wrap justify-center gap-2">
          <label
            className={`btn btn-secondary btn-sm cursor-pointer ${busy ? "pointer-events-none opacity-50" : ""}`}
          >
            <FileText className="h-4 w-4" aria-hidden />
            Choose PDFs
            <input
              type="file"
              accept=".pdf,application/pdf"
              multiple
              disabled={busy}
              className="sr-only"
              onChange={(e) => {
                const files = Array.from(e.target.files ?? []);
                e.target.value = "";
                if (files.length)
                  void uploadAll(files.map((file) => ({ file, folder: "" })));
              }}
            />
          </label>
          <label
            className={`btn btn-secondary btn-sm cursor-pointer ${busy ? "pointer-events-none opacity-50" : ""}`}
          >
            <FolderOpen className="h-4 w-4" aria-hidden />
            Choose a folder
            <input
              type="file"
              multiple
              disabled={busy}
              className="sr-only"
              // Non-standard but supported by every current browser.
              {...{ webkitdirectory: "", directory: "" }}
              onChange={(e) => {
                const files = Array.from(e.target.files ?? []);
                e.target.value = "";
                if (files.length)
                  void uploadAll(
                    files.map((file) => ({
                      file,
                      folder: dirname(file.webkitRelativePath || file.name),
                    })),
                  );
              }}
            />
          </label>
        </div>
        <span className="text-subtle text-xs">
          Up to 50 MB per PDF · subfolders become labels · duplicates are
          skipped
        </span>
      </div>

      {items.length > 0 && (
        <div className="card overflow-hidden">
          <div className="border-line text-muted flex items-center justify-between border-b px-4 py-2 text-xs">
            <span>
              {done} uploaded
              {ignored > 0 && ` · ${ignored} already in the project`}
              {items.some((i) => i.state === "error") &&
                ` · ${items.filter((i) => i.state === "error").length} failed`}
            </span>
            {!busy && (
              <button
                type="button"
                className="link"
                onClick={() => setItems([])}
              >
                Clear
              </button>
            )}
          </div>
          <ul className="divide-line flex max-h-64 flex-col divide-y overflow-y-auto">
            {items.map((i) => (
              <li key={i.key} className="flex flex-col gap-1 px-4 py-2 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span className="flex min-w-0 items-center gap-2">
                    <FileText
                      className="text-subtle h-4 w-4 shrink-0"
                      aria-hidden
                    />
                    <span className="truncate">
                      {i.folder && (
                        <span className="text-subtle">{i.folder}/</span>
                      )}
                      {i.name}
                    </span>
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
                    {i.state === "skipped" && "Skipped"}
                    {i.state === "error" && "Failed"}
                  </span>
                </div>
                {i.message && (
                  <p
                    className={`text-xs ${i.state === "error" ? "text-red-600 dark:text-red-400" : "text-subtle"}`}
                  >
                    {i.message}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
