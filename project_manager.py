import os
import json
import logging
import numpy as np
import soundfile as sf
import uuid
import scipy.signal as signal
from pydub import AudioSegment
from audio_engine import Clip

logger = logging.getLogger(__name__)

class ProjectManager:
    def __init__(self, audio_engine):
        self.engine = audio_engine
        self.project_name = "Untitled"
        self.project_dir = None
        self.sample_rate = self.engine.sample_rate

    def save_project(self, save_path):
        """Saves the NLE project state to a folder containing separate flac files per clip."""
        logger.info(f"Saving project to {save_path}")
        if not os.path.exists(save_path):
            os.makedirs(save_path)
            
        self.project_dir = save_path
        self.project_name = os.path.basename(save_path)
        
        metadata = {
            "name": self.project_name,
            "master_volume": self.engine.master_volume,
            "track_volumes": self.engine.track_volumes,
            "track_pans": self.engine.track_pans,
            "track_mutes": self.engine.track_mutes,
            "track_solos": self.engine.track_solos,
            "track_monitoring": self.engine.track_monitoring,
            "input_gains": self.engine.input_gains,
            "track_eq_lo": self.engine.track_eq_lo,
            "track_eq_hi": self.engine.track_eq_hi,
            "track_tape": self.engine.track_tape,
            "track_rev_send": self.engine.track_rev_send,
            "bus_reverb_type": self.engine.bus_reverb_type,
            "bus_reverb_return": self.engine.bus_reverb_return,
            "track_spread": self.engine.track_spread,
            "track_chroma": self.engine.track_chroma,
            "track_harmony": self.engine.track_harmony,
            "track_harmony_mode": self.engine.track_harmony_mode,
            "track_harmony_mix": self.engine.track_harmony_mix,
            "track_pultec_enabled": self.engine.track_pultec_enabled,
            "track_pultec_low_freq": self.engine.track_pultec_low_freq,
            "track_pultec_low_boost": self.engine.track_pultec_low_boost,
            "track_pultec_low_cut": self.engine.track_pultec_low_cut,
            "track_pultec_high_freq": self.engine.track_pultec_high_freq,
            "track_pultec_high_boost": self.engine.track_pultec_high_boost,
            "track_pultec_high_cut": self.engine.track_pultec_high_cut,
            "track_pultec_preset": self.engine.track_pultec_preset,
            "tracks": [] # List of clip arrays
        }
        
        # We need an audio/ subdirectory to store the clip files
        audio_dir = os.path.join(save_path, "audio")
        if not os.path.exists(audio_dir):
            os.makedirs(audio_dir)
        
        # Save tracks
        with self.engine.lock:
            for i in range(4):
                track_clips = []
                for clip in self.engine.tracks[i]:
                    clip_file = f"clip_{clip.id}.flac"
                    file_path = os.path.join(audio_dir, clip_file)
                    
                    # We save the *full* original underlying data to disk, allowing non-destructive stretching later!
                    if not os.path.exists(file_path):
                        sf.write(file_path, clip.data, self.sample_rate, format='FLAC')
                        
                    clip_meta = {
                        "id": clip.id,
                        "file": clip_file,
                        "start_frame": clip.start_frame,
                        "offset_frame": clip.offset_frame,
                        "length_frame": clip.length_frame
                    }
                    track_clips.append(clip_meta)
                metadata["tracks"].append(track_clips)
                
        # Write metadata
        with open(os.path.join(save_path, "project.json"), 'w') as f:
            json.dump(metadata, f, indent=4)
            
    def load_project(self, load_path):
        """Loads an NLE project folder or a direct project.json file."""
        logger.info(f"Loading project from {load_path}")
        
        # If user selected the json file directly, use its parent folder as the load_path
        if os.path.isfile(load_path) and load_path.endswith(".json"):
            actual_load_path = os.path.dirname(load_path)
            json_path = load_path
        else:
            actual_load_path = load_path
            json_path = os.path.join(load_path, "project.json")
            
        if not os.path.exists(json_path):
            raise FileNotFoundError(f"project.json not found at {json_path}")
            
        with open(json_path, 'r') as f:
            metadata = json.load(f)
            
        self.project_dir = actual_load_path
        self.project_name = metadata.get("name", os.path.basename(actual_load_path))
        
        with self.engine.lock:
            self.engine.current_frame = 0
            self.engine.master_volume = metadata.get("master_volume", 1.0)
            self.engine.track_volumes = metadata.get("track_volumes", [1.0, 1.0, 1.0, 1.0])
            self.engine.track_pans = metadata.get("track_pans", [0.0, 0.0, 0.0, 0.0])
            self.engine.track_mutes = metadata.get("track_mutes", [False, False, False, False])
            self.engine.track_solos = metadata.get("track_solos", [False, False, False, False])
            self.engine.track_monitoring = metadata.get("track_monitoring", [True, True, True, True])
            self.engine.input_gains = metadata.get("input_gains", [1.0, 1.0, 1.0, 1.0])
            self.engine.track_eq_lo = metadata.get("track_eq_lo", [0.0, 0.0, 0.0, 0.0])
            self.engine.track_eq_hi = metadata.get("track_eq_hi", [0.0, 0.0, 0.0, 0.0])
            self.engine.track_tape = metadata.get("track_tape", [False, False, False, False])
            self.engine.track_rev_send = metadata.get("track_rev_send", [0.0, 0.0, 0.0, 0.0])
            self.engine.bus_reverb_type = metadata.get("bus_reverb_type", 0)
            self.engine.bus_reverb_return = metadata.get("bus_reverb_return", 1.0)
            self.engine.track_spread = metadata.get("track_spread", [0, 0, 0, 0])
            self.engine.track_chroma = metadata.get("track_chroma", [0, 0, 0, 0])
            self.engine.track_harmony = metadata.get("track_harmony", [False, False, False, False])
            self.engine.track_harmony_mode = metadata.get("track_harmony_mode", [0, 0, 0, 0])
            self.engine.track_harmony_mix = metadata.get("track_harmony_mix", [0.0, 0.0, 0.0, 0.0])
            self.engine.track_pultec_enabled = metadata.get("track_pultec_enabled", [False, False, False, False])
            self.engine.track_pultec_low_freq = metadata.get("track_pultec_low_freq", [1, 1, 1, 1])
            self.engine.track_pultec_low_boost = metadata.get("track_pultec_low_boost", [0.0, 0.0, 0.0, 0.0])
            self.engine.track_pultec_low_cut = metadata.get("track_pultec_low_cut", [0.0, 0.0, 0.0, 0.0])
            self.engine.track_pultec_high_freq = metadata.get("track_pultec_high_freq", [2, 2, 2, 2])
            self.engine.track_pultec_high_boost = metadata.get("track_pultec_high_boost", [0.0, 0.0, 0.0, 0.0])
            self.engine.track_pultec_high_cut = metadata.get("track_pultec_high_cut", [0.0, 0.0, 0.0, 0.0])
            self.engine.track_pultec_preset = metadata.get("track_pultec_preset", [0, 0, 0, 0])
            
            # Re-initialize harmony objects after load
            for i in range(4):
                if self.engine.track_harmony[i]:
                    self.engine.update_harmony_params(i, True, self.engine.track_harmony_mode[i], self.engine.track_harmony_mix[i])
                
                # Re-initialize Pultec state (reset biquads)
                self.engine.update_pultec_params(
                    i,
                    self.engine.track_pultec_enabled[i],
                    self.engine.track_pultec_low_freq[i],
                    self.engine.track_pultec_low_boost[i],
                    self.engine.track_pultec_low_cut[i],
                    self.engine.track_pultec_high_freq[i],
                    self.engine.track_pultec_high_boost[i],
                    self.engine.track_pultec_high_cut[i],
                    self.engine.track_pultec_preset[i]
                )

            # Load clips
            audio_dir = os.path.join(actual_load_path, "audio")
            
            tracks_meta = metadata.get("tracks", [[], [], [], []])
            for i in range(4):
                self.engine.tracks[i] = []
                if i < len(tracks_meta):
                    for c_meta in tracks_meta[i]:
                        file_path = os.path.join(audio_dir, c_meta["file"])
                        if os.path.exists(file_path):
                            data, sr = sf.read(file_path, dtype='float32')
                            if len(data.shape) > 1: data = data[:, 0] # ensure mono
                            
                            clip = Clip(data, c_meta["start_frame"])
                            clip.id = c_meta["id"]
                            clip.offset_frame = c_meta.get("offset_frame", 0)
                            clip.length_frame = c_meta.get("length_frame", len(data))
                            
                            self.engine.tracks[i].append(clip)
                            
    def bounce_mix(self, output_path, format="WAV"):
        """Bounces all tracks down to stereo via in-memory allocation."""
        max_len = self.engine.get_max_length()
        if max_len == 0:
            raise ValueError("No audio to bounce!")
            
        with self.engine.lock:
            from pedalboard import Reverb, PitchShift, Pedalboard
            from dsp_effects import HARMONY_MODES
            
            # Find maximum needed length across source tracks
            max_len = 0
            for i in range(4):
                for clip in self.engine.tracks[i]:
                    end = clip.absolute_end_frame()
                    if end > max_len:
                        max_len = end
            
            if max_len == 0:
                raise ValueError("No audio to bounce!")
                
            # Append tail time if ANY reverb is present so decay isn't cut off
            has_reverb = any(self.engine.track_rev_send[i] > 0.0 for i in range(4))
            if has_reverb:
                tail_samples = int(self.sample_rate * 3.0)
                max_len += tail_samples

            mixed = np.zeros((max_len, 2), dtype=np.float32)
            bus_send_stereo = np.zeros((max_len, 2), dtype=np.float32)
            any_solo = any(self.engine.track_solos)
            alpha = self.engine._eq_alpha
            t_alpha = self.engine._tape_alpha
            
            for i in range(4):
                if self.engine.track_mutes[i] and not self.engine.track_solos[i]:
                    continue
                if any_solo and not self.engine.track_solos[i]:
                    continue
                    
                track_mono = np.zeros(max_len, dtype=np.float32)
                has_audio = False
                
                for clip in self.engine.tracks[i]:
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
                track_mono *= self.engine.track_volumes[i]
                
                # EQ
                lo_db = self.engine.track_eq_lo[i]
                hi_db = self.engine.track_eq_hi[i]
                if lo_db != 0.0 or hi_db != 0.0:
                    lo_gain = 10.0 ** (lo_db / 20.0)
                    hi_gain = 10.0 ** (hi_db / 20.0)
                    
                    b, a = [alpha], [1.0, alpha - 1.0]
                    bass = signal.lfilter(b, a, track_mono)
                    treble = track_mono - bass
                    track_mono[:] = bass * lo_gain + treble * hi_gain
                
                # Pultec EQ (Offline)
                if self.engine.track_pultec_enabled[i]:
                    track_mono = signal.sosfilt(
                        self.engine._pultec_sos[i],
                        track_mono
                    )
                        
                # Harmony (Bug H1 fix: Route through apply_harmony_offline for correct warmup/reset)
                if self.engine.track_harmony[i] and self.engine.track_harmony_mix[i] > 0:
                    from dsp_effects import apply_harmony_offline
                    track_mono = apply_harmony_offline(
                        track_mono,
                        self.sample_rate,
                        self.engine.track_harmony_mode[i],
                        self.engine.track_harmony_mix[i]
                    )

                # Chroma Glow
                chroma_mode = self.engine.track_chroma[i]
                if chroma_mode > 0:
                    if chroma_mode == 1: # DARK
                        track_mono *= 2.0
                        track_mono = np.arctan(track_mono)
                        a_dark = min(0.99, 2 * np.pi * 1200 / self.sample_rate)
                        b, a = [a_dark], [1.0, a_dark - 1.0]
                        track_mono[:] = signal.lfilter(b, a, track_mono)
                        track_mono *= 1.2
                    elif chroma_mode == 2: # SPARKLE
                        a_high = min(0.99, 2 * np.pi * 6000 / self.sample_rate)
                        b, a = [a_high], [1.0, a_high - 1.0]
                        lp_sig = signal.lfilter(b, a, track_mono)
                        wet_sig = track_mono - lp_sig
                        wet_sig = np.tanh(wet_sig * 4.0)
                        track_mono = track_mono + wet_sig * 0.4
                    elif chroma_mode == 3: # WARM
                        offset = 0.15
                        track_mono = np.tanh(track_mono + offset) - np.tanh(offset)
                        track_mono *= 1.1

                # Tape Saturation
                if self.engine.track_tape[i]:
                    # 1) Aggressive drive — push hard into saturation for compression & grit
                    drive = 3.5
                    track_mono *= drive
                    
                    # 2) Asymmetric soft-clip — adds even harmonics for "analog warmth"
                    asym_offset = 0.2
                    track_mono = np.tanh(track_mono + asym_offset) - np.tanh(asym_offset)
                    
                    # 3) HF rolloff — tape loses sparkle (frequency-dependent compression)
                    b, a = [t_alpha], [1.0, t_alpha - 1.0]
                    track_mono[:] = signal.lfilter(b, a, track_mono)
                        
                    # 4) Makeup gain — compensate for high drive + tanh attenuation
                    track_mono *= 0.75
                    
                # Apply pan and spread to create stereo image
                pan = self.engine.track_pans[i]
                l_gain = min(1.0, 1.0 - pan)
                r_gain = min(1.0, 1.0 + pan)
                track_stereo = np.zeros((max_len, 2), dtype=np.float32)
                
                spread_mode = self.engine.track_spread[i]
                if spread_mode > 0:
                    f1, f2 = (200, 3000) if spread_mode == 1 else (300, 1500) if spread_mode == 2 else (150, 2500)
                    a1 = min(0.99, 2 * np.pi * f1 / self.sample_rate)
                    a2 = min(0.99, 2 * np.pi * f2 / self.sample_rate)
                    lp1, lp2 = 0.0, 0.0
                    for s in range(max_len):
                        val = track_mono[s]
                        lp1 = lp1 + a1 * (val - lp1)
                        lp2 = lp2 + a2 * (val - lp2)
                        low, mid, high = lp1, lp2 - lp1, val - lp2
                        track_stereo[s, 0] = low * 0.707 + mid * 1.0 + high * 0.1
                        track_stereo[s, 1] = low * 0.707 + mid * 0.1 + high * 1.0
                    track_stereo[:, 0] *= l_gain
                    track_stereo[:, 1] *= r_gain
                else:
                    track_stereo[:, 0] = track_mono * l_gain
                    track_stereo[:, 1] = track_mono * r_gain
                
                # Send to bus
                rev_send = self.engine.track_rev_send[i]
                if rev_send > 0.0:
                    bus_send_stereo += track_stereo * rev_send
                    
                mixed += track_stereo

            # Apply bus reverb
            if np.max(np.abs(bus_send_stereo)) > 1e-6:
                reverb_params = self.engine._bus_reverbs.get(self.engine.bus_reverb_type)
                if reverb_params is not None:
                    wet_t = reverb_params.process(bus_send_stereo.T, int(self.sample_rate), reset=True)
                    wet_stereo = wet_t.T
                    mixed += wet_stereo * self.engine.bus_reverb_return

            mixed *= self.engine.master_volume
            mixed = np.clip(mixed, -1.0, 1.0)
        
        # Export
        format = format.upper()
        if format in ["WAV", "FLAC"]:
            sf.write(output_path, mixed, self.sample_rate, format=format)
        elif format == "MP3":
            mixed_16bit = np.int16(mixed * 32767)
            audio_seg = AudioSegment(
                mixed_16bit.tobytes(),
                frame_rate=self.sample_rate,
                sample_width=mixed_16bit.dtype.itemsize,
                channels=2
            )
            audio_seg.export(output_path, format="mp3")
        else:
            raise ValueError(f"Unsupported format: {format}")
