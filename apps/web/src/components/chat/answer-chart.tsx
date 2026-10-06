"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatNum } from "@/lib/format";
import type { ChartSpec } from "@/lib/types";

// Categorical slots in fixed order (globals.css); a chart has at most 4 series.
const SERIES = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
];
const GRID = "var(--chart-grid)";
const AXIS = "var(--chart-axis)";
const tick = { fill: AXIS, fontSize: 11 };

function label(v: unknown): string {
  return typeof v === "number" ? formatNum(v) : String(v ?? "–");
}

function TooltipBox({
  title,
  rows,
}: {
  title: string;
  rows: { name: string; value: unknown; color: string }[];
}) {
  return (
    <div className="rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-xs shadow-sm dark:border-zinc-700 dark:bg-zinc-900">
      <p className="font-medium">{title}</p>
      {rows.map((r) => (
        <p
          key={r.name}
          className="flex items-center gap-1.5 text-zinc-600 dark:text-zinc-400"
        >
          <span
            className="inline-block size-2 rounded-full"
            style={{ background: r.color }}
          />
          {r.name}: {label(r.value)}
        </p>
      ))}
    </div>
  );
}

export function AnswerChart({ chart }: { chart: ChartSpec }) {
  const { x, y, data } = chart;
  const multi = y.length > 1;
  const common = {
    data,
    margin: { top: 8, right: 12, bottom: 0, left: 0 },
  };
  const grid = <CartesianGrid vertical={false} stroke={GRID} strokeWidth={1} />;
  const xAxis = (
    <XAxis
      dataKey={x}
      type={chart.type === "scatter" ? "number" : "category"}
      name={x}
      tick={tick}
      tickLine={false}
      axisLine={{ stroke: GRID }}
      tickFormatter={label}
      interval="preserveStartEnd"
      minTickGap={24}
      domain={chart.type === "scatter" ? ["auto", "auto"] : undefined}
    />
  );
  const yAxis = (
    <YAxis
      tick={tick}
      tickLine={false}
      axisLine={false}
      width={52}
      tickFormatter={(v: number) => formatNum(v)}
      type="number"
      dataKey={chart.type === "scatter" ? y[0] : undefined}
      name={chart.type === "scatter" ? y[0] : undefined}
      domain={chart.type === "scatter" ? ["auto", "auto"] : undefined}
    />
  );
  const tooltip = (
    <Tooltip
      cursor={{ fill: GRID, opacity: 0.5, stroke: GRID }}
      content={({ active, payload }) => {
        const row = active ? payload?.[0]?.payload : undefined;
        if (!row) return null;
        return (
          <TooltipBox
            title={`${x}: ${label(row[x])}`}
            rows={y.map((s, i) => ({
              name: s,
              value: row[s],
              color: SERIES[i],
            }))}
          />
        );
      }}
    />
  );
  const legend = multi ? (
    <Legend
      iconType="circle"
      iconSize={8}
      wrapperStyle={{ fontSize: 12, color: AXIS }}
    />
  ) : null;

  let body: React.ReactElement;
  if (chart.type === "line") {
    body = (
      <LineChart {...common}>
        {grid}
        {xAxis}
        {yAxis}
        {tooltip}
        {legend}
        {y.map((s, i) => (
          <Line
            key={s}
            dataKey={s}
            stroke={SERIES[i]}
            strokeWidth={2}
            dot={
              data.length <= 40
                ? { r: 3, strokeWidth: 0, fill: SERIES[i] }
                : false
            }
            activeDot={{ r: 5, stroke: "var(--chart-surface)", strokeWidth: 2 }}
            isAnimationActive={false}
          />
        ))}
      </LineChart>
    );
  } else if (chart.type === "scatter") {
    body = (
      <ScatterChart {...common}>
        {grid}
        {xAxis}
        {yAxis}
        {tooltip}
        <Scatter
          data={data}
          fill={SERIES[0]}
          stroke="var(--chart-surface)"
          strokeWidth={1}
          isAnimationActive={false}
        />
      </ScatterChart>
    );
  } else {
    body = (
      <BarChart {...common} barGap={2}>
        {grid}
        {xAxis}
        {yAxis}
        {tooltip}
        {legend}
        {y.map((s, i) => (
          <Bar
            key={s}
            dataKey={s}
            fill={SERIES[i]}
            maxBarSize={28}
            radius={[4, 4, 0, 0]}
            isAnimationActive={false}
          />
        ))}
      </BarChart>
    );
  }

  return (
    <figure className="flex flex-col gap-2 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
      <figcaption className="text-sm font-medium">
        {chart.title}
        {chart.truncated && (
          <span className="ml-2 text-xs font-normal text-zinc-500">
            first {data.length} rows of the query
          </span>
        )}
      </figcaption>
      <ResponsiveContainer width="100%" height={260}>
        {body}
      </ResponsiveContainer>
    </figure>
  );
}
