"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

type Result = { matched: number; unmatched: string[] };

export function DictionaryUpload({
  projectId,
  datasetId,
}: {
  projectId: number;
  datasetId: number;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    setResult(null);
    const body = new FormData();
    body.append("file", file);
    try {
      const res = await fetch(
        `/api/projects/${projectId}/datasets/${datasetId}/dictionary`,
        { method: "POST", body },
      );
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail ?? `Upload failed (${res.status}).`);
      } else {
        setResult(data);
        router.refresh();
      }
    } catch {
      setError("Upload failed: network error.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
      <label htmlFor="dictionary" className="text-sm font-medium">
        Data dictionary (optional)
      </label>
      <p className="text-xs text-zinc-500">
        A CSV with a column-name column (such as &quot;variable&quot;) and a
        description column (such as &quot;label&quot;). Its descriptions replace
        AI suggestions but not ones you wrote.
      </p>
      <input
        id="dictionary"
        type="file"
        accept=".csv,text/csv"
        disabled={busy}
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) void upload(file);
        }}
        className="text-sm file:mr-3 file:rounded-md file:border-0 file:bg-zinc-200 file:px-3 file:py-1 file:text-sm hover:file:bg-zinc-300 dark:file:bg-zinc-800 dark:file:text-zinc-100"
      />
      {busy && <p className="text-xs text-zinc-500">Uploading…</p>}
      {result && (
        <p className="text-sm">
          Matched {result.matched} column{result.matched === 1 ? "" : "s"}.
          {result.unmatched.length > 0 &&
            ` Not found in this dataset: ${result.unmatched.slice(0, 10).join(", ")}${result.unmatched.length > 10 ? "…" : ""}.`}
        </p>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}
