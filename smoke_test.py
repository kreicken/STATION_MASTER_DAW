"""
Station Master 4-Track — Smoke Test Suite
==========================================
Run from the project root directory:
    python smoke_test.py

All tests run WITHOUT audio hardware (uses silent/virtual audio).
No microphone or speakers needed. Tests the engine logic only.

Pass criteria: all tests print PASS. Any FAIL = regression introduced.
"""

import sys
import os
import time
import numpy as np
import unittest

# Add project root to path so audio_engine imports correctly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Silence sounddevice hardware errors during testing — we inject audio manually
import unittest.mock as mock

# ─── Helpers ────────────────────────────────────────────────────────────────

def make_engine():
    """Create an AudioEngine with no hardware stream."""
    from audio_engine import AudioEngine
    engine = AudioEngine(sample_rate=44100)
    return engine

def make_sine_clip(engine, duration_sec=1.0, freq=440.0, start_frame=0):
    """Create a Clip containing a pure sine wave."""
    from audio_engine import Clip
    sr = engine.sample_rate
    n = int(duration_sec * sr)
    t = np.linspace(0, duration_sec, n, endpoint=False)
    data = np.sin(2 * np.pi * freq * t).astype(np.float32)
    return Clip(data, start_frame)

def run_callback_blocks(engine, n_blocks=10, block_size=512, inject_audio=None):
    """
    Drive the audio callback manually with synthetic input.
    Returns the output buffer from the last block.
    """
    indata = np.zeros((block_size, 1), dtype=np.float32)
    outdata = np.zeros((block_size, 2), dtype=np.float32)

    if inject_audio is not None:
        indata[:, 0] = inject_audio[:block_size]

    for _ in range(n_blocks):
        outdata.fill(0)
        try:
            engine._do_audio_callback(indata, outdata, block_size, None, None)
        except Exception as e:
            return None, str(e)

    return outdata.copy(), None


# ─── Test Cases ─────────────────────────────────────────────────────────────

class TestEngineInit(unittest.TestCase):

    def test_engine_creates_without_error(self):
        """AudioEngine __init__ must complete without raising."""
        try:
            engine = make_engine()
            self.assertIsNotNone(engine)
        except Exception as e:
            self.fail(f"AudioEngine() raised during init: {e}")

    def test_initial_state(self):
        """Transport flags must be False at init."""
        engine = make_engine()
        self.assertFalse(engine.is_playing)
        self.assertFalse(engine.is_recording)
        self.assertEqual(engine.armed_track, -1)
        self.assertEqual(engine.current_frame, 0)

    def test_pultec_sos_initialized(self):
        """Pultec SOS array must be shape (4,4,6) and not all zeros on flat preset."""
        engine = make_engine()
        # Flat preset produces unity coefficients [1,0,0,1,0,0] — shape must be correct
        self.assertEqual(engine._pultec_sos.shape, (4, 4, 6))

    def test_preallocated_buffers_exist(self):
        """Pre-allocated working buffers must exist and be numpy arrays."""
        engine = make_engine()
        self.assertIsInstance(engine._buf_mixed,      np.ndarray)
        self.assertIsInstance(engine._buf_bus_send,   np.ndarray)
        self.assertIsInstance(engine._buf_track_mono, np.ndarray)


class TestCallbackSilence(unittest.TestCase):

    def test_callback_runs_when_stopped(self):
        """Callback must run without exception when transport is stopped."""
        engine = make_engine()
        out, err = run_callback_blocks(engine, n_blocks=5)
        self.assertIsNone(err, f"Callback raised: {err}")

    def test_output_is_silent_when_stopped(self):
        """Output must be silence (all zeros) when not playing and no arm."""
        engine = make_engine()
        out, err = run_callback_blocks(engine, n_blocks=1)
        self.assertIsNone(err)
        self.assertTrue(np.all(out == 0.0), "Expected silence but got non-zero output")

    def test_no_nan_in_output_when_stopped(self):
        """Output must contain no NaN or Inf values even when stopped."""
        engine = make_engine()
        out, err = run_callback_blocks(engine, n_blocks=5)
        self.assertIsNone(err)
        self.assertTrue(np.isfinite(out).all(), "NaN or Inf in silent output")


