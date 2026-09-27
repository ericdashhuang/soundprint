import { describe, expect, test } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import GameChart, { buildChartData, valueForMetric } from "./GameChart";
import { formatMetricAxisTick, formatMetricValue } from "./metrics";
import type { HintPoint, RevealedMetric } from "./types";

const hints: HintPoint[] = [
  { track_number: 1, vibe_score: 0.72 },
  { track_number: 2, vibe_score: null },
  { track_number: 3, vibe_score: 0.31 },
];

const revealedMetrics: RevealedMetric[] = [
  {
    metric: "danceability",
    data: [
      { track_number: 1, value: 0.6, mode: null },
      { track_number: 2, value: null, mode: null },
      { track_number: 3, value: 0.2, mode: null },
    ],
  },
];

describe("buildChartData", () => {
  test("merges base vibe scores with revealed metrics per track number", () => {
    const data = buildChartData(hints, revealedMetrics);

    expect(data).toEqual([
      {
        trackNumber: 1,
        name: undefined,
        vibeScore: 0.72,
        metricValues: { danceability: 0.6 },
        metricModes: { danceability: null },
      },
      {
        trackNumber: 2,
        name: undefined,
        vibeScore: null,
        metricValues: { danceability: null },
        metricModes: { danceability: null },
      },
      {
        trackNumber: 3,
        name: undefined,
        vibeScore: 0.31,
        metricValues: { danceability: 0.2 },
        metricModes: { danceability: null },
      },
    ]);
  });

  test("attaches track names when provided (post-reveal)", () => {
    const data = buildChartData(hints, [], { 1: "Opener", 3: "Closer" });
    expect(data.map((point) => point.name)).toEqual(["Opener", undefined, "Closer"]);
  });
});

describe("GameChart", () => {
  test("renders only the base vibe-score toggle when no metric is revealed yet", () => {
    render(<GameChart hints={hints} revealedMetrics={[]} />);
    expect(screen.getByTestId("game-chart")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /energy level/i })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /danceability/i })).not.toBeInTheDocument();
  });

  test("adds a toggle for each newly revealed metric", () => {
    render(<GameChart hints={hints} revealedMetrics={revealedMetrics} />);
    expect(screen.getByRole("tab", { name: /energy level/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /danceability/i })).toBeInTheDocument();
  });

  test("shows one metric's line at a time, switching which is active on toggle click", () => {
    render(<GameChart hints={hints} revealedMetrics={revealedMetrics} />);

    const vibeTab = screen.getByRole("tab", { name: /energy level/i });
    const danceabilityTab = screen.getByRole("tab", { name: /danceability/i });

    expect(vibeTab).toHaveAttribute("aria-selected", "true");
    expect(danceabilityTab).toHaveAttribute("aria-selected", "false");

    fireEvent.click(danceabilityTab);

    expect(danceabilityTab).toHaveAttribute("aria-selected", "true");
    expect(vibeTab).toHaveAttribute("aria-selected", "false");
  });

  test("auto-switches the active tab to a newly revealed metric", async () => {
    const { rerender } = render(<GameChart hints={hints} revealedMetrics={[]} />);
    expect(screen.getByRole("tab", { name: /energy level/i })).toHaveAttribute(
      "aria-selected",
      "true"
    );

    rerender(<GameChart hints={hints} revealedMetrics={revealedMetrics} />);

    await waitFor(() =>
      expect(screen.getByRole("tab", { name: /danceability/i })).toHaveAttribute(
        "aria-selected",
        "true"
      )
    );
    expect(screen.getByRole("tab", { name: /energy level/i })).toHaveAttribute(
      "aria-selected",
      "false"
    );
  });

  test("does not auto-switch away from a manually selected tab until a new metric arrives", async () => {
    const { rerender } = render(<GameChart hints={hints} revealedMetrics={revealedMetrics} />);

    // player manually switches back to vibe score after danceability unlocked
    fireEvent.click(screen.getByRole("tab", { name: /energy level/i }));
    expect(screen.getByRole("tab", { name: /energy level/i })).toHaveAttribute(
      "aria-selected",
      "true"
    );

    // rerendering with an equal length revealedMetrics array (a new
    // reference, but no *new* metric) must not snap the tab back
    rerender(<GameChart hints={hints} revealedMetrics={[...revealedMetrics]} />);
    expect(screen.getByRole("tab", { name: /energy level/i })).toHaveAttribute(
      "aria-selected",
      "true"
    );
  });
});

describe("key metric signed encoding", () => {
  test("valueForMetric encodes major as positive and minor as negative, magnitude = pitch class + 1", () => {
    const cMajor = {
      trackNumber: 1,
      vibeScore: null,
      metricValues: { key: 0 },
      metricModes: { key: 1 },
    };
    const cMinor = {
      trackNumber: 2,
      vibeScore: null,
      metricValues: { key: 0 },
      metricModes: { key: 0 },
    };
    const bMajor = {
      trackNumber: 3,
      vibeScore: null,
      metricValues: { key: 11 },
      metricModes: { key: 1 },
    };
    const bMinor = {
      trackNumber: 4,
      vibeScore: null,
      metricValues: { key: 11 },
      metricModes: { key: 0 },
    };
    const missingMode = {
      trackNumber: 5,
      vibeScore: null,
      metricValues: { key: 3 },
      metricModes: {},
    };

    expect(valueForMetric(cMajor, "key")).toBe(1);
    expect(valueForMetric(cMinor, "key")).toBe(-1);
    expect(valueForMetric(bMajor, "key")).toBe(12);
    expect(valueForMetric(bMinor, "key")).toBe(-12);
    expect(valueForMetric(missingMode, "key")).toBeNull();
  });

  test("formatMetricValue decodes the signed value back into note name + mode", () => {
    expect(formatMetricValue("key", 1)).toBe("C major");
    expect(formatMetricValue("key", -1)).toBe("C minor");
    expect(formatMetricValue("key", 2)).toBe("C♯ major");
    expect(formatMetricValue("key", 12)).toBe("B major");
    expect(formatMetricValue("key", -12)).toBe("B minor");
  });

  test("formatMetricAxisTick renders a readable note label, marking minor with a trailing 'm'", () => {
    expect(formatMetricAxisTick("key", 1)).toBe("C");
    expect(formatMetricAxisTick("key", -1)).toBe("Cm");
    expect(formatMetricAxisTick("key", 12)).toBe("B");
    expect(formatMetricAxisTick("key", -12)).toBe("Bm");
  });
});
