# Station DAW Workspace Overview

## What is it?
**Station Master 4-Track** is a Python-based Digital Audio Workstation (DAW) built with PyQt6. It provides a retro-styled 4-track recording environment with built-in effects, level metering, and timeline editing. 

## Key Components
1. **`main.py`**: The GUI application. It handles the timeline drawing, track strip UI, and orchestrating interactions. It contains custom widgets like `TimelineWidget`, `TrackStrip`, and `LevelMeter`.
2. **`audio_engine.py`**: The DSP core. It handles audio playback, recording, and applying real-time effects (EQ, Tape Saturation, Reverb, Delay) using `sounddevice`, `numpy`, and `soundfile`.
3. **`project_manager.py`**: Manages saving and loading project states, managing audio files, and undo/redo states.

## How it works with Golden Bull / ASHERAH
Station DAW has native "tethering" support for the Golden Bull Synthesizer and ASHERAH Sequencer Suite. Instead of running them via traditional plugin formats (like VST), Station DAW spawns them as child Python processes and routes their audio natively via Linux PulseAudio.

### The Tethering Process:
1. **Source Selection**: When a user selects "Golden Bull Synth" or "ASHERAH Suite" on a Track Strip's input source dropdown, `main.py` launches the respective Python application from the `golden_bull_synth` directory.
2. **Virtual Piping**: It automatically creates a dedicated PulseAudio null sink for that specific track (e.g., `station_track_0_pipe`).
3. **Audio Capture**: The child synth process's `PULSE_SINK` is set to this pipe, and the DAW's `PULSE_SOURCE` for that track is set to `station_track_0_pipe.monitor`. This pipes the pure generated NumPy audio directly into the DAW's timeline when armed/recording.

## Up to Speed / Future Sessions
- **Audio Processing**: All audio is processed as float32 `numpy` arrays. If you modify DSP code, stick to fast numpy vector operations to avoid dropping frames in the `audio_engine.py` audio callback.
- **UI Modifications**: The UI heavily relies on `QVBoxLayout` and `QHBoxLayout` in `TrackStrip`. Hardcoded heights (like `TRACK_HEIGHT = 160`) are used to synchronize the track strips on the left with the timeline tracks on the right.
- **Dependencies**: The project relies on `numpy`, `sounddevice`, `soundfile`, `pydub`, and `PyQt6`. Run from the `.venv` virtual environment.