class TestClipPlayback(unittest.TestCase):

    def test_clip_produces_nonzero_output(self):
        """A clip placed at frame 0 must produce non-silent output during playback."""
        engine = make_engine()
        clip = make_sine_clip(engine, duration_sec=1.0)
        with engine.lock:
            engine.tracks[0].append(clip)
            engine._active_track_buf[0] = list(engine.tracks[0])

        engine.is_playing = True
        engine._sp_playing = True
        engine.current_frame = 0

        out, err = run_callback_blocks(engine, n_blocks=3)
        self.assertIsNone(err, f"Callback raised during playback: {err}")
        self.assertGreater(np.max(np.abs(out)), 0.0, "Clip playback produced silence")

    def test_no_nan_during_playback(self):
        """No NaN or Inf must appear in output during normal clip playback."""
        engine = make_engine()
        clip = make_sine_clip(engine, duration_sec=2.0)
        with engine.lock:
            engine.tracks[0].append(clip)
            engine._active_track_buf[0] = list(engine.tracks[0])

        engine.is_playing = True
        engine._sp_playing = True

        out, err = run_callback_blocks(engine, n_blocks=10)
        self.assertIsNone(err)
        self.assertTrue(np.isfinite(out).all(), "NaN/Inf detected during playback")

    def test_muted_track_produces_silence(self):
        """A muted track must contribute no signal to the mix."""
        engine = make_engine()
        clip = make_sine_clip(engine, duration_sec=1.0)
        with engine.lock:
            engine.tracks[0].append(clip)
            engine._active_track_buf[0] = list(engine.tracks[0])
            engine.track_mutes[0] = True

        engine.is_playing = True
        engine._sp_playing = True
        engine._sp_mutes[0] = True

        out, err = run_callback_blocks(engine, n_blocks=3)
        self.assertIsNone(err)
        self.assertTrue(np.all(out == 0.0), "Muted track leaked signal into output")

    def test_volume_zero_produces_silence(self):
        """Track volume at 0.0 must produce silence."""
        engine = make_engine()
        clip = make_sine_clip(engine, duration_sec=1.0)
        with engine.lock:
            engine.tracks[0].append(clip)
            engine._active_track_buf[0] = list(engine.tracks[0])
            engine.track_volumes[0] = 0.0

        engine.is_playing = True
        engine._sp_playing = True
        engine._sp_vols[0] = 0.0

        out, err = run_callback_blocks(engine, n_blocks=3)
        self.assertIsNone(err)
        self.assertTrue(np.all(out == 0.0), "Zero-volume track leaked signal")


