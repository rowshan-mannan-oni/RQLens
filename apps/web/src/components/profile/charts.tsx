"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatInt, formatNum, formatPct } from "@/lib/format";
import type { TopValue } from "@/lib/types";

// Single-series charts: one colour, thin bars with a rounded data end, hairline grid,
// axis and label text in text colours (never the series colour).
const BAR = "var(--chart-1)";
const GRID = "var(--chart-grid)";
const AXIS = "var(--chart-axis)";
const tick = { fill: AXIS, fontSize: 11 };

function TooltipBox({ title, lines }: { title: string; lines: string[] }) {
  return (
    <div className="rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-xs shadow-sm dark:border-zinc-700 dark:bg-zinc-900">
      <p className="font-medium">{title}</p>
      {lines.map((l) => (
        <p key={l} className="text-zinc-600 dark:text-zinc-400">
          {l}
        </p>
      ))}
    </div>
  );
}

type Bin = { start: number; end: number; count: number };

export function Histogram({ bins, total }: { bins: Bin[]; total: number }) {
  const data = bins.map((b) => ({ ...b, label: formatNum(b.start) }));
  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid vertical={false} stroke={GRID} strokeWidth={1} />
        <XAxis
          dataKey="label"
          tick={tick}
          tickLine={false}
          axisLine={{ stroke: GRID }}
          interval="preserveStartEnd"
          minTickGap={24}
        />
        <YAxis
          tick={tick}
          tickLine={false}
          axisLine={false}
          width={44}
          allowDecimals={false}
          tickFormatter={(v: number) => formatInt(v)}
        />
        <Tooltip
          cursor={{ fill: GRID, opacity: 0.5 }}
          content={({ active, payload }) => {
            const b = active ? (payload?.[0]?.payload as Bin) : undefined;
            if (!b) return null;
            return (
              <TooltipBox
                title={`${formatNum(b.start)} to ${formatNum(b.end)}`}
                lines={[
                  `${formatInt(b.count)} rows (${formatPct(b.count / total)})`,
                ]}
              />
            );
          }}
        />
        <Bar
          dataKey="count"
          fill={BAR}
          maxBarSize={24}
          radius={[4, 4, 0, 0]}
          isAnimationActive={false}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function TopValuesChart({ values }: { values: TopValue[] }) {
  const data = values.map((v) => ({
    ...v,
    label: v.value.length > 24 ? `${v.value.slice(0, 23)}…` : v.value,
  }));
  return (
    <ResponsiveContainer width="100%" height={Math.max(80, data.length * 30)}>
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 0, right: 56, bottom: 0, left: 0 }}
      >
        <XAxis type="number" hide />
        <YAxis
          type="category"
          dataKey="label"
          tick={tick}
          tickLine={false}
          axisLine={{ stroke: GRID }}
          width={140}
        />
        <Tooltip
          cursor={{ fill: GRID, opacity: 0.5 }}
          content={({ active, payload }) => {
            const v = active ? (payload?.[0]?.payload as TopValue) : undefined;
            if (!v) return null;
            return (
              <TooltipBox
                title={v.value}
                lines={[`${formatInt(v.count)} rows (${formatPct(v.share)})`]}
              />
            );
          }}
        />
        <Bar
          dataKey="count"
          fill={BAR}
          maxBarSize={20}
          radius={[0, 4, 4, 0]}
          isAnimationActive={false}
        >
          <LabelList
            dataKey="share"
            position="right"
            formatter={(v: unknown) => formatPct(Number(v))}
            style={{ fill: AXIS, fontSize: 11 }}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

type PeriodCount = { period: string; count: number };

export function PeriodChart({
  counts,
  period,
}: {
  counts: PeriodCount[];
  period: string;
}) {
  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={counts} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid vertical={false} stroke={GRID} strokeWidth={1} />
        <XAxis
          dataKey="period"
          tick={tick}
          tickLine={false}
          axisLine={{ stroke: GRID }}
          minTickGap={32}
        />
        <YAxis
          tick={tick}
          tickLine={false}
          axisLine={false}
          width={44}
          allowDecimals={false}
          tickFormatter={(v: number) => formatInt(v)}
        />
        <Tooltip
          cursor={{ fill: GRID, opacity: 0.5 }}
          content={({ active, payload }) => {
            const p = active
              ? (payload?.[0]?.payload as PeriodCount)
              : undefined;
            if (!p) return null;
            return (
              <TooltipBox
                title={`${period} of ${p.period}`}
                lines={[
                  p.count === 0
                    ? "No rows (gap)"
                    : `${formatInt(p.count)} rows`,
                ]}
              />
            );
          }}
        />
        <Bar
          dataKey="count"
          fill={BAR}
          maxBarSize={24}
          radius={[4, 4, 0, 0]}
          isAnimationActive={false}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}
