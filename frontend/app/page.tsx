"use client";

import { useState, type FormEvent } from "react";
import Image from "next/image";
import styles from "./page.module.css";
import { ApiRequestError, revealRound, startRound, submitGuess } from "./api";
import ArtistAutocomplete from "./ArtistAutocomplete";
import GameChart from "./GameChart";
import MetricGlossary from "./MetricGlossary";
import type {
  AlbumOption,
  ArtistSuggestion,
  HintPoint,
  RevealedMetric,
  RevealResponse,
} from "./types";
import { HINT_METRIC_ORDER } from "./types";

type GameState = "landing" | "round" | "reveal";

function revealedMetricsFromReveal(reveal: RevealResponse): RevealedMetric[] {
  return reveal.revealed_metrics.map((metric) => ({
    metric,
    data: reveal.tracks.map((track) => ({
      track_number: track.track_number,
      value: (track[metric] as number | null | undefined) ?? null,
      mode: metric === "key" ? (track.mode ?? null) : null,
    })),
  }));
}

function hintsFromReveal(reveal: RevealResponse): HintPoint[] {
  return reveal.tracks.map((track) => ({
    track_number: track.track_number,
    vibe_score: track.vibe_score,
  }));
}

function trackNamesFromReveal(reveal: RevealResponse): Record<number, string> {
  return Object.fromEntries(reveal.tracks.map((track) => [track.track_number, track.name]));
}

