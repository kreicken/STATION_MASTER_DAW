# Station Master 4-Track — Fixes Log

## 2026-05-06 — IIR filter states not reset between stop/play cycles

**Bug:** Every play session started with residual IIR filter charge from wherever the previous session stopped, causing audible transients/clicks at the playhead — most noticeable with Pultec low-shelf cut and tape saturation active.
**Root cause:** `audio_engine.py` `start_playback()` never reset any filter state arrays. States are only reset at `__init__` time or on explicit parameter changes. Normal stop→play left `_sp_pultec_zi`, `_pultec_zi`, `_tape_lp_state`, `_tape_dc_state`, `_trk_lp_state`, `_chroma_lp_state`, `_chroma_dc_state`, `_spread_zi`, and `_mst_lp_state` carrying stale values.
**Fix:** Added `_reset_filter_states()` which zeroes all IIR state arrays. Called from `start_playback()` after `_stop_monitor()` returns (no stream active at that point — no race condition). `start_recording()` deliberately NOT changed (recording from mid-session needs a pre-settled filter).
**Lines changed:** 17
**Smoke test:** PASS (24/24)

## 2026-05-06 — Harmony blender abandons pre-allocated buffer (dtype and design violation)

**Bug:** When Harmony was active, the wet/dry blend rebound `track_mono` to a new heap-allocated float64 array, silently breaking the zero-copy callback design for all effects downstream (Chroma, Tape, Spread).
**Root cause:** `audio_engine.py` line 600 — `track_mono = track_mono * (1.0 - mix) + wet * mix` is a Python name rebind, not an in-place write. The pre-allocated float32 `_buf_track_mono` slice was abandoned.
**Fix:** Changed to `track_mono[:] = track_mono * (1.0 - mix) + wet * mix` — one character (`[:]`) — so the name stays bound to the original float32 pre-allocated buffer throughout the callback.
**Lines changed:** 1
**Smoke test:** PASS (24/24)

## 2026-05-06 — Chroma DARK and WARM lfilter aliasing (crash on hot signal)

**Bug:** Chroma Glow DARK and WARM modes would crash or produce corrupted audio on hot signals — same native segfault pattern as the tape saturation bug.
**Root cause:** `audio_engine.py` line 612 (DARK) and line 635 (WARM) — `signal.lfilter()` received `track_mono` as both input and in-place write target via `track_mono[:] =`. Identical buffer aliasing to the tape DC/LP rolloff crash fixed previously.
**Fix:** Captured lfilter return values into `dark_out` and `warm_dc_out` local variables before writing back to `track_mono[:]`.
**Lines changed:** 2 (each 1-line split into 2)
**Smoke test:** PASS (24/24)

## 2026-05-06 — AttributeError on project load: 'TimelineWidget' has no attribute 'envelopes'

**Bug:** Loading a project (and undo/redo, harmony processing, track summing) raised `AttributeError: 'TimelineWidget' object has no attribute 'envelopes'`.
**Root cause:** `main.py` lines 214, 2032, 2342, 2416 all call `self.timeline.envelopes.clear()` to invalidate waveform envelope caches after clips change. `TimelineWidget.__init__` never initialised `self.envelopes = {}`.
**Fix:** Added `self.envelopes = {}` to `TimelineWidget.__init__`. The dict is intentionally kept empty — actual caching uses per-clip `_envelope_cache` attributes — but `.clear()` must not raise.
**Lines changed:** 1
**Smoke test:** PASS (24/24)

## 2026-05-06 — Playhead (meridian) not draggable

