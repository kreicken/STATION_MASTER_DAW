import numpy as np
import sounddevice as sd
import scipy.signal as signal
import threading
import uuid
import time
import math
import logging
from pedalboard import Reverb, Pedalboard, PitchShift
from dsp_effects import HARMONY_MODES

logger = logging.getLogger(__name__)

PULTEC_PRESETS = {
    0:  {"name": "Flat",              "lf":1, "lb":0.0, "lc":0.0, "hf":2, "hb":0.0, "hc":0.0},
    1:  {"name": "1-Mic Drumset",     "lf":1, "lb":4.0, "lc":2.0, "hf":3, "hb":5.0, "hc":0.0},
    2:  {"name": "2-Mic Drumset",     "lf":1, "lb":6.0, "lc":1.5, "hf":3, "hb":3.0, "hc":0.0},
    3:  {"name": "P-Bass Boost",      "lf":0, "lb":8.0, "lc":4.0, "hf":1, "hb":2.0, "hc":0.0},
    4:  {"name": "Acoustic Guitar",   "lf":2, "lb":2.0, "lc":3.0, "hf":3, "hb":5.0, "hc":0.0},
    5:  {"name": "12-String Acoustic","lf":2, "lb":1.5, "lc":4.0, "hf":4, "hb":6.0, "hc":0.0},
    6:  {"name": "Nashville Acoustic","lf":2, "lb":0.0, "lc":5.0, "hf":4, "hb":5.0, "hc":1.0},
    7:  {"name": "Telecaster",        "lf":2, "lb":2.0, "lc":0.0, "hf":2, "hb":2.0, "hc":3.0},
    8:  {"name": "12-String Electric","lf":2, "lb":3.0, "lc":2.0, "hf":3, "hb":4.0, "hc":0.0},
    9:  {"name": "Recorder",          "lf":3, "lb":0.0, "lc":3.0, "hf":3, "hb":6.0, "hc":0.0},
    10: {"name": "Irish Bouzouki",    "lf":2, "lb":3.0, "lc":2.0, "hf":2, "hb":3.0, "hc":1.0},
    11: {"name": "Melodica",          "lf":3, "lb":0.0, "lc":5.0, "hf":2, "hb":4.0, "hc":2.0},
    12: {"name": "Harmonica",         "lf":3, "lb":0.0, "lc":6.0, "hf":2, "hb":5.0, "hc":0.0},
    13: {"name": "Synth Pad",         "lf":3, "lb":0.0, "lc":5.0, "hf":2, "hb":0.0, "hc":4.0},
    14: {"name": "Synth Lead",        "lf":3, "lb":0.0, "lc":6.0, "hf":2, "hb":5.0, "hc":0.0},
    15: {"name": "Tambourine",        "lf":3, "lb":0.0, "lc":8.0, "hf":3, "hb":5.0, "hc":0.0},
    16: {"name": "Backing Vocal",     "lf":3, "lb":0.0, "lc":5.0, "hf":4, "hb":5.0, "hc":0.0},
    17: {"name": "Chest Vocal",       "lf":1, "lb":3.0, "lc":0.0, "hf":2, "hb":4.0, "hc":0.0},
    18: {"name": "Throat Vocal",      "lf":2, "lb":1.0, "lc":3.0, "hf":2, "hb":2.0, "hc":4.0},
}

def _get_biquad_shelf_coeffs(mode, freq_hz, gain_db, sr):
    """Calculates biquad coefficients for a shelf filter. Returns [b0, b1, b2, 1.0, a1, a2]."""
    # BUG-P12 FIX: Cap gain to +/- 15dB to prevent unstable biquads
    gain_db = max(-15.0, min(15.0, gain_db))
    
    A  = 10.0 ** (abs(gain_db) / 40.0)
    w0 = 2.0 * math.pi * freq_hz / sr
    cw = math.cos(w0)
    sw = math.sin(w0)
    S  = 1.0  # shelf slope
    alpha = sw / 2.0 * math.sqrt((A + 1.0/A) * (1.0/S - 1.0) + 2.0)

    # Calculate boost coefficients
    b0 =  A * ((A+1) - (A-1)*cw + 2*math.sqrt(A)*alpha)
    b1 =  2*A * ((A-1) - (A+1)*cw)
    b2 =  A * ((A+1) - (A-1)*cw - 2*math.sqrt(A)*alpha)
    a0 =       (A+1) + (A-1)*cw + 2*math.sqrt(A)*alpha
    a1 = -2  * ((A-1) + (A+1)*cw)
    a2 =       (A+1) + (A-1)*cw - 2*math.sqrt(A)*alpha

    if mode in ('low_boost', 'high_boost'):
        if mode == 'high_boost':
            # High shelf boost
            b0 =  A * ((A+1) + (A-1)*cw + 2*math.sqrt(A)*alpha)
            b1 = -2*A * ((A-1) + (A+1)*cw)
            b2 =  A * ((A+1) + (A-1)*cw - 2*math.sqrt(A)*alpha)
            a0 =       (A+1) - (A-1)*cw + 2*math.sqrt(A)*alpha
            a1 =  2  * ((A-1) - (A+1)*cw)
            a2 =       (A+1) - (A-1)*cw - 2*math.sqrt(A)*alpha
        return [b0/a0, b1/a0, b2/a0, 1.0, a1/a0, a2/a0]

    elif mode in ('low_cut', 'high_cut'):
        if mode == 'high_cut':
            # High shelf boost coefficients
            b0 =  A * ((A+1) + (A-1)*cw + 2*math.sqrt(A)*alpha)
            b1 = -2*A * ((A-1) + (A+1)*cw)
            b2 =  A * ((A+1) + (A-1)*cw - 2*math.sqrt(A)*alpha)
            a0 =       (A+1) - (A-1)*cw + 2*math.sqrt(A)*alpha
            a1 =  2  * ((A-1) - (A+1)*cw)
            a2 =       (A+1) - (A-1)*cw - 2*math.sqrt(A)*alpha
        
        # Shelf cut is the inverse of shelf boost: swap b and a coefficients
        # H_cut(z) = 1 / H_boost(z)  -> swap numerator and denominator
        # Normalize so a0 is always 1.0
        return [a0/b0, a1/b0, a2/b0, 1.0, b1/b0, b2/b0]

    else:
        return [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]

# dsp_effects is used by main.py for offline harmony processing (not in callback)

class Clip:
    def __init__(self, data: np.ndarray, start_frame: int):
        self.id = str(uuid.uuid4())
        self.data = data.astype(np.float32)
        
        # Timeline coordinate
        self.start_frame = start_frame
        
        # Cropping indices internal to self.data
        self.offset_frame = 0
        self.length_frame = len(data)
        
    def copy(self):
        new_clip = Clip(self.data, self.start_frame)
        new_clip.id = self.id
        new_clip.offset_frame = self.offset_frame
        new_clip.length_frame = self.length_frame
        return new_clip

    def absolute_end_frame(self):
        return self.start_frame + self.length_frame
        
    def get_audio_segment(self, global_start: int, global_end: int):
        """Returns the chunk of audio data overlapping the requested timeline bounds."""
        clip_end = self.absolute_end_frame()
        
        # If no overlap
        if global_end <= self.start_frame or global_start >= clip_end:
            return None, 0, 0
            
        # Calculate overlap bounds relative to timeline
        overlap_start = max(global_start, self.start_frame)
        overlap_end = min(global_end, clip_end)
        
        # Convert timeline bounds to internal data indices
        internal_start = self.offset_frame + (overlap_start - self.start_frame)
        internal_end = self.offset_frame + (overlap_end - self.start_frame)
        
        return self.data[internal_start:internal_end], overlap_start, overlap_end


