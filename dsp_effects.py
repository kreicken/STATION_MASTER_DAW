import numpy as np
from pedalboard import Pedalboard, PitchShift

# ---------------------------------------------------------------------------
# Offline Harmony Processor — Rubber Band via pedalboard
# ---------------------------------------------------------------------------
# Strategy: Apply pitch-shifting destructively to recorded clips using
# pedalboard's PitchShift (backed by Rubber Band Library).  This runs
# offline (not in the audio callback), so quality is unconstrained by
# real-time deadlines.
#
# Called from a QThread in main.py so the UI stays responsive.
# ---------------------------------------------------------------------------

# Semitone intervals per named mode — matches HarmonyDialog in main.py
HARMONY_MODES = {
    0: [4],        # Higher       — 3rd up
    1: [-5],       # Lower        — 4th down
    2: [4, 7],     # High & Higher — 3rd up & 5th up
    3: [-5, -9],   # Low & Lower  — 4th down & 6th down
    4: [4, -5],    # High & Low   — 3rd up & 4th down
    5: [7, -9],    # Higher & Lower — 5th up & 6th down
    6: [12],       # Octave Up
    7: [-12],      # Octave Down
}


def apply_harmony_offline(
    audio: np.ndarray,
    sample_rate: int,
    mode_index: int,
    mix: float,
) -> np.ndarray:
    """
    Pitch-shift ``audio`` using Rubber Band and blend with the dry signal.

    Args:
        audio:       1-D float32 mono array (the clip's active region).
        sample_rate: Engine sample rate (44100 or 48000).
        mode_index:  Index into HARMONY_MODES (0–7).
        mix:         Wet mix 0.0–1.0.

    Returns:
        Processed 1-D float32 array, same length as input.
    """
    audio = np.asarray(audio, dtype=np.float32)
    if len(audio) == 0 or mix <= 0.0:
        return audio

    shifts = HARMONY_MODES.get(mode_index, [0])

    # Build wet signal: sum of all shifted voices, normalised to unity gain
    wet = np.zeros_like(audio)
    chunk_2d = audio.reshape(1, -1)   # pedalboard expects (channels, samples)

    for semitones in shifts:
        board = Pedalboard([PitchShift(semitones=float(semitones))])
        shifted = board.process(chunk_2d, sample_rate, reset=True)  # offline — full quality
        # Rubber Band output is always the same length when reset=True
        shifted_mono = shifted[0]
        # Guard against length mismatch (Rubber Band can differ by a few samples)
        l = min(len(wet), len(shifted_mono))
        # Bug H6 fix: Use += for accumulation instead of assignment
        wet[:l] += shifted_mono[:l]

    wet /= max(len(shifts), 1)

    # Dry / wet blend
    result = audio * (1.0 - mix) + wet * mix
    return np.clip(result, -1.0, 1.0).astype(np.float32)
