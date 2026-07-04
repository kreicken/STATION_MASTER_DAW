# Station Master 4-Track — Performance & Pultec Fix Brief

**Target:** ASUS C302 (Celeron/Core m3) · Python/PyQt6 · sounddevice callback @ 44100Hz / 512 frames
**Callback budget:** 11.6ms per block · Current observed CPU: 60–70% on single vocal + Pultec

---

## Situation Summary

Two separate problems are presenting simultaneously:

1. **The Pultec EQ is likely not producing any audible effect** — a logic flaw in the parallel delta architecture means it silently outputs the dry signal unmodified in most configurations.
2. **The audio callback has severe Python object churn** — allocating dozens of new Python/NumPy objects on the heap every block, triggering the garbage collector inside a hard real-time thread and causing the excessive CPU load.

Automated agents have addressed DSP correctness bugs in prior rounds but have not had profiler data to identify these two root causes. This document provides explicit, targeted instructions for both fixes.

---

## Fix 1: Diagnose the Silent Pultec

### Why It's Silent

The callback uses a parallel biquad delta architecture:

```python
for s_idx in range(4):
    section_out, next_zi = signal.sosfilt(
        self._sp_pultec_sos[i, s_idx : s_idx+1], dry, zi=...
    )
    wet_sum += (section_out - dry)
track_mono = dry + wet_sum
```

