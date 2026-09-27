"""per track vibe/energy analysis from spotify 30-second preview clips

spotify's own audio-features/audio-analysis endpoints are permanently gone for
apps registered after 2024/11/27 (see project AGENTS.md), so this module
computes an approximate "energy" signal itself from the preview clip audio

essentia was evaluated as the primary approach (its pretrained
mood_happy/mood_sad/mood_aggressive/mood_relaxed/danceability classifiers are
the more credible signal, see the linked research report), it was not used
here because, in this environment

  the plain `essentia` PyPI wheel does not include the tensorflow inference
    ops (`TensorflowPredict*`) needed to run those pretrained classifiers at
    all, only `essentia-tensorflow` does
  `essentia-tensorflow` bundles a full tensorflow build (a ~100mb wheel) and
    still ships no model weights running the actual mood_happy/mood_sad/etc
    classifiers requires separately downloading multiple pretrained `.pb`
    model files from essentia.upf.edu at runtime, which has no clean vendoring
    story for this repo and would make the automated test suite depend on
    live network access to a third party model host

given that, this module uses librosa instead, as the explicitly sanctioned
fallback rms energy, spectral centroid ("brightness"), and tempo, combined
into a single 0 to 1 `vibe_score` that approximates "energetic/bright vs calm/
mellow." this is a hand tuned proxy, not a validated mood classifier, it's
an approximation, not an audio features replacement
"""

from dataclasses import dataclass
from io import BytesIO

import httpx
import librosa
import numpy as np

SOURCE_LABEL = "librosa_fallback"

# normalization ceilings for mapping raw librosa features into a 0 to 1 range
# these are rough, empirically reasonable bounds for mastered pop/rock preview
# clips, not derived from a labeled dataset, see module docstring
_RMS_ENERGY_CEILING = 0.3
_BRIGHTNESS_CEILING_HZ = 4000.0


class PreviewDownloadError(Exception):
    """raised when a preview clip url can't be fetched"""


class AudioAnalysisError(Exception):
    """raised when a downloaded clip can't be decoded/analyzed"""


@dataclass(frozen=True)
class VibeFeatures:
    vibe_score: float
    energy: float
    brightness: float
    tempo_bpm: float
    source: str = SOURCE_LABEL


async def download_preview_clip(
    preview_url: str, http_client: httpx.AsyncClient | None = None
) -> bytes:
    """fetch a 30-second preview clip's raw audio bytes"""
    client = http_client or httpx.AsyncClient(timeout=10.0)
    try:
        response = await client.get(preview_url)
        response.raise_for_status()
        return response.content
    except httpx.HTTPError as exc:
        raise PreviewDownloadError(f"Could not download preview clip: {exc}") from exc
    finally:
        if http_client is None:
            await client.aclose()


def analyze_audio(clip_bytes: bytes) -> VibeFeatures:
    """compute an approximate vibe/energy signal from raw preview clip bytes"""
    try:
        y, sr = librosa.load(BytesIO(clip_bytes), sr=None, mono=True)
    except Exception as exc:  # librosa/soundfile raise varied decode errors
        raise AudioAnalysisError(f"Could not decode audio clip: {exc}") from exc

    if y.size == 0:
        raise AudioAnalysisError("Decoded audio clip is empty.")

    rms_mean = float(np.mean(librosa.feature.rms(y=y)))
    centroid_mean = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    tempo_bpm = float(np.atleast_1d(tempo)[0])

    energy = min(rms_mean / _RMS_ENERGY_CEILING, 1.0)
    brightness = min(centroid_mean / _BRIGHTNESS_CEILING_HZ, 1.0)
    vibe_score = round((energy + brightness) / 2, 4)

    return VibeFeatures(
        vibe_score=vibe_score,
        energy=round(energy, 4),
        brightness=round(brightness, 4),
        tempo_bpm=round(tempo_bpm, 2),
    )
