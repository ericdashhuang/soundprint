"use client";

import { useEffect, useRef, useState } from "react";
import {
  CartesianGrid,
  Label,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { HintMetric, HintPoint, RevealedMetric } from "./types";
import {
  ALL_METRIC_LABELS,
  formatMetricAxisTick,
  formatMetricValue,
  METRIC_COLORS,
  METRIC_Y_DOMAIN,
  type ChartMetric,
} from "./metrics";
import styles from "./GameChart.module.css";

const PX_PER_TRACK = 76;
const MIN_CHART_WIDTH = 480;
// revealed track title labels are pinned to this fixed y (within the
// chart's top margin, reserved space the line's plotted values never enter)
// rather than positioned relative to each point's own y, a label near a
// high point would otherwise sit right on the line itself
const TRACK_LABEL_Y = 16;
const CHART_TOP_MARGIN = 32;

export interface ChartDataPoint {
  trackNumber: number;
  name?: string;
  vibeScore: number | null;
  metricValues: Partial<Record<HintMetric, number | null>>;
  metricModes: Partial<Record<HintMetric, number | null>>;
}

export function buildChartData(
  hints: HintPoint[],
  revealedMetrics: RevealedMetric[],
  trackNames?: Record<number, string>
): ChartDataPoint[] {
  const points = new Map<number, ChartDataPoint>();

  for (const hint of hints) {
    points.set(hint.track_number, {
      trackNumber: hint.track_number,
      name: trackNames?.[hint.track_number],
      vibeScore: hint.vibe_score,
      metricValues: {},
      metricModes: {},
    });
  }

  for (const revealed of revealedMetrics) {
    for (const point of revealed.data) {
      const existing = points.get(point.track_number);
      if (!existing) continue;
      existing.metricValues[revealed.metric] = point.value;
      existing.metricModes[revealed.metric] = point.mode;
    }
  }

  return Array.from(points.values()).sort((a, b) => a.trackNumber - b.trackNumber);
}

export function valueForMetric(point: ChartDataPoint, metric: ChartMetric): number | null {
  if (metric === "vibe_score") {
    return point.vibeScore;
  }
  if (metric === "key") {
    const rawKey = point.metricValues.key;
    const mode = point.metricModes.key;
    if (rawKey === undefined || rawKey === null || mode === undefined || mode === null) {
      return null;
    }
    const magnitude = rawKey + 1;
    return mode === 0 ? -magnitude : magnitude;
  }
  const raw = point.metricValues[metric];
  return raw === undefined ? null : raw;
}

function truncateTitle(title: string, max = 14): string {
  return title.length > max ? `${title.slice(0, max - 1)}…` : title;
}

interface PointLabelProps {
  x?: number;
  index?: number;
  data: ChartDataPoint[];
}

function TrackTitleLabel({ x, index, data }: PointLabelProps) {
  if (x === undefined || index === undefined) {
    return null;
  }
  const name = data[index]?.name;
  if (!name) {
    return null;
  }
  return (
    <text x={x} y={TRACK_LABEL_Y} textAnchor="middle" className={styles.pointLabel}>
      {truncateTitle(name)}
    </text>
  );
}

interface TooltipPayloadEntry {
  value?: number | null;
  payload?: ChartDataPoint;
}

interface ChartTooltipProps {
  active?: boolean;
  label?: number;
  payload?: readonly TooltipPayloadEntry[];
  metric: ChartMetric;
}

function ChartTooltip({ active, label, payload, metric }: ChartTooltipProps) {
  if (!active || !payload || payload.length === 0) {
    return null;
  }
  const point = payload[0].payload;
  if (!point) {
    return null;
  }
  const value = valueForMetric(point, metric);

  return (
    <div className={styles.tooltip}>
      <p className={styles.tooltipTrack}>{point.name ?? `Track ${label}`}</p>
      <p className={styles.tooltipRow}>
        <span className={styles.tooltipSwatch} style={{ background: METRIC_COLORS[metric] }} />
        {ALL_METRIC_LABELS[metric]}:{" "}
        {value === null ? "No data" : formatMetricValue(metric, value)}
      </p>
    </div>
  );
}

interface GameChartProps {
  hints: HintPoint[];
  revealedMetrics: RevealedMetric[];
  trackNames?: Record<number, string>;
}

export default function GameChart({ hints, revealedMetrics, trackNames }: GameChartProps) {
  const availableMetrics: ChartMetric[] = ["vibe_score", ...revealedMetrics.map((m) => m.metric)];
  const [selectedMetric, setSelectedMetric] = useState<ChartMetric>("vibe_score");
  const activeMetric = availableMetrics.includes(selectedMetric) ? selectedMetric : "vibe_score";

  const previousRevealedCount = useRef(revealedMetrics.length);
  useEffect(() => {
    if (revealedMetrics.length > previousRevealedCount.current) {
      setSelectedMetric(revealedMetrics[revealedMetrics.length - 1].metric);
    }
    previousRevealedCount.current = revealedMetrics.length;
  }, [revealedMetrics]);

  const data = buildChartData(hints, revealedMetrics, trackNames);
  const chartWidth = Math.max(MIN_CHART_WIDTH, data.length * PX_PER_TRACK);

  return (
    <div className={styles.wrapper}>
      <div className={styles.toggleRow} role="tablist" aria-label="Chart metric">
        {availableMetrics.map((metric) => (
          <button
            key={metric}
            type="button"
            role="tab"
            aria-selected={metric === activeMetric}
            className={metric === activeMetric ? styles.toggleActive : styles.toggle}
            style={metric === activeMetric ? { borderColor: METRIC_COLORS[metric] } : undefined}
            onClick={() => setSelectedMetric(metric)}
          >
            <span className={styles.toggleSwatch} style={{ background: METRIC_COLORS[metric] }} />
            {ALL_METRIC_LABELS[metric]}
          </button>
        ))}
      </div>

      <div className={styles.scrollArea} data-testid="game-chart">
        <div style={{ width: chartWidth }}>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart
              data={data}
              margin={{ top: CHART_TOP_MARGIN, right: 48, left: 40, bottom: 8 }}
            >
              <CartesianGrid stroke="var(--border)" vertical={false} />
              <XAxis
                dataKey="trackNumber"
                interval={0}
                tickFormatter={(value: number) => `Track ${value}`}
                tick={{ fill: "var(--muted)", fontFamily: "var(--font-mono)", fontSize: 11 }}
                axisLine={{ stroke: "var(--border)" }}
                tickLine={false}
              />
              <YAxis
                domain={METRIC_Y_DOMAIN[activeMetric] ?? ["auto", "auto"]}
                tickFormatter={(value: number) => formatMetricAxisTick(activeMetric, value)}
                tick={{ fill: "var(--muted)", fontFamily: "var(--font-mono)", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={48}
              >
                <Label
                  value={ALL_METRIC_LABELS[activeMetric]}
                  angle={-90}
                  position="insideLeft"
                  style={{ fill: "var(--muted)", fontSize: 11, textAnchor: "middle" }}
                />
              </YAxis>
              <Tooltip content={<ChartTooltip metric={activeMetric} />} />
              <Line
                type="monotone"
                dataKey={(point: ChartDataPoint) => valueForMetric(point, activeMetric)}
                stroke={METRIC_COLORS[activeMetric]}
                strokeWidth={2}
                dot={{ r: 3, fill: METRIC_COLORS[activeMetric] }}
                activeDot={{ r: 5 }}
                connectNulls={false}
                isAnimationActive={false}
                label={<TrackTitleLabel data={data} />}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