When any section has flat (unity) coefficients — `[1.0, 0.0, 0.0, 1.0, 0.0, 0.0]` — `section_out` equals `dry` exactly, so `section_out - dry = 0`. If all four sections are flat (i.e., all boost/cut values are 0.0 or the enabled flag hasn't reached the callback), `wet_sum` is zero and the Pultec passes audio completely unmodified with significant CPU overhead and zero audible effect.

### Step 1: Add a Runtime Diagnostic Print

Insert this **temporarily** at the top of the Pultec block inside `_do_audio_callback`:

```python
if self._sp_pultec_enabled[i]:
    print(f"[PULTEC] track={i} lboost={self._sp_pultec_lboost[i]:.2f} "
          f"hboost={self._sp_pultec_hboost[i]:.2f} "
          f"sos_row0={self._sp_pultec_sos[i, 0, :3]}")
```

**Interpret the output:**

| Result | Diagnosis |
|---|---|
| Print never fires | `_sp_pultec_enabled[i]` is False — the enabled flag is not reaching the callback from the UI |
| Fires but `lboost=0.00 hboost=0.00` | Parameters are not being pushed from the UI to `update_pultec_params()` |
| Fires but `sos_row0=[1. 0. 0.]` | `update_pultec_params()` is not recomputing SOS — coefficient pipeline is broken |
| Fires with non-unity SOS but still inaudible | DSP is running correctly; check output gain/routing |

### Step 2: Verify the UI→Engine Plumbing in `main.py`

Search `main.py` for every location that calls `engine.update_pultec_params(...)`. Verify:

- It is being called with `enabled=True`
- The `track_idx` argument matches the track that is armed/playing
- The `low_boost`, `low_cut`, `high_boost`, `high_cut` values are non-zero when a preset is active
- The call happens **after** the user changes a preset, not only at initialization

### Step 3: Replace the Parallel Architecture with Serial Cascade

The parallel delta approach is architecturally fragile and wastes CPU on the subtraction operations. Replace with a single serial `sosfilt` call that processes all 4 biquad sections in one C-level pass:

**Current (broken under flat conditions, 4× Python→C overhead):**
```python
dry = track_mono.copy()
wet_sum = np.zeros_like(track_mono)
for s_idx in range(4):
    section_out, next_zi = signal.sosfilt(
        self._sp_pultec_sos[i, s_idx : s_idx+1],
        dry,
        zi=self._sp_pultec_zi[i, s_idx : s_idx+1]
    )
    self._sp_pultec_zi[i, s_idx : s_idx+1] = next_zi
    wet_sum += (section_out - dry)
track_mono = dry + wet_sum
```

**Replacement (serial cascade, 1× Python→C call, correct at all parameter values):**
```python
track_mono, self._sp_pultec_zi[i] = signal.sosfilt(
    self._sp_pultec_sos[i],       # shape (4, 6) — all 4 sections at once
    track_mono,
    zi=self._sp_pultec_zi[i]      # shape (4, 2)
)
```

This is the standard digital EQ biquad cascade. It is audibly correct, immune to the flat-section silent bug, and requires one C call instead of four.

---

## Fix 2: Zero-Allocation Callback

### The Problem

The `_do_audio_callback` currently allocates the following **on every single block** (86 times per second at 512 frames/44100Hz):

| Allocation | Location | Type |
|---|---|---|
| `list(self.track_volumes)` × 12+ | State snapshot | New Python list object |
| `[list(t) for t in self.tracks]` | State snapshot | New list of lists |
| `np.zeros((chunk_size, 2), ...)` | `mixed` buffer | New NumPy array |
| `np.zeros((chunk_size, 2), ...)` | `bus_send_stereo` buffer | New NumPy array |
| `np.zeros(chunk_size, ...)` | `track_mono` per track | New NumPy array (×4) |
| `track_mono.copy()` | Pultec `dry` | New NumPy array |
| `np.zeros_like(track_mono)` | Pultec `wet_sum` | New NumPy array |
| `np.tanh(track_mono + asym_offset) - np.tanh(...)` | Tape saturation | 3 temporary arrays |

Each allocation adds a Python object to the heap. When enough objects accumulate, Python's garbage collector pauses the callback thread to reclaim memory — a pause that has no maximum bound and violates PortAudio real-time constraints, causing xruns and dropout.

### Fix 2a: Pre-Allocate State Snapshot Arrays

**In `__init__`, replace list fields with NumPy arrays:**

```python
# Replace:
self._sp_vols = [1.0, 1.0, 1.0, 1.0]
self._sp_pans = [0.0, 0.0, 0.0, 0.0]
self._sp_mutes = [False, False, False, False]
self._sp_solos = [False, False, False, False]
self._sp_monitoring = [False, False, False, False]
self._sp_input_gains = [1.0, 1.0, 1.0, 1.0]
self._sp_eq_lo = [0.0, 0.0, 0.0, 0.0]
self._sp_eq_hi = [0.0, 0.0, 0.0, 0.0]
self._sp_rev_send = [0.0, 0.0, 0.0, 0.0]
self._sp_tape = [False, False, False, False]
self._sp_spread = [0, 0, 0, 0]
self._sp_chroma = [0, 0, 0, 0]
self._sp_harmony = [False, False, False, False]
self._sp_harmony_mode = [0, 0, 0, 0]
self._sp_harmony_mix = [0.0, 0.0, 0.0, 0.0]

# With:
self._sp_vols         = np.ones(4,  dtype=np.float32)
self._sp_pans         = np.zeros(4, dtype=np.float32)
self._sp_mutes        = np.zeros(4, dtype=np.bool_)
self._sp_solos        = np.zeros(4, dtype=np.bool_)
self._sp_monitoring   = np.zeros(4, dtype=np.bool_)
self._sp_input_gains  = np.ones(4,  dtype=np.float32)
self._sp_eq_lo        = np.zeros(4, dtype=np.float32)
self._sp_eq_hi        = np.zeros(4, dtype=np.float32)
self._sp_rev_send     = np.zeros(4, dtype=np.float32)
self._sp_tape         = np.zeros(4, dtype=np.bool_)
self._sp_spread       = np.zeros(4, dtype=np.int32)
self._sp_chroma       = np.zeros(4, dtype=np.int32)
self._sp_harmony      = np.zeros(4, dtype=np.bool_)
self._sp_harmony_mode = np.zeros(4, dtype=np.int32)
self._sp_harmony_mix  = np.zeros(4, dtype=np.float32)
```

**In the callback snapshot block, replace `list(...)` with `np.copyto(...)`:**

```python
# Replace every:   self._sp_vols = list(self.track_volumes)
# With:            np.copyto(self._sp_vols, self.track_volumes)
```

`np.copyto` writes into the pre-existing buffer with zero heap allocation.

### Fix 2b: Pre-Allocate Working Buffers

Block size is fixed at 512 in `_ensure_stream`. Pre-allocate all working buffers at init:

```python
# In __init__:
BS = 512  # fixed blocksize
self._buf_mixed       = np.zeros((BS, 2), dtype=np.float32)
self._buf_bus_send    = np.zeros((BS, 2), dtype=np.float32)
self._buf_track_mono  = np.zeros(BS,      dtype=np.float32)
self._buf_track_stereo= np.zeros((BS, 2), dtype=np.float32)
```

**In the callback, replace allocations with `.fill(0)`:**

```python
# Replace:
mixed = np.zeros((chunk_size, 2), dtype=np.float32)
bus_send_stereo = np.zeros((chunk_size, 2), dtype=np.float32)
track_mono = np.zeros(chunk_size, dtype=np.float32)

# With:
self._buf_mixed.fill(0)
self._buf_bus_send.fill(0)
self._buf_track_mono.fill(0)
```

Update all downstream references from local variable names to `self._buf_*` names.

### Fix 2c: In-Place Math for Tape Saturation

Precompute the static scalar at init, use `out=` parameter for tanh:

```python
# In __init__:
self._tanh_asym_offset = float(np.tanh(0.2))  # scalar, computed once

# In callback, replace:
track_mono = np.tanh(track_mono + asym_offset) - np.tanh(asym_offset)

# With (zero allocation):
self._buf_track_mono += 0.2
np.tanh(self._buf_track_mono, out=self._buf_track_mono)
self._buf_track_mono -= self._tanh_asym_offset
```

Apply the same `out=` pattern to `np.arctan` in Chroma DARK mode and `np.tanh` in Chroma SPARKLE.

### Fix 2d: Replace Reverb Dict Lookup with Direct Array Index

```python
# In __init__, after creating reverb objects:
self._reverb_list = [
    self._bus_reverbs[0],   # Room
    self._bus_reverbs[1],   # Ambience
    self._bus_reverbs[2],   # Plate
]

# In callback, replace:
active_reverb = self._sp_bus_reverbs.get(self._sp_bus_reverb_type)

# With:
active_reverb = self._reverb_list[self._sp_bus_reverb_type]
```

### Fix 2e: Double-Buffer Track List (Eliminate `[list(t) for t in self.tracks]`)

```python
# In __init__:
self._track_buf_a    = [[], [], [], []]
self._track_buf_b    = [[], [], [], []]
self._active_track_buf = self._track_buf_a

# When UI modifies clips (anywhere clips are added/removed, under self.lock):
# Write to the inactive buffer, then atomically swap the pointer
inactive = (self._track_buf_b
            if self._active_track_buf is self._track_buf_a
            else self._track_buf_a)
for i in range(4):
    inactive[i] = list(self.tracks[i])
self._active_track_buf = inactive   # GIL-atomic pointer swap in CPython

# In callback snapshot, replace:
self._sp_tracks = [list(t) for t in self.tracks]

# With:
# (nothing — callback reads self._active_track_buf directly, no copy needed)
```

Update all `self._sp_tracks[i]` references in the callback to `self._active_track_buf[i]`.

---

## Expected Performance Impact on ASUS C302

| Fix | Estimated CPU Reduction |
|---|---|
| Pre-allocated snapshot arrays (Fix 2a) | 8–12% |
| Pre-allocated working buffers (Fix 2b) | 15–20% |
| In-place math / `out=` params (Fix 2c) | 10–15% |
| Reverb direct indexing (Fix 2d) | 2–3% |
| Double-buffer track list (Fix 2e) | 3–5% |
| Serial Pultec cascade (Fix 1 Step 3) | 5–8% (eliminates 3 redundant sosfilt calls) |
| **Total realistic estimate** | **~43–63% of current callback overhead** |

Target outcome: single vocal track + active Pultec EQ should run comfortably at **30–40% CPU** on the C302 after all fixes are applied.

---

## Optional: Block Size Increase

If CPU is still marginal after all fixes, increase `blocksize` from `512` to `1024` in `_ensure_stream`:

```python
self.stream = sd.Stream(
    ...
    blocksize=1024,   # was 512
    ...
)
```

Also update `BS = 1024` in `__init__` to match the pre-allocated buffer sizes.

This halves callback frequency from 86/sec to 43/sec, cutting all Python overhead in half at the cost of ~23ms latency (vs ~11ms). Imperceptible for non-live-monitoring use (reviewing recordings, bouncing).

---

## Implementation Order

1. Add the diagnostic print (Fix 1 Step 1) and confirm whether Pultec is even executing
2. Trace the UI→engine plumbing in `main.py` (Fix 1 Step 2)
3. Replace parallel Pultec with serial cascade (Fix 1 Step 3)
4. Apply pre-allocated working buffers (Fix 2b) — biggest single win
5. Apply pre-allocated snapshot arrays (Fix 2c)
6. Apply in-place math (Fix 2d)
7. Apply remaining fixes (2d, 2e)
8. Retest CPU; increase blocksize only if still needed

---

*Generated for Station Master 4-Track · audio_engine.py performance audit · May 2026*