class TestRecording(unittest.TestCase):

    def test_start_recording_sets_flags(self):
        """start_recording must set is_recording, is_playing, and armed_track."""
        engine = make_engine()
        # Patch _ensure_stream and _stop_monitor so no hardware is touched
        engine._ensure_stream = mock.MagicMock()
        engine._stop_monitor = mock.MagicMock()

        engine.start_recording(0)

        self.assertTrue(engine.is_recording,  "is_recording not set after start_recording()")
        self.assertTrue(engine.is_playing,    "is_playing not set after start_recording()")
        self.assertEqual(engine.armed_track, 0, "armed_track not set correctly")

    def test_start_recording_calls_ensure_stream(self):
        """start_recording MUST call _ensure_stream — this was the missing-stream bug."""
        engine = make_engine()
        engine._ensure_stream = mock.MagicMock()
        engine._stop_monitor = mock.MagicMock()

        engine.start_recording(1)

        engine._ensure_stream.assert_called_once(), \
            "REGRESSION: _ensure_stream not called — recording will never start"

    def test_recording_buffer_cleared_on_start(self):
        """recording_buffer must be empty list at start of a new recording session."""
        engine = make_engine()
        engine._ensure_stream = mock.MagicMock()
        engine._stop_monitor = mock.MagicMock()
        engine.recording_buffer = [np.zeros(512)]  # Simulate leftover data

        engine.start_recording(0)

        self.assertEqual(engine.recording_buffer, [],
                         "recording_buffer not cleared on new session start")

    def test_callback_captures_audio_when_recording(self):
        """Callback must append to recording_buffer when armed and recording."""
        engine = make_engine()
        engine.is_playing = True
        engine.is_recording = True
        engine.armed_track = 0
        engine._sp_playing = True
        engine._sp_recording = True
        engine._sp_armed = 0
        engine._sp_monitoring[0] = True
        engine._sp_input_gains[0] = 1.0

        # Inject a non-silent sine signal as mic input
        sr = engine.sample_rate
        block = 512
        t = np.linspace(0, block/sr, block, endpoint=False)
        mic = np.sin(2 * np.pi * 440 * t).astype(np.float32)

        out, err = run_callback_blocks(engine, n_blocks=5, inject_audio=mic)
        self.assertIsNone(err, f"Callback raised during recording: {err}")
        self.assertGreater(len(engine.recording_buffer), 0,
                           "Nothing was captured in recording_buffer during record")

    def test_stop_commits_clip(self):
        """stop() must commit recording_buffer as a Clip on the armed track."""
        engine = make_engine()
        engine._stop_monitor = mock.MagicMock()
        engine._ensure_stream = mock.MagicMock()

        # Pre-populate a recording buffer as if the callback captured audio
        engine.is_recording = True
        engine.is_playing = True
        engine.armed_track = 2
        engine.record_start_frame = 0
        engine.recording_buffer = [np.zeros(512, dtype=np.float32) + 0.5]

        # Patch stream teardown
        engine.stream = mock.MagicMock()
        engine.stream.stop = mock.MagicMock()
        engine.stream.close = mock.MagicMock()

        engine.stop()

        clips = engine.tracks[2]
        self.assertEqual(len(clips), 1, "stop() did not commit recording_buffer as a Clip")
        self.assertGreater(clips[0].length_frame, 0, "Committed clip has zero length")


