# Station Master 4-Track: Gemini Project Instructions

This project is a Python-based Digital Audio Workstation (DAW) built with PyQt6. It focuses on a retro 4-track recording experience with native "tethering" support for external synthesizers.

## Architecture & Core Components

1.  **`main.py`**: The GUI layer.
    *   Uses custom widgets like `TimelineWidget`, `TrackStrip`, and `LevelMeter`.
    *   Hardcoded constants (e.g., `TRACK_HEIGHT = 160`) are critical for UI synchronization.
    *   Handles "Tethering" logic: spawning child processes (Golden Bull, ASHERAH) and managing PulseAudio routing.

2.  **`audio_engine.py`**: The DSP Core.
    *   **Callback Pattern**: Uses `sounddevice` with a non-blocking `_audio_callback`.
    *   **Locking Strategy**: Uses `threading.RLock` to synchronize between the UI thread and the audio thread. Employs a "snapshot" pattern (`_sp_` variables) to minimize lock contention in the high-priority callback.
    *   **Data Format**: All audio is processed as `float32` NumPy arrays.

3.  **`project_manager.py`**: Persistence Layer.
    *   Saves project state as JSON (`project.json`) and individual clips as FLAC files in an `audio/` subdirectory.
    *   Handles non-destructive clip management and "bouncing" the final mix.

## Engineering Conventions

-   **DSP Performance**: Always use vectorized NumPy operations inside the `audio_engine.py` callback to avoid dropping frames. Avoid heavy allocations or complex logic during the callback.
-   **UI Layout**: The UI relies on `QVBoxLayout` and `QHBoxLayout`. Ensure that modifications to `TrackStrip` maintain the fixed height to stay aligned with the `TimelineWidget`.
-   **Tethering**: External audio is routed via PulseAudio null sinks (e.g., `station_track_0_pipe`). The DAW captures the `.monitor` source of these sinks.

## Recent Features & Changes

-   **Real-time Harmony Singer**: The Harmony effect (previously a destructive offline process) is now a real-time togglable effect.
    *   Managed via `AudioEngine.update_harmony_params`.
    *   Uses `pedalboard` for real-time pitch shifting in the audio callback.
    *   The UI button (**HARMONY**) matches the **TAPE** button's checkable toggle behavior.

-   **Stereo Spread (Pseudo-Stereo)**: A frequency-splitting spread effect inspired by Logic Pro.
    *   Presets: **DRUM**, **BASS**, **GUITAR**.
    *   Implemented via 3-band frequency split and alternate panning.
    *   Controlled via the **SPREAD** menu button next to **TAPE**.

- **Chroma Glow**: A character-shaping saturation effect inspired by Logic Pro.
    *   Presets: **DARK**, **SPARKLE**, **WARM**.
    *   **DARK**: Tube-style soft clipping combined with a 1.2kHz low-pass filter for a "vintage" roll-off.
    *   **SPARKLE**: A high-frequency exciter that saturates signals above 6kHz to add "air" and detail.
    *   **WARM**: Asymmetric harmonic saturation focusing on even-order harmonics for "analog warmth."
    *   Controlled via the **CHROMA** menu button next to **SPREAD**.

- **Screenshot Capture**: A built-in feature to capture the current state of the DAW.
    *   Accessible via the **📸** button in the Project IO section.
    *   Shortcut: **F12**.
    *   Screenshots are saved to the current project directory (if loaded) or `~/Pictures/Screenshots`.

## Workflow: Adding New Effects

1.  **Engine State**: Add state variables to `AudioEngine.__init__` and their corresponding shadow variables (`_sp_`).
2.  **State Sync**: Update the state snapshot logic in `_do_audio_callback`.
3.  **DSP Implementation**: Apply the effect in the processing loop within `_do_audio_callback`.
4.  **UI Control**: Add the control to `TrackStrip` and connect it to an engine update method (use `with self.engine.lock:`).
5.  **Persistence**: Update `save_project` and `load_project` in `project_manager.py`.
6.  **Bounce**: Ensure the effect is correctly applied in `project_manager.bounce_mix`.
