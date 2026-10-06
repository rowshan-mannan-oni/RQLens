"use client";

import {
  AlertTriangle,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Check,
  Download,
  FileText,
  LoaderCircle,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  Plus,
  RotateCw,
  Search,
  Trash2,
  Undo2,
  X,
} from "lucide-react";
import Link from "next/link";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  useTransition,
} from "react";

import {
  addColumn,
  deleteColumn,
  deleteTable,
  editCell,
  renameTable,
  reorderColumns,
  rerun,
  revertCell,
  reviewCell,
  updateColumn,
} from "@/app/projects/[id]/literature/actions";
import type { ActionState } from "@/components/confirm-dialog";
import { PdfReader } from "@/components/literature/pdf-reader";
import type {
  CellValue,
  Citation,
  ColumnKind,
  Paper,
  ReviewCell,
  ReviewTable,
  TemplateColumn,
} from "@/lib/types";

const PAPER_WIDTH = 280;
const PAPER_WIDTH_NARROW = 168;
const DEFAULT_WIDTH = 260;
const MIN_WIDTH = 140;
const CLAMP_CHARS = 240;

type Filter = "all" | "attention" | "not_found" | "edited";
type Open = { paperId: number; key: string; index: number } | null;

function valueText(v: CellValue): string {
  if (v == null) return "";
  if (Array.isArray(v)) return v.join("; ");
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(v);
  return v;
}

const STORAGE_EVENT = "rqlens-storage";

function subscribeStorage(callback: () => void) {
  window.addEventListener("storage", callback);
  window.addEventListener(STORAGE_EVENT, callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener(STORAGE_EVENT, callback);
  };
}

/** A value kept in localStorage per browser (column widths, pinned columns). */
function useStored<T>(key: string, initial: T): [T, (v: T) => void] {
  const raw = useSyncExternalStore(
    subscribeStorage,
    () => {
      try {
        return localStorage.getItem(key);
      } catch {
        return null;
      }
    },
    () => null,
  );
  // Used when storage is unavailable (private mode), so changes still apply this session.
  const [local, setLocal] = useState<T | undefined>(undefined);
  const stored = useMemo(() => {
    try {
      return raw ? (JSON.parse(raw) as T) : initial;
    } catch {
      return initial;
    }
  }, [raw, initial]);
  return [
    local ?? stored,
    (v: T) => {
      setLocal(v);
      try {
        localStorage.setItem(key, JSON.stringify(v));
        window.dispatchEvent(new Event(STORAGE_EVENT));
      } catch {}
    },
  ];
}

function subscribeResize(callback: () => void) {
  window.addEventListener("resize", callback);
  return () => window.removeEventListener("resize", callback);
}

/** True on phone-sized screens, where the paper column is narrower. */
function useNarrow(): boolean {
  return useSyncExternalStore(
    subscribeResize,
    () => window.innerWidth < 640,
    () => false,
  );
}

const NO_WIDTHS: Record<string, number> = {};
const NO_PINS: string[] = [];