**Bug:** Clicking the playhead only issued a one-shot seek; holding and dragging did not continuously update position. Clicking anywhere in the ruler or on the vertical playhead line in the track area had no drag effect.
**Root cause:** `main.py` `mousePressEvent` — ruler click posted `_seek_request` once and returned. `mouseMoveEvent` only checked `dragging_clip`; no scrubbing state existed. Additionally `_seek_request` is only consumed by the audio callback (not running when stopped), so even the one-shot click failed to visually move the playhead when the transport was stopped.
**Fix:** Added `_scrubbing` flag and `_do_seek()` helper (sets `current_frame` directly for immediate visual update + posts `_seek_request` for the callback). `mousePressEvent` now sets `_scrubbing=True` on ruler click and on track-area click within ±8px of the playhead line. `mouseMoveEvent` checks `_scrubbing` first and calls `_do_seek()`. `mouseReleaseEvent` clears `_scrubbing`.
**Lines changed:** 18
**Smoke test:** PASS (24/24)

## 2026-05-06 — TimelineWidget._update_size missing (BUG A)

**Bug:** `_update_size()` was called every 30ms and on every zoom but never defined, causing an `AttributeError` crash.
**Root cause:** `main.py` lines 1951 and 2074 call `self.timeline._update_size()` — method not defined on `TimelineWidget`.
**Fix:** Added `_update_size()` to resize canvas width based on `engine.get_max_length()` scaled by `pps`, floored at `MIN_TIMELINE_SECS`.
**Lines changed:** 7
**Smoke test:** PASS (24/24)

## 2026-05-06 — TimelineWidget ruler right-edge divider at wrong x (BUG C)

**Bug:** The vertical divider line at the end of the ruler was drawn at the last tick-mark pixel, not at the canvas right edge.
**Root cause:** `main.py` `paintEvent` — stale `x` variable from the ruler `for` loop was used after the loop ended.
**Fix:** Replaced `x` with `self.width() - 1` in the `drawLine` call.
**Lines changed:** 1
**Smoke test:** PASS (24/24)

## 2026-05-06 — TimelineWidget mouse interaction dead (BUG D)

**Bug:** Clicking and dragging on the timeline did nothing — no seek, no clip selection, no clip move.
**Root cause:** `mousePressEvent`, `mouseMoveEvent`, and `mouseReleaseEvent` were entirely absent despite `selected_clip`, `dragging_clip`, and `drag_offset` state vars being initialized in `__init__`.
**Fix:** Added `_clip_at()` hit-test helper and the three mouse event handlers: ruler-click seeks playhead; left-click on clip selects and begins drag; drag moves clip start_frame under the lock; right-click deletes clip; release commits and pushes undo snapshot.
**Lines changed:** 67
**Smoke test:** PASS (24/24)

## 2026-05-06 — TestTapeSaturation

**Bug:** Tape saturation failed with NameError: name 't_alpha' is not defined.
**Root cause:** Variable `t_alpha` was used in `_do_audio_callback` but not defined in that scope. File: `audio_engine.py`, Line: 672.
**Fix:** Replaced `t_alpha` with `self._sp_tape_alpha` which is the correct snapshotted parameter.
**Lines changed:** 1
**Smoke test:** PASS

## 2026-05-06 — TestProjectManager

**Bug:** ProjectManager.load_project failed when passed a direct path to project.json.
**Root cause:** Method assumed load_path was a folder and tried to append "project.json". File: `project_manager.py`, Line: 92.
**Fix:** Added logic to detect if load_path is a .json file and resolve the actual project directory accordingly. Also updated `main.py` to use `getOpenFileName` instead of `getExistingDirectory` for a better user experience.
**Lines changed:** 15 (ProjectManager) + 10 (main.py)
**Smoke test:** PASS

## 2026-05-06 — TestTapeSaturation (segfault on hot signal)

**Bug:** Tape saturation caused a native segfault (exit code 139) when processing a hot constant signal.
**Root cause:** `audio_engine.py` lines 653 and 658 — `signal.lfilter(…, track_mono, …)` passed `track_mono` as both the input and the in-place write target (`track_mono[:] = …`), aliasing the same underlying buffer. scipy's lfilter does not support aliased in/out and crashes the interpreter.
**Fix:** Captured `lfilter` return value into separate local variables (`dc_out`, `lp_out`) before assigning back into `track_mono[:]`.
**Lines changed:** 2
**Smoke test:** PASS (25/25)