class AudioEngine:
    def __init__(self, sample_rate=44100):
        self.sample_rate = sample_rate
        
        # Tracks are lists of Clips
        self.tracks = [[], [], [], []] 
        
        self.is_playing = False
        self.is_recording = False
        self.current_frame = 0
        
        self.stream = None
        self.input_device = None  # None means PortAudio default
        self.output_device = None
        self.lock = threading.RLock()
        
        self.armed_track = -1
        self.recording_buffer = [] # Temporarily collects incoming frames
        self.record_start_frame = 0 # Timeline position when REC started
        
        self.master_volume = 1.0
        self.track_volumes = [1.0, 1.0, 1.0, 1.0]
        self.track_pans = [0.0, 0.0, 0.0, 0.0]
        self.track_mutes = [False, False, False, False]
        self.track_solos = [False, False, False, False]
        self.track_monitoring = [True, True, True, True]
        self.input_gains = [1.0, 1.0, 1.0, 1.0]
        
        # Per-track EQ (dB values, -15 to +15)
        self.track_eq_lo = [0.0, 0.0, 0.0, 0.0]
        self.track_eq_hi = [0.0, 0.0, 0.0, 0.0]
        # Master EQ (dB)
        self.master_eq_lo = 0.0
        self.master_eq_hi = 0.0
        
        # 1-pole filter state for real-time EQ (per-track mono + master stereo)
        # Cutoff ~300Hz: alpha = 2*pi*300/SR
        self._eq_alpha = 2.0 * np.pi * 300.0 / self.sample_rate
        self._trk_lp_state = [np.zeros(1, dtype=np.float32) for _ in range(4)]
        self._mst_lp_state = [np.zeros(1, dtype=np.float32) for _ in range(2)]
        
        # Per-track analog tape saturation (toggle on/off)
        self.track_tape = [False, False, False, False]
        # Tape HF rolloff filter state (~8kHz cutoff)
        self._tape_alpha = 2.0 * np.pi * 8000.0 / self.sample_rate
        self._tape_lp_state = [np.zeros(1, dtype=np.float32) for _ in range(4)]
        self._tape_dc_state = [np.zeros(1, dtype=np.float32) for _ in range(4)]
        
        # Per-track send amounts (0.0 = silent send, 1.0 = full send)
        self.track_rev_send = [0.0, 0.0, 0.0, 0.0]

        # Bus reverb: 0 = Room, 1 = Ambience, 2 = Plate
        self.bus_reverb_type = 0
        self.bus_reverb_return = 1.0  # Master wet return level (0.0–1.0)

        self._bus_reverbs = {
            0: Reverb(room_size=0.45, damping=0.65, wet_level=1.0, dry_level=0.0),   # Room
            1: Reverb(room_size=0.30, damping=0.70, wet_level=1.0, dry_level=0.0),   # Ambience
            2: Reverb(room_size=0.85, damping=0.08, wet_level=1.0, dry_level=0.0),   # Plate
        }
        
        # Harmony Singer — mode/mix stored here
        self.track_harmony = [False, False, False, False]
        self.track_harmony_mode = [0, 0, 0, 0]
        self.track_harmony_mix = [0.0, 0.0, 0.0, 0.0]
        self._trk_harmony_objs = [None, None, None, None] # Lists of Pedalboards
        
        # Input metering (updated by audio callback, read by UI)
        self.input_level = 0.0  # Peak level 0.0 to 1.0+
        self.input_clipping = False  # True if level >= 1.0
        self.playback_levels = [0.0] * 4
        self.playback_clipping = [False] * 4
        self.master_level = 0.0
        self.master_clipping = False
        self.cpu_load = 0.0 # 0.0 to 1.0 (1.0 = 100% of callback time used)
        self._cpu_accum = 0.0
        self._cpu_count = 0
        
        # Looping state
        self.loop_enabled = False
        self.loop_start_frame = 0
        self.loop_end_frame = 44100 * 4 # Default 4 seconds
        
        # Audio buffers for real-time callback (Bug 001)
        self._max_frames = 8192
        self._buf_mixed = np.zeros((self._max_frames, 2), dtype=np.float32)
        self._buf_bus_send = np.zeros((self._max_frames, 2), dtype=np.float32)
        self._buf_track_mono = np.zeros(self._max_frames, dtype=np.float32)
        self._buf_track_stereo = np.zeros((self._max_frames, 2), dtype=np.float32)
        self._buf_wet_sum = np.zeros(self._max_frames, dtype=np.float32)
        self._buf_input_mono = np.zeros(self._max_frames, dtype=np.float32)
        
        self._seek_request = None # Bug 010
        
        self.monitor_stream = None
        
        self._sp_eq_alpha = 0.0427
        self._sp_tape_alpha = 0.75
        
        # Shadow state for lock-free audio thread (mirrored from Golden Bull pattern)
        self._sp_playing = False
        self._sp_recording = False
        self._sp_armed = -1
        self._sp_master_vol = 1.0
        self._sp_vols         = np.ones(4,  dtype=np.float32)
        self._sp_pans         = np.zeros(4, dtype=np.float32)
        self._sp_mutes        = np.zeros(4, dtype=np.bool_)
        self._sp_solos        = np.zeros(4, dtype=np.bool_)
        self._sp_monitoring   = np.zeros(4, dtype=np.bool_)
        self._sp_input_gains  = np.ones(4,  dtype=np.float32)
        self._sp_eq_lo        = np.zeros(4, dtype=np.float32)
        self._sp_eq_hi        = np.zeros(4, dtype=np.float32)
        self._sp_mst_eq_lo = 0.0
        self._sp_mst_eq_hi = 0.0

        # Pultec EQ — per-track parameters
        # Low section: frequency selector (0–3 maps to 30/60/100/200 Hz)
        # boost and cut are independent gain values in dB (0.0–15.0)
        self.track_pultec_enabled = [False, False, False, False]
        self.track_pultec_low_freq  = [1, 1, 1, 1]     # index into [30, 60, 100, 200]
        self.track_pultec_low_boost = [0.0, 0.0, 0.0, 0.0]   # dB, 0–15
        self.track_pultec_low_cut   = [0.0, 0.0, 0.0, 0.0]   # dB, 0–15
        self.track_pultec_high_freq = [2, 2, 2, 2]     # index into [3k, 5k, 8k, 12k, 16k]
        self.track_pultec_high_boost= [0.0, 0.0, 0.0, 0.0]   # dB, 0–12
        self.track_pultec_high_cut  = [0.0, 0.0, 0.0, 0.0]   # dB, 0–12
        self.track_pultec_preset    = [0, 0, 0, 0]     # 0 = Flat/Off (no preset active)

        # Shadow state
        self._sp_pultec_enabled  = np.zeros(4, dtype=np.bool_)
        self._sp_pultec_lf       = np.ones(4,  dtype=np.int32)
        self._sp_pultec_lboost   = np.zeros(4, dtype=np.float32)
        self._sp_pultec_lcut     = np.zeros(4, dtype=np.float32)
        self._sp_pultec_hf       = np.full(4, 2, dtype=np.int32)
        self._sp_pultec_hboost   = np.zeros(4, dtype=np.float32)
        self._sp_pultec_hcut     = np.zeros(4, dtype=np.float32)

        # Biquad filter states per track: [w1, w2] × 4 sections (low boost, low cut, high boost, high cut)
        self._pultec_states = [
            {'lboost': [0.0]*2, 'lcut': [0.0]*2, 'hboost': [0.0]*2, 'hcut': [0.0]*2}
            for _ in range(4)
        ]
        # Pre-calculated SOS (Second Order Sections) for Pultec (4 sections per track)
        # Shape: (4 tracks, 4 sections, 6 coefficients [b0,b1,b2, a0,a1,a2])
        self._pultec_sos = np.zeros((4, 4, 6), dtype=np.float32)
        # We also need a combined zi state for sosfilt: (4 tracks, 4 sections, 2 states)
        self._pultec_zi = np.zeros((4, 4, 2), dtype=np.float32)
        
        # Shadow state references for callback (SOS is copied in snapshot, ZI is mutated in callback)
        self._sp_pultec_sos = np.zeros_like(self._pultec_sos)
        self._sp_pultec_zi = np.zeros_like(self._pultec_zi)
        self._pultec_reset_pending = [False] * 4
        
        # Initialize Pultec SOS for all tracks
        for i in range(4):
            self.update_pultec_params(
                i, 
                self.track_pultec_enabled[i],
                self.track_pultec_low_freq[i],
                self.track_pultec_low_boost[i],
                self.track_pultec_low_cut[i],
                self.track_pultec_high_freq[i],
                self.track_pultec_high_boost[i],
                self.track_pultec_high_cut[i],
                self.track_pultec_preset[i]
            )

        self._sp_tape = np.zeros(4, dtype=np.bool_)
        self._sp_rev_send = np.zeros(4, dtype=np.float32)
        self._sp_bus_reverb_type = 0
        self._sp_bus_reverb_return = 1.0
        self._sp_bus_reverbs = dict(self._bus_reverbs)
        self._reverb_list = [
            self._bus_reverbs[0],   # Room
            self._bus_reverbs[1],   # Ambience
            self._bus_reverbs[2],   # Plate
        ]
        self._sp_harmony = np.zeros(4, dtype=np.bool_)
        self._sp_harmony_mode = np.zeros(4, dtype=np.int32)
        self._sp_harmony_mix = np.zeros(4, dtype=np.float32)
        self._sp_harmony_objs = [None, None, None, None]
        
        self.track_spread = [0, 0, 0, 0] # 0: Off, 1: Drum, 2: Bass, 3: Guitar
        self._sp_spread = np.zeros(4, dtype=np.int32)
        # 2 crossover states per track (low-pass 1 and low-pass 2)
        self._spread_zi = np.zeros((4, 2, 1), dtype=np.float32)
        
        # Pre-calculate spread coefficients (Fix 2c)
        self._spread_coeffs = {} 
        for mode, freqs in {1:(200,3000), 2:(300,1500), 3:(150,2500)}.items():
            a1 = min(0.99, 2 * np.pi * freqs[0] / self.sample_rate)
            a2 = min(0.99, 2 * np.pi * freqs[1] / self.sample_rate)
            self._spread_coeffs[mode] = (
                np.array([a1], dtype=np.float32), np.array([1.0, a1-1.0], dtype=np.float32),
                np.array([a2], dtype=np.float32), np.array([1.0, a2-1.0], dtype=np.float32)
            )
        
        self.track_chroma = [0, 0, 0, 0] # 0: Off, 1: Dark, 2: Sparkle, 3: Warm
        self._sp_chroma = np.zeros(4, dtype=np.int32)
        self._chroma_lp_state = [np.zeros(1, dtype=np.float32) for _ in range(4)] # For Dark/Sparkle
        self._chroma_dc_state = [np.zeros(1, dtype=np.float32) for _ in range(4)]
        
        self._sp_loop_enabled = False
        self._sp_loop_start = 0
        self._sp_loop_end = 0
        
        # Snapshot of track clip lists (Double buffered for Fix 2e)
        self._track_buf_a = [[], [], [], []]
        self._track_buf_b = [[], [], [], []]
        self._active_track_buf = self._track_buf_a
        
        self._sp_prev_tape = np.zeros(4, dtype=np.bool_)
        self._sp_prev_chroma = np.zeros(4, dtype=np.int32)
        self._sp_prev_spread = np.zeros(4, dtype=np.int32)
        
        # Precompute tanh scalar for Fix 2c
        self._tanh_asym_offset = float(np.tanh(0.2))
        self._tanh_chroma_warm_offset = float(np.tanh(0.15))
        
        # Pre-allocate 1-pole EQ coeffs (Fix 2a)
        self._eq_b = np.array([self._eq_alpha], dtype=np.float32)
        self._eq_a = np.array([1.0, self._eq_alpha - 1.0], dtype=np.float32)
        self._tape_b = np.array([self._tape_alpha], dtype=np.float32)
        self._tape_a = np.array([1.0, self._tape_alpha - 1.0], dtype=np.float32)
        
    def get_max_length(self):
        max_len = 0
        for track in self.tracks:
            for clip in track:
                end = clip.absolute_end_frame()
                if end > max_len:
                    max_len = end
        return max_len
        
    def _audio_callback(self, indata, outdata, frames, time_info, status):
        try:
            self._do_audio_callback(indata, outdata, frames, time_info, status)
        except Exception as e:
            logger.exception("Error in audio callback")
            raise

    def _do_audio_callback(self, indata, outdata, frames, time_info, status):
        start_t = time.perf_counter()
        
        # --- 0. ALWAYS-UPDATE TRANSPORT FLAGS (Safe scalar reads) ---
        self._sp_playing = self.is_playing
        self._sp_recording = self.is_recording
        self._sp_armed = self.armed_track
        self._sp_loop_enabled = self.loop_enabled

        if self._seek_request is not None:
            self.current_frame = self._seek_request
            self._seek_request = None
            
        # Reset master clipping at start of each block
        self.master_clipping = False
        
        # --- 1. NON-BLOCKING STATE SNAPSHOT ---
        if self.lock.acquire(blocking=False):
            try:
                self._sp_master_vol = self.master_volume
                np.copyto(self._sp_vols, self.track_volumes)
                np.copyto(self._sp_pans, self.track_pans)
                np.copyto(self._sp_mutes, self.track_mutes)
                np.copyto(self._sp_solos, self.track_solos)
                np.copyto(self._sp_monitoring, self.track_monitoring)
                np.copyto(self._sp_input_gains, self.input_gains)
                np.copyto(self._sp_eq_lo, self.track_eq_lo)
                np.copyto(self._sp_eq_hi, self.track_eq_hi)
                self._sp_mst_eq_lo = self.master_eq_lo
                self._sp_mst_eq_hi = self.master_eq_hi

                np.copyto(self._sp_pultec_enabled, self.track_pultec_enabled)
                np.copyto(self._sp_pultec_lf, self.track_pultec_low_freq)
                np.copyto(self._sp_pultec_lboost, self.track_pultec_low_boost)
                np.copyto(self._sp_pultec_lcut, self.track_pultec_low_cut)
                np.copyto(self._sp_pultec_hf, self.track_pultec_high_freq)
                np.copyto(self._sp_pultec_hboost, self.track_pultec_high_boost)
                np.copyto(self._sp_pultec_hcut, self.track_pultec_high_cut)
                
                # Copy Pultec SOS coefficients to shadow state
                np.copyto(self._sp_pultec_sos, self._pultec_sos)

                np.copyto(self._sp_prev_tape, self._sp_tape)
                np.copyto(self._sp_prev_chroma, self._sp_chroma)
                np.copyto(self._sp_prev_spread, self._sp_spread)

                np.copyto(self._sp_tape, self.track_tape)
                np.copyto(self._sp_rev_send, self.track_rev_send)
                self._sp_bus_reverb_type = self.bus_reverb_type
                self._sp_bus_reverb_return = self.bus_reverb_return
                np.copyto(self._sp_harmony, self.track_harmony)
                np.copyto(self._sp_harmony_mode, self.track_harmony_mode)
                np.copyto(self._sp_harmony_mix, self.track_harmony_mix)
                self._sp_harmony_objs = list(self._trk_harmony_objs) # Small allocation here is acceptable as it's just refs
                np.copyto(self._sp_spread, self.track_spread)
                np.copyto(self._sp_chroma, self.track_chroma)
                
                for i in range(4):
                    if self._sp_tape[i] and not self._sp_prev_tape[i]:
                        self._tape_lp_state[i][0] = 0.0
                        self._tape_dc_state[i][0] = 0.0
                    if self._sp_chroma[i] > 0 and self._sp_prev_chroma[i] == 0:
                        self._chroma_lp_state[i][0] = 0.0
                        self._chroma_dc_state[i][0] = 0.0
                    if self._sp_spread[i] > 0 and self._sp_prev_spread[i] == 0:
                        self._spread_zi[i, 0] = 0.0
                        self._spread_zi[i, 1] = 0.0
                
                # Check for pending Pultec state resets (Bug P3)
                for i in range(4):
                    if self._pultec_reset_pending[i]:
                        if not self._sp_pultec_enabled[i]:
                            self._sp_pultec_zi[i] = 0.0
                        self._pultec_reset_pending[i] = False
                
                self._sp_loop_start = self.loop_start_frame
                self._sp_loop_end = self.loop_end_frame
                
                self._sp_eq_alpha = self._eq_alpha
                self._sp_tape_alpha = self._tape_alpha
            finally:
                self.lock.release()
        
        # Track data is accessed via self._active_track_buf (Double buffered, zero-alloc snapshot)
        sp_tracks = self._active_track_buf

        # --- 2. INPUT METERING ---
        if self._sp_armed != -1:
            mono_in = self._buf_input_mono[:frames]
            np.copyto(mono_in, indata[:, 0])
            np.nan_to_num(mono_in, copy=False, nan=0.0, posinf=1.0, neginf=-1.0)
            
            gain = self._sp_input_gains[self._sp_armed]
            mono_in *= gain
            
            peak = float(np.max(np.abs(mono_in)))
            self.input_level = peak
            self.input_clipping = (peak >= 0.95)
        else:
            mono_in = None
            self.input_level = 0.0
            self.input_clipping = False
                
        # --- 3. EARLY EXIT ON SILENCE ---
        if not self._sp_playing and not self._sp_recording:
            if self._sp_armed == -1 or mono_in is None:
                outdata.fill(0)
                self.playback_levels = [0.0] * 4
                self.playback_clipping = [False] * 4
                self.master_level = 0.0
                self.master_clipping = False
                return
            
        frames_left = frames
        out_offset = 0
        
        while frames_left > 0:
            if self._sp_loop_enabled and not self._sp_recording:
                if self.current_frame >= self._sp_loop_end:
                    self.current_frame = self._sp_loop_start
                frames_to_loop_end = self._sp_loop_end - self.current_frame
                chunk_size = min(frames_left, frames_to_loop_end)
                if chunk_size <= 0:
                    self.current_frame = self._sp_loop_start
                    chunk_size = min(frames_left, self._sp_loop_end - self.current_frame)
            else:
                chunk_size = frames_left
                
            chunk_start = self.current_frame
            chunk_end = self.current_frame + chunk_size
        
            # --- 4. OUTPUT MIXING + PER-TRACK EQ ---
            mixed = self._buf_mixed[:chunk_size]
            mixed.fill(0.0)
            bus_send_stereo = self._buf_bus_send[:chunk_size]
            bus_send_stereo.fill(0.0)
            any_solo = any(self._sp_solos)
        
            for i in range(4):
                self.playback_clipping[i] = False
                if self._sp_mutes[i] and not self._sp_solos[i]:
                    continue
                if any_solo and not self._sp_solos[i]:
                    continue
            
                # Accumulate this track's mono signal
                track_mono = self._buf_track_mono[:chunk_size]
                track_mono.fill(0.0)
                has_audio = False
            
                for clip in sp_tracks[i]:
                    try:
                        audio_seg, ov_start, ov_end = clip.get_audio_segment(chunk_start, chunk_end)
                        if audio_seg is not None and len(audio_seg) > 0:
                            out_s = ov_start - chunk_start
                            out_e = ov_end - chunk_start
                            track_mono[out_s:out_e] += audio_seg
                            has_audio = True
                    except Exception as e:
                        logger.debug(f"Error getting clip segment for track {i}: {e}")
            
                # --- Live Input Monitoring ---
                if i == self._sp_armed and self._sp_monitoring[i] and mono_in is not None:
                    track_mono += mono_in
                    has_audio = True
            
                rev_send = self._sp_rev_send[i]
                harmony_mix = self._sp_harmony_mix[i]
            
                if not has_audio and rev_send == 0.0 and harmony_mix == 0.0:
                    continue
            
                # Apply volume
                track_mono *= self._sp_vols[i]
            
                # Apply per-track EQ (1-pole bass/treble tone control)
                lo_db = self._sp_eq_lo[i]
                hi_db = self._sp_eq_hi[i]
                if lo_db != 0.0 or hi_db != 0.0:
                    lo_gain = 10.0 ** (lo_db / 20.0)
                    hi_gain = 10.0 ** (hi_db / 20.0)
                
                    bass, next_zi = signal.lfilter(self._eq_b, self._eq_a, track_mono, zi=self._trk_lp_state[i])
                    self._trk_lp_state[i] = next_zi
                
                    treble = track_mono - bass
                    track_mono[:] = bass * lo_gain + treble * hi_gain

                # --- PULTEC EQ (Serial Cascade - Fix 1 Step 3) ---
                if self._sp_pultec_enabled[i]:
                    try:
                        track_mono[:], self._sp_pultec_zi[i] = signal.sosfilt(
                            self._sp_pultec_sos[i], 
                            track_mono, 
                            zi=self._sp_pultec_zi[i]
                        )

                        # Safety check for NaNs/Infs (BUG-P12)
                        if not np.isfinite(track_mono).all():
                            logger.error(f"Non-finite audio in Pultec track {i}")
                            self._sp_pultec_zi[i] = 0.0 # Clear state
                    except Exception as e:
                        logger.error(f"Pultec filter error on track {i}: {e}")
                        self._sp_pultec_enabled[i] = False

            
                # Apply Harmony (Real-time)
                if self._sp_harmony[i] and self._sp_harmony_mix[i] > 0:

                    pbs = self._sp_harmony_objs[i]
                    if pbs:
                        mix = self._sp_harmony_mix[i]
                        # Pedalboard.process expects (channels, samples)
                        chunk_2d = track_mono.reshape(1, -1)
                    
                        # Parallel voice summing to match offline logic
                        wet_sum = self._buf_wet_sum[:chunk_size]
                        wet_sum.fill(0.0)
                        for pb in pbs:
                            try:
                                processed = pb.process(chunk_2d, float(self.sample_rate), reset=False)
                                if processed.shape[1] > 0:
                                    # We sum all shifted voices (Bug H2: was assignment, now accumulation)
                                    wet_sum += processed[0]
                            except Exception:
                                pass
                    
                        # Normalise wet signal by voice count and blend with dry
                        n_voices = len(pbs)
                        wet = wet_sum / n_voices if n_voices > 0 else wet_sum
                        # Bug H6 fix: Clip wet signal before blending
                        wet = np.clip(wet, -1.0, 1.0)
                        track_mono[:] = track_mono * (1.0 - mix) + wet * mix
            
                # --- CHROMA GLOW (Pseudo-Analog Character) ---
                chroma_mode = self._sp_chroma[i]
                if chroma_mode > 0:
                    if chroma_mode == 1: # DARK (Tube-style saturator + Darkening)
                        # Drive into soft clipper
                        track_mono *= 2.0
                        np.arctan(track_mono, out=track_mono)
                        # Vectorized Darken (1.2kHz)
                        a_dark = min(0.99, 2 * np.pi * 1200 / self.sample_rate)
                        b, a = [a_dark], [1.0, a_dark - 1.0]
                        dark_out, next_zi = signal.lfilter(b, a, track_mono, zi=self._chroma_lp_state[i])
                        track_mono[:] = dark_out
                        self._chroma_lp_state[i] = next_zi
                        track_mono *= 1.2 # Makeup
                    elif chroma_mode == 2: # SPARKLE (Exciter / HF Air)
                        # Vectorized High pass (6kHz)
                        a_high = min(0.99, 2 * np.pi * 6000 / self.sample_rate)
                        b, a = [a_high], [1.0, a_high - 1.0]
                        lp_sig, next_zi = signal.lfilter(b, a, track_mono, zi=self._chroma_lp_state[i])
                        self._chroma_lp_state[i] = next_zi

                        # We reuse self._buf_wet_sum as a temp buffer for Sparkle calculation
                        wet_sig = self._buf_wet_sum[:chunk_size]
                        np.subtract(track_mono, lp_sig, out=wet_sig)
                        # Saturate high frequencies and blend back
                        wet_sig *= 4.0
                        np.tanh(wet_sig, out=wet_sig)
                        track_mono += wet_sig * 0.4
                    elif chroma_mode == 3: # WARM (Even-order saturation)
                        # Asymmetric saturation (similar to tape but cleaner)
                        track_mono += 0.15
                        np.tanh(track_mono, out=track_mono)
                        track_mono -= self._tanh_chroma_warm_offset
                        dc_a = 0.995
                        warm_dc_out, next_dc_zi = signal.lfilter([1.0, -1.0], [1.0, -dc_a], track_mono, zi=self._chroma_dc_state[i])
                        track_mono[:] = warm_dc_out
                        self._chroma_dc_state[i] = next_dc_zi
                        track_mono *= 1.1
            
                # Apply analog tape saturation (if enabled)
                if self._sp_tape[i]:
                    # 1) Aggressive drive — push hard into saturation for compression & grit
                    drive = 3.5
                    track_mono *= drive
                
                    # 2) Asymmetric soft-clip — adds even harmonics for "analog warmth"
                    # Using a DC offset shift before tanh produces even-order distortion
                    track_mono += 0.2
                    np.tanh(track_mono, out=track_mono)
                    track_mono -= self._tanh_asym_offset
                
                    # DC Blocker (10Hz high-pass)
                    dc_a = 0.995
                    dc_out, next_dc_zi = signal.lfilter([1.0, -1.0], [1.0, -dc_a], track_mono, zi=self._tape_dc_state[i])
                    track_mono[:] = dc_out
                    self._tape_dc_state[i] = next_dc_zi
                
                    # 3) HF rolloff — tape loses sparkle (frequency-dependent compression)
                    b, a = [self._sp_tape_alpha], [1.0, self._sp_tape_alpha - 1.0]
                    lp_out, next_zi = signal.lfilter(b, a, track_mono, zi=self._tape_lp_state[i])
                    track_mono[:] = lp_out
                    self._tape_lp_state[i] = next_zi
                
                    # 4) Makeup gain — compensate for high drive + tanh attenuation
                    track_mono *= 0.75
            
                # Apply pan to create stereo image
                pan = self._sp_pans[i]
                l_gain = min(1.0, 1.0 - pan)
                r_gain = min(1.0, 1.0 + pan)
                track_stereo = self._buf_track_stereo[:chunk_size]
                track_stereo.fill(0.0)
            
                # --- STEREO SPREAD (Pseudo-Stereo) ---
                spread_mode = self._sp_spread[i]
                if spread_mode > 0:
                    # Frequencies: 1:Drum(200,3k), 2:Bass(300,1.5k), 3:Guitar(150,2.5k)
                    b1, a1_arr, b2, a2_arr = self._spread_coeffs[spread_mode]
                
                    low, next_zi1 = signal.lfilter(b1, a1_arr, track_mono, zi=self._spread_zi[i, 0])
                    lp2_sig, next_zi2 = signal.lfilter(b2, a2_arr, track_mono, zi=self._spread_zi[i, 1])
                
                    self._spread_zi[i, 0] = next_zi1
                    self._spread_zi[i, 1] = next_zi2
                
                    mid = lp2_sig - low
                    high = track_mono - lp2_sig
                
                    # Spread: Low is mono, Mid/High are panned opposite
                    track_stereo[:, 0] = low * 0.707 + mid * 1.0 + high * 0.1
                    track_stereo[:, 1] = low * 0.707 + mid * 0.1 + high * 1.0
                
                    # Apply track pan as a balance control on the spread signal
                    track_stereo[:, 0] *= l_gain
                    track_stereo[:, 1] *= r_gain
                else:
                    track_stereo[:, 0] = track_mono * l_gain
                    track_stereo[:, 1] = track_mono * r_gain
            
                # Capture track playback output peak
                peak = float(np.max(np.abs(track_stereo)))
                self.playback_levels[i] = peak
                if peak >= 1.0: self.playback_clipping[i] = True
            
                if rev_send > 0.0:
                    bus_send_stereo += track_stereo * rev_send
                mixed += track_stereo

            # --- BUS REVERB RETURN ---
            active_reverb = self._reverb_list[self._sp_bus_reverb_type]
            if active_reverb is not None:
                wet_t = active_reverb.process(
                    bus_send_stereo.T,
                    int(self.sample_rate),
                    reset=False
                )
                wet_stereo = wet_t.T
                mixed += wet_stereo * self._sp_bus_reverb_return

            mixed *= self._sp_master_vol
        
            # Apply master EQ
            mlo = self._sp_mst_eq_lo
            mhi = self._sp_mst_eq_hi
            if mlo != 0.0 or mhi != 0.0:
                mlo_gain = 10.0 ** (mlo / 20.0)
                mhi_gain = 10.0 ** (mhi / 20.0)
            
                for ch in range(2):
                    bass, next_zi = signal.lfilter(self._eq_b, self._eq_a, mixed[:, ch], zi=self._mst_lp_state[ch])
                    self._mst_lp_state[ch] = next_zi
                    treble = mixed[:, ch] - bass
                    mixed[:, ch] = bass * mlo_gain + treble * mhi_gain
        
            # Capture master playback peak
            mst_peak = float(np.max(np.abs(mixed)))
            self.master_level = mst_peak
            if mst_peak >= 1.0: self.master_clipping = True
        
            np.clip(mixed, -1.0, 1.0, out=outdata[out_offset : out_offset + chunk_size])
            out_offset += chunk_size
            frames_left -= chunk_size
            
            if self._sp_playing or self._sp_recording:
                self.current_frame += chunk_size
        
        # --- 5. RECORDING CAPTURE (stamp actual start frame on first buffer) ---
        if self._sp_recording and self._sp_armed != -1 and mono_in is not None:
            # Important: mono_in already has input_gain applied (see Metering section above)
            if len(self.recording_buffer) == 0:
                # This is the FIRST buffer of the recording session.
                # Stamp the actual timeline position to guarantee sample-accurate alignment.
                self.record_start_frame = self.current_frame
            self.recording_buffer.append(mono_in.copy())
            
        # Loop advancement handled inside the while loop above

        # --- 7. CPU LOAD METERING ---
        end_t = time.perf_counter()
        elapsed = end_t - start_t
        available = frames / self.sample_rate
        load = elapsed / available
        
        self._cpu_accum += load
        self._cpu_count += 1
        
        # Update public CPU load approx once per second
        # (at 44100Hz with 512 frames, this is ~86 callbacks/sec)
        callbacks_per_sec = int(self.sample_rate / frames)
        if self._cpu_count >= callbacks_per_sec:
            self.cpu_load = min(1.0, self._cpu_accum / self._cpu_count)
            self._cpu_accum = 0.0
            self._cpu_count = 0

    def _ensure_stream(self):
        """Start the audio stream if not already running.
        
        Queries the device's native sample rate to avoid PaErrorCode -9997
        (Invalid sample rate) on devices that don't support 44100 Hz directly.
        """
        if self.stream is not None and self.stream.active:
            return

        max_retries = 3
        retry_delay = 0.2

        for attempt in range(max_retries):
            try:
                if self.stream is not None:
                    try:
                        self.stream.stop()
                        self.stream.close()
                        import time
                        time.sleep(0.2)
                    except:
                        pass
                self.stream = None

                # Resolve the best sample rate for the chosen devices.
                try:
                    dev_info = sd.query_devices(self.input_device, 'input')
                    native_sr = int(dev_info['default_samplerate'])
                except Exception:
                    native_sr = self.sample_rate

                if native_sr not in (44100, 48000):
                    native_sr = 44100

                self.stream = sd.Stream(
                    device=(self.input_device, self.output_device),
                    samplerate=native_sr,
                    blocksize=512,
                    channels=(1, 2),
                    callback=self._audio_callback
                )
                self.stream.start()
                
                self.sample_rate = native_sr
                self._eq_alpha = 2.0 * np.pi * 300.0 / self.sample_rate
                self._tape_alpha = 2.0 * np.pi * 8000.0 / self.sample_rate
                logger.info(f"Audio stream started at {native_sr}Hz")
                return # Success!
                
            except Exception as e:
                logger.error(f"Error starting audio stream (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(retry_delay * (attempt + 1))
                else:
                    print(f"Final error starting audio stream: {e}")

    def set_devices(self, input_dev, output_dev):
        """Update the audio devices and restart the stream if it was running."""
        with self.lock:
            self.input_device = input_dev
            self.output_device = output_dev
        
        had_full_stream = self.stream is not None
        had_monitor = self.monitor_stream is not None and (
            self.monitor_stream.active if self.monitor_stream else False
        )

        # If full stream is active, restart it with new devices
        if had_full_stream:
            was_playing = self.is_playing
            was_recording = self.is_recording
            was_armed = self.armed_track
            
            # Stop existing stream
            try:
                self.stream.stop()
                self.stream.close()
            except:
                pass
            self.stream = None
            
            # Re-ensure stream if it was playing or recording
            if was_playing or was_recording:
                self._ensure_stream()
                self.is_playing = was_playing
                self.is_recording = was_recording
                self.armed_track = was_armed

        # Always restart monitor if it was running (even without a full stream)
        if had_monitor:
            self._stop_monitor()
            self.start_monitoring()

    def _reset_filter_states(self):
        """Zero all IIR filter states so each play session starts clean.
        Safe to call only when no audio stream is running (after _stop_monitor)."""
        for i in range(4):
            self._trk_lp_state[i][:]     = 0.0
            self._tape_lp_state[i][:]    = 0.0
            self._tape_dc_state[i][:]    = 0.0
            self._chroma_lp_state[i][:] = 0.0
            self._chroma_dc_state[i][:] = 0.0
        self._pultec_zi[:]    = 0.0
        self._sp_pultec_zi[:] = 0.0
        self._spread_zi[:]    = 0.0
        for ch in range(2):
            self._mst_lp_state[ch][:] = 0.0

    def start_playback(self):
        # Stop monitor stream OUTSIDE the lock first
        self._stop_monitor()
        # Reset all IIR filter states — ensures each play starts with zero
        # residual charge (no transient clicks from previous session)
        self._reset_filter_states()
        with self.lock:
            self.is_playing = True
        self._ensure_stream()

    def start_recording(self, track_index):
        # Stop monitor stream OUTSIDE the lock first
        self._stop_monitor()
        with self.lock:
            self.armed_track = track_index
            self.record_start_frame = self.current_frame
            self.recording_buffer = []
            self.is_recording = True
            self.is_playing = True  # Also play back other tracks during recording

        self._ensure_stream()

    def start_monitoring(self):
        """Start the audio stream just for input metering (no playback/record).
        
        Uses self.input_device / self.output_device so that PulseAudio virtual
        sink monitors (for tethered synths) are picked up correctly instead of
        falling back to the system default (internal mic).
        """
        if self.stream is not None and self.stream.active:
            return  # Already have a full stream running
        if self.monitor_stream is not None and self.monitor_stream.active:
            return  # Already monitoring
        # Clean up any stale inactive monitor stream before starting fresh:
        if self.monitor_stream is not None and not self.monitor_stream.active:
            try:
                self.monitor_stream.close()
            except Exception:
                pass
            self.monitor_stream = None
        try:
            if self.monitor_stream is not None:
                try:
                    self.monitor_stream.stop()
                    self.monitor_stream.close()
                    import time
                    time.sleep(0.1)
                except:
                    pass
                    
            self.monitor_stream = sd.Stream(
                device=(self.input_device, self.output_device),
                samplerate=self.sample_rate,
                blocksize=512,
                channels=(1, 2),
                callback=self._audio_callback
            )
            self.monitor_stream.start()
        except Exception as e:
            print(f"Monitor stream error: {e}")
            pass
    
    def _stop_monitor(self):
        """Stop the monitoring stream. MUST be called OUTSIDE self.lock."""
        mon = self.monitor_stream
        self.monitor_stream = None
        if mon is not None:
            try:
                mon.stop()
                mon.close()
                import time
                time.sleep(0.1)
            except Exception:
                pass
                
    def stop(self):
        # 1. Signal the callback to stop producing/capturing audio
        with self.lock:
            self.is_playing = False
            self.is_recording = False
            
            # Commit recorded buffer into a Clip (but keep armed_track set for metering)
            armed = self.armed_track
            buf = self.recording_buffer
            rec_start = self.record_start_frame
            self.recording_buffer = []
        
        # 2. Commit clip OUTSIDE the lock (no contention with callback)
        if armed != -1 and len(buf) > 0:
            raw_data = np.concatenate(buf)
            new_clip = Clip(raw_data, rec_start)
            with self.lock:
                self._insert_clip_destructive(armed, new_clip)
        
        # 3. Tear down main stream OUTSIDE the lock
        stream_ref = self.stream
        self.stream = None
        if stream_ref is not None:
            try:
                stream_ref.stop()
                stream_ref.close()
            except Exception:
                pass
        
        # 4. If still armed, restart monitoring for the meter
        if self.armed_track != -1:
            self.start_monitoring()
                
    def rewind(self):
        with self.lock:
            self.current_frame = 0
            self._seek_request = 0

    def update_pultec_params(self, track_idx, enabled, low_freq, low_boost, low_cut,
                              high_freq, high_boost, high_cut, preset=0):
        # 1. Pre-calculate SOS outside the lock to minimize contention (Performance fix)
        lf_hz = [30, 60, 100, 200][low_freq]
        hf_hz = [3000, 5000, 8000, 12000, 16000][high_freq]
        sr = float(self.sample_rate)

        new_sos = []
        new_sos.append(_get_biquad_shelf_coeffs('low_boost', lf_hz, low_boost, sr))
        new_sos.append(_get_biquad_shelf_coeffs('low_cut', lf_hz, low_cut, sr))
        new_sos.append(_get_biquad_shelf_coeffs('high_boost', hf_hz, high_boost, sr))
        new_sos.append(_get_biquad_shelf_coeffs('high_cut', hf_hz, high_cut, sr))
        new_sos_np = np.array(new_sos, dtype=np.float32)

        with self.lock:
            params_changed = (
                self.track_pultec_low_freq[track_idx]  != low_freq or
                self.track_pultec_low_boost[track_idx] != low_boost or
                self.track_pultec_low_cut[track_idx]   != low_cut or
                self.track_pultec_high_freq[track_idx] != high_freq or
                self.track_pultec_high_boost[track_idx]!= high_boost or
                self.track_pultec_high_cut[track_idx]  != high_cut
            )
            
            self.track_pultec_enabled[track_idx]    = enabled
            self.track_pultec_low_freq[track_idx]   = low_freq
            self.track_pultec_low_boost[track_idx]  = low_boost
            self.track_pultec_low_cut[track_idx]    = low_cut
            self.track_pultec_high_freq[track_idx]  = high_freq
            self.track_pultec_high_boost[track_idx] = high_boost
            self.track_pultec_high_cut[track_idx]   = high_cut
            self.track_pultec_preset[track_idx]     = preset

            # Update shadow state
            self._sp_pultec_enabled[track_idx]  = enabled
            self._sp_pultec_lf[track_idx]       = low_freq
            self._sp_pultec_lboost[track_idx]   = low_boost
            self._sp_pultec_lcut[track_idx]     = low_cut
            self._sp_pultec_hf[track_idx]       = high_freq
            self._sp_pultec_hboost[track_idx]   = high_boost
            self._sp_pultec_hcut[track_idx]     = high_cut

            if params_changed or not enabled:
                self._pultec_zi[track_idx] = 0.0
                self._pultec_reset_pending[track_idx] = True
                self._pultec_sos[track_idx] = new_sos_np


    def update_harmony_params(self, track_idx, enabled, mode_idx, mix):
        """Update harmony parameters and regenerate pedalboard objects if needed."""
        with self.lock:
            self.track_harmony[track_idx] = enabled
            self.track_harmony_mode[track_idx] = mode_idx
            self.track_harmony_mix[track_idx] = mix
            
        def _warmup_worker():
            new_pbs = None
            if enabled and mix > 0:
                shifts = HARMONY_MODES.get(mode_idx, [0])
                # Parallel voices: separate Pedalboard per shift to match offline logic
                new_pbs = []
                for s in shifts:
                    pb = Pedalboard([PitchShift(semitones=float(s))])
                    # Warm up / Initialize buffers for mono
                    # Use standard blocksize to ensure Rubber Band is ready
                    warmup_size = 2048
                    for _ in range(20):
                        dummy = np.zeros((1, warmup_size), dtype=np.float32)
                        pb.process(dummy, float(self.sample_rate), reset=False)
                    new_pbs.append(pb)

            with self.lock:
                self._trk_harmony_objs[track_idx] = new_pbs

        # Offload warmup to background thread (Bug H3)
        threading.Thread(target=_warmup_worker, daemon=True).start()

    def set_track_rev_send(self, track_idx: int, send: float):
        """Set how much of track i is fed to the bus reverb (0.0–1.0)."""
        with self.lock:
            self.track_rev_send[track_idx] = float(np.clip(send, 0.0, 1.0))

    def set_bus_reverb_type(self, reverb_type: int):
        """Switch active bus reverb: 0=Room, 1=Ambience, 2=Plate."""
        with self.lock:
            if reverb_type in self._bus_reverbs:
                self.bus_reverb_type = reverb_type

    def set_bus_reverb_return(self, level: float):
        """Set the master wet return level of the bus (0.0–1.0)."""
        with self.lock:
            self.bus_reverb_return = float(np.clip(level, 0.0, 1.0))

    def _insert_clip_destructive(self, track_idx, new_clip):
        """Inserts a new clip and forces boundaries to prevent overlaps with existing clips."""
        track = self.tracks[track_idx]
        new_start = new_clip.start_frame
        new_end = new_clip.absolute_end_frame()
        
        final_clips = []
        
        for c in track:
            c_start = c.start_frame
            c_end = c.absolute_end_frame()
            
            if c_end <= new_start or c_start >= new_end:
                # No overlap
                final_clips.append(c)
            elif c_start < new_start and c_end > new_end:
                # The existing clip completely envelops the new clip. Split into two.
                left_clip = Clip(c.data, c.start_frame)
                left_clip.offset_frame = c.offset_frame
                left_clip.length_frame = (new_start - c.start_frame)
                
                right_clip = Clip(c.data, new_end)
                right_clip.offset_frame = c.offset_frame + (new_end - c.start_frame)
                right_clip.length_frame = c_end - new_end
                
                final_clips.extend([left_clip, right_clip])
            elif c_start >= new_start and c_end <= new_end:
                # New clip completely covers this one. Drop it.
                pass
            elif c_start < new_start and c_end <= new_end:
                # New clip eats the right tail. Create a new truncated version.
                new_c = Clip(c.data, c.start_frame)
                new_c.id = c.id
                new_c.offset_frame = c.offset_frame
                new_c.length_frame = (new_start - c.start_frame)
                final_clips.append(new_c)
            elif c_start >= new_start and c_end > new_end:
                # New clip eats the left head. Create a new truncated version.
                new_c = Clip(c.data, new_end)
                new_c.id = c.id
                new_c.offset_frame = c.offset_frame + (new_end - c.start_frame)
                new_c.length_frame = c.length_frame - (new_end - c.start_frame)
                final_clips.append(new_c)
                
        final_clips.append(new_clip)
        final_clips.sort(key=lambda x: x.start_frame)
        self.tracks[track_idx] = final_clips
        self._sync_track_buffer()

    def _sync_track_buffer(self):
        """Atomically updates the lock-free track snapshot for the callback (Fix 2e)."""
        inactive = (self._track_buf_b if self._active_track_buf is self._track_buf_a else self._track_buf_a)
        # Deep copy the list structure but shared Clip references are fine since they are cloned in snapshot 
        # (Wait, Fix 2e says eliminating [list(t) for t in self.tracks] in callback).
        # If I eliminate the clone in callback, I must clone here.
        for i in range(4):
            inactive[i] = [c.copy() for c in self.tracks[i]]
        self._active_track_buf = inactive

    # --- DSP DESTRUCTIVE EFFECTS ---
    def apply_delay(self, track_index, delay_time_sec=0.3, feedback=0.3, mix=0.5):
        with self.lock:
            track_clips = self.tracks[track_index]
            if len(track_clips) == 0:
                return
                
            delay_samples = int(delay_time_sec * self.sample_rate)
            if delay_samples <= 0:
                return
                
            new_clips = []
            for clip in track_clips:
                active_audio = clip.data[clip.offset_frame : clip.offset_frame + clip.length_frame]
                tail_samples = int(delay_samples * 10)
                processed = np.pad(active_audio, (0, tail_samples))
                
                out_track = np.copy(processed)
                b = processed.copy()
                current_feedback = feedback * mix
                shift = delay_samples
                
                for i in range(10):
                    if current_feedback < 0.01: break
                    echo = np.roll(b, shift)
                    echo[:shift] = 0
                    out_track += echo * current_feedback
                    b = echo
                    current_feedback *= feedback
                    
                final_out = processed * (1.0 - mix) + out_track
                max_val = np.max(np.abs(final_out))
                if max_val > 1.0: final_out /= max_val
                
                new_clip = Clip(final_out.astype(np.float32), clip.start_frame)
                new_clips.append(new_clip)
                
            self.tracks[track_index] = []
            for nc in new_clips:
                self._insert_clip_destructive(track_index, nc)

    def apply_eq(self, track_index, low_gain_db=0.0, high_gain_db=0.0):
        with self.lock:
            new_track = []
            for clip in self.tracks[track_index]:
                nyq = 0.5 * self.sample_rate
                
                b_l, a_l = signal.butter(2, 300 / nyq, btype='low')
                low_band = signal.filtfilt(b_l, a_l, clip.data)
                
                b_h, a_h = signal.butter(2, 3000 / nyq, btype='high')
                high_band = signal.filtfilt(b_h, a_h, clip.data)
                
                mid_band = clip.data - low_band - high_band
                
                l_scalar = 10 ** (low_gain_db / 20.0)
                h_scalar = 10 ** (high_gain_db / 20.0)
                
                out_track = (low_band * l_scalar) + mid_band + (high_band * h_scalar)
                
                new_clip = Clip(np.clip(out_track, -1.0, 1.0).astype(np.float32), clip.start_frame)
                new_clip.id = clip.id
                new_clip.offset_frame = clip.offset_frame
                new_clip.length_frame = clip.length_frame
                new_track.append(new_clip)
            self.tracks[track_index] = new_track

    def sum_tracks_offline(self, source_indices, target_index):
        with self.lock:
            # 1) Find maximum needed length across source tracks
            max_len = 0
            for i in source_indices:
                for clip in self.tracks[i]:
                    end = clip.absolute_end_frame()
                    if end > max_len:
                        max_len = end
            
            if max_len == 0:
                return False  # Nothing to sum
                
            mono_mix = np.zeros(max_len, dtype=np.float32)
            
            # 2) Render each track identically to how the real-time mixer does it (Vol, EQ, Tape)
            alpha = self._eq_alpha
            t_alpha = self._tape_alpha
            
            # Append tail time if ANY reverb is present so decay isn't cut off
            has_reverb = any(self.track_rev_send[i] > 0.0 for i in source_indices)
            if has_reverb:
                tail_samples = int(self.sample_rate * 3.0)
                mono_mix = np.pad(mono_mix, (0, tail_samples))
                max_len += tail_samples
            
            bus_send_offline = np.zeros(max_len, dtype=np.float32)
            
            for i in source_indices:
                if self.track_mutes[i]: continue
                
                track_mono = np.zeros(max_len, dtype=np.float32)
                has_audio = False
                
                for clip in self.tracks[i]:
                    active_audio = clip.data[clip.offset_frame : clip.offset_frame + clip.length_frame]
                    start = clip.start_frame
                    l = len(active_audio)
                    if l > 0:
                        mapped_end = min(start + l, max_len)
                        valid_l = mapped_end - start
                        track_mono[start:mapped_end] += active_audio[:valid_l]
                        has_audio = True
                        
                if not has_audio:
                    continue
                    
                # Volume
                track_mono *= self.track_volumes[i]
                
                # EQ
                lo_db = self.track_eq_lo[i]
                hi_db = self.track_eq_hi[i]
                if lo_db != 0.0 or hi_db != 0.0:
                    lo_gain = 10.0 ** (lo_db / 20.0)
                    hi_gain = 10.0 ** (hi_db / 20.0)
                    
                    # Vectorized 1-pole filter: b=[alpha], a=[1, alpha-1]
                    b, a = [alpha], [1.0, alpha - 1.0]
                    bass = signal.lfilter(b, a, track_mono)
                    
                    treble = track_mono - bass
                    track_mono[:] = bass * lo_gain + treble * hi_gain
                        
                # Pultec EQ (Offline)
                if self.track_pultec_enabled[i]:
                    # Serial cascade matching real-time path
                    offline_zi = np.zeros((4, 2), dtype=np.float32)
                    track_mono, _ = signal.sosfilt(
                        self._pultec_sos[i], 
                        track_mono, 
                        zi=offline_zi
                    )

                # Harmony
                if self.track_harmony[i] and self.track_harmony_mix[i] > 0:
                    mode_idx = self.track_harmony_mode[i]
                    h_mix = self.track_harmony_mix[i]
                    shifts = HARMONY_MODES.get(mode_idx, [0])
                    
                    chunk_2d = track_mono.reshape(1, -1)
                    wet_sum = np.zeros_like(track_mono)
                    for s_val in shifts:
                        pb = Pedalboard([PitchShift(semitones=float(s_val))])
                        shifted = pb.process(chunk_2d, self.sample_rate)
                        l = min(len(wet_sum), shifted.shape[1])
                        wet_sum[:l] += shifted[0, :l]
                    
                    wet_sum /= len(shifts)
                    track_mono = track_mono * (1.0 - h_mix) + wet_sum * h_mix

                # Tape Saturation
                if self.track_tape[i]:
                    # 1) Aggressive drive — push hard into saturation for compression & grit
                    drive = 3.5
                    track_mono *= drive
                    
                    # 2) Asymmetric soft-clip — adds even harmonics for "analog warmth"
                    asym_offset = 0.2
                    track_mono = np.tanh(track_mono + asym_offset) - np.tanh(asym_offset)
                    
                    dc_a = 0.995
                    track_mono[:] = signal.lfilter([1.0, -1.0], [1.0, -dc_a], track_mono)
                    
                    # 3) HF rolloff — tape loses sparkle (frequency-dependent compression)
                    b, a = [t_alpha], [1.0, t_alpha - 1.0]
                    track_mono[:] = signal.lfilter(b, a, track_mono)
                        
                    # 4) Makeup gain — compensate for high drive + tanh attenuation
                    track_mono *= 0.75
                    
                # Accumulate bus send (offline)
                rev_send = self.track_rev_send[i]
                if rev_send > 0.0:
                    bus_send_offline += track_mono * rev_send
                    
                # Sum into master mono bus
                mono_mix += track_mono

            # Apply bus reverb to accumulated send (offline)
            if np.max(np.abs(bus_send_offline)) > 1e-6:
                reverb_params = self._bus_reverbs.get(self.bus_reverb_type)
                if reverb_params is not None:
                    wet_t = reverb_params.process(
                        bus_send_offline.reshape(1, -1),
                        int(self.sample_rate),
                        reset=True
                    )
                    mono_mix += wet_t[0] * self.bus_reverb_return
                
            # 3) Soft-clip the summed master to prevent ugly digital clipping (Analog headroom)
            # This allows gentle saturation if pushing levels hard when bouncing
            mono_mix = np.clip(mono_mix, -1.0, 1.0)
            
            # 4) Overwrite target track with new summed clip
            new_clip = Clip(mono_mix, 0)
            self.tracks[target_index] = [new_clip]
            self._sync_track_buffer()
            return True
