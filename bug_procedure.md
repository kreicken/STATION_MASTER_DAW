# Station Master 4-Track — Bug Squash Procedure

**Read this entire document before touching any code.**
This procedure exists because previous sessions produced net-negative results — each round of fixes introduced new regressions. You are bound by this protocol.

---

## The Prime Directive

**One bug. One fix. One verified test run. No exceptions.**

You are not permitted to fix multiple bugs in a single session. You are not permitted to refactor code that is not directly related to the target bug. You are not permitted to submit a fix without a passing smoke test.

---

## Step 0 — Run the Smoke Test First

Before reading any code, before forming any hypothesis, run:

```bash
source .venv/bin/activate
python smoke_test.py
```

Record the exact output. Every FAIL and ERROR line is your working list.
**Do not invent bugs that are not in the smoke test output.**
If the smoke test passes entirely, the session is over — do not go looking for more bugs.

---

## Step 1 — Pick Exactly One Failing Test

Choose the single highest-priority failing test from this order:

1. `TestRecording` — any failure here means recording is broken (app is unusable)
2. `TestPultecEQ` — any failure here means the primary effect is broken
3. `TestNaNInjection` — any failure here means the engine can be permanently corrupted
4. `TestLooping` — any failure here means loop playback is broken
5. `TestTapeSaturation` — saturation failures
6. `TestClipPlayback` — basic playback failures
7. `TestCallbackSilence` — callback stability failures
8. `TestEngineInit` — init failures (fix these before anything else regardless of order)

Write down the test name and the exact failure message. That is your target.

---

## Step 2 — Locate the Defect

Read **only** the code directly relevant to the failing test. Do not read the entire file.

Relevant file map:

| Failing test class | Primary file | Specific area |
|---|---|---|
| `TestRecording` | `audio_engine.py` | `start_recording()`, `stop()`, `_ensure_stream()` |
| `TestPultecEQ` | `audio_engine.py` | `_do_audio_callback()` Pultec block, `update_pultec_params()` |
| `TestNaNInjection` | `audio_engine.py` | Input metering section, filter state variables |
| `TestLooping` | `audio_engine.py` | Loop section of `_do_audio_callback()` |
| `TestTapeSaturation` | `audio_engine.py` | Tape saturation block in `_do_audio_callback()` |
| `TestClipPlayback` | `audio_engine.py` | `get_audio_segment()`, clip mixing loop |
| `TestCallbackSilence` | `audio_engine.py` | Early exit and output fill logic |
| `TestEngineInit` | `audio_engine.py` | `__init__()` |

---

## Step 3 — State the Bug in Plain English

Before writing a single line of code, write out:

```
BUG: [what is wrong]
ROOT CAUSE: [why it is wrong — specific line or logic]
FIX: [exactly what will be changed — no more, no less]
RISK: [what adjacent code could be affected by this change]
```

If you cannot fill in all four fields with specificity, you do not understand the bug well enough to fix it yet. Keep reading.

---

## Step 4 — Apply the Minimal Fix

Rules:
- Change the **fewest lines possible** to fix the defect.
- Do not rename variables, reformat code, or reorganize logic unless it is the direct fix.
- Do not add new features.
- Do not add new comments explaining what old code did — if a comment is needed, it explains what the new code does.
- If the fix requires touching more than ~15 lines, stop and re-evaluate. You are likely fixing a symptom, not the cause.

---

## Step 5 — Run the Smoke Test Again

```bash
python smoke_test.py
```

**Required outcome:** The test that was failing now passes.
**Required outcome:** No test that was previously passing is now failing.

If any previously-passing test is now failing, you have introduced a regression. Revert your change immediately using:

```bash
git diff audio_engine.py   # review what changed
git checkout audio_engine.py   # revert if needed
```

Do not proceed with a regression present. Understand why the regression occurred before retrying.

---

## Step 6 — Document the Fix

Add one entry to `FIXES.md` (create it if it doesn't exist):

```markdown
## [DATE] — [Test name fixed]

**Bug:** [one sentence]
**Root cause:** [one sentence, file and line number]
**Fix:** [one sentence describing what changed]
**Lines changed:** [N]
**Smoke test:** PASS
```

---

## Step 7 — Stop

Commit the change. Close the session. Do not continue to the next bug in the same session.

The next session starts at Step 0.

---

## Constraints Reference

### What You May NOT Do

- Modify `main.py` unless the failing test explicitly involves UI plumbing
- Modify `project_manager.py` unless the failing test involves save/load
- Add new effects, parameters, or features
- Change the Pultec SOS architecture (it was deliberately changed from parallel to serial — do not revert)
- Change pre-allocated buffer names or shapes (downstream code depends on them)
- Remove the `_sp_prev_*` shadow arrays (they track toggle transitions for click prevention)
- Change `blocksize` in `_ensure_stream()` without updating `max_frames` in `__init__`

### What You May Do

- Fix logic errors, missing function calls, wrong variable names
- Fix incorrect mathematical expressions
- Fix missing guard conditions
- Add `np.nan_to_num()` sanitization where inputs are not sanitized
- Zero out filter state (`zi`) arrays on specific guarded conditions

### The Known Bug List (as of last session)

These bugs are confirmed present. Fix them in smoke-test order, not this order:

1. **`start_recording()` missing `_ensure_stream()` call** — recording never starts
2. **`start_monitoring()` stale stream guard** — arm intermittently fails after stop/start
3. **BUG-003 Loop wrap-around overrun** — loop boundary not split mid-chunk
4. **BUG-004 Reverb tail abrupt mute** — `bus_send_peak > 1e-6` gate kills tail
5. **BUG-006 DC offset from asymmetric saturation** — no DC blocker after tape/chroma WARM
6. **BUG-007 Stale IIR state on toggle** — `zi` not zeroed on effect re-enable
7. **BUG-009 `apply_eq()` in-place write race** — writes to `clip.data` without protection
8. **BUG-010 `current_frame` unsynchronized** — race between `rewind()` and callback

---

## Performance Context

**Target machine:** ASUS C302 (Celeron/Core m3)
**Callback budget:** 11.6ms per block at 512 frames / 44100Hz
**Observed CPU on single vocal + Pultec:** 60–70% (unacceptable)

### Effects Chain Cost (approximate, C302)

| Effect | Estimated callback cost | Status |
|---|---|---|
| 1-pole EQ (bass/treble) | ~0.2ms | Acceptable |
| Pultec EQ (serial sosfilt) | ~1.5ms | Acceptable after serial fix |
| Tape Saturation | ~0.5ms | Acceptable |
| Chroma Glow | ~0.5ms | Acceptable |
| Bus Reverb (pedalboard) | ~2–4ms | High — Python/C++ boundary overhead |
| Harmony Singer (pedalboard PitchShift) | ~4–8ms | Very high — do not enable on C302 |
| Stereo Spread | ~0.3ms | Acceptable |

**Do not attempt to optimize effects costs in a bug-fix session.**
Performance work is a separate session with profiler data (`py-spy` output required).

---

## Smoke Test Quick Reference

```bash
# Full run
python smoke_test.py

# Run one test class only
python -m unittest smoke_test.TestRecording -v

# Run one specific test
python -m unittest smoke_test.TestRecording.test_start_recording_calls_ensure_stream -v
```

The test that catches the known missing `_ensure_stream` regression is:
```
smoke_test.TestRecording.test_start_recording_calls_ensure_stream
```
This must pass before any other recording work is considered complete.

---

*Station Master 4-Track · Bug Squash Protocol · May 2026*