class TestPultecEQ(unittest.TestCase):

    def test_pultec_changes_output_when_enabled(self):
        """Pultec with non-zero boost must change the output vs. dry signal."""
        engine = make_engine()
        clip = make_sine_clip(engine, duration_sec=1.0, freq=60.0)

        with engine.lock:
            engine.tracks[0].append(clip)
            engine._active_track_buf[0] = list(engine.tracks[0])

        engine.is_playing = True
        engine._sp_playing = True
        engine.current_frame = 0

        # Run dry pass
        out_dry, _ = run_callback_blocks(engine, n_blocks=5)

        # Reset and run with Pultec low boost engaged
        engine.current_frame = 0
        engine.update_pultec_params(
            0, enabled=True,
            low_freq=0, low_boost=10.0, low_cut=0.0,
            high_freq=2, high_boost=0.0, high_cut=0.0,
            preset=0
        )
        engine._sp_pultec_enabled[0] = True
        np.copyto(engine._sp_pultec_sos[0], engine._pultec_sos[0])

        out_wet, err = run_callback_blocks(engine, n_blocks=5)
        self.assertIsNone(err)

        diff = np.max(np.abs(out_wet - out_dry))
        self.assertGreater(diff, 1e-4,
            "Pultec with 10dB low boost produced identical output to dry — EQ is silent/broken")

    def test_pultec_flat_matches_dry(self):
        """Pultec at flat (all zero gains) must not alter the signal."""
        engine = make_engine()
        clip = make_sine_clip(engine, duration_sec=1.0)

        with engine.lock:
            engine.tracks[0].append(clip)
            engine._active_track_buf[0] = list(engine.tracks[0])

        engine.is_playing = True
        engine._sp_playing = True
        engine.current_frame = 0
        out_dry, _ = run_callback_blocks(engine, n_blocks=5)

        engine.current_frame = 0
        engine.update_pultec_params(
            0, enabled=True,
            low_freq=1, low_boost=0.0, low_cut=0.0,
            high_freq=2, high_boost=0.0, high_cut=0.0,
            preset=0
        )
        engine._sp_pultec_enabled[0] = True
        np.copyto(engine._sp_pultec_sos[0], engine._pultec_sos[0])

        out_flat, err = run_callback_blocks(engine, n_blocks=5)
        self.assertIsNone(err)

        diff = np.max(np.abs(out_flat - out_dry))
        self.assertLess(diff, 1e-3,
            f"Pultec at flat settings altered signal by {diff:.6f} — unity filter broken")

    def test_pultec_no_nan_output(self):
        """Pultec at extreme gain must never produce NaN or Inf."""
        engine = make_engine()
        clip = make_sine_clip(engine, duration_sec=1.0)

        with engine.lock:
            engine.tracks[0].append(clip)
            engine._active_track_buf[0] = list(engine.tracks[0])

        engine.update_pultec_params(
            0, enabled=True,
            low_freq=0, low_boost=15.0, low_cut=15.0,
            high_freq=4, high_boost=12.0, high_cut=12.0,
            preset=0
        )
        engine._sp_pultec_enabled[0] = True
        np.copyto(engine._sp_pultec_sos[0], engine._pultec_sos[0])

        engine.is_playing = True
        engine._sp_playing = True

        out, err = run_callback_blocks(engine, n_blocks=10)
        self.assertIsNone(err)
        self.assertTrue(np.isfinite(out).all(),
            "Pultec at extreme gain produced NaN or Inf — numerical instability")


class TestNaNInjection(unittest.TestCase):

    def test_nan_input_does_not_poison_output(self):
        """NaN injected as mic input must not propagate to output (BUG-002 regression)."""
        engine = make_engine()
        engine.is_playing = True
        engine._sp_playing = True
        engine.armed_track = 0
        engine._sp_armed = 0
        engine._sp_monitoring[0] = True

        nan_block = np.full(512, float('nan'), dtype=np.float32)
        out, err = run_callback_blocks(engine, n_blocks=3, inject_audio=nan_block)

        self.assertIsNone(err, f"Callback raised on NaN input: {err}")
        self.assertTrue(np.isfinite(out).all(),
            "NaN from mic input leaked into output — BUG-002 not fixed")

    def test_nan_input_does_not_corrupt_filter_state(self):
        """After NaN input, subsequent clean audio must produce finite output."""
        engine = make_engine()
        engine.is_playing = True
        engine._sp_playing = True
        engine.armed_track = 0
        engine._sp_armed = 0
        engine._sp_monitoring[0] = True

        # Inject NaN
        nan_block = np.full(512, float('nan'), dtype=np.float32)
        run_callback_blocks(engine, n_blocks=2, inject_audio=nan_block)

        # Now inject clean silence
        clean_block = np.zeros(512, dtype=np.float32)
        out, err = run_callback_blocks(engine, n_blocks=5, inject_audio=clean_block)

        self.assertIsNone(err)
        self.assertTrue(np.isfinite(out).all(),
            "Filter state poisoned by prior NaN input — engine requires restart to recover")


class TestLooping(unittest.TestCase):

    def test_loop_wrap_does_not_exceed_end(self):
        """current_frame must never exceed loop_end after a loop wrap (BUG-003 regression)."""
        engine = make_engine()
        clip = make_sine_clip(engine, duration_sec=5.0)

        with engine.lock:
            engine.tracks[0].append(clip)
            engine._active_track_buf[0] = list(engine.tracks[0])

        engine.loop_enabled = True
        engine.loop_start_frame = 0
        engine.loop_end_frame = 1000   # Tight loop — will wrap mid-block
        engine._sp_loop_enabled = True
        engine._sp_loop_start = 0
        engine._sp_loop_end = 1000
        engine.is_playing = True
        engine._sp_playing = True
        engine.current_frame = 990     # Close to end — will wrap mid-block

        run_callback_blocks(engine, n_blocks=5)

        self.assertLessEqual(engine.current_frame, engine.loop_end_frame,
            f"current_frame ({engine.current_frame}) exceeded loop_end ({engine.loop_end_frame}) — BUG-003 not fixed")


