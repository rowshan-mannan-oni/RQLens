"use client";

import {
  AlertTriangle,
  BadgeCheck,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  LoaderCircle,
  X,
} from "lucide-react";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import { useEffect, useMemo, useRef, useState } from "react";

import type { Citation, Paper, PassageInfo } from "@/lib/types";

// PDF.js is loaded on demand in the browser only; documents and passages are cached per paper.
// The legacy build includes polyfills: the modern one needs JavaScript features that many
// current browsers lack.
type PdfJs = typeof import("pdfjs-dist");
let pdfjsPromise: Promise<PdfJs> | null = null;
function loadPdfJs(): Promise<PdfJs> {
  pdfjsPromise ??= import("pdfjs-dist/legacy/build/pdf.mjs").then((pdfjs) => {
    pdfjs.GlobalWorkerOptions.workerSrc = new URL(
      "pdfjs-dist/legacy/build/pdf.worker.min.mjs",
      import.meta.url,
    ).toString();
    return pdfjs;
  });
  return pdfjsPromise;
}
const docs = new Map<string, Promise<PDFDocumentProxy>>();
const passageCache = new Map<string, Promise<PassageInfo[]>>();

function fileUrl(projectId: number, paperId: number) {
  return `/api/projects/${projectId}/papers/${paperId}/file`;
}

function getDoc(url: string) {
  if (!docs.has(url))
    docs.set(
      url,
      loadPdfJs().then((pdfjs) => pdfjs.getDocument({ url }).promise),
    );
  return docs.get(url)!;
}

function getPassages(projectId: number, paperId: number) {
  const url = `/api/projects/${projectId}/papers/${paperId}/passages`;
  if (!passageCache.has(url))
    passageCache.set(
      url,
      fetch(url).then((r) => {
        if (!r.ok) throw new Error(`Could not load passages (${r.status})`);
        return r.json();
      }),
    );
  return passageCache.get(url)!;
}

/** Wrap the quoted words inside the passage text in <mark>, comparing word by word and
 * ignoring case and punctuation (so a hyphenated line break still matches). */
function markQuote(text: string, quote: string) {
  const key = (w: string) => w.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
  const tokens = [...text.matchAll(/\S+/g)].map((m) => ({
    start: m.index,
    end: m.index + m[0].length,
    k: key(m[0]),
  }));
  const q = quote.split(/\s+/).map(key).filter(Boolean);
  if (!q.length) return text;
  for (let i = 0; i + q.length <= tokens.length; i++) {
    const hit = q.every((w, j) => {
      const t = tokens[i + j].k;
      if (q.length === 1) return t.includes(w);
      if (j === 0) return t.endsWith(w);
      if (j === q.length - 1) return t.startsWith(w);
      return t === w;
    });
    if (!hit) continue;
    const a = tokens[i].start;
    const b = tokens[i + q.length - 1].end;
    return (
      <>
        {text.slice(0, a)}
        <mark className="rounded bg-amber-200/70 px-0.5 text-inherit dark:bg-amber-400/30">
          {text.slice(a, b)}
        </mark>
        {text.slice(b)}
      </>
    );
  }
  return text;
}