## 2026-05-06 — UI Painter Warnings

**Bug:** Terminal flooded with `QBackingStore::endPaint() called with an active painter` warnings.
**Root cause:** `QPainter` objects in custom widgets were not being closed before `paintEvent` finished. File: `main.py`, various classes.
**Fix:** Wrapped all `QPainter` usage in `with QPainter(self):` context managers to ensure immediate closure.
**Lines changed:** ~20
**Smoke test:** PASS

## 2026-05-07 — UI timecode display not resetting on REW

**Bug:** The timecode label ("time mast") reverted from `0:00.0` back to the old position within 50ms after REW was pressed.
**Root cause:** `rewind()` in `audio_engine.py:993` only set `_seek_request = 0`; when the transport was stopped there was no active audio callback to consume the seek, so `current_frame` remained stale and the 50ms UI timer in `_update_meters()` immediately overwrote the label with the old value.
**Fix:** `rewind()` now also sets `self.current_frame = 0` directly inside the lock, so the UI timer reads the correct value at once.
**Lines changed:** 1
**Smoke test:** PASS (24/24)

## 2026-05-07 — Backspace no longer deletes selected clip

**Bug:** Pressing Backspace (or Delete) with a clip selected had no effect — the clip was not removed.
**Root cause:** `TimelineWidget` had no `keyPressEvent` handler and no `setFocusPolicy` — the widget never accepted keyboard focus so key events were never delivered to it. A prior session's mouse handler rewrite omitted the keyboard delete path.
**Fix:** Added `setFocusPolicy(Qt.FocusPolicy.StrongFocus)` to `__init__`, `self.setFocus()` call in `mousePressEvent` when a clip is selected, and a `keyPressEvent` that removes `selected_clip` from `engine.tracks` on `Key_Backspace`/`Key_Delete` then pushes an undo snapshot.
**Lines changed:** 17
**Smoke test:** PASS (24/24)

## 2026-05-07 — Cannot crop (trim) audio regions with the mouse

**Bug:** Clicking anywhere on a clip always started a drag-to-move; there was no way to trim the start or end of a region with the mouse.
**Root cause:** `TimelineWidget.mousePressEvent` had no edge-detection logic — it treated all clip clicks as body drags. The `Clip` data model already had `offset_frame` and `length_frame` fields supporting non-destructive trimming, but nothing used them.
**Fix:** Added `_crop_clip`/`_crop_edge`/`_crop_track` state vars. `mousePressEvent` now detects clicks within ±8px of the left or right clip edge and starts a crop drag instead of a move. `mouseMoveEvent` applies the crop (left edge: adjusts `offset_frame`+`start_frame`+`length_frame` so the right edge stays fixed; right edge: adjusts `length_frame` only). `mouseMoveEvent` also sets `SizeHorCursor` when hovering an edge for discoverability. `mouseReleaseEvent` clears crop state and pushes undo.
**Lines changed:** 42
**Smoke test:** PASS (25/25)

## 2026-05-07 — Recording progress bar stops painting at ~16s

**Bug:** During recording, the red "RECORDING" progress bar on the timeline stopped growing at ~16 seconds and the canvas did not auto-resize.
**Root cause:** `_update_size()` in `main.py` calls `engine.get_max_length()` to determine the required canvas width. During recording, audio is held in `recording_buffer` (not yet committed as a Clip), so `get_max_length()` returns 0. The canvas was constrained to `setMinimumWidth(800)` = 16 seconds at 50pps, and the recording bar clipped to the canvas right edge at exactly that point.
**Fix:** Added a guard in `_update_size()`: if `engine.is_recording`, take `max(max_frame, engine.current_frame)` so the canvas always covers the live recording head. The existing `+ 10` second lookahead and auto-scroll logic then handle smooth growth and panning.
**Lines changed:** 2
**Smoke test:** PASS (25/25)