export function ReviewTableView({
  projectId,
  table,
}: {
  projectId: number;
  table: ReviewTable;
}) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const [open, setOpen] = useState<Open>(null);
  const [widths, setWidths] = useStored(
    `rqlens:table:${table.id}:widths`,
    NO_WIDTHS,
  );
  const [pinned, setPinned] = useStored(
    `rqlens:table:${table.id}:pinned`,
    NO_PINS,
  );

  const paperWidth = useNarrow() ? PAPER_WIDTH_NARROW : PAPER_WIDTH;
  const run = (fn: () => Promise<ActionState>) =>
    start(async () => {
      const res = await fn();
      setError(res.error);
    });

  const cells = useMemo(() => {
    const m = new Map<string, ReviewCell>();
    for (const c of table.cells) m.set(`${c.paper_id}:${c.column_key}`, c);
    return m;
  }, [table.cells]);
  const cellOf = (paperId: number, key: string) =>
    cells.get(`${paperId}:${key}`);

  // Pinned columns sit next to the paper column and stay in view when scrolling sideways.
  const columns = useMemo(() => {
    const pins = table.columns.filter((c) => pinned.includes(c.key));
    return [...pins, ...table.columns.filter((c) => !pinned.includes(c.key))];
  }, [table.columns, pinned]);
  const widthOf = (key: string) => widths[key] ?? DEFAULT_WIDTH;
  const stickyLeft = useMemo(() => {
    const left: Record<string, number> = {};
    let x = paperWidth;
    for (const c of columns) {
      if (!pinned.includes(c.key)) break;
      left[c.key] = x;
      x += widths[c.key] ?? DEFAULT_WIDTH;
    }
    return left;
  }, [columns, pinned, widths, paperWidth]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    let list = table.papers.filter((p) => {
      const rowCells = table.columns.map((c) => cellOf(p.id, c.key));
      if (
        filter === "attention" &&
        !rowCells.some(
          (c) => c && (c.status === "unverified" || c.status === "failed"),
        )
      )
        return false;
      if (
        filter === "not_found" &&
        !rowCells.some((c) => c?.status === "not_found")
      )
        return false;
      if (filter === "edited" && !rowCells.some((c) => c?.source === "user"))
        return false;
      if (!q) return true;
      const hay = [
        p.title,
        p.filename,
        p.folder,
        ...(p.authors_json ?? []),
        ...rowCells.map((c) => valueText(c?.value_json ?? null)),
      ]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
    if (sort) {
      const val = (p: Paper) =>
        sort.key === "__paper"
          ? (p.title ?? p.filename).toLowerCase()
          : valueText(cellOf(p.id, sort.key)?.value_json ?? null).toLowerCase();
      list = [...list].sort((a, b) => {
        const x = val(a);
        const y = val(b);
        const nx = Number(x);
        const ny = Number(y);
        if (x && y && !Number.isNaN(nx) && !Number.isNaN(ny))
          return (nx - ny) * sort.dir;
        if (!x) return 1;
        if (!y) return -1;
        return x.localeCompare(y) * sort.dir;
      });
    }
    return list;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [table.papers, table.columns, cells, query, filter, sort]);

  const counts = useMemo(() => {
    const c = { done: 0, running: 0, unverified: 0, not_found: 0, failed: 0 };
    for (const cell of table.cells) {
      if (cell.status === "queued" || cell.status === "running") c.running++;
      else c[cell.status]++;
    }
    return c;
  }, [table.cells]);

  const openPaper = open
    ? table.papers.find((p) => p.id === open.paperId)
    : undefined;
  const openCell = open ? cellOf(open.paperId, open.key) : undefined;
  const openColumn = open
    ? table.columns.find((c) => c.key === open.key)
    : undefined;
  const openCitations = openCell?.citations_json ?? [];

  function startResize(key: string, e: React.PointerEvent) {
    e.preventDefault();
    const startX = e.clientX;
    const startW = widthOf(key);
    const move = (ev: PointerEvent) => {
      const w = Math.max(MIN_WIDTH, Math.round(startW + ev.clientX - startX));
      setWidths({ ...widths, [key]: w });
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  function move(key: string, delta: -1 | 1) {
    const keys = table.columns.map((c) => c.key);
    const i = keys.indexOf(key);
    const j = i + delta;
    if (j < 0 || j >= keys.length) return;
    [keys[i], keys[j]] = [keys[j], keys[i]];
    run(() => reorderColumns(projectId, table.id, keys));
  }

  return (
    <div className="flex flex-col gap-4">
      <Toolbar
        projectId={projectId}
        table={table}
        query={query}
        setQuery={setQuery}
        filter={filter}
        setFilter={setFilter}
        counts={counts}
        pending={pending}
        run={run}
      />
      {error && (
        <p
          role="alert"
          className="flex items-center gap-2 text-sm text-red-600"
        >
          <AlertTriangle className="h-4 w-4" aria-hidden />
          {error}
          <button type="button" className="link" onClick={() => setError(null)}>
            Dismiss
          </button>
        </p>
      )}

      {table.papers.length === 0 ? (
        <div className="card text-muted px-6 py-10 text-center text-sm">
          No papers yet.{" "}
          <Link href={`/projects/${projectId}/literature`} className="link">
            Upload papers
          </Link>{" "}
          and they are added to this table as soon as they are read.
        </div>
      ) : (
        <div className="card relative max-h-[calc(100dvh-15rem)] min-h-80 overflow-auto">
          <table className="w-max border-separate border-spacing-0 text-sm">
            <thead>
              <tr>
                <th
                  scope="col"
                  className="bg-surface-2 border-line sticky top-0 left-0 z-30 border-r border-b p-0 text-left"
                  style={{ width: paperWidth, minWidth: paperWidth }}
                >
                  <HeaderButton
                    label="Paper"
                    sort={sort?.key === "__paper" ? sort.dir : null}
                    onSort={() =>
                      setSort(
                        sort?.key === "__paper" && sort.dir === 1
                          ? { key: "__paper", dir: -1 }
                          : sort?.key === "__paper"
                            ? null
                            : { key: "__paper", dir: 1 },
                      )
                    }
                  />
                </th>
                {columns.map((c, i) => (
                  <th
                    key={c.key}
                    scope="col"
                    className={`bg-surface-2 border-line group/th sticky top-0 border-b p-0 text-left align-top ${
                      c.key in stickyLeft ? "z-30 border-r" : "z-20"
                    }`}
                    style={{
                      width: widthOf(c.key),
                      minWidth: widthOf(c.key),
                      maxWidth: widthOf(c.key),
                      left: stickyLeft[c.key],
                    }}
                  >
                    <div className="flex items-start">
                      <HeaderButton
                        label={c.label}
                        hint={c.instructions}
                        sort={sort?.key === c.key ? sort.dir : null}
                        onSort={() =>
                          setSort(
                            sort?.key === c.key && sort.dir === 1
                              ? { key: c.key, dir: -1 }
                              : sort?.key === c.key
                                ? null
                                : { key: c.key, dir: 1 },
                          )
                        }
                      />
                      <ColumnMenu
                        column={c}
                        pinned={pinned.includes(c.key)}
                        first={i === 0}
                        last={i === columns.length - 1}
                        onPin={() =>
                          setPinned(
                            pinned.includes(c.key)
                              ? pinned.filter((k) => k !== c.key)
                              : [...pinned, c.key],
                          )
                        }
                        onMove={(d) => move(c.key, d)}
                        onRerun={() =>
                          run(() =>
                            rerun(projectId, table.id, { column_key: c.key }),
                          )
                        }
                        onSave={(patch) =>
                          run(() =>
                            updateColumn(projectId, table.id, c.key, patch),
                          )
                        }
                        onDelete={() => {
                          if (
                            confirm(
                              `Delete the column "${c.label}" and its values?`,
                            )
                          )
                            run(() => deleteColumn(projectId, table.id, c.key));
                        }}
                      />
                    </div>
                    <span
                      role="separator"
                      aria-orientation="vertical"
                      aria-label={`Resize ${c.label}`}
                      onPointerDown={(e) => startResize(c.key, e)}
                      className="hover:bg-brand/40 absolute top-0 right-0 h-full w-1.5 cursor-col-resize"
                    />
                  </th>
                ))}
                <th className="bg-surface-2 border-line sticky top-0 z-20 border-b p-2 align-top">
                  <AddColumnButton
                    onAdd={(column) =>
                      run(() => addColumn(projectId, table.id, column))
                    }
                  />
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id} className="group/row">
                  <th
                    scope="row"
                    className="bg-surface border-line group-hover/row:bg-surface-2 sticky left-0 z-10 border-r border-b p-3 text-left align-top font-normal"
                    style={{
                      width: paperWidth,
                      minWidth: paperWidth,
                      maxWidth: paperWidth,
                    }}
                  >
                    <PaperHeader
                      projectId={projectId}
                      paper={p}
                      onRerun={() =>
                        run(() =>
                          rerun(projectId, table.id, { paper_id: p.id }),
                        )
                      }
                    />
                  </th>
                  {columns.map((c) => (
                    <td
                      key={c.key}
                      className={`border-line group-hover/row:bg-surface-2 border-b p-3 align-top ${
                        c.key in stickyLeft
                          ? "bg-surface sticky z-10 border-r"
                          : ""
                      }`}
                      style={{
                        width: widthOf(c.key),
                        minWidth: widthOf(c.key),
                        maxWidth: widthOf(c.key),
                        left: stickyLeft[c.key],
                      }}
                    >
                      <CellView
                        paper={p}
                        column={c}
                        cell={cellOf(p.id, c.key)}
                        active={open?.paperId === p.id && open.key === c.key}
                        onCite={(index) =>
                          setOpen({ paperId: p.id, key: c.key, index })
                        }
                        onEdit={(value, cellId) =>
                          run(() =>
                            editCell(projectId, table.id, cellId, value),
                          )
                        }
                        onRevert={(cellId) =>
                          run(() => revertCell(projectId, table.id, cellId))
                        }
                        onReview={(cellId, d) =>
                          run(() => reviewCell(projectId, table.id, cellId, d))
                        }
                        onRerun={() =>
                          run(() =>
                            rerun(projectId, table.id, {
                              paper_id: p.id,
                              column_key: c.key,
                            }),
                          )
                        }
                      />
                    </td>
                  ))}
                  <td className="border-line border-b" />
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td
                    colSpan={columns.length + 2}
                    className="text-muted p-8 text-center"
                  >
                    No papers match.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {open && openPaper && openColumn && openCitations.length > 0 && (
        <>
          <div
            className="fixed inset-0 z-40 bg-black/20 lg:hidden"
            onClick={() => setOpen(null)}
            aria-hidden
          />
          <div className="shadow-pop fixed inset-y-0 right-0 z-50 w-full max-w-[min(42rem,100vw)] lg:w-[46vw]">
            <PdfReader
              projectId={projectId}
              paper={openPaper}
              columnLabel={openColumn.label}
              citations={openCitations}
              index={Math.min(open.index, openCitations.length - 1)}
              onIndex={(index) => setOpen({ ...open, index })}
              onClose={() => setOpen(null)}
            />
          </div>
        </>
      )}
    </div>
  );
}

// --- toolbar --------------------------------------------------------------------------------

function Toolbar({
  projectId,
  table,
  query,
  setQuery,
  filter,
  setFilter,
  counts,
  pending,
  run,
}: {
  projectId: number;
  table: ReviewTable;
  query: string;
  setQuery: (q: string) => void;
  filter: Filter;
  setFilter: (f: Filter) => void;
  counts: {
    done: number;
    running: number;
    unverified: number;
    not_found: number;
    failed: number;
  };
  pending: boolean;
  run: (fn: () => Promise<ActionState>) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(table.name);
  const exportUrl = (f: string) =>
    `/api/projects/${projectId}/review-tables/${table.id}/export?format=${f}`;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <Link
          href={`/projects/${projectId}/literature`}
          className="btn btn-ghost btn-sm"
          aria-label="Back to papers and tables"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden />
        </Link>
        {editing ? (
          <form
            className="flex items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              setEditing(false);
              if (name.trim() && name !== table.name)
                run(() => renameTable(projectId, table.id, name.trim()));
            }}
          >
            <input
              className="input py-1 text-lg font-semibold"
              value={name}
              autoFocus
              maxLength={200}
              onChange={(e) => setName(e.target.value)}
              aria-label="Table name"
            />
            <button type="submit" className="btn btn-secondary btn-sm">
              Save
            </button>
          </form>
        ) : (
          <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
            {table.name}
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setEditing(true)}
              aria-label="Rename table"
            >
              <Pencil className="h-3.5 w-3.5" aria-hidden />
            </button>
          </h2>
        )}
        <div className="text-muted ml-auto flex flex-wrap items-center gap-2 text-xs">
          {counts.running > 0 && (
            <span className="badge badge-brand">
              <LoaderCircle className="h-3 w-3 animate-spin" aria-hidden />
              {counts.running} cells filling
            </span>
          )}
          {counts.unverified > 0 && (
            <span className="badge badge-warning">
              {counts.unverified} unverified
            </span>
          )}
          {counts.failed > 0 && (
            <span className="badge badge-danger">{counts.failed} failed</span>
          )}
          <span className="badge badge-neutral">
            {counts.not_found} not found
          </span>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="relative min-w-48 flex-1 sm:max-w-xs">
          <Search
            className="text-subtle pointer-events-none absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2"
            aria-hidden
          />
          <input
            type="search"
            className="input py-1.5 pl-8"
            placeholder="Filter papers and values"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Filter rows"
          />
        </label>
        <select
          className="input w-auto py-1.5"
          value={filter}
          onChange={(e) => setFilter(e.target.value as Filter)}
          aria-label="Show rows"
        >
          <option value="all">All papers</option>
          <option value="attention">Needs attention</option>
          <option value="not_found">With &ldquo;not found&rdquo;</option>
          <option value="edited">Edited by you</option>
        </select>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            disabled={pending}
            onClick={() => {
              if (
                confirm("Re-run every cell? Cells you edited keep your value.")
              )
                run(() => rerun(projectId, table.id, {}));
            }}
          >
            <RotateCw className="h-3.5 w-3.5" aria-hidden />
            Re-run table
          </button>
          <details className="relative">
            <summary className="btn btn-secondary btn-sm list-none">
              <Download className="h-3.5 w-3.5" aria-hidden />
              Export
            </summary>
            <div className="card shadow-pop absolute right-0 z-40 mt-1 flex w-48 flex-col p-1 text-sm">
              {[
                ["csv", "CSV"],
                ["xlsx", "Excel (with citations sheet)"],
                ["md", "Markdown with citations"],
                ["bib", "BibTeX of the papers"],
              ].map(([f, label]) => (
                <a
                  key={f}
                  href={exportUrl(f)}
                  className="hover:bg-surface-3 rounded-md px-3 py-1.5"
                >
                  {label}
                </a>
              ))}
            </div>
          </details>
          <button
            type="button"
            className="btn btn-ghost btn-sm hover:text-red-600"
            disabled={pending}
            onClick={() => {
              if (
                confirm(
                  `Delete the table "${table.name}"? The papers stay in the project.`,
                )
              )
                run(() => deleteTable(projectId, table.id));
            }}
            aria-label="Delete table"
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden />
          </button>
        </div>
      </div>
    </div>
  );
}

// --- header pieces --------------------------------------------------------------------------

function HeaderButton({
  label,
  hint,
  sort,
  onSort,
}: {
  label: string;
  hint?: string;
  sort: 1 | -1 | null;
  onSort: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSort}
      title={hint || undefined}
      className="text-muted hover:text-fg flex min-w-0 flex-1 items-center gap-1 px-3 py-2.5 text-left text-xs font-semibold"
    >
      <span className="line-clamp-2">{label}</span>
      {sort === 1 && (
        <ArrowUp className="h-3 w-3 shrink-0" aria-label="sorted ascending" />
      )}
      {sort === -1 && (
        <ArrowDown
          className="h-3 w-3 shrink-0"
          aria-label="sorted descending"
        />
      )}
    </button>
  );
}

