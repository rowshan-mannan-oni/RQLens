const integer = new Intl.NumberFormat("en-US");
const compact = new Intl.NumberFormat("en-US", { maximumSignificantDigits: 4 });

export function formatInt(n: number | null | undefined): string {
  return n == null ? "–" : integer.format(n);
}

/** Up to 4 significant digits, thousands separated. */
export function formatNum(n: number | null | undefined): string {
  return n == null ? "–" : compact.format(n);
}

export function formatPct(
  share: number | null | undefined,
  digits = 1,
): string {
  if (share == null) return "–";
  const pct = share * 100;
  return `${pct > 0 && pct < 0.1 ? "<0.1" : pct.toFixed(digits)}%`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}