export default function Home() {
  const [gameState, setGameState] = useState<GameState>("landing");
  const [artistInput, setArtistInput] = useState("");
  const [artistName, setArtistName] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [roundId, setRoundId] = useState<string | null>(null);
  const [albumOptions, setAlbumOptions] = useState<AlbumOption[]>([]);
  const [eliminatedIds, setEliminatedIds] = useState<string[]>([]);
  const [hints, setHints] = useState<HintPoint[]>([]);
  const [revealedMetrics, setRevealedMetrics] = useState<RevealedMetric[]>([]);
  const [wrongGuessCount, setWrongGuessCount] = useState(0);
  const [trackCount, setTrackCount] = useState(0);
  const [guessing, setGuessing] = useState(false);

  const [reveal, setReveal] = useState<RevealResponse | null>(null);

  function resetRoundState() {
    setRoundId(null);
    setAlbumOptions([]);
    setEliminatedIds([]);
    setHints([]);
    setRevealedMetrics([]);
    setWrongGuessCount(0);
    setTrackCount(0);
    setReveal(null);
  }

  async function beginRound(params: { artistName?: string; artistSpotifyId?: string }) {
    setLoading(true);
    setError(null);
    resetRoundState();

    try {
      const result = await startRound(params);
      setRoundId(result.round_id);
      setArtistName(result.artist_name);
      setAlbumOptions(result.album_options);
      setHints(result.hints);
      setTrackCount(result.track_count);
      setGameState("round");
    } catch (err) {
      const attemptedName = params.artistName ?? artistInput;
      if (err instanceof ApiRequestError) {
        if (err.status === 404) {
          setError(
            `Couldn't find an artist named "${attemptedName}" on Spotify. Check the spelling and try again.`
          );
        } else {
          // backend already phrases 422s ("not enough albums" / "no suitable
          // album") as friendly, artist specific sentences, show as is
          setError(err.message);
        }
      } else {
        setError("Couldn't reach the SoundPrint backend. Is it running?");
      }
      setGameState("landing");
    } finally {
      setLoading(false);
    }
  }

  async function handleStartSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = artistInput.trim();
    if (!name) {
      return;
    }
    await beginRound({ artistName: name });
  }

  function handleSelectSuggestion(artist: ArtistSuggestion) {
    setArtistInput(artist.name);
    void beginRound({ artistSpotifyId: artist.spotify_id, artistName: artist.name });
  }

  async function fetchReveal(giveUp: boolean) {
    if (!roundId) {
      return;
    }
    try {
      const result = await revealRound(roundId, giveUp);
      setReveal(result);
      setGameState("reveal");
    } catch {
      setError("Couldn't load the reveal for this round. Please try again.");
    }
  }

  async function handleGuess(albumSpotifyId: string) {
    if (!roundId || guessing) {
      return;
    }
    setGuessing(true);
    setError(null);

    try {
      const result = await submitGuess(roundId, albumSpotifyId);
      if (result.correct) {
        await fetchReveal(false);
        return;
      }

      setWrongGuessCount(result.wrong_guess_count);
      setEliminatedIds(result.eliminated_album_ids);
      if (result.newly_revealed_metric) {
        const metric = result.newly_revealed_metric;
        setRevealedMetrics((prev) => [...prev, metric]);
      }
    } catch {
      setError("Couldn't submit that guess. Please try again.");
    } finally {
      setGuessing(false);
    }
  }

  function handleNewArtist() {
    resetRoundState();
    setArtistName(null);
    setArtistInput("");
    setError(null);
    setGameState("landing");
  }

  const remainingOptions = albumOptions.filter(
    (option) => !eliminatedIds.includes(option.spotify_id)
  );

  return (
    <div className={styles.page}>
      <main className={styles.main}>
        <div className={styles.header}>
          <h1 className={styles.title}>SoundPrint</h1>
          <p className={styles.subtitle}>
            Guess the album from its unlabeled energy chart.
          </p>
        </div>

        {gameState === "landing" && (
          <form className={`${styles.form} ${styles.headerWidth}`} onSubmit={handleStartSubmit}>
            <ArtistAutocomplete
              value={artistInput}
              onChange={setArtistInput}
              onSelect={handleSelectSuggestion}
              disabled={loading}
            />
            <button className={styles.button} type="submit" disabled={loading}>
              {loading ? "Starting..." : "Start guessing"}
            </button>
          </form>
        )}

        {error && (
          <p className={`${styles.error} ${styles.headerWidth}`} role="alert">
            {error}
          </p>
        )}

        {gameState === "round" && (
          <div className={styles.gameLayout}>
            <section className={styles.gameMain}>
              <div>
                <h2 className={styles.resultTitle}>Guess the {artistName} album</h2>
                <p className={styles.resultMeta}>
                  {trackCount} tracks · {wrongGuessCount}{" "}
                  {wrongGuessCount === 1 ? "wrong guess" : "wrong guesses"}
                </p>
              </div>

              <GameChart key={roundId} hints={hints} revealedMetrics={revealedMetrics} />

              <ul className={styles.optionList}>
                {remainingOptions.map((option) => (
                  <li key={option.spotify_id}>
                    <button
                      className={styles.optionButton}
                      onClick={() => handleGuess(option.spotify_id)}
                      disabled={guessing}
                    >
                      {option.name}
                    </button>
                  </li>
                ))}
              </ul>

              <button
                className={styles.giveUpButton}
                type="button"
                onClick={() => fetchReveal(true)}
                disabled={guessing}
              >
                Give up &amp; reveal the answer
              </button>
            </section>

            <MetricGlossary revealedMetrics={revealedMetrics.map((entry) => entry.metric)} />
          </div>
        )}

        {gameState === "reveal" && reveal && (
          <div className={styles.gameLayout}>
            <section className={styles.gameMain}>
              <div className={styles.resultHeader}>
                {reveal.album_image_url && (
                  <Image
                    className={styles.coverArt}
                    src={reveal.album_image_url}
                    alt={`${reveal.album_name} cover art`}
                    width={160}
                    height={160}
                    unoptimized
                  />
                )}
                <div>
                  <h2 className={styles.resultTitle}>{reveal.album_name}</h2>
                  <p className={styles.resultOwner}>{reveal.artist_name}</p>
                </div>
              </div>

              <GameChart
                key={`${roundId}-reveal`}
                hints={hintsFromReveal(reveal)}
                revealedMetrics={revealedMetricsFromReveal(reveal)}
                trackNames={trackNamesFromReveal(reveal)}
              />

              <ol className={styles.trackList}>
                {reveal.tracks.map((track) => (
                  <li key={track.track_number} className={styles.track}>
                    <span className={styles.trackNumber}>{track.track_number}</span>
                    <span className={styles.trackName}>{track.name}</span>
                  </li>
                ))}
              </ol>

              <div className={styles.playAgainRow}>
                <button
                  className={styles.button}
                  type="button"
                  onClick={() => artistName && beginRound({ artistName })}
                >
                  Play again ({artistName})
                </button>
                <button className={styles.secondaryButton} type="button" onClick={handleNewArtist}>
                  Try a different artist
                </button>
              </div>
            </section>

            <MetricGlossary revealedMetrics={HINT_METRIC_ORDER} />
          </div>
        )}
      </main>
    </div>
  );
}