class TestTapeSaturation(unittest.TestCase):

    def test_tape_produces_nonzero_output(self):
        """Tape saturation enabled must produce non-silent output from a sine clip."""
        engine = make_engine()
        clip = make_sine_clip(engine, duration_sec=1.0)

        with engine.lock:
            engine.tracks[0].append(clip)
            engine._active_track_buf[0] = list(engine.tracks[0])
            engine.track_tape[0] = True

        engine._sp_tape[0] = True
        engine.is_playing = True
        engine._sp_playing = True

        out, err = run_callback_blocks(engine, n_blocks=5)
        self.assertIsNone(err)
        self.assertGreater(np.max(np.abs(out)), 0.0, "Tape saturation produced silence")

    def test_tape_no_nan(self):
        """Tape saturation must never produce NaN or Inf."""
        engine = make_engine()
        # Use a hot signal to stress the saturation curve
        from audio_engine import Clip
        hot = np.ones(44100, dtype=np.float32) * 0.99
        clip = Clip(hot, 0)

        with engine.lock:
            engine.tracks[0].append(clip)
            engine._active_track_buf[0] = list(engine.tracks[0])
            engine.track_tape[0] = True

        engine._sp_tape[0] = True
        engine.is_playing = True
        engine._sp_playing = True

        out, err = run_callback_blocks(engine, n_blocks=10)
        self.assertIsNone(err)
        self.assertTrue(np.isfinite(out).all(), "Tape saturation produced NaN/Inf on hot signal")


# ─── Runner ──────────────────────────────────────────────────────────────────

class TestProjectManager(unittest.TestCase):

    def test_load_project_from_json_file_path(self):
        """ProjectManager.load_project should handle a path to project.json directly (User request)."""
        import tempfile
        import shutil
        import json

        engine = make_engine()
        from project_manager import ProjectManager
        pm = ProjectManager(engine)

        # Create a dummy project structure
        tmp_dir = tempfile.mkdtemp()
        try:
            audio_dir = os.path.join(tmp_dir, "audio")
            os.makedirs(audio_dir)
            
            project_data = {
                "name": "Test Project",
                "tracks": [[], [], [], []]
            }
            json_path = os.path.join(tmp_dir, "project.json")
            with open(json_path, 'w') as f:
                json.dump(project_data, f)

            # Test loading via the FOLDER path (should work)
            pm.load_project(tmp_dir)
            self.assertEqual(pm.project_name, "Test Project")

            # Test loading via the JSON FILE path (reported bug)
            try:
                pm.load_project(json_path)
                self.assertEqual(pm.project_name, "Test Project")
            except Exception as e:
                self.fail(f"load_project failed when passed a direct path to project.json: {e}")

        finally:
            shutil.rmtree(tmp_dir)


if __name__ == '__main__':
    print("=" * 60)
    print("  Station Master 4-Track — Smoke Test Suite")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_classes = [
        TestEngineInit,
        TestCallbackSilence,
        TestClipPlayback,
        TestRecording,
        TestPultecEQ,
        TestNaNInjection,
        TestLooping,
        TestTapeSaturation,
        TestProjectManager,
    ]

    for tc in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(tc))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print("  ALL TESTS PASSED ✓")
    else:
        print(f"  FAILED: {len(result.failures)} failure(s), {len(result.errors)} error(s)")
        print("  Fix all failures before running another agent session.")
    print("=" * 60)

    sys.exit(0 if result.wasSuccessful() else 1)
