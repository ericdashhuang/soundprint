import type { HintMetric } from "./types";

const NOTE_NAMES = [
  "C",
  "C♯",
  "D",
  "D♯",
  "E",
  "F",
  "F♯",
  "G",
  "G♯",
  "A",
  "A♯",
  "B",
];

export type ChartMetric = HintMetric | "vibe_score";

export const ALL_METRIC_LABELS: Record<ChartMetric, string> = {
  vibe_score: "Energy level",
  danceability: "Danceability",
  acousticness: "Acousticness",
  instrumentalness: "Instrumentalness",
  speechiness: "Speechiness",
  loudness: "Loudness",
  key: "Key",
};

export const METRIC_LABELS: Record<HintMetric, string> = {
  danceability: "Danceability",
  acousticness: "Acousticness",
  instrumentalness: "Instrumentalness",
  speechiness: "Speechiness",
  loudness: "Loudness",
  key: "Key",
};

export const METRIC_COLORS: Record<ChartMetric, string> = {
  vibe_score: "var(--accent)",
  danceability: "var(--chart-danceability)",
  acousticness: "var(--chart-acousticness)",
  instrumentalness: "var(--chart-instrumentalness)",
  speechiness: "var(--chart-speechiness)",
  loudness: "var(--chart-loudness)",
  key: "var(--chart-key)",
};

/** each metric now renders on its own chart (one line visible at a time via
 * a toggle), so there's no need to squeeze every metric onto a shared 0 to 1
 * axis anymore, each gets the y domain that actually fits its raw values */
export const METRIC_Y_DOMAIN: Record<ChartMetric, [number, number] | undefined> = {
  vibe_score: [0, 1],
  danceability: [0, 1],
  acousticness: [0, 1],
  instrumentalness: [0, 1],
  speechiness: [0, 1],
  loudness: undefined,
  key: [-12, 12],
};

// key is charted as a single signed value sign = major (+) / minor (-),
// magnitude = 1-indexed pitch class (c = 1 ... b = 12, ie raw spotify
// pitch class + 1), these helpers decode that back into a note name + mode
function decodeKeyValue(value: number): { noteName: string; modeName: "major" | "minor" } {
  const magnitude = Math.round(Math.abs(value));
  const pitchClass = (magnitude - 1 + NOTE_NAMES.length) % NOTE_NAMES.length;
  const noteName = NOTE_NAMES[pitchClass] ?? "?";
  const modeName = value < 0 ? "minor" : "major";
  return { noteName, modeName };
}

export function formatMetricValue(metric: ChartMetric, value: number): string {
  if (metric === "loudness") {
    return `${value.toFixed(1)} dB`;
  }
  if (metric === "key") {
    const { noteName, modeName } = decodeKeyValue(value);
    return `${noteName} ${modeName}`;
  }
  return value.toFixed(2);
}

export function formatMetricAxisTick(metric: ChartMetric, value: number): string {
  if (metric === "key") {
    const { noteName, modeName } = decodeKeyValue(value);
    return modeName === "minor" ? `${noteName}m` : noteName;
  }
  if (metric === "loudness") {
    return `${value.toFixed(0)} dB`;
  }
  return value.toFixed(2);
}
