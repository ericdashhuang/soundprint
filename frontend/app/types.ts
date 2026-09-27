export interface Vibe {
  vibe_score: number;
  energy: number;
  brightness: number;
  tempo_bpm: number;
  source: string;
  danceability?: number | null;
  acousticness?: number | null;
  instrumentalness?: number | null;
  speechiness?: number | null;
  loudness?: number | null;
  key?: number | null;
  mode?: number | null;
}

export interface Track {
  spotify_id: string;
  name: string;
  artist: string;
  duration_ms: number;
  track_number: number;
  preview_url: string | null;
  vibe: Vibe | null;
}

export interface LookupResult {
  item_type: "album" | "playlist";
  spotify_id: string;
  name: string;
  owner: string;
  cover_art_url: string | null;
  tracks: Track[];
}

// --- album guessing game -----------------------------------------------------

// metric keys revealed one at a time as guesses go wrong, in reveal order
// "vibeScore" is the always visible base line and is not part of this list
export type HintMetric =
  | "danceability"
  | "acousticness"
  | "instrumentalness"
  | "speechiness"
  | "loudness"
  | "key";

export const HINT_METRIC_ORDER: HintMetric[] = [
  "danceability",
  "acousticness",
  "instrumentalness",
  "speechiness",
  "loudness",
  "key",
];

export const METRIC_DESCRIPTIONS: Record<HintMetric | "vibe_score", string> = {
  vibe_score: "A 0-1 rating of valence and musical positiveness.",
  danceability:
    "How suitable the track is for dancing, based on rhythm and beat regularity.",
  acousticness: "How acoustic the track sounds versus electronic.",
  instrumentalness: "How much of the track is instrumental.",
  speechiness: "How much of the track is spoken versus sung.",
  loudness: "Overall loudness of the track, in decibels.",
  key: "A positive or negative score based on whether the key is major or minor.",
};

export interface AlbumOption {
  spotify_id: string;
  name: string;
}

export interface HintPoint {
  track_number: number;
  vibe_score: number | null;
}

export interface StartRoundResponse {
  round_id: string;
  artist_name: string;
  album_options: AlbumOption[];
  track_count: number;
  hints: HintPoint[];
}

export interface MetricPoint {
  track_number: number;
  value: number | null;
  mode: number | null;
}

export interface RevealedMetric {
  metric: HintMetric;
  data: MetricPoint[];
}

export interface GuessResponse {
  correct: boolean;
  wrong_guess_count: number;
  // authoritative, cumulative list of every album id guessed wrong so far
  // this round, render eliminated options from this, not from locally
  // accumulated state
  eliminated_album_ids: string[];
  newly_revealed_metric: RevealedMetric | null;
}

export interface ArtistSuggestion {
  spotify_id: string;
  name: string;
  image_url: string | null;
}

export interface RevealedTrack {
  track_number: number;
  name: string;
  vibe_score: number | null;
  danceability?: number | null;
  acousticness?: number | null;
  instrumentalness?: number | null;
  speechiness?: number | null;
  loudness?: number | null;
  key?: number | null;
  mode?: number | null;
}

export interface RevealResponse {
  album_name: string;
  album_image_url: string | null;
  artist_name: string;
  tracks: RevealedTrack[];
  revealed_metrics: HintMetric[];
}

export interface ApiError {
  detail: string;
}