export function PdfReader({
  projectId,
  paper,
  columnLabel,
  citations,
  index,
  onIndex,
  onClose,
}: {
  projectId: number;
  paper: Paper;
  columnLabel: string;
  citations: Citation[];
  index: number;
  onIndex: (i: number) => void;
  onClose: () => void;
}) {
  const citation = citations[index];
  const [passages, setPassages] = useState<Map<number, PassageInfo> | null>(
    null,
  );
  const [page, setPage] = useState(citation?.page ?? 1);
  const [pageCount, setPageCount] = useState(paper.page_count ?? 1);
  const [error, setError] = useState<string | null>(null);
  const [rendering, setRendering] = useState(true);
  const [size, setSize] = useState<{ w: number; h: number; scale: number }>();
  const canvas = useRef<HTMLCanvasElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    let live = true;
    getPassages(projectId, paper.id)
      .then((list) => live && setPassages(new Map(list.map((p) => [p.id, p]))))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [projectId, paper.id]);

  // Jump to the citation's page whenever another citation is shown.
  const citationKey = `${paper.id}:${citation?.label}:${index}`;
  const [shown, setShown] = useState(citationKey);
  if (shown !== citationKey) {
    setShown(citationKey);
    if (citation?.page) setPage(citation.page);
  }

  useEffect(() => {
    const el = frame.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) =>
      setWidth(Math.floor(e.contentRect.width)),
    );
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (!width || !canvas.current) return;
    let task: RenderTask | null = null;
    let live = true;
    setRendering(true);
    getDoc(fileUrl(projectId, paper.id))
      .then(async (doc) => {
        if (!live) return;
        setPageCount(doc.numPages);
        const p = await doc.getPage(Math.min(Math.max(page, 1), doc.numPages));
        const base = p.getViewport({ scale: 1 });
        const scale = width / base.width;
        const viewport = p.getViewport({ scale });
        const ratio = window.devicePixelRatio || 1;
        const el = canvas.current!;
        el.width = Math.floor(viewport.width * ratio);
        el.height = Math.floor(viewport.height * ratio);
        el.style.width = `${viewport.width}px`;
        el.style.height = `${viewport.height}px`;
        task = p.render({
          canvas: el,
          viewport,
          transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined,
        });
        await task.promise;
        if (!live) return;
        setSize({ w: viewport.width, h: viewport.height, scale });
        setError(null);
      })
      .catch((e: Error) => {
        if (live && e?.name !== "RenderingCancelledException")
          setError(`The PDF could not be shown: ${e.message}`);
      })
      .finally(() => live && setRendering(false));
    return () => {
      live = false;
      task?.cancel();
    };
  }, [projectId, paper.id, page, width]);

  const current = citation?.passage_id
    ? passages?.get(citation.passage_id)
    : undefined;

  // Highlights on the visible page: the current citation strongly, the cell's others lightly.
  const highlights = useMemo(() => {
    if (!passages || !size) return [];
    return citations.flatMap((c, i) => {
      const p = c.passage_id ? passages.get(c.passage_id) : undefined;
      if (!p || p.page !== page) return [];
      return p.rects_json.map((r, j) => ({
        r,
        current: i === index,
        key: `${i}-${j}`,
      }));
    });
  }, [passages, size, citations, page, index]);

  useEffect(() => {
    const target = scroller.current?.querySelector("[data-current='true']");
    target?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [highlights]);

  return (
    <aside
      aria-label="Paper reader"
      className="border-line bg-surface flex h-full min-h-0 flex-col border-l"
    >
      <header className="border-line flex items-start gap-3 border-b px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="eyebrow truncate">{columnLabel}</p>
          <p
            className="truncate text-sm font-medium"
            title={paper.title ?? paper.filename}
          >
            {paper.title ?? paper.filename}
          </p>
        </div>
        <a
          href={fileUrl(projectId, paper.id)}
          target="_blank"
          rel="noreferrer"
          className="btn btn-ghost btn-sm"
          title="Open the PDF in a new tab"
        >
          <ExternalLink className="h-4 w-4" aria-hidden />
        </a>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={onClose}
          aria-label="Close reader"
        >
          <X className="h-4 w-4" aria-hidden />
        </button>
      </header>

      {citation && (
        <div className="border-line bg-surface-2 flex flex-col gap-2 border-b px-4 py-3">
          <div className="flex items-center gap-2 text-xs">
            <span className="text-muted">
              Citation {index + 1} of {citations.length} · p. {citation.page}
              {current?.section ? ` · ${current.section}` : ""}
            </span>
            <span className="text-subtle font-mono">{citation.label}</span>
            <span className="ml-auto flex items-center gap-1">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={index === 0}
                onClick={() => onIndex(index - 1)}
                aria-label="Previous citation"
              >
                <ChevronLeft className="h-4 w-4" aria-hidden />
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={index >= citations.length - 1}
                onClick={() => onIndex(index + 1)}
                aria-label="Next citation"
              >
                <ChevronRight className="h-4 w-4" aria-hidden />
              </button>
            </span>
          </div>
          <p className="text-sm leading-relaxed">
            {current
              ? markQuote(current.text, citation.quote)
              : `“${citation.quote}”`}
          </p>
          {citation.verified ? (
            <p className="flex items-center gap-1 text-xs text-emerald-700 dark:text-emerald-400">
              <BadgeCheck className="h-3.5 w-3.5" aria-hidden />
              Quote found in this sentence
            </p>
          ) : (
            <p className="flex items-start gap-1 text-xs text-amber-700 dark:text-amber-400">
              <AlertTriangle
                className="mt-px h-3.5 w-3.5 shrink-0"
                aria-hidden
              />
              Unverified{citation.problem ? `: ${citation.problem}` : ""}
            </p>
          )}
        </div>
      )}

      <div className="border-line text-muted flex items-center justify-between border-b px-4 py-1.5 text-xs">
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={page <= 1}
          onClick={() => setPage(page - 1)}
        >
          <ChevronLeft className="h-4 w-4" aria-hidden /> Page
        </button>
        <span className="flex items-center gap-1.5">
          {rendering && (
            <LoaderCircle className="h-3 w-3 animate-spin" aria-hidden />
          )}
          Page {page} of {pageCount}
        </span>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={page >= pageCount}
          onClick={() => setPage(page + 1)}
        >
          Page <ChevronRight className="h-4 w-4" aria-hidden />
        </button>
      </div>

      <div
        ref={scroller}
        className="bg-surface-3 min-h-0 flex-1 overflow-auto p-3"
      >
        {error && (
          <p role="alert" className="mb-3 text-sm text-red-600">
            {error}
          </p>
        )}
        <div
          ref={frame}
          className="relative mx-auto w-full max-w-3xl bg-white shadow-sm"
        >
          <canvas ref={canvas} className="block" />
          {size &&
            highlights.map(({ r, current: isCurrent, key }) => (
              <span
                key={key}
                data-current={isCurrent}
                className={`pointer-events-none absolute rounded-[2px] mix-blend-multiply ${
                  isCurrent
                    ? "bg-amber-300/60 ring-2 ring-amber-500/70"
                    : "bg-sky-300/40"
                }`}
                style={{
                  left: r[0] * size.scale - 1,
                  top: r[1] * size.scale - 1,
                  width: (r[2] - r[0]) * size.scale + 2,
                  height: (r[3] - r[1]) * size.scale + 2,
                }}
              />
            ))}
        </div>
      </div>
    </aside>
  );
}