function Popover({
  label,
  children,
  className,
}: {
  label: string;
  children: (close: () => void) => React.ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <div
      ref={ref}
      data-open={open || undefined}
      className={`data-[open]:opacity-100 ${className?.includes("absolute") ? "" : "relative"} ${className ?? ""}`}
    >
      <button
        type="button"
        className="btn btn-ghost btn-sm px-1.5"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        title={label}
        onClick={() => setOpen(!open)}
      >
        <MoreHorizontal className="h-4 w-4" aria-hidden />
      </button>
      {open && (
        <div
          role="menu"
          className="card shadow-pop absolute right-0 z-40 mt-1 flex w-56 flex-col p-1 text-sm font-normal"
        >
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

function MenuItem({
  icon: Icon,
  children,
  onClick,
  danger,
  disabled,
}: {
  icon: typeof Pin;
  children: React.ReactNode;
  onClick: () => void;
  danger?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`hover:bg-surface-3 flex items-center gap-2 rounded-md px-2.5 py-1.5 text-left disabled:opacity-40 ${
        danger ? "text-red-600 dark:text-red-400" : ""
      }`}
    >
      <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
      {children}
    </button>
  );
}

function ColumnMenu({
  column,
  pinned,
  first,
  last,
  onPin,
  onMove,
  onRerun,
  onSave,
  onDelete,
}: {
  column: TemplateColumn;
  pinned: boolean;
  first: boolean;
  last: boolean;
  onPin: () => void;
  onMove: (d: -1 | 1) => void;
  onRerun: () => void;
  onSave: (patch: { label: string; instructions: string }) => void;
  onDelete: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  return (
    <>
      <Popover
        label={`Column options for ${column.label}`}
        className="pt-1.5 pr-1.5"
      >
        {(close) => (
          <>
            <MenuItem
              icon={Pencil}
              onClick={() => (close(), dialog.current?.showModal())}
            >
              Rename or change instructions
            </MenuItem>
            <MenuItem icon={RotateCw} onClick={() => (close(), onRerun())}>
              Re-run this column
            </MenuItem>
            <MenuItem
              icon={pinned ? PinOff : Pin}
              onClick={() => (close(), onPin())}
            >
              {pinned ? "Unpin" : "Pin to the left"}
            </MenuItem>
            <MenuItem
              icon={ArrowLeft}
              disabled={first}
              onClick={() => (close(), onMove(-1))}
            >
              Move left
            </MenuItem>
            <MenuItem
              icon={ArrowRight}
              disabled={last}
              onClick={() => (close(), onMove(1))}
            >
              Move right
            </MenuItem>
            <MenuItem
              icon={Trash2}
              danger
              onClick={() => (close(), onDelete())}
            >
              Delete column
            </MenuItem>
          </>
        )}
      </Popover>
      <dialog
        ref={dialog}
        className="border-line bg-surface text-fg shadow-pop m-auto w-[calc(100%-2rem)] max-w-lg rounded-2xl border p-0 font-normal backdrop:bg-black/40"
      >
        <form
          className="flex flex-col gap-3 p-6"
          onSubmit={(e) => {
            e.preventDefault();
            const data = new FormData(e.currentTarget);
            onSave({
              label: String(data.get("label") ?? "").trim() || column.label,
              instructions: String(data.get("instructions") ?? ""),
            });
            dialog.current?.close();
          }}
        >
          <h2 className="text-lg font-semibold tracking-tight">Edit column</h2>
          <label className="flex flex-col gap-1">
            <span className="label">Label</span>
            <input
              name="label"
              defaultValue={column.label}
              className="input"
              maxLength={120}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="label">Instructions for the AI</span>
            <textarea
              name="instructions"
              defaultValue={column.instructions}
              rows={4}
              className="input"
              maxLength={2000}
            />
            <span className="text-subtle text-xs">
              New instructions apply when you re-run the column.
            </span>
          </label>
          <div className="mt-2 flex justify-end gap-2">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => dialog.current?.close()}
            >
              Cancel
            </button>
            <button type="submit" className="btn btn-primary">
              Save
            </button>
          </div>
        </form>
      </dialog>
    </>
  );
}

function AddColumnButton({
  onAdd,
}: {
  onAdd: (c: Partial<TemplateColumn>) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [kind, setKind] = useState<ColumnKind>("text");
  const [err, setErr] = useState<string | null>(null);
  return (
    <>
      <button
        type="button"
        className="btn btn-ghost btn-sm whitespace-nowrap"
        onClick={() => dialog.current?.showModal()}
      >
        <Plus className="h-3.5 w-3.5" aria-hidden />
        Add column
      </button>
      <dialog
        ref={dialog}
        className="border-line bg-surface text-fg shadow-pop m-auto w-[calc(100%-2rem)] max-w-lg rounded-2xl border p-0 text-left font-normal backdrop:bg-black/40"
      >
        <form
          className="flex flex-col gap-3 p-6"
          onSubmit={(e) => {
            e.preventDefault();
            const data = new FormData(e.currentTarget);
            const label = String(data.get("label") ?? "").trim();
            const options = String(data.get("options") ?? "")
              .split("\n")
              .map((o) => o.trim())
              .filter(Boolean);
            if (!label) return setErr("Give the column a label.");
            if (kind === "category" && options.length < 2)
              return setErr("A category column needs at least two options.");
            setErr(null);
            onAdd({
              label,
              instructions: String(data.get("instructions") ?? ""),
              kind,
              options: kind === "category" ? options : [],
            });
            e.currentTarget.reset();
            setKind("text");
            dialog.current?.close();
          }}
        >
          <h2 className="text-lg font-semibold tracking-tight">Add a column</h2>
          <p className="text-muted text-sm">
            Only this column is extracted for every paper; the rest of the table
            is left as it is.
          </p>
          <label className="flex flex-col gap-1">
            <span className="label">Label</span>
            <input
              name="label"
              className="input"
              maxLength={120}
              placeholder="e.g. Sample size"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="label">Instructions for the AI</span>
            <textarea
              name="instructions"
              rows={3}
              className="input"
              maxLength={2000}
              placeholder="What to extract, and what counts as not found."
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="label">Kind</span>
            <select
              className="input"
              value={kind}
              onChange={(e) => setKind(e.target.value as ColumnKind)}
            >
              <option value="text">Text</option>
              <option value="list">List</option>
              <option value="number">Number</option>
              <option value="category">Category (fixed options)</option>
            </select>
          </label>
          {kind === "category" && (
            <label className="flex flex-col gap-1">
              <span className="label">Options, one per line</span>
              <textarea name="options" rows={4} className="input" />
            </label>
          )}
          {err && (
            <p role="alert" className="text-sm text-red-600">
              {err}
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
            <button type="submit" className="btn btn-primary">
              Add and extract
            </button>
          </div>
        </form>
      </dialog>
    </>
  );
}

// --- rows -----------------------------------------------------------------------------------

function PaperHeader({
  projectId,
  paper: p,
  onRerun,
}: {
  projectId: number;
  paper: Paper;
  onRerun: () => void;
}) {
  const authors = p.authors_json ?? [];
  return (
    <div className="flex items-start gap-2">
      <div className="min-w-0 flex-1">
        <p className="line-clamp-3 font-medium" title={p.title ?? p.filename}>
          {p.title ?? p.filename}
        </p>
        <p className="text-muted mt-0.5 truncate text-xs">
          {authors.length > 0 &&
            `${authors[0].split(" ").slice(-1)[0]}${authors.length > 1 ? " et al." : ""}`}
          {p.year ? ` (${p.year})` : ""}
        </p>
        {p.folder && <p className="text-subtle truncate text-xs">{p.folder}</p>}
        {p.status !== "ready" && (
          <span
            className={`badge mt-1 ${p.status === "failed" || p.status === "needs_ocr" ? "badge-warning" : "badge-neutral"}`}
          >
            {p.status === "needs_ocr"
              ? "Needs OCR"
              : p.status === "failed"
                ? "Unreadable"
                : "Reading…"}
          </span>
        )}
      </div>
      <Popover
        label={`Options for ${p.title ?? p.filename}`}
        className="opacity-0 group-hover/row:opacity-100 focus-within:opacity-100"
      >
        {(close) => (
          <>
            <a
              href={`/api/projects/${projectId}/papers/${p.id}/file`}
              target="_blank"
              rel="noreferrer"
              className="hover:bg-surface-3 flex items-center gap-2 rounded-md px-2.5 py-1.5"
            >
              <FileText className="h-3.5 w-3.5" aria-hidden />
              Open PDF
            </a>
            <MenuItem
              icon={RotateCw}
              disabled={p.status !== "ready"}
              onClick={() => (close(), onRerun())}
            >
              Re-run this paper
            </MenuItem>
          </>
        )}
      </Popover>
    </div>
  );
}

function CellView({
  paper,
  column,
  cell,
  active,
  onCite,
  onEdit,
  onRevert,
  onReview,
  onRerun,
}: {
  paper: Paper;
  column: TemplateColumn;
  cell: ReviewCell | undefined;
  active: boolean;
  onCite: (index: number) => void;
  onEdit: (value: CellValue, cellId: number) => void;
  onRevert: (cellId: number) => void;
  onReview: (cellId: number, d: "accepted" | "rejected" | null) => void;
  onRerun: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);

  if (paper.status !== "ready")
    return (
      <span className="text-subtle text-xs">
        {paper.status === "needs_ocr" || paper.status === "failed"
          ? "–"
          : "Waiting for the paper…"}
      </span>
    );
  if (!cell || cell.status === "queued" || cell.status === "running")
    return (
      <div className="flex flex-col gap-1.5" aria-label="Filling">
        <span className="bg-surface-3 h-3 w-4/5 animate-pulse rounded" />
        <span className="bg-surface-3 h-3 w-3/5 animate-pulse rounded" />
      </div>
    );

  if (editing)
    return (
      <CellEditor
        column={column}
        value={cell.value_json}
        onCancel={() => setEditing(false)}
        onSave={(v) => {
          setEditing(false);
          onEdit(v, cell.id);
        }}
      />
    );

  const citations: Citation[] = cell.citations_json ?? [];
  const text = valueText(cell.value_json);
  const long =
    text.length > CLAMP_CHARS ||
    (Array.isArray(cell.value_json) && cell.value_json.length > 4);
  const rejected = cell.review === "rejected";

  return (
    <div
      className={`group/cell relative flex flex-col gap-1.5 ${active ? "ring-brand/60 -m-1.5 rounded-md p-1.5 ring-2" : ""}`}
    >
      {cell.status === "not_found" ? (
        <p
          className="text-subtle text-xs italic"
          title={cell.note ?? undefined}
        >
          Not found{cell.note ? ` – ${cell.note}` : ""}
        </p>
      ) : cell.status === "failed" ? (
        <p className="flex items-start gap-1 text-xs text-red-600 dark:text-red-400">
          <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
          <span className="line-clamp-4">{cell.note ?? "Failed"}</span>
        </p>
      ) : (
        <div
          className={`${rejected ? "text-subtle line-through" : ""} ${long && !expanded ? "line-clamp-5" : ""}`}
        >
          {Array.isArray(cell.value_json) ? (
            <ul className="marker:text-subtle list-disc space-y-0.5 pl-4">
              {cell.value_json.map((v, i) => (
                <li key={i}>{v}</li>
              ))}
            </ul>
          ) : (
            <p className="whitespace-pre-wrap">{text}</p>
          )}
        </div>
      )}

      {long && cell.status !== "not_found" && (
        <button
          type="button"
          className="link w-fit text-xs"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}

      <div className="flex flex-wrap items-center gap-1">
        {citations.map((c, i) => (
          <button
            key={i}
            type="button"
            onClick={() => onCite(i)}
            title={`p. ${c.page}: “${c.quote}”${c.verified ? "" : " (unverified)"}`}
            className={`rounded px-1 font-mono text-[11px] leading-5 font-medium transition ${
              c.verified
                ? "bg-brand-soft text-brand-fg hover:bg-brand hover:text-white"
                : "bg-amber-100 text-amber-800 hover:bg-amber-200 dark:bg-amber-950 dark:text-amber-200"
            }`}
          >
            [{i + 1}]
          </button>
        ))}
        {cell.status === "unverified" && (
          <span className="badge badge-warning" title={cell.note ?? undefined}>
            Unverified
          </span>
        )}
        {cell.source === "user" && (
          <span className="badge badge-neutral">Edited</span>
        )}
        {cell.source === "metadata" && citations.length === 0 && (
          <span className="badge badge-neutral" title={cell.note ?? undefined}>
            PDF metadata
          </span>
        )}
        {cell.review === "accepted" && (
          <span className="badge badge-success">
            <Check className="h-3 w-3" aria-hidden />
            Accepted
          </span>
        )}
        {cell.confidence === "low" && cell.source === "llm" && (
          <span className="badge badge-neutral">Low confidence</span>
        )}
      </div>

      <Popover
        label="Cell options"
        className="absolute -top-1 -right-1 opacity-0 group-hover/cell:opacity-100 focus-within:opacity-100"
      >
        {(close) => (
          <>
            <MenuItem icon={Pencil} onClick={() => (close(), setEditing(true))}>
              Edit value
            </MenuItem>
            {cell.status !== "not_found" && cell.status !== "failed" && (
              <>
                <MenuItem
                  icon={Check}
                  onClick={() => (
                    close(),
                    onReview(
                      cell.id,
                      cell.review === "accepted" ? null : "accepted",
                    )
                  )}
                >
                  {cell.review === "accepted" ? "Undo accept" : "Accept"}
                </MenuItem>
                <MenuItem
                  icon={X}
                  onClick={() => (
                    close(),
                    onReview(
                      cell.id,
                      cell.review === "rejected" ? null : "rejected",
                    )
                  )}
                >
                  {cell.review === "rejected"
                    ? "Undo reject"
                    : "Reject (leave out of exports)"}
                </MenuItem>
              </>
            )}
            {cell.source === "user" && cell.ai_json && (
              <MenuItem
                icon={Undo2}
                onClick={() => (close(), onRevert(cell.id))}
              >
                Go back to the AI value
              </MenuItem>
            )}
            <MenuItem icon={RotateCw} onClick={() => (close(), onRerun())}>
              Re-run this cell
            </MenuItem>
            {cell.source === "user" && cell.ai_json && (
              <p className="text-subtle border-line mt-1 border-t px-2.5 pt-1.5 pb-1 text-xs">
                AI value: {valueText(cell.ai_json.value) || "not found"}
              </p>
            )}
          </>
        )}
      </Popover>
    </div>
  );
}

function CellEditor({
  column,
  value,
  onSave,
  onCancel,
}: {
  column: TemplateColumn;
  value: CellValue;
  onSave: (v: CellValue) => void;
  onCancel: () => void;
}) {
  const initial =
    column.kind === "list" && Array.isArray(value)
      ? value.join("\n")
      : valueText(value);
  const [text, setText] = useState(initial);
  const save = () => {
    const t = text.trim();
    if (!t) return onSave(null);
    if (column.kind === "list")
      return onSave(
        t
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean),
      );
    if (column.kind === "number") {
      const n = Number(t.replace(/,/g, ""));
      return onSave(Number.isFinite(n) ? n : t);
    }
    onSave(t);
  };
  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        save();
      }}
      onKeyDown={(e) => e.key === "Escape" && onCancel()}
    >
      {column.kind === "category" ? (
        <select
          className="input py-1 text-sm"
          value={text}
          onChange={(e) => setText(e.target.value)}
          autoFocus
        >
          <option value="">Not found</option>
          {column.options.map((o) => (
            <option key={o}>{o}</option>
          ))}
        </select>
      ) : (
        <textarea
          className="input text-sm"
          rows={column.kind === "number" ? 1 : 4}
          value={text}
          onChange={(e) => setText(e.target.value)}
          autoFocus
          aria-label={`Edit ${column.label}`}
          placeholder={column.kind === "list" ? "One item per line" : undefined}
        />
      )}
      <div className="flex gap-2">
        <button type="submit" className="btn btn-primary btn-sm">
          Save
        </button>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={onCancel}
        >
          Cancel
        </button>
      </div>
      <p className="text-subtle text-xs">
        Your value is kept when the table is re-run.
      </p>
    </form>
  );
}
