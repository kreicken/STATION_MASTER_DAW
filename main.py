import sys
import os
import logging
from datetime import datetime

def crash_handler(etype, value, tb):
    """Global hook to catch and log unhandled exceptions (Bug fix: communicating jack shit)."""
    import traceback
    from datetime import datetime
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    crash_file = os.path.join(log_dir, "last_crash.log")
    with open(crash_file, "a") as f:
        f.write(f"\n{'='*60}\nCRASH AT {datetime.now()}\n{'='*60}\n")
        traceback.print_exception(etype, value, tb, file=f)
    # Also attempt to log to session if active
    logging.critical("CRASH DETECTED", exc_info=(etype, value, tb))

sys.excepthook = crash_handler

def _setup_asoundrc():
    rc_path = os.path.expanduser("~/.asoundrc")
    content = ""
    if os.path.exists(rc_path):
        with open(rc_path, "r") as f:
            content = f.read()
    changed = False
    for i in range(4):
        dev = f"station_track_{i}_pipe"
        if f"pcm.{dev}" not in content:
            content += f"\n\npcm.{dev} {{\n    type pulse\n    device \"{dev}.monitor\"\n}}\n"
            changed = True
    if "pcm.Asherah_Pipe" not in content:
        content += f"\n\npcm.Asherah_Pipe {{\n    type pulse\n    device \"Asherah_Pipe.monitor\"\n}}\n"
        changed = True
    if changed:
        with open(rc_path, "w") as f:
            f.write(content)

_setup_asoundrc()
import math
import json
import subprocess
import numpy as np
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QVBoxLayout, QInputDialog,
    QHBoxLayout, QWidget, QFrame, QPushButton, QSlider, QDial, QFileDialog,
    QComboBox, QMessageBox, QProgressBar, QScrollArea, QDialog, QCheckBox, QMenu,
    QButtonGroup, QRadioButton
)
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, QThread, pyqtSignal, QSettings
import collections
import soundfile as sf
import sounddevice as sd
from PyQt6.QtGui import QFont, QPainter, QColor, QPen, QBrush, QKeySequence, QShortcut

from audio_engine import AudioEngine, Clip
from project_manager import ProjectManager
from dsp_effects import HARMONY_MODES

class HarmonyWorker(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, engine, track_idx, mode, mix):
        super().__init__()
        self.engine = engine
        self.track_idx = track_idx
        self.mode = mode
        self.mix = mix

    def run(self):
        try:
            from dsp_effects import apply_harmony_offline
            # 1. Snapshot the clips to process
            with self.engine.lock:
                clips = list(self.engine.tracks[self.track_idx])
            
            if not clips:
                self.finished.emit()
                return

            # 2. Process each clip (Destructive)
            for clip in clips:
                # apply_harmony_offline handles the dry/wet mix internally
                processed = apply_harmony_offline(
                    clip.data, 
                    self.engine.sample_rate, 
                    self.mode, 
                    self.mix
                )
                with self.engine.lock:
                    clip.data = processed
            
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

class HarmonyDialog(QDialog):
    def __init__(self, track_idx, engine, current_mode, current_mix, parent=None):
        super().__init__(parent)
        self.track_idx = track_idx
        self.engine = engine
        self.setWindowTitle(f"Harmony Singer - TRK {track_idx + 1}")
        self.setFixedSize(320, 520)
        
        self.mode = current_mode
        self.mix = current_mix
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        
        # 1. Mode Selector
        lbl = QLabel("HARMONY MODE")
        lbl.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        lbl.setStyleSheet("color: #e8a317;")
        layout.addWidget(lbl)
        
        self.mode_group = QButtonGroup(self)
        modes = [
            "1. Higher (3rd up)",
            "2. Lower (4th down)",
            "3. High & Higher (3rd+5th)",
            "4. Low & Lower (4th+6th)",
            "5. High & Low (3rd+4th)",
            "6. Higher & Lower (5th+6th)",
            "7. Octave Up",
            "8. Octave Down"
        ]
        
        for i, text in enumerate(modes):
            rb = QRadioButton(text)
            rb.setFont(QFont("Courier New", 9))
            if i == self.mode:
                rb.setChecked(True)
            self.mode_group.addButton(rb, i)
            layout.addWidget(rb)
            
        layout.addSpacing(5)

        # 2. Dry/Wet Slider
        mix_layout = QVBoxLayout()
        mix_lbl = QLabel("DRY / WET MIX")
        mix_lbl.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        mix_layout.addWidget(mix_lbl)
        
        self.mix_slider = QSlider(Qt.Orientation.Horizontal)
        self.mix_slider.setRange(0, 100)
        self.mix_slider.setValue(int(self.mix * 100))
        self.mix_slider.setStyleSheet("""
            QSlider::groove:horizontal { background: #222; height: 8px; border-radius: 4px; }
            QSlider::handle:horizontal { background: #e8a317; width: 16px; height: 16px; margin: -4px 0; border-radius: 8px; border: 1px solid #fff; }
        """)
        mix_layout.addWidget(self.mix_slider)
        layout.addLayout(mix_layout)
        
        layout.addStretch()

        # 3. Action Buttons
        btn_vbox = QVBoxLayout()
        btn_vbox.setSpacing(8)
        
        self.process_btn = QPushButton("PROCESS CLIPS (Offline)")
        self.process_btn.setFixedHeight(32)
        self.process_btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self.process_btn.setStyleSheet("""
            QPushButton { background-color: #222; color: #e8a317; border: 1px solid #e8a317; border-radius: 4px; }
            QPushButton:hover { background-color: #333; }
            QPushButton:disabled { color: #555; border-color: #444; }
        """)
        self.process_btn.clicked.connect(self._on_process_offline)
        btn_vbox.addWidget(self.process_btn)

        ok_btn = QPushButton("DONE (Real-time)")
        ok_btn.setFixedHeight(32)
        ok_btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        ok_btn.setStyleSheet("""
            QPushButton { background-color: #e8a317; color: #000; border-radius: 4px; }
            QPushButton:hover { background-color: #ffb732; }
        """)
        ok_btn.clicked.connect(self.accept)
        btn_vbox.addWidget(ok_btn)
        
        layout.addLayout(btn_vbox)

    def _on_process_offline(self):
        # Guard: Mode and Mix from UI
        mode = max(0, self.mode_group.checkedId())
        mix = self.mix_slider.value() / 100.0

        reply = QMessageBox.question(
            self, "Destructive Processing",
            "This will apply harmony permanently to all clips on this track. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.No:
            return

        self.process_btn.setEnabled(False)
        self.process_btn.setText("Processing...")
        
        self.worker = HarmonyWorker(self.engine, self.track_idx, mode, mix)
        self.worker.finished.connect(self._on_process_finished)
        self.worker.error.connect(self._on_process_error)
        self.worker.start()

    def _on_process_finished(self):
        self.process_btn.setEnabled(True)
        self.process_btn.setText("PROCESS CLIPS (Destructive)")
        QMessageBox.information(self, "Finished", "Harmony applied to track clips.")
        if self.parent() and hasattr(self.parent(), 'timeline'):
            self.parent().timeline.envelopes.clear()
            self.parent().timeline.update()

    def _on_process_error(self, err_msg):
        self.process_btn.setEnabled(True)
        self.process_btn.setText("PROCESS CLIPS (Destructive)")
        QMessageBox.critical(self, "Error", f"Processing failed: {err_msg}")
        
    def accept(self):
        # NOTE: self.mode_group.checkedId() returns 0-indexed values matching HARMONY_MODES (Bug H7)
        # Bug H5 fix: Guard against -1 if no button is checked
        self.mode = max(0, self.mode_group.checkedId())
        self.mix = self.mix_slider.value() / 100.0
        super().accept()

class PultecPopup(QDialog):
    def __init__(self, track_idx, engine, parent=None):
        super().__init__(parent)
        self.track_idx = track_idx
        self.engine = engine
        self.setWindowTitle(f"Track {track_idx + 1} — Pultec EQ")
        self.setModal(False)           # Non-blocking: user can interact with DAW while open
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowCloseButtonHint
        )
        self.setFixedSize(560, 340)
        self.setStyleSheet("background-color: #1e1e1e; color: #eee;") # Dark panel color
        self._build_ui()
        self._load_state()             # Populate controls from engine state on open

    def _build_ui(self):
        main_vbox = QVBoxLayout(self)
        main_vbox.setContentsMargins(15, 15, 15, 15)
        main_vbox.setSpacing(10)
        
        # Top Row: Preset and Enabled
        top_row = QHBoxLayout()
        
        self.preset_combo = QComboBox()
        self.preset_combo.setFont(QFont("Courier New", 9))
        self.preset_combo.addItem("Flat") # Index 0
        from audio_engine import PULTEC_PRESETS
        for i in range(1, 19):
            self.preset_combo.addItem(PULTEC_PRESETS[i]["name"])
        self.preset_combo.currentIndexChanged.connect(self._apply_preset)
        top_row.addWidget(self.preset_combo)
        
        top_row.addStretch()
        
        title = QLabel(f"PULTEC EQ — Track {self.track_idx + 1}")
        title.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        title.setStyleSheet("color: #e8a317;")
        top_row.addWidget(title)
        
        top_row.addStretch()
        
        self.enabled_btn = QPushButton("EQ ON")
        self.enabled_btn.setCheckable(True)
        self.enabled_btn.setFixedSize(80, 26)
        self.enabled_btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self.enabled_btn.setStyleSheet("""
            QPushButton { background-color: #333; color: gray; border: 1px solid #555; }
            QPushButton:checked {
                background-color: #e8a317; color: black;
                border: 2px solid white;
            }
        """)
        self.enabled_btn.clicked.connect(self._send_to_engine)
        top_row.addWidget(self.enabled_btn)
        
        main_vbox.addLayout(top_row)
        
        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("background-color: #444;")
        main_vbox.addWidget(line)
        
        # Sections
        sections_layout = QHBoxLayout()
        sections_layout.setSpacing(20)
        
        # --- LOW SECTION ---
        low_vbox = QVBoxLayout()
        low_vbox.addWidget(self._create_section_label("LOW SECTION"))
        
        # Freq selector
        low_freq_layout = QHBoxLayout()
        low_freq_layout.addStretch()
        self.low_freq_group = QButtonGroup(self)
        self.low_freq_group.setExclusive(True)
        
        low_freq_grid_layout = QVBoxLayout()
        r1 = QHBoxLayout()
        r2 = QHBoxLayout()
        for i, label in enumerate(["30", "60", "100", "200"]):
            btn = self._create_freq_btn(label)
            self.low_freq_group.addButton(btn, i)
            if i < 2: r1.addWidget(btn)
            else: r2.addWidget(btn)
        low_freq_grid_layout.addLayout(r1)
        low_freq_grid_layout.addLayout(r2)
        low_freq_layout.addLayout(low_freq_grid_layout)
        low_freq_layout.addStretch()
        low_vbox.addLayout(low_freq_layout)
        
        low_vbox.addSpacing(10)
        
        # Knobs
        low_knobs = QHBoxLayout()
        self.low_boost_knob = self._create_pultec_knob("BOOST", 0, 15)
        self.low_cut_knob = self._create_pultec_knob("CUT", 0, 15)
        low_knobs.addLayout(self.low_boost_knob['layout'])
        low_knobs.addLayout(self.low_cut_knob['layout'])
        low_vbox.addLayout(low_knobs)
        
        sections_layout.addLayout(low_vbox)
        
        # Vertical Divider
        v_line = QFrame()
        v_line.setFrameShape(QFrame.Shape.VLine)
        v_line.setFrameShadow(QFrame.Shadow.Sunken)
        v_line.setStyleSheet("background-color: #444;")
        sections_layout.addWidget(v_line)
        
        # --- HIGH SECTION ---
        high_vbox = QVBoxLayout()
        high_vbox.addWidget(self._create_section_label("HIGH SECTION"))
        
        # Freq selector
        high_freq_layout = QHBoxLayout()
        high_freq_layout.addStretch()
        self.high_freq_group = QButtonGroup(self)
        self.high_freq_group.setExclusive(True)
        for i, label in enumerate(["3k", "5k", "8k", "12k", "16k"]):
            btn = self._create_freq_btn(label)
            self.high_freq_group.addButton(btn, i)
            high_freq_layout.addWidget(btn)
        high_freq_layout.addStretch()
        high_vbox.addLayout(high_freq_layout)
        
        high_vbox.addSpacing(10)
        
        # Knobs
        high_knobs = QHBoxLayout()
        self.high_boost_knob = self._create_pultec_knob("BOOST", 0, 12)
        self.high_cut_knob = self._create_pultec_knob("CUT", 0, 12)
        high_knobs.addLayout(self.high_boost_knob['layout'])
        high_knobs.addLayout(self.high_cut_knob['layout'])
        high_vbox.addLayout(high_knobs)
        
        sections_layout.addLayout(high_vbox)
        
        main_vbox.addLayout(sections_layout)
        
        # Connect signals
        self.low_freq_group.idClicked.connect(self._send_to_engine)
        self.high_freq_group.idClicked.connect(self._send_to_engine)
        self.low_boost_knob['dial'].valueChanged.connect(self._send_to_engine)
        self.low_cut_knob['dial'].valueChanged.connect(self._send_to_engine)
        self.high_boost_knob['dial'].valueChanged.connect(self._send_to_engine)
        self.high_cut_knob['dial'].valueChanged.connect(self._send_to_engine)

    def _create_section_label(self, text):
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        lbl.setStyleSheet("color: #888;")
        return lbl

    def _create_freq_btn(self, text):
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setFixedSize(42, 24)
        btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        btn.setStyleSheet("""
            QPushButton { background-color: #2a2a2a; color: #777; border: 1px solid #444; }
            QPushButton:checked { background-color: #e8a317; color: black; border: 1px solid #fff; }
        """)
        return btn

    def _create_pultec_knob(self, label_text, min_v, max_v):
        layout = QVBoxLayout()
        layout.setSpacing(2)
        lbl = QLabel(label_text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        lbl.setStyleSheet("color: #aaa;")
        layout.addWidget(lbl)
        
        dial = StyledDial()
        dial.setRange(int(min_v * 10), int(max_v * 10))
        dial.setFixedSize(72, 72)
        layout.addWidget(dial, 0, Qt.AlignmentFlag.AlignCenter)
        
        val_lbl = QLabel("0.0 dB")
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        val_lbl.setFont(QFont("Courier New", 8))
        val_lbl.setStyleSheet("color: #e8a317;")
        layout.addWidget(val_lbl)
        
        def update_lbl(v):
            val_lbl.setText(f"{v/10.0:+.1f} dB")
        dial.valueChanged.connect(update_lbl)
        
        return {'layout': layout, 'dial': dial, 'label': val_lbl}

    def _load_state(self):
        # Block signals while loading to prevent re-sending (Bug P5 fix: block before set)
        self.enabled_btn.blockSignals(True)
        self.low_freq_group.blockSignals(True)
        self.high_freq_group.blockSignals(True)
        self.low_boost_knob['dial'].blockSignals(True)
        self.low_cut_knob['dial'].blockSignals(True)
        self.high_boost_knob['dial'].blockSignals(True)
        self.high_cut_knob['dial'].blockSignals(True)
        self.preset_combo.blockSignals(True)

        with self.engine.lock:
            enabled = self.engine.track_pultec_enabled[self.track_idx]
            lf = self.engine.track_pultec_low_freq[self.track_idx]
            lb = self.engine.track_pultec_low_boost[self.track_idx]
            lc = self.engine.track_pultec_low_cut[self.track_idx]
            hf = self.engine.track_pultec_high_freq[self.track_idx]
            hb = self.engine.track_pultec_high_boost[self.track_idx]
            hc = self.engine.track_pultec_high_cut[self.track_idx]
            preset = self.engine.track_pultec_preset[self.track_idx]
            
        self.enabled_btn.setChecked(enabled)

        if self.low_freq_group.button(lf):
            self.low_freq_group.button(lf).setChecked(True)
        self.low_boost_knob['dial'].setValue(int(lb * 10))
        self.low_cut_knob['dial'].setValue(int(lc * 10))
        if self.high_freq_group.button(hf):
            self.high_freq_group.button(hf).setChecked(True)
        self.high_boost_knob['dial'].setValue(int(hb * 10))
        self.high_cut_knob['dial'].setValue(int(hc * 10))
        self.preset_combo.setCurrentIndex(preset)
        
        self.enabled_btn.blockSignals(False)
        self.low_freq_group.blockSignals(False)
        self.high_freq_group.blockSignals(False)
        self.low_boost_knob['dial'].blockSignals(False)
        self.low_cut_knob['dial'].blockSignals(False)
        self.high_boost_knob['dial'].blockSignals(False)
        self.high_cut_knob['dial'].blockSignals(False)
        self.preset_combo.blockSignals(False)

    def _apply_preset(self, preset_idx):
        from audio_engine import PULTEC_PRESETS
        if preset_idx == 0:
            p = {"lf":1, "lb":0.0, "lc":0.0, "hf":2, "hb":0.0, "hc":0.0}
        else:
            p = PULTEC_PRESETS[preset_idx]
            
        # Temporarily disconnect to avoid multiple engine updates
        self.low_boost_knob['dial'].blockSignals(True)
        self.low_cut_knob['dial'].blockSignals(True)
        self.high_boost_knob['dial'].blockSignals(True)
        self.high_cut_knob['dial'].blockSignals(True)
        self.low_freq_group.blockSignals(True)
        self.high_freq_group.blockSignals(True)
        
        if self.low_freq_group.button(p['lf']):
            self.low_freq_group.button(p['lf']).setChecked(True)
        self.low_boost_knob['dial'].setValue(int(p['lb'] * 10))
        self.low_cut_knob['dial'].setValue(int(p['lc'] * 10))
        if self.high_freq_group.button(p['hf']):
            self.high_freq_group.button(p['hf']).setChecked(True)
        self.high_boost_knob['dial'].setValue(int(p['hb'] * 10))
        self.high_cut_knob['dial'].setValue(int(p['hc'] * 10))
        
        self.low_boost_knob['dial'].blockSignals(False)
        self.low_cut_knob['dial'].blockSignals(False)
        self.high_boost_knob['dial'].blockSignals(False)
        self.high_cut_knob['dial'].blockSignals(False)
        self.low_freq_group.blockSignals(False)
        self.high_freq_group.blockSignals(False)
        
        # Enable EQ if any non-zero value was loaded, else disable (Bug P4 fix)
        any_active = any(p[k] > 0.0 for k in ('lb','lc','hb','hc'))
        self.enabled_btn.setChecked(any_active)
            
        self._send_to_engine()

    def _send_to_engine(self):
        enabled = self.enabled_btn.isChecked()
        self.engine.update_pultec_params(
            self.track_idx,
            enabled    = enabled,
            low_freq   = self.low_freq_group.checkedId(),
            low_boost  = self.low_boost_knob['dial'].value() / 10.0,
            low_cut    = self.low_cut_knob['dial'].value() / 10.0,
            high_freq  = self.high_freq_group.checkedId(),
            high_boost = self.high_boost_knob['dial'].value() / 10.0,
            high_cut   = self.high_cut_knob['dial'].value() / 10.0,
            preset     = self.preset_combo.currentIndex(),
        )
        if self.parent() and hasattr(self.parent(), 'track_strips'):
            ts = self.parent().track_strips[self.track_idx]
            ts.eq_btn.blockSignals(True)
            ts.eq_btn.setChecked(enabled)
            ts.eq_btn.blockSignals(False)


# --- CONSTANTS ---
DEFAULT_PPS = 50.0  # Default pixels per second
TRACK_HEIGHT = 160
TIMELINE_Y_OFFSET = 30 # space for ruler
MIN_TIMELINE_SECS = 120 # Always show at least 2 minutes

class StyledDial(QDial):
    def paintEvent(self, event):
        painter = QPainter(self)
        with painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            rect = self.rect()
            center = rect.center()
            radius = int(min(rect.width(), rect.height()) / 2 - 2)
            
            # Draw background base (grey knob)
            painter.setBrush(QColor("#555555"))
            painter.setPen(QPen(QColor("#222222"), 2))
            painter.drawEllipse(center, radius, radius)
            
            val = self.value()
            min_val = self.minimum()
            max_val = self.maximum()
            
            ratio = (val - min_val) / (max_val - min_val) if max_val > min_val else 0
            angle = -135 + (ratio * 270)
            
            painter.setPen(QPen(QColor("green"), max(2, int(radius/5)), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            rad_angle = math.radians(angle - 90) 
            
            p1_x = center.x() + math.cos(rad_angle) * (radius * 0.3)
            p1_y = center.y() + math.sin(rad_angle) * (radius * 0.3)
            
            p2_x = center.x() + math.cos(rad_angle) * (radius * 0.8)
            p2_y = center.y() + math.sin(rad_angle) * (radius * 0.8)
            
            painter.drawLine(int(p1_x), int(p1_y), int(p2_x), int(p2_y))


class TimelineWidget(QWidget):
    def __init__(self, engine, parent_ui):
        super().__init__()
        self.engine = engine
        self.parent_ui = parent_ui
        self.pps = DEFAULT_PPS
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.selected_clip = None
        self.dragging_clip = None
        self.drag_start_frame = 0
        self.drag_offset = 0
        self._scrubbing = False
        self._crop_clip = None    # Clip being edge-cropped (non-destructive)
        self._crop_edge = None    # 'left' or 'right'
        self._crop_track = None
        self.envelopes = {}  # Widget-level cache invalidation dict (cleared on clip changes)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        self.setMinimumWidth(800)
        self.setMinimumHeight(TRACK_HEIGHT * 4 + TIMELINE_Y_OFFSET + 20)

    def _update_size(self):
        """Resize canvas width to fit the furthest clip end (or MIN_TIMELINE_SECS minimum)."""
        max_frame = self.engine.get_max_length()
        # During recording the buffer isn't committed yet, so also track the playhead position
        if self.engine.is_recording:
            max_frame = max(max_frame, self.engine.current_frame)
        total_secs = max(MIN_TIMELINE_SECS, max_frame / self.engine.sample_rate + 10)
        new_w = max(800, int(total_secs * self.pps))
        if new_w != self.width():
            self.resize(new_w, self.height())

    def _frame_to_x(self, frame):
        return (frame / self.engine.sample_rate) * self.pps

    def _x_to_frame(self, x):
        return int((x / self.pps) * self.engine.sample_rate)

    def _get_envelope(self, clip):
        # Dummy envelope for rendering
        if not hasattr(clip, "_envelope_cache"):
            n = 100
            data = clip.data
            if len(data) == 0: return []
            step = len(data) // n
            if step == 0: step = 1
            env = []
            for i in range(0, len(data), step):
                chunk = data[i:i+step]
                if len(chunk) > 0:
                    env.append((float(np.min(chunk)), float(np.max(chunk))))
            clip._envelope_cache = env
        return clip._envelope_cache

    def paintEvent(self, event):
        painter = QPainter(self)
        with painter:
            painter.fillRect(self.rect(), QColor("#111111"))
            
            # Draw Ruler
            painter.setPen(QPen(QColor("gray"), 1))
            painter.drawLine(0, TIMELINE_Y_OFFSET, self.width(), TIMELINE_Y_OFFSET)
            
            # Draw Loop Region
            lx1 = self._frame_to_x(self.engine.loop_start_frame)
            lx2 = self._frame_to_x(self.engine.loop_end_frame)
            loop_rect = QRectF(lx1, 0, lx2 - lx1, TIMELINE_Y_OFFSET)
            if self.engine.loop_enabled:
                painter.fillRect(loop_rect, QColor(150, 0, 150, 60))
            else:
                painter.fillRect(loop_rect, QColor(100, 100, 100, 30))
            
            # Draw loop brackets
            painter.setPen(QPen(QColor("#ff00ff" if self.engine.loop_enabled else "#666"), 2))
            painter.drawLine(int(lx1), 0, int(lx1), TIMELINE_Y_OFFSET)
            painter.drawLine(int(lx2), 0, int(lx2), TIMELINE_Y_OFFSET)
            painter.drawLine(int(lx1), 0, int(lx1 + 5), 0)
            painter.drawLine(int(lx2), 0, int(lx2 - 5), 0)
            
            total_secs = int(self.width() / self.pps) + 10
            x = 0
            for i in range(total_secs):
                x = int(i * self.pps)
                if i % 5 == 0:
                    painter.drawLine(x, int(TIMELINE_Y_OFFSET - 15), x, TIMELINE_Y_OFFSET)
                    mins = i // 60
                    secs = i % 60
                    painter.setPen(QColor("green"))
                    painter.drawText(x + 2, int(TIMELINE_Y_OFFSET - 5), f"{mins}:{secs:02d}")
                    painter.setPen(QColor("gray"))
                else:
                    painter.drawLine(x, int(TIMELINE_Y_OFFSET - 5), x, TIMELINE_Y_OFFSET)
                
            painter.setPen(QPen(QColor("#222"), 1))
            painter.drawLine(self.width() - 1, TIMELINE_Y_OFFSET, self.width() - 1, self.height())
            
            # Draw Tracks
            font = QFont("Courier New", 10)
            painter.setFont(font)
            for i in range(4):
                y_top = TIMELINE_Y_OFFSET + i * TRACK_HEIGHT
                if i % 2 == 1:
                    painter.fillRect(0, int(y_top), self.width(), TRACK_HEIGHT, QColor("#181818"))
                    
                painter.setPen(QPen(QColor("#444"), 1))
                painter.drawLine(0, int(y_top + TRACK_HEIGHT), self.width(), int(y_top + TRACK_HEIGHT))
                
                # Draw Clips
                if self.engine.lock.acquire(blocking=False):
                    try:
                        track_clips_snapshot = list(self.engine.tracks[i])
                    finally:
                        self.engine.lock.release()
                else:
                    track_clips_snapshot = list(self.engine._active_track_buf[i])
                    
                for clip in track_clips_snapshot:
                    x1 = self._frame_to_x(clip.start_frame)
                    x2 = self._frame_to_x(clip.absolute_end_frame())
                    w = max(2, x2 - x1)
                    
                    rect = QRectF(x1, y_top + 10, w, TRACK_HEIGHT - 20)
                    painter.setBrush(QBrush(QColor("#003333")))
                    
                    if clip == self.selected_clip:
                        painter.setPen(QPen(QColor("green"), 2))  # Green highlight for selection
                        painter.setBrush(QBrush(QColor("#1a3333")))
                    elif clip == self.dragging_clip:
                        painter.setPen(QPen(QColor("white"), 2))
                    else:
                        painter.setPen(QPen(QColor("teal"), 1))
                        
                    painter.drawRect(rect)
                    
                    env = self._get_envelope(clip)
                    if env:
                        painter.setPen(QPen(QColor("green"), 1))
                        chunk_px = w / len(env)
                        cy = y_top + TRACK_HEIGHT / 2
                        half_h = (TRACK_HEIGHT - 22) / 2
                        
                        for e_i, (c_min, c_max) in enumerate(env):
                            px = x1 + e_i * chunk_px
                            py1 = cy - (c_max * half_h)
                            py2 = cy - (c_min * half_h)
                            painter.drawLine(int(px), int(py1), int(px), int(py2))

                # Draw active recording indicator
                if self.engine.is_recording and self.engine.armed_track == i:
                    rec_x1 = self._frame_to_x(self.engine.record_start_frame)
                    rec_x2 = self._frame_to_x(self.engine.current_frame)
                    rec_w = max(2, rec_x2 - rec_x1)
                    
                    rec_rect = QRectF(rec_x1, y_top + 10, rec_w, TRACK_HEIGHT - 20)
                    
                    painter.setBrush(QBrush(QColor(150, 0, 0, 150))) # Semi-transparent red
                    painter.setPen(QPen(QColor("red"), 2))
                    painter.drawRect(rec_rect)
                    
                    painter.setPen(QColor("white"))
                    painter.drawText(rec_rect, Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter, "RECORDING")

            # Playhead
            ph_x = self._frame_to_x(self.engine.current_frame)
            painter.setPen(QPen(QColor("red"), 2))
            painter.drawLine(int(ph_x), 0, int(ph_x), self.height())
            
            poly = [QPointF(ph_x-6, 0), QPointF(ph_x+6, 0), QPointF(ph_x, 12)]
            painter.setBrush(QBrush(QColor("red")))
            painter.drawPolygon(poly)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            
    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if not urls: return
        
        y = event.position().y() - TIMELINE_Y_OFFSET
        track_idx = int(y // TRACK_HEIGHT)
        if track_idx < 0 or track_idx >= 4:
            return
            
        frame = self._x_to_frame(max(0, event.position().x()))
        
        for url in urls:
            path = url.toLocalFile()
            if path.lower().endswith((".wav", ".mp3", ".flac")):
                try:
                    import soundfile as sf
                    import numpy as np
                    data, sr = sf.read(path, dtype="float32")
                    if len(data.shape) > 1:
                        data = data[:, 0]
                    
                    if sr != self.engine.sample_rate:
                        duration = len(data) / sr
                        new_len = int(duration * self.engine.sample_rate)
                        old_indices = np.linspace(0, len(data)-1, len(data))
                        new_indices = np.linspace(0, len(data)-1, new_len)
                        data = np.interp(new_indices, old_indices, data).astype(np.float32)
                        
                    from audio_engine import Clip
                    clip = Clip(data, max(0, frame))
                    with self.engine.lock:
                        self.engine.tracks[track_idx].append(clip)
                        
                    self.parent_ui._push_undo_snapshot()
                    self.update()
                except Exception as e:
                    from PyQt6.QtWidgets import QMessageBox
                    QMessageBox.warning(self, "Import Error", f"Failed to load {os.path.basename(path)}:\n{e}")
                break

    def _clip_at(self, x, y):
        """Return (track_idx, clip) under pixel (x, y), or (None, None)."""
        if y < TIMELINE_Y_OFFSET:
            return None, None
        track_idx = int((y - TIMELINE_Y_OFFSET) // TRACK_HEIGHT)
        if track_idx < 0 or track_idx >= 4:
            return None, None
        frame = self._x_to_frame(x)
        with self.engine.lock:
            for clip in self.engine.tracks[track_idx]:
                if clip.start_frame <= frame <= clip.absolute_end_frame():
                    return track_idx, clip
        return track_idx, None

    def _do_seek(self, x):
        """Seek the playhead to pixel x. Works whether the transport is playing or stopped."""
        seek_frame = max(0, self._x_to_frame(x))
        # Set current_frame directly for immediate visual feedback when stopped.
        # _seek_request is consumed by the callback to re-sync when the stream is running.
        self.engine.current_frame = seek_frame
        self.engine._seek_request = seek_frame
        self.update()

    def mousePressEvent(self, event):
        x = event.position().x()
        y = event.position().y()

        # ── Ruler click → scrub start ─────────────────────────────────
        if y < TIMELINE_Y_OFFSET:
            self._scrubbing = True
            self._do_seek(x)
            return

        # ── Playhead grab in track area (within ±8px of the line) ─────
        ph_x = self._frame_to_x(self.engine.current_frame)
        if abs(x - ph_x) <= 8:
            self._scrubbing = True
            self._do_seek(x)
            return

        track_idx, clip = self._clip_at(x, y)

        if event.button().name == "RightButton":
            # Right-click on clip → delete
            if clip is not None:
                with self.engine.lock:
                    try:
                        self.engine.tracks[track_idx].remove(clip)
                    except ValueError:
                        pass
                if self.selected_clip is clip:
                    self.selected_clip = None
                self.parent_ui._push_undo_snapshot()
                self.update()
            return

        # Left-click on a clip → check for edge-crop before body-drag
        if clip is not None:
            self.selected_clip = clip
            self.setFocus()  # Claim keyboard focus so Backspace/Delete is delivered here
            clip_x1 = self._frame_to_x(clip.start_frame)
            clip_x2 = self._frame_to_x(clip.absolute_end_frame())
            EDGE_PX = 8
            if abs(x - clip_x1) <= EDGE_PX:
                # Left-edge crop
                self._crop_clip = clip
                self._crop_edge = 'left'
                self._crop_track = track_idx
            elif abs(x - clip_x2) <= EDGE_PX:
                # Right-edge crop
                self._crop_clip = clip
                self._crop_edge = 'right'
                self._crop_track = track_idx
            else:
                # Body drag → move
                self.dragging_clip = clip
                self._drag_track = track_idx
                self.drag_offset = self._x_to_frame(x) - clip.start_frame
        else:
            # Click on empty space → deselect
            self.selected_clip = None
            self.dragging_clip = None

        self.update()

    def mouseMoveEvent(self, event):
        x = event.position().x()
        y = event.position().y()

        # Playhead scrub takes priority
        if self._scrubbing:
            self._do_seek(x)
            return

        # Active crop drag
        if self._crop_clip is not None:
            frame = self._x_to_frame(x)
            clip = self._crop_clip
            with self.engine.lock:
                if self._crop_edge == 'left':
                    # Clamp: cannot go past the clip's original data start or past right edge
                    max_offset = clip.offset_frame + clip.length_frame - 1
                    new_offset = max(0, min(frame - clip.start_frame + clip.offset_frame, max_offset))
                    delta = new_offset - clip.offset_frame
                    clip.offset_frame = new_offset
                    clip.start_frame = max(0, clip.start_frame + delta)
                    clip.length_frame = max(1, clip.length_frame - delta)
                else:  # 'right'
                    # Clamp: cannot extend past raw data, cannot shrink below 1 frame
                    max_len = len(clip.data) - clip.offset_frame
                    new_len = max(1, min(frame - clip.start_frame, max_len))
                    clip.length_frame = new_len
            self.update()
            return

        # Active body drag
        if self.dragging_clip is not None:
            new_start = max(0, self._x_to_frame(x) - self.drag_offset)
            with self.engine.lock:
                self.dragging_clip.start_frame = new_start
            self.update()
            return

        # No drag active — update cursor based on hover position
        _, hover_clip = self._clip_at(x, y)
        if hover_clip is not None:
            EDGE_PX = 8
            clip_x1 = self._frame_to_x(hover_clip.start_frame)
            clip_x2 = self._frame_to_x(hover_clip.absolute_end_frame())
            if abs(x - clip_x1) <= EDGE_PX or abs(x - clip_x2) <= EDGE_PX:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if self._scrubbing:
            self._scrubbing = False
            self.update()
            return
        if self._crop_clip is not None:
            self._crop_clip = None
            self._crop_edge = None
            self._crop_track = None
            self.parent_ui._push_undo_snapshot()
            self.update()
            return
        if self.dragging_clip is not None:
            self.dragging_clip = None
            self.parent_ui._push_undo_snapshot()
            self.update()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            if self.selected_clip is not None:
                clip = self.selected_clip
                # Find which track owns this clip and remove it
                with self.engine.lock:
                    for track in self.engine.tracks:
                        try:
                            track.remove(clip)
                            break
                        except ValueError:
                            pass
                self.selected_clip = None
                self.parent_ui._push_undo_snapshot()
                self.update()
        else:
            super().keyPressEvent(event)

class LevelMeter(QWidget):
    """A custom-painted horizontal level meter with clipping indicator."""
    def __init__(self):
        super().__init__()
        self.level = 0.0
        self.clipping = False
        self.setFixedHeight(32)
        self.setMinimumWidth(80)
        
    def set_level(self, level, clipping):
        self.level = min(level, 1.5)  # cap display at 1.5
        self.clipping = clipping
        self.update()
        
    def paintEvent(self, event):
        p = QPainter(self)
        with p:
            p.fillRect(self.rect(), QColor("#000"))
            
            h = self.height()
            w = self.width()
            
            # Draw meter fill
            fill_w = int(min(self.level, 1.0) * w)
            if fill_w > 0:
                # Color gradient: green -> yellow -> red
                if self.level < 0.6:
                    color = QColor("#00FF00")
                elif self.level < 0.85:
                    color = QColor("#FFFF00")
                else:
                    color = QColor("#FF0000")
                p.fillRect(0, 0, fill_w, h, color)
            
            # Clipping indicator at right
            if self.clipping:
                p.fillRect(w - 4, 0, 4, h, QColor("#FF0000"))
            
            # Border
            p.setPen(QPen(QColor("#555"), 1))
            p.drawRect(0, 0, w - 1, h - 1)

class SynthWaveformWidget(QWidget):
    """Oscilloscope display + preset name overlay for tethered synth tracks."""
    def __init__(self):
        super().__init__()
        self.waveform = [0.0] * 64
        self.preset_name = "(none)"
        self.setFixedHeight(32)
        self.setMinimumWidth(80)

    def update_state(self, preset, waveform):
        self.preset_name = preset
        self.waveform = waveform
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        with p:
            p.fillRect(self.rect(), QColor("#000"))
            w, h = self.width(), self.height()
            mid = h / 2.0

            # Draw waveform
            p.setPen(QPen(QColor("#00d4aa"), 1))
            pts = len(self.waveform)
            if pts > 1:
                step = w / (pts - 1)
                for i in range(pts - 1):
                    x1 = int(i * step)
                    y1 = int(mid - self.waveform[i] * mid * 0.9)
                    x2 = int((i + 1) * step)
                    y2 = int(mid - self.waveform[i + 1] * mid * 0.9)
                    p.drawLine(x1, y1, x2, y2)

            # Preset name overlay
            p.setPen(QColor("#e8a317"))
            p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            p.drawText(4, h - 4, self.preset_name[:24])

            # Border
            p.setPen(QPen(QColor("#00a080"), 1))
            p.drawRect(0, 0, w - 1, h - 1)


class TrackStrip(QFrame):
    def __init__(self, track_index, engine, parent_ui):
        super().__init__()
        self.idx = track_index
        self.engine = engine
        self.parent_ui = parent_ui
        self.synth_mode = None  # None, 'golden_bull', 'asherah'

        # Set fixed height to exactly match the timeline tracks
        self.setFixedHeight(TRACK_HEIGHT)
        self.setFixedWidth(560)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 4, 6, 4)
        main_layout.setSpacing(4)

        # ── Source Selector Row ───────────────────────────────────────
        src_row = QHBoxLayout()
        src_lbl = QLabel("SRC:")
        src_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        src_row.addWidget(src_lbl)
        self.src_combo = QComboBox()
        self.src_combo.setFont(QFont("Courier New", 8))
        self.src_combo.setMinimumWidth(150)
        self.src_combo.currentIndexChanged.connect(self._on_source_changed)
        src_row.addWidget(self.src_combo)
        
        self.mon_btn = QPushButton("MON")
        self.mon_btn.setCheckable(True)
        self.mon_btn.setChecked(True)
        self.mon_btn.setFixedSize(70, 24)
        self.mon_btn.clicked.connect(self._on_mon)
        self.mon_btn.setStyleSheet("""
            QPushButton { color: gray; }
            QPushButton:checked {
                background-color: #004400; color: #00ff00;
                border: 2px solid gray; font-weight: bold;
            }
        """)
        src_row.addWidget(self.mon_btn)
        
        src_row.addStretch()
        main_layout.addLayout(src_row)

        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(10) # Closer fit for buttons and knobs
        
        # Left side: Buttons & Dials
        col1 = QVBoxLayout()
        col1.setSpacing(4)
        self.title_label = QLabel(f"TRK {self.idx + 1}")
        self.title_label.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        col1.addWidget(self.title_label)
        
        self.arm_btn = QPushButton("REC ARM")
        self.arm_btn.setCheckable(True)
        self.arm_btn.setFixedWidth(85)
        self.arm_btn.setFixedHeight(30)
        self.arm_btn.clicked.connect(self._on_arm)
        col1.addWidget(self.arm_btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        ms_layout = QHBoxLayout()
        self.mute_btn = QPushButton("M")
        self.mute_btn.setCheckable(True)
        self.mute_btn.setFixedSize(40, 30)
        self.mute_btn.clicked.connect(self._on_mute)
        self.solo_btn = QPushButton("S")
        self.solo_btn.setCheckable(True)
        self.solo_btn.setFixedSize(40, 30)
        self.solo_btn.clicked.connect(self._on_solo)
        ms_layout.addWidget(self.mute_btn)
        ms_layout.addWidget(self.solo_btn)
        col1.addLayout(ms_layout)
        
        controls_layout.addLayout(col1)
        
        # Consistent spacing for the knob group
        knobs_layout = QHBoxLayout()
        knobs_layout.setSpacing(15) # Compact but readable
        
        # Input Gain knob
        self.gain_col_widget = QWidget()
        gain_col = QVBoxLayout(self.gain_col_widget)
        gain_col.setSpacing(2)
        gain_col.setContentsMargins(0, 0, 0, 0)
        gain_col.addWidget(self.create_label("IN GAIN"), 0, Qt.AlignmentFlag.AlignCenter)
        self.gain_val_lbl = self.create_value_label("0")
        gain_col.addWidget(self.gain_val_lbl, 0, Qt.AlignmentFlag.AlignCenter)
        self.gain_dial = StyledDial()
        self.gain_dial.setRange(-50, 50)
        self.gain_dial.setValue(0)
        self.gain_dial.setFixedSize(38, 38)
        self.gain_dial.valueChanged.connect(self._on_gain)
        gain_col.addWidget(self.gain_dial, 0, Qt.AlignmentFlag.AlignCenter)
        knobs_layout.addWidget(self.gain_col_widget)

        # PAN knob
        col_pan = QVBoxLayout()
        col_pan.setSpacing(2)
        col_pan.addWidget(self.create_label("PAN"), 0, Qt.AlignmentFlag.AlignCenter)
        self.pan_val_lbl = self.create_value_label("0")
        col_pan.addWidget(self.pan_val_lbl, 0, Qt.AlignmentFlag.AlignCenter)
        self.pan_dial = StyledDial()
        self.pan_dial.setRange(-50, 50)
        self.pan_dial.setValue(0)
        self.pan_dial.setFixedSize(38, 38)
        self.pan_dial.valueChanged.connect(self._on_pan)
        col_pan.addWidget(self.pan_dial, 0, Qt.AlignmentFlag.AlignCenter)
        knobs_layout.addLayout(col_pan)
        
        # HI EQ
        col_hi = QVBoxLayout()
        col_hi.setSpacing(2)
        col_hi.addWidget(self.create_label("HI EQ"), 0, Qt.AlignmentFlag.AlignCenter)
        self.hi_val_lbl = self.create_value_label("0")
        col_hi.addWidget(self.hi_val_lbl, 0, Qt.AlignmentFlag.AlignCenter)
        self.hi_dial = StyledDial()
        self.hi_dial.setRange(-50, 50)
        self.hi_dial.setValue(0)
        self.hi_dial.setFixedSize(38, 38)
        self.hi_dial.valueChanged.connect(self._on_eq_hi)
        col_hi.addWidget(self.hi_dial, 0, Qt.AlignmentFlag.AlignCenter)
        knobs_layout.addLayout(col_hi)
        
        # LO EQ
        col_lo = QVBoxLayout()
        col_lo.setSpacing(2)
        col_lo.addWidget(self.create_label("LO EQ"), 0, Qt.AlignmentFlag.AlignCenter)
        self.lo_val_lbl = self.create_value_label("0")
        col_lo.addWidget(self.lo_val_lbl, 0, Qt.AlignmentFlag.AlignCenter)
        self.lo_dial = StyledDial()
        self.lo_dial.setRange(-50, 50)
        self.lo_dial.setValue(0)
        self.lo_dial.setFixedSize(38, 38)
        self.lo_dial.valueChanged.connect(self._on_eq_lo)
        col_lo.addWidget(self.lo_dial, 0, Qt.AlignmentFlag.AlignCenter)
        knobs_layout.addLayout(col_lo)

        # REVERB
        col_rev = QVBoxLayout()
        col_rev.setSpacing(2)
        col_rev.addWidget(self.create_label("REVERB"), 0, Qt.AlignmentFlag.AlignCenter)
        self.rev_val_lbl = self.create_value_label("0")
        col_rev.addWidget(self.rev_val_lbl, 0, Qt.AlignmentFlag.AlignCenter)
        self.rev_dial = StyledDial()
        self.rev_dial.setRange(0, 99)
        self.rev_dial.setFixedSize(38, 38)
        self.rev_dial.valueChanged.connect(self._on_rev)
        col_rev.addWidget(self.rev_dial, 0, Qt.AlignmentFlag.AlignCenter)
        knobs_layout.addLayout(col_rev)
        
        # Initialize value labels
        self.gain_val_lbl.setText(str(self.gain_dial.value()))
        self.pan_val_lbl.setText(str(self.pan_dial.value()))
        self.hi_val_lbl.setText(str(self.hi_dial.value()))
        self.lo_val_lbl.setText(str(self.lo_dial.value()))
        self.rev_val_lbl.setText(str(self.rev_dial.value()))
        
        controls_layout.addLayout(knobs_layout)
        
        # Space before buttons
        controls_layout.addSpacing(12)
        
        col4_buttons = QVBoxLayout()
        col4_buttons.setSpacing(4)
        col4_buttons.addStretch()
        
        # Row 1: TAPE and HARMONY
        tape_harmony_row = QHBoxLayout()
        tape_harmony_row.setSpacing(4)
        
        self.tape_btn = QPushButton("TAPE")
        self.tape_btn.setCheckable(True)
        self.tape_btn.setStyleSheet("""
            QPushButton { color: gray; }
            QPushButton:checked {
                background-color: teal; color: green;
                border: 2px solid gray; font-weight: bold;
            }
        """)
        self.tape_btn.clicked.connect(self._on_tape)
        self.tape_btn.setFixedSize(70, 26)
        tape_harmony_row.addWidget(self.tape_btn)

        self.harmony_btn = QPushButton("HARMONY")
        self.harmony_btn.setCheckable(True)
        self.harmony_btn.setFixedSize(70, 26)
        self.harmony_btn.setStyleSheet("""
            QPushButton { color: gray; }
            QPushButton:checked {
                background-color: #5a005a; color: #ff00ff;
                border: 2px solid gray; font-weight: bold;
            }
        """)
        self.harmony_btn.clicked.connect(self._on_harmony_clicked)
        tape_harmony_row.addWidget(self.harmony_btn)
        
        col4_buttons.addLayout(tape_harmony_row)
        
        # Centering helper for single-width buttons
        def add_centered_btn(btn):
            row = QHBoxLayout()
            row.addWidget(btn)
            row.addStretch()
            col4_buttons.addLayout(row)

        self.spread_btn = QPushButton("SPREAD")
        self.spread_btn.setFixedSize(70, 26)
        self.spread_btn.setMenu(self._create_spread_menu())
        self.spread_btn.setStyleSheet("""
            QPushButton { color: gray; }
            QPushButton:checked {
                background-color: #005a5a; color: #00ffff;
                border: 2px solid gray; font-weight: bold;
            }
        """)
        self.spread_btn.setCheckable(True)
        add_centered_btn(self.spread_btn)
        
        self.chroma_btn = QPushButton("CHROMA")
        self.chroma_btn.setFixedSize(70, 26)
        self.chroma_btn.setMenu(self._create_chroma_menu())
        self.chroma_btn.setStyleSheet("""
            QPushButton { color: gray; }
            QPushButton:checked {
                background-color: #5a5a00; color: #ffff00;
                border: 2px solid gray; font-weight: bold;
            }
        """)
        self.chroma_btn.setCheckable(True)
        add_centered_btn(self.chroma_btn)

        self.eq_btn = QPushButton("EQ")
        self.eq_btn.setCheckable(True)
        self.eq_btn.setFixedSize(70, 26)
        self.eq_btn.setStyleSheet("""
            QPushButton { color: gray; }
            QPushButton:checked {
                background-color: #e8a317; color: black;
                border: 2px solid gray; font-weight: bold;
            }
        """)
        self.eq_btn.clicked.connect(self._open_pultec_popup)
        add_centered_btn(self.eq_btn)
        
        self.fx_btn = QPushButton("DELAY")
        self.fx_btn.setMenu(self._create_fx_menu())
        self.fx_btn.setFixedSize(70, 26)
        add_centered_btn(self.fx_btn)
        
        col4_buttons.addStretch()
        controls_layout.addLayout(col4_buttons)

        # Persistent Pultec Popup
        self._pultec_popup = PultecPopup(self.idx, self.engine, parent=self.parent_ui)

        # Stretch to push everything left
        controls_layout.addStretch()

        main_layout.addLayout(controls_layout)

        # Combined row for meter, waveform, and volume
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)
        
        self.meter = LevelMeter()
        self.meter.setFixedHeight(24)
        self.synth_wave = SynthWaveformWidget()
        self.synth_wave.setFixedHeight(24)
        self.synth_wave.setVisible(False)
        
        bottom_row.addWidget(self.meter, 1)
        bottom_row.addWidget(self.synth_wave, 1)
        
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 150)
        self.vol_slider.setValue(100)
        self.vol_slider.setFixedHeight(24)
        self.vol_slider.valueChanged.connect(self._on_vol)
        self.vol_slider.setStyleSheet("""
            QSlider::groove:horizontal { border: 1px solid #333; height: 6px; background: #222; margin: 2px 0; }
            QSlider::handle:horizontal { background: teal; border: 1px solid #111; width: 14px; margin: -6px 0; border-radius: 2px; }
        """)
        bottom_row.addWidget(self.vol_slider, 2)
        
        main_layout.addLayout(bottom_row)
        
    def create_label(self, text):
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setFont(QFont("Courier New", 7))
        return lbl

    def create_value_label(self, text):
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        lbl.setStyleSheet("color: #00ff00;")
        return lbl
        
    def _on_arm(self):
        if self.arm_btn.isChecked():
            for i, ts in enumerate(self.parent_ui.track_strips):
                if i != self.idx:
                    ts.arm_btn.setChecked(False)
            self.engine.armed_track = self.idx

            source_key = self.src_combo.currentData()

            # Use the ALSA device alias instead of None + PULSE_SOURCE
            if self.synth_mode in ('golden_bull', 'asherah'):
                alias = f"station_track_{self.idx}_pipe"
                self.engine.set_devices(input_dev=alias, output_dev=None)
            elif source_key == "ASHERAH_PIPE":
                self.engine.set_devices(input_dev="Asherah_Pipe", output_dev=None)
            else:
                self.engine.set_devices(input_dev=source_key, output_dev=None)

            # Start monitoring stream for input metering
            self.engine.start_monitoring()
        else:
            self.engine.armed_track = -1
            self.engine.input_level = 0.0
            self.engine.input_clipping = False
            self.engine._stop_monitor()

    def _on_mon(self, checked):
        with self.engine.lock:
            self.engine.track_monitoring[self.idx] = checked
        self.parent_ui._push_undo_snapshot()

    def _on_harmony_clicked(self, checked):
        if not checked:
            with self.engine.lock:
                self.engine.track_harmony[self.idx] = False
                # Don't reset mode/mix so they are preserved for when we turn it back on
            return

        # Always open the dialog so the user can choose mode/mix
        current_mode = self.engine.track_harmony_mode[self.idx]
        current_mix  = self.engine.track_harmony_mix[self.idx]
        if current_mix <= 0: current_mix = 0.5 # Default mix if it was 0

        dlg = HarmonyDialog(self.idx, self.engine, current_mode, current_mix, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.engine.update_harmony_params(self.idx, True, dlg.mode, dlg.mix)
        else:
            # If they cancelled, we might need to uncheck if it wasn't already on
            if not self.engine.track_harmony[self.idx]:
                self.harmony_btn.setChecked(False)

        self.parent_ui.timeline.update()

    def _on_source_changed(self, idx):
        """Handle source selector change — launch or close tethered synth, or update mic device."""
        source_key = self.src_combo.currentData()

        # Close existing synth if switching away from one
        old_synth_mode = self.synth_mode
        if old_synth_mode in ('golden_bull', 'asherah') and source_key != old_synth_mode:
            self.parent_ui._close_synth_for_track(self.idx)
            self.synth_mode = None

        if source_key == 'golden_bull':
            if old_synth_mode != 'golden_bull':
                self.parent_ui._launch_synth_for_track(self.idx, 'golden_bull')
                self.synth_mode = 'golden_bull'
                self._enter_synth_mode()
        elif source_key == 'asherah':
            if old_synth_mode != 'asherah':
                if self.parent_ui.asherah_track != -1 and self.parent_ui.asherah_track != self.idx:
                    QMessageBox.warning(self, "ASHERAH Running",
                        f"ASHERAH is already tethered to Track {self.parent_ui.asherah_track + 1}.")
                    self.src_combo.blockSignals(True)
                    self.src_combo.setCurrentIndex(0)
                    self.src_combo.blockSignals(False)
                    return
                self.parent_ui._launch_synth_for_track(self.idx, 'asherah')
                self.synth_mode = 'asherah'
                self._enter_synth_mode()
        elif source_key == 'ASHERAH_PIPE':
            self._exit_synth_mode()
            # Device will be set when armed
        else:
            # Regular mic/hardware device — tell the engine immediately
            self._exit_synth_mode()
            if self.arm_btn.isChecked():
                # If already armed, hot-swap the input device
                if 'PULSE_SOURCE' in os.environ:
                    del os.environ['PULSE_SOURCE']
                self.engine.set_devices(input_dev=source_key, output_dev=None)

        if self.arm_btn.isChecked():
            self._on_arm()

    def _enter_synth_mode(self):
        """Switch track strip to tethered synth visual mode."""
        self.gain_col_widget.setVisible(False)
        self.meter.setVisible(False)
        self.synth_wave.setVisible(True)
        self.setStyleSheet("QFrame { border: 2px solid #00a080; border-radius: 4px; }")
        trk_name = "GOLDEN BULL" if self.synth_mode == 'golden_bull' else "ASHERAH"
        self.title_label.setText(f"TRK {self.idx + 1} / {trk_name}")
        self.title_label.setStyleSheet("color: #00d4aa; border: none;")

    def _exit_synth_mode(self):
        """Restore track strip to normal mic/hardware mode."""
        self.synth_mode = None
        self.gain_col_widget.setVisible(True)
        self.meter.setVisible(True)
        self.synth_wave.setVisible(False)
        self.setStyleSheet("")
        self.title_label.setText(f"TRK {self.idx + 1}")
        self.title_label.setStyleSheet("color: green; border: none;")

    def _on_pan(self, val):
        self.pan_val_lbl.setText(str(val))
        self.engine.track_pans[self.idx] = val / 50.0
        self.parent_ui._push_undo_snapshot()

    def _on_gain(self, val):
        self.gain_val_lbl.setText(str(val))
        # Map -50..50 to 0.0..2.0 (0 is unity/1.0)
        self.engine.input_gains[self.idx] = (val + 50) / 50.0
        self.parent_ui._push_undo_snapshot()

    def _on_vol(self, val):
        self.engine.track_volumes[self.idx] = val / 100.0
        self.parent_ui._push_undo_snapshot()

    def _on_mute(self, checked):
        self.engine.track_mutes[self.idx] = checked
        self.parent_ui._push_undo_snapshot()

    def _on_solo(self, checked):
        self.engine.track_solos[self.idx] = checked
        self.parent_ui._push_undo_snapshot()
    
    def _on_eq_hi(self, val):
        self.hi_val_lbl.setText(str(val))
        # Map -50..50 to -15.0..15.0
        self.engine.track_eq_hi[self.idx] = (val / 50.0) * 15.0
        self.parent_ui._push_undo_snapshot()

    def _on_eq_lo(self, val):
        self.lo_val_lbl.setText(str(val))
        # Map -50..50 to -15.0..15.0
        self.engine.track_eq_lo[self.idx] = (val / 50.0) * 15.0
        self.parent_ui._push_undo_snapshot()

    def _on_tape(self, checked):
        with self.engine.lock:
            self.engine.track_tape[self.idx] = checked
        self.parent_ui._push_undo_snapshot()

    def _create_spread_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background-color: #111; color: #00ffff; border: 1px solid #333; }")
        
        a_off = menu.addAction("Off")
        a_off.triggered.connect(lambda: self._on_spread(0))
        
        menu.addSeparator()
        
        a_drum = menu.addAction("Drum")
        a_drum.triggered.connect(lambda: self._on_spread(1))
        
        a_bass = menu.addAction("Bass")
        a_bass.triggered.connect(lambda: self._on_spread(2))
        
        a_guitar = menu.addAction("Guitar")
        a_guitar.triggered.connect(lambda: self._on_spread(3))
        
        return menu

    def _on_spread(self, mode):
        with self.engine.lock:
            self.engine.track_spread[self.idx] = mode
        
        label = ["SPREAD", "DRUM", "BASS", "GUITAR"][mode]
        self.spread_btn.setText(label)
        self.spread_btn.setChecked(mode > 0)
        self.parent_ui.timeline.update()

    def _create_chroma_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background-color: #111; color: #ffff00; border: 1px solid #333; }")
        
        a_off = menu.addAction("Off")
        a_off.triggered.connect(lambda: self._on_chroma(0))
        
        menu.addSeparator()
        
        a_dark = menu.addAction("Dark")
        a_dark.triggered.connect(lambda: self._on_chroma(1))
        
        a_sparkle = menu.addAction("Sparkle")
        a_sparkle.triggered.connect(lambda: self._on_chroma(2))
        
        a_warm = menu.addAction("Warm")
        a_warm.triggered.connect(lambda: self._on_chroma(3))
        
        return menu

    def _on_chroma(self, mode):
        with self.engine.lock:
            self.engine.track_chroma[self.idx] = mode
        
        label = ["CHROMA", "DARK", "SPARKLE", "WARM"][mode]
        self.chroma_btn.setText(label)
        self.chroma_btn.setChecked(mode > 0)
        self.parent_ui.timeline.update()

    def _create_fx_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background-color: #111; color: green; border: 1px solid #333; }")
        
        a_slap = menu.addAction("Slapback")
        a_slap.triggered.connect(lambda: self._apply_fx("SLAP"))
        
        a_dub = menu.addAction("Dub Delay")
        a_long = menu.addAction("Long Echo")
        
        a_dub.triggered.connect(lambda: self._apply_fx("DUB"))
        a_long.triggered.connect(lambda: self._apply_fx("LONG"))
        
        return menu

    def _apply_fx(self, mode):
        if mode == "SLAP":
            self.engine.apply_delay(self.idx, 0.1, 0.2, 0.4)
        elif mode == "DUB":
            self.engine.apply_delay(self.idx, 0.4, 0.6, 0.5)
        elif mode == "LONG":
            self.engine.apply_delay(self.idx, 0.8, 0.7, 0.6)
        
        self.parent_ui._push_undo_snapshot()
        self.parent_ui.timeline.update()
            
    def _on_rev(self, val):
        self.rev_val_lbl.setText(str(val))
        # Map 0..99 to 0.0..1.0 send level
        self.engine.set_track_rev_send(self.idx, val / 99.0)

    def _open_pultec_popup(self):
        # Revert the click toggle so it only reflects actual engine state
        self.eq_btn.blockSignals(True)
        self.eq_btn.setChecked(self.engine.track_pultec_enabled[self.idx])
        self.eq_btn.blockSignals(False)

        popup = self._pultec_popup
        if popup.isVisible():
            popup.raise_()
            popup.activateWindow()
        else:
            # Position popup near the EQ button, offset so it doesn't obscure the track
            btn_pos = self.eq_btn.mapToGlobal(self.eq_btn.rect().bottomLeft())
            popup.move(btn_pos.x(), btn_pos.y() + 4)
            popup.show()
        self.parent_ui._push_undo_snapshot()

class SumTracksDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SUM TRACKS")
        self.setFixedSize(300, 350)
        self.setStyleSheet("""
            QDialog { background-color: #1a1a1a; border: 2px solid teal; border-radius: 8px;}
            QLabel { color: green; font-family: "Courier New", monospace; font-weight: bold; }
            QCheckBox { color: green; font-family: "Courier New", monospace; }
            QComboBox { background-color: #000; color: green; border: 1px solid #555; padding:4px;}
            QPushButton {
                color: green; background: #000; border: 2px solid #555;
                padding: 6px; font-family: "Courier New", monospace; font-weight: bold;
            }
            QPushButton:hover { background: #444; color: white; border-color: #888; }
            QPushButton:pressed { background: teal; color: black; }
        """)
        
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("SELECT SOURCE TRACKS:"))
        self.cb_sources = []
        for i in range(4):
            cb = QCheckBox(f"Track {i+1}")
            self.cb_sources.append(cb)
            layout.addWidget(cb)
            
        layout.addSpacing(15)
        
        layout.addWidget(QLabel("SELECT DESTINATION TRACK:"))
        self.dest_combo = QComboBox()
        self.dest_combo.addItems(["Track 1", "Track 2", "Track 3", "Track 4"])
        layout.addWidget(self.dest_combo)
        
        layout.addSpacing(15)
        
        self.cb_delete = QCheckBox("Delete source clips after summing")
        self.cb_delete.setChecked(True)
        layout.addWidget(self.cb_delete)
        
        layout.addStretch()
        
        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("CANCEL")
        btn_cancel.clicked.connect(self.reject)
        self.btn_sum = QPushButton("SUM")
        self.btn_sum.clicked.connect(self.accept)
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(self.btn_sum)
        layout.addLayout(btn_layout)
        
    def get_selection(self):
        sources = [i for i, cb in enumerate(self.cb_sources) if cb.isChecked()]
        dest = self.dest_combo.currentIndex()
        delete = self.cb_delete.isChecked()
        return sources, dest, delete


class MT50MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.engine = AudioEngine()
        self.pm = ProjectManager(self.engine)

        # Tethered synth management
        self.synth_procs = {}      # track_idx -> subprocess.Popen
        self.asherah_track = -1    # Only one ASHERAH allowed
        
        self.setWindowTitle("STATION MASTER 4-TRACK")
        self.showMaximized()
        
        self.setStyleSheet("""
            QMainWindow { background-color: #0A0A0A; }
            QWidget#CentralWidget { background-color: #0A0A0A; }
            QFrame { background-color: #111; border: 1px solid #333; border-radius: 4px; }
            QFrame#MasterPane { border: 2px solid teal; background-color: #182828;}
            QLabel { color: green; font-family: "Courier New", monospace; font-weight: bold; background: transparent; border: none; }
            QPushButton {
                color: green; font-family: "Courier New", monospace; font-size: 13px;
                background-color: #000; border: 2px solid #555; border-radius: 4px; padding: 4px;
            }
            QPushButton:hover { background-color: #444; color: #FFF; border: 2px solid #888;}
            QPushButton:pressed { background-color: teal; color: black; }
            QPushButton:checked { background-color: #AA0000; color: #FFF; border: 2px solid #FF0000; }
            QPushButton#TransportBtn:checked { background-color: #5a005a; color: #ff00ff; border: 2px solid #ff00ff; }
            QPushButton#TransportBtn:pressed { background-color: #444; color: white; }
            QPushButton#TransportBtn { font-size: 14px; font-weight: bold; padding: 8px 16px; border-radius: 8px;}
            QSlider::groove:vertical { border: 1px solid #333; background: #000; width: 16px; border-radius: 8px; }
            QSlider::add-page:vertical { background: teal; border: 1px solid #333; width: 16px; border-radius: 8px; }
            QSlider::handle:vertical { background: teal; border: 2px solid green; height: 30px; margin: -2px -6px; border-radius: 6px; }
            QSlider::groove:horizontal { border: 1px solid #333; background: #000; height: 16px; border-radius: 8px; }
            QSlider::sub-page:horizontal { background: teal; border: 1px solid #333; height: 16px; border-radius: 8px; }
            QSlider::handle:horizontal { background: teal; border: 2px solid green; width: 30px; margin: -6px -2px; border-radius: 6px; }
             
            QComboBox { background-color: #000; color: green; border: 1px solid #555; padding: 4px; font-family: "Courier New", monospace; }
        """)
        
        cw = QWidget()
        cw.setObjectName("CentralWidget")
        self.setCentralWidget(cw)
        
        main_layout = QVBoxLayout(cw)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0,0,0,0)
        
        # --- TOP HORIZONTAL SPLIT (MIXER + TIMELINE) ---
        top_split = QHBoxLayout()
        top_split.setSpacing(0)
        
        # MIXER HEADERS — VBox for diagnostics header + 4 track strips
        mixer_layout = QVBoxLayout()
        mixer_layout.setSpacing(0)

        # Top-left header above Track 1: DIAGNOSTICS button
        self.btn_log = QPushButton("DIAGNOSTICS: OFF")
        self.btn_log.setCheckable(True)
        self.btn_log.setFixedHeight(TIMELINE_Y_OFFSET)
        self.btn_log.setToolTip("Start detailed session logging for debugging (F11)")
        self.btn_log.setStyleSheet("""
            QPushButton { color: #888; border: 1px solid #333; border-radius: 0px;
                          font-size: 10px; font-weight: bold; background-color: #0a0a0a; }
            QPushButton:checked { background-color: #5a5a00; color: #ffff00; border: 1px solid #fff; }
        """)
        self.btn_log.clicked.connect(self._toggle_logging)
        mixer_layout.addWidget(self.btn_log)
        QShortcut(QKeySequence("F11"), self).activated.connect(self.btn_log.toggle)

        self.track_strips = []
        for i in range(4):
            ts = TrackStrip(i, self.engine, self)
            self.track_strips.append(ts)
            mixer_layout.addWidget(ts)
        mixer_layout.addStretch()

        
        w_mix = QWidget()
        w_mix.setLayout(mixer_layout)
        w_mix.setFixedWidth(580)
        top_split.addWidget(w_mix)
        
        # TIMELINE inside a scroll area
        self.timeline = TimelineWidget(self.engine, self)
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(self.timeline)
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("""
            QScrollArea { border: none; background: #111; }
            QScrollBar:horizontal {
                background: #111; height: 14px; border: none;
            }
            QScrollBar::handle:horizontal {
                background: #555; border-radius: 4px; min-width: 40px;
            }
            QScrollBar::handle:horizontal:hover { background: teal; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
        """)
        top_split.addWidget(self.scroll_area, stretch=1)
        
        main_layout.addLayout(top_split, stretch=1)
        
        # --- BOTTOM MASTER PANE ---
        master_pane = QFrame()
        master_pane.setObjectName("MasterPane")
        master_pane.setFixedHeight(100)
        m_layout = QHBoxLayout(master_pane)
        
        # Timecode display
        self.timecode_label = QLabel("0:00.0")
        self.timecode_label.setFont(QFont("Courier New", 18, QFont.Weight.Bold))
        self.timecode_label.setStyleSheet("color: green; background: #000; border: 2px solid #333; padding: 4px 12px; border-radius: 4px;")
        m_layout.addWidget(self.timecode_label)
        
        # CPU Meter
        cpu_layout = QVBoxLayout()
        cpu_lbl = QLabel("CPU")
        cpu_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        cpu_lbl.setStyleSheet("color: #666;")
        cpu_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cpu_layout.addWidget(cpu_lbl)
        self.cpu_meter = LevelMeter()
        self.cpu_meter.setFixedSize(40, 10)
        cpu_layout.addWidget(self.cpu_meter)
        self.cpu_pct_label = QLabel("0%")
        self.cpu_pct_label.setFont(QFont("Courier New", 8))
        self.cpu_pct_label.setStyleSheet("color: #666;")
        self.cpu_pct_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cpu_layout.addWidget(self.cpu_pct_label)
        m_layout.addLayout(cpu_layout)
        
        # Zoom controls
        zoom_layout = QVBoxLayout()
        zoom_in_btn = QPushButton("🔍+")
        zoom_in_btn.setFixedSize(40, 30)
        zoom_in_btn.clicked.connect(lambda: self._zoom(1.5))
        zoom_out_btn = QPushButton("🔍−")
        zoom_out_btn.setFixedSize(40, 30)
        zoom_out_btn.clicked.connect(lambda: self._zoom(1.0 / 1.5))
        zoom_layout.addWidget(zoom_in_btn)
        zoom_layout.addWidget(zoom_out_btn)
        m_layout.addLayout(zoom_layout)
        
        m_layout.addSpacing(20)
        
        # Populate input devices on all track strips
        self._cleanup_ghost_sinks()
        self._populate_devices()
        
        m_layout.addStretch()
        
        # Transport
        t_layout = QHBoxLayout()
        self.btn_rewind = QPushButton("⏪ REW")
        self.btn_rewind.setObjectName("TransportBtn")
        self.btn_rewind.clicked.connect(self._rewind)
        self.btn_play = QPushButton("▶ PLAY")
        self.btn_play.setObjectName("TransportBtn")
        self.btn_play.clicked.connect(self._play)
        self.btn_rec = QPushButton("🔴 RECORD")
        self.btn_rec.setObjectName("TransportBtn")
        self.btn_rec.clicked.connect(self._record)
        self.btn_stop = QPushButton("⏹ STOP")
        self.btn_stop.setObjectName("TransportBtn")
        self.btn_stop.clicked.connect(self._stop)
        self.btn_loop = QPushButton("🔁 LOOP")
        self.btn_loop.setObjectName("TransportBtn")
        self.btn_loop.setCheckable(True)
        self.btn_loop.clicked.connect(self._toggle_loop)
        
        t_layout.addWidget(self.btn_rewind)
        t_layout.addWidget(self.btn_play)
        t_layout.addWidget(self.btn_rec)
        t_layout.addWidget(self.btn_stop)
        t_layout.addWidget(self.btn_loop)
        m_layout.addLayout(t_layout)
        
        m_layout.addStretch()
        
        # Master EQ
        meq_layout = QVBoxLayout()
        meq_label = QLabel("MASTER EQ")
        meq_label.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        meq_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        meq_layout.addWidget(meq_label)
        
        meq_knobs = QHBoxLayout()
        hi_col = QVBoxLayout()
        hi_lbl = QLabel("HI")
        hi_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hi_lbl.setFont(QFont("Courier New", 8))
        hi_col.addWidget(hi_lbl)
        self.mst_hi_dial = StyledDial()
        self.mst_hi_dial.setRange(-15, 15)
        self.mst_hi_dial.setValue(0)
        self.mst_hi_dial.setFixedSize(40, 40)
        self.mst_hi_dial.valueChanged.connect(self._on_mst_hi)
        hi_col.addWidget(self.mst_hi_dial)
        meq_knobs.addLayout(hi_col)
        
        lo_col = QVBoxLayout()
        lo_lbl = QLabel("LO")
        lo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lo_lbl.setFont(QFont("Courier New", 8))
        lo_col.addWidget(lo_lbl)
        self.mst_lo_dial = StyledDial()
        self.mst_lo_dial.setRange(-15, 15)
        self.mst_lo_dial.setValue(0)
        self.mst_lo_dial.setFixedSize(40, 40)
        self.mst_lo_dial.valueChanged.connect(self._on_mst_lo)
        lo_col.addWidget(self.mst_lo_dial)
        meq_knobs.addLayout(lo_col)
        meq_layout.addLayout(meq_knobs)
        m_layout.addLayout(meq_layout)
        
        m_layout.addStretch()
        
        # Master Vol
        mv_layout = QVBoxLayout()
        mv_layout.addWidget(self.create_label("MASTER VOL"))
        
        self.m_vol = QSlider(Qt.Orientation.Horizontal)
        self.m_vol.setRange(0, 150)
        self.m_vol.setValue(100)
        self.m_vol.setFixedHeight(40)
        self.m_vol.setMinimumWidth(133)
        self.m_vol.valueChanged.connect(self._on_mst_vol)
        mv_layout.addWidget(self.m_vol)
        
        self.master_meter = LevelMeter()
        mv_layout.addWidget(self.master_meter)
        
        m_layout.addLayout(mv_layout)
        
        m_layout.addStretch()

        # Reverb Bus Controls
        rev_bus_layout = QVBoxLayout()
        rev_bus_label = QLabel("REV BUS")
        rev_bus_label.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        rev_bus_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rev_bus_layout.addWidget(rev_bus_label)

        rev_ctrls = QHBoxLayout()
        
        # Type Selector
        self.rev_type_combo = QComboBox()
        self.rev_type_combo.addItems(["ROOM", "AMB", "PLATE"])
        self.rev_type_combo.setFixedWidth(70)
        self.rev_type_combo.currentIndexChanged.connect(self._on_rev_type_changed)
        rev_ctrls.addWidget(self.rev_type_combo)

        # Return Level Knob
        ret_col = QVBoxLayout()
        ret_lbl = QLabel("RET")
        ret_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ret_lbl.setFont(QFont("Courier New", 8))
        ret_col.addWidget(ret_lbl)
        self.rev_ret_dial = StyledDial()
        self.rev_ret_dial.setRange(0, 100)
        self.rev_ret_dial.setValue(100)
        self.rev_ret_dial.setFixedSize(36, 36)
        self.rev_ret_dial.valueChanged.connect(self._on_rev_ret_changed)
        ret_col.addWidget(self.rev_ret_dial)
        rev_ctrls.addLayout(ret_col)
        
        rev_bus_layout.addLayout(rev_ctrls)
        m_layout.addLayout(rev_bus_layout)

        m_layout.addStretch()
        
        # Offline Processing (Moved left for more space)
        offline_layout = QVBoxLayout()
        offline_layout.setSpacing(8)
        self.btn_bounce = QPushButton("BOUNCE MIX")
        self.btn_bounce.setFixedHeight(30)
        self.btn_bounce.setFixedWidth(100)
        self.btn_bounce.setStyleSheet("color: teal; border-color: teal; font-weight:bold;")
        self.btn_bounce.clicked.connect(self._bounce)
        offline_layout.addWidget(self.btn_bounce)
        
        self.btn_sum = QPushButton("SUM OFFLINE")
        self.btn_sum.setFixedHeight(30)
        self.btn_sum.setFixedWidth(100)
        self.btn_sum.setStyleSheet("color: teal; border-color: teal; font-weight:bold;")
        self.btn_sum.clicked.connect(self._sum_tracks)
        offline_layout.addWidget(self.btn_sum)

        # Project IO buttons
        io_layout = QVBoxLayout()
        io_layout.setSpacing(8)
        io_top = QHBoxLayout()
        io_top.setSpacing(6)
        self.btn_load = QPushButton("LOAD")
        self.btn_load.setFixedHeight(28)
        self.btn_load.clicked.connect(self._load_proj)
        self.btn_save = QPushButton("SAVE")
        self.btn_save.setFixedHeight(28)
        self.btn_save.clicked.connect(self._save_proj)
        self.btn_screenshot = QPushButton("📸")
        self.btn_screenshot.setFixedSize(32, 28)
        self.btn_screenshot.setToolTip("Take Screenshot (F12)")
        self.btn_screenshot.clicked.connect(self._screenshot)
        self.btn_new = QPushButton("NEW")
        self.btn_new.setFixedHeight(28)
        self.btn_new.setToolTip("Create new project — clears all tracks and resets settings")
        self.btn_new.setStyleSheet("color: #ff8800; border-color: #ff8800; font-weight: bold;")
        self.btn_new.clicked.connect(self._new_proj)
        io_top.addWidget(self.btn_new)
        io_top.addWidget(self.btn_load)
        io_top.addWidget(self.btn_save)
        io_top.addWidget(self.btn_screenshot)
        io_layout.addLayout(io_top)

        m_layout.addLayout(offline_layout)
        m_layout.addSpacing(25)
        m_layout.addLayout(io_layout)
        m_layout.addSpacing(10)


        main_layout.addWidget(master_pane)
        
        self._log_handler = None
        self._console_handler = None
        
        # Undo/Redo
        self._undo_stack = collections.deque(maxlen=50)
        self._undo_idx = -1
        QShortcut(QKeySequence("Ctrl+Z"), self).activated.connect(self._undo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self).activated.connect(self._redo)
        QShortcut(QKeySequence("F12"), self).activated.connect(self._screenshot)
        
        # Timer for UI updates
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_meters)
        self.timer.start(50)
        
        # Capture baseline snapshot
        self._push_undo_snapshot()

    def _on_mst_hi(self, v):
        self.engine.master_eq_hi = float(v)
        self._push_undo_snapshot()

    def _on_mst_lo(self, v):
        self.engine.master_eq_lo = float(v)
        self._push_undo_snapshot()

    def _on_mst_vol(self, v):
        self.engine.master_volume = v / 100.0
        self._push_undo_snapshot()

    def _on_rev_type_changed(self, idx):
        self.engine.set_bus_reverb_type(idx)
        self._push_undo_snapshot()

    def _on_rev_ret_changed(self, v):
        self.engine.set_bus_reverb_return(v / 100.0)
        self._push_undo_snapshot()

    def _push_undo_snapshot(self):
        with self.engine.lock:
            # Capture full project state: clips + mixer settings
            snap = {
                "tracks": [[c.copy() for c in t] for t in self.engine.tracks],
                "master_volume": self.engine.master_volume,
                "track_volumes": list(self.engine.track_volumes),
                "track_pans": list(self.engine.track_pans),
                "track_mutes": list(self.engine.track_mutes),
                "track_solos": list(self.engine.track_solos),
                "track_monitoring": list(self.engine.track_monitoring),
                "input_gains": list(self.input_gains if hasattr(self, 'input_gains') else self.engine.input_gains),
                "track_eq_lo": list(self.engine.track_eq_lo),
                "track_eq_hi": list(self.engine.track_eq_hi),
                "track_tape": list(self.engine.track_tape),
                "track_rev_send": list(self.engine.track_rev_send),
                "bus_reverb_type": self.engine.bus_reverb_type,
                "bus_reverb_return": self.engine.bus_reverb_return,
                "track_spread": list(self.engine.track_spread),
                "track_chroma": list(self.engine.track_chroma),
                "track_harmony": list(self.engine.track_harmony),
                "track_harmony_mode": list(self.engine.track_harmony_mode),
                "track_harmony_mix": list(self.engine.track_harmony_mix),
                "track_pultec_enabled": list(self.engine.track_pultec_enabled),
                "track_pultec_low_freq": list(self.engine.track_pultec_low_freq),
                "track_pultec_low_boost": list(self.engine.track_pultec_low_boost),
                "track_pultec_low_cut": list(self.engine.track_pultec_low_cut),
                "track_pultec_high_freq": list(self.engine.track_pultec_high_freq),
                "track_pultec_high_boost": list(self.engine.track_pultec_high_boost),
                "track_pultec_high_cut": list(self.engine.track_pultec_high_cut),
                "track_pultec_preset": list(self.engine.track_pultec_preset),
                }        
        # If we went back in time and made a change, fork history by dropping future redos
        while len(self._undo_stack) > self._undo_idx + 1:
            self._undo_stack.pop()
            
        self._undo_stack.append(snap)
        self._undo_idx = len(self._undo_stack) - 1
        
    def _apply_snapshot(self, snap):
        with self.engine.lock:
            # Restore clips
            for i in range(4):
                self.engine.tracks[i] = [c.copy() for c in snap["tracks"][i]]
            
            # Restore mixer settings
            self.engine.master_volume = snap.get("master_volume", 1.0)
            self.engine.track_volumes = list(snap["track_volumes"])
            self.engine.track_pans = list(snap["track_pans"])
            self.engine.track_mutes = list(snap["track_mutes"])
            self.engine.track_solos = list(snap["track_solos"])
            self.engine.track_monitoring = list(snap["track_monitoring"])
            self.engine.input_gains = list(snap["input_gains"])
            self.engine.track_eq_lo = list(snap["track_eq_lo"])
            self.engine.track_eq_hi = list(snap["track_eq_hi"])
            self.engine.track_tape = list(snap["track_tape"])
            self.engine.track_rev_send = list(snap["track_rev_send"])
            self.engine.bus_reverb_type = snap.get("bus_reverb_type", 0)
            self.engine.bus_reverb_return = snap.get("bus_reverb_return", 1.0)
            self.engine.track_spread = list(snap["track_spread"])
            self.engine.track_chroma = list(snap["track_chroma"])
            self.engine.track_harmony = list(snap["track_harmony"])
            self.engine.track_harmony_mode = list(snap["track_harmony_mode"])
            self.engine.track_harmony_mix = list(snap["track_harmony_mix"])
            self.engine.track_pultec_enabled = list(snap.get("track_pultec_enabled", [False]*4))
            self.engine.track_pultec_low_freq = list(snap.get("track_pultec_low_freq", [1]*4))
            self.engine.track_pultec_low_boost = list(snap.get("track_pultec_low_boost", [0.0]*4))
            self.engine.track_pultec_low_cut = list(snap.get("track_pultec_low_cut", [0.0]*4))
            self.engine.track_pultec_high_freq = list(snap.get("track_pultec_high_freq", [2]*4))
            self.engine.track_pultec_high_boost = list(snap.get("track_pultec_high_boost", [0.0]*4))
            self.engine.track_pultec_high_cut = list(snap.get("track_pultec_high_cut", [0.0]*4))
            self.engine.track_pultec_preset = list(snap.get("track_pultec_preset", [0]*4))

            # Re-initialize engine internal state (harmony pedalboards, etc.)
            for i in range(4):
                self.engine.update_harmony_params(i, self.engine.track_harmony[i],
                                                self.engine.track_harmony_mode[i],
                                                self.engine.track_harmony_mix[i])
                # Also update pultec params to reset biquad states if needed
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
                # Refresh popup UI
                self.track_strips[i]._pultec_popup._load_state()
        self.timeline.envelopes.clear()
        self._sync_ui_to_engine()
        self.timeline.update()

    def _undo(self):
        if self._undo_idx > 0:
            self._undo_idx -= 1
            self._apply_snapshot(self._undo_stack[self._undo_idx])

    def _redo(self):
        if self._undo_idx < len(self._undo_stack) - 1:
            self._undo_idx += 1
            self._apply_snapshot(self._undo_stack[self._undo_idx])

    def _update_meters(self):
        """Called every 30ms to update timeline, meters, timecode, and auto-scroll."""
        # Update timecode
        secs = self.engine.current_frame / self.engine.sample_rate
        mins = int(secs) // 60
        s = secs - (mins * 60)
        self.timecode_label.setText(f"{mins}:{s:04.1f}")
        
        # Grow timeline if needed (during recording the content grows)
        self.timeline._update_size()
        
        # Auto-follow playhead: scroll to keep it in view 
        if self.engine.is_playing or self.engine.is_recording:
            ph_x = self.timeline._frame_to_x(self.engine.current_frame)
            viewport_w = self.scroll_area.viewport().width()
            scrollbar = self.scroll_area.horizontalScrollBar()
            current_scroll = scrollbar.value()
            
            # If playhead moves past 75% of the visible area, scroll right
            visible_right = current_scroll + viewport_w
            if ph_x > current_scroll + int(viewport_w * 0.75):
                scrollbar.setValue(ph_x - int(viewport_w * 0.25))
            elif ph_x < current_scroll:
                scrollbar.setValue(max(0, ph_x - int(viewport_w * 0.1)))
        
        self.timeline.update()
        
        # Route the engine's dynamic levels to the meters
        armed = self.engine.armed_track
        for i, ts in enumerate(self.track_strips):
            if i == armed:
                ts.meter.set_level(self.engine.input_level, self.engine.input_clipping)
            else:
                ts.meter.set_level(self.engine.playback_levels[i], self.engine.playback_clipping[i])

            # Sync EQ button light
            ts.eq_btn.setChecked(self.engine.track_pultec_enabled[i])

        self.master_meter.set_level(self.engine.master_level, self.engine.master_clipping)
        self.cpu_meter.set_level(self.engine.cpu_load, self.engine.cpu_load >= 0.9)
        self.cpu_pct_label.setText(f"{int(self.engine.cpu_load * 100)}%")

        # Poll tethered synth state files for waveform + preset updates
        for i, ts in enumerate(self.track_strips):
            if ts.synth_mode in ('golden_bull', 'asherah'):
                state_file = f"/tmp/station_track_{i}_state.json"
                try:
                    with open(state_file, 'r') as f:
                        state = json.load(f)
                    ts.synth_wave.update_state(
                        state.get("preset", "?"),
                        state.get("waveform", [])
                    )
                except Exception:
                    pass

    def _launch_synth_for_track(self, track_idx, synth_type):
        """Spawn a tethered Golden Bull or ASHERAH process for the given track."""
        gb_dir = os.path.expanduser("~/Documents/golden_bull_synth")
        venv_py = os.path.join(gb_dir, "venv", "bin", "python3")
        if not os.path.exists(venv_py):
            venv_py = "python3"

        # Create a named PulseAudio virtual sink for this track
        pipe_name = f"station_track_{track_idx}_pipe"
        try:
            subprocess.run(
                ["pactl", "load-module", "module-null-sink",
                 f"sink_name={pipe_name}",
                 f"sink_properties=device.description={pipe_name}"],
                capture_output=True
            )
        except Exception as e:
            print(f"Could not create virtual sink: {e}")

        # Launch the process
        env = os.environ.copy()
        env['PULSE_SINK'] = pipe_name

        procs = []
        if synth_type == 'golden_bull':
            script = os.path.join(gb_dir, "main.py")
            cmd = [venv_py, script, "--tethered", "--track", str(track_idx)]
            procs.append(subprocess.Popen(cmd, cwd=gb_dir, env=env))
        else:  # asherah
            engine_script = os.path.join(gb_dir, "main.py")
            engine_cmd = [venv_py, engine_script, "--tethered", "--track", str(track_idx)]
            procs.append(subprocess.Popen(engine_cmd, cwd=gb_dir, env=env))
            
            ui_script = os.path.join(gb_dir, "grid_ui.py")
            ui_cmd = [venv_py, ui_script, "--tethered", "--track", str(track_idx)]
            procs.append(subprocess.Popen(ui_cmd, cwd=gb_dir, env=env))
            self.asherah_track = track_idx

        self.synth_procs[track_idx] = procs
        print(f"Launched {synth_type} ({len(procs)} processes) → TRK {track_idx + 1}")

    def _close_synth_for_track(self, track_idx):
        """Terminate the tethered synth process for a track."""
        procs = self.synth_procs.pop(track_idx, [])
        if not isinstance(procs, list):
            procs = [procs]
            
        for proc in procs:
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    proc.kill()

        # Clean up ASHERAH singleton tracker
        if self.asherah_track == track_idx:
            self.asherah_track = -1

        # Clean up state file
        try:
            os.remove(f"/tmp/station_track_{track_idx}_state.json")
        except Exception:
            pass

        # Un-tether the track strip
        ts = self.track_strips[track_idx]
        ts._exit_synth_mode()
        ts.src_combo.blockSignals(True)
        ts.src_combo.setCurrentIndex(0)
        ts.src_combo.blockSignals(False)
        
    def _zoom(self, factor):
        """Zoom the timeline by the given factor (>1 = zoom in, <1 = zoom out)."""
        old_pps = self.timeline.pps
        self.timeline.pps = max(5.0, min(500.0, old_pps * factor))
        self.timeline._update_size()
        
        # Keep the playhead roughly centered after zoom
        ph_x = self.timeline._frame_to_x(self.engine.current_frame)
        viewport_w = self.scroll_area.viewport().width()
        self.scroll_area.horizontalScrollBar().setValue(max(0, ph_x - viewport_w // 2))
        
        self.timeline.update()
        
    def create_label(self, text):
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setFont(QFont("Courier New", 10))
        return lbl

    def _cleanup_ghost_sinks(self):
        """Unload any existing station_track null sinks to prevent menu overgrowth."""
        try:
            out = subprocess.check_output(["pactl", "list", "short", "modules"], stderr=subprocess.DEVNULL).decode()
            for line in out.splitlines():
                if "module-null-sink" in line and "station_track_" in line:
                    mod_id = line.split()[0]
                    subprocess.run(["pactl", "unload-module", mod_id], capture_output=True)
        except Exception as e:
            print(f"Error cleaning ghost sinks: {e}")

    def _populate_devices(self):
        devices = []
        try:
            import sounddevice as sd
            import subprocess
            
            # 1. Identify the "Best" System Default
            def_source_desc = "System Default"
            try:
                out = subprocess.check_output(["pactl", "info"], stderr=subprocess.DEVNULL).decode()
                for line in out.splitlines():
                    if "Default Source:" in line:
                        src_id = line.split(":", 1)[1].strip()
                        src_info = subprocess.check_output(["pactl", "list", "sources"], stderr=subprocess.DEVNULL).decode()
                        for chunk in src_info.split("\n\n"):
                            if src_id in chunk:
                                for l in chunk.splitlines():
                                    if "Description:" in l:
                                        def_source_desc = l.split(":", 1)[1].strip()
                                        break
                                break
            except:
                pass

            # 2. Query all devices but filter aggressively
            seen_names = set()
            devs = sd.query_devices()
            
            # We want the "Pulse/Default" entry first as it follows OS settings
            for i, d in enumerate(devs):
                if d['max_input_channels'] <= 0: continue
                
                name = d['name']
                
                # SUPPRESS: Internal DAW pipes and monitor sources
                if "station_track" in name.lower() or ".monitor" in name.lower():
                    continue
                
                # SUPPRESS: Common clutter
                if any(x in name.lower() for x in ["hdmi", "loopback", "null"]):
                    continue

                display_name = name
                is_default = False

                if name in ["pulse", "default"]:
                    display_name = f"Best: {def_source_desc}"
                    is_default = True
                
                # De-duplicate: If we've seen this name (or a truncated version), skip
                if display_name in seen_names:
                    continue
                seen_names.add(display_name)

                if is_default:
                    devices.insert(0, (display_name, i)) # Top priority
                else:
                    devices.append((display_name, i))
            
            # 3. Add Asherah Pipe ONLY if active
            try:
                out = subprocess.check_output(["pactl", "list", "short", "sources"], stderr=subprocess.DEVNULL).decode()
                if "Asherah_Pipe.monitor" in out:
                    devices.append(("🌟 ASHERAH VIRTUAL PIPE", "ASHERAH_PIPE"))
            except:
                pass
                    
        except Exception as e:
            devices.append(("Default System Mic", None))
            print(f"Error populating devices: {e}")
            
        for ts in self.track_strips:
            ts.src_combo.blockSignals(True)
            ts.src_combo.clear()
            for name, data in devices:
                prefix = "✨ " if "Best:" in name else "🎤 "
                ts.src_combo.addItem(f"{prefix}{name}", data)
            ts.src_combo.addItem("🐂  Golden Bull Synth", "golden_bull")
            ts.src_combo.addItem("⬡  ASHERAH Suite", "asherah")
            ts.src_combo.setCurrentIndex(0)
            ts.src_combo.blockSignals(False)

    def _rewind(self): 
        self.engine.rewind()
        self.scroll_area.horizontalScrollBar().setValue(0)
        self.timecode_label.setText("0:00.0")
        self.timeline.update()
    def _play(self): self.engine.start_playback()
    def _record(self):
        if self.engine.armed_track == -1:
            QMessageBox.warning(self, "No Track Armed", "Please Arm a track (REC ARM) to record.")
            return
        self.engine.start_recording(self.engine.armed_track)
    def _stop(self):
        was_recording = self.engine.is_recording
        self.engine.stop()
        if was_recording:
            self._push_undo_snapshot()
        self.timeline.update()

    def _toggle_loop(self, checked):
        with self.engine.lock:
            self.engine.loop_enabled = checked
        self.timeline.update()

    def _sync_ui_to_engine(self):
        self.m_vol.setValue(int(self.engine.master_volume * 100))
        self.rev_type_combo.blockSignals(True)
        self.rev_type_combo.setCurrentIndex(self.engine.bus_reverb_type)
        self.rev_type_combo.blockSignals(False)
        self.rev_ret_dial.setValue(int(self.engine.bus_reverb_return * 100))
        
        for i, ts in enumerate(self.track_strips):
            ts.vol_slider.setValue(int(self.engine.track_volumes[i] * 100))
            # Map internal -1.0..1.0 back to UI -50..50
            ts.pan_dial.setValue(int(self.engine.track_pans[i] * 50))
            ts.mute_btn.setChecked(self.engine.track_mutes[i])
            ts.solo_btn.setChecked(self.engine.track_solos[i])
            ts.mon_btn.setChecked(self.engine.track_monitoring[i])
            # Map internal 0.0..2.0 back to UI -50..50
            ts.gain_dial.setValue(int(self.engine.input_gains[i] * 50 - 50))
            # Map internal -15..15 back to UI -50..50
            ts.lo_dial.setValue(int((self.engine.track_eq_lo[i] / 15.0) * 50))
            ts.hi_dial.setValue(int((self.engine.track_eq_hi[i] / 15.0) * 50))
            ts.rev_dial.setValue(int(self.engine.track_rev_send[i] * 99))
            ts.tape_btn.setChecked(self.engine.track_tape[i])
            ts.harmony_btn.setChecked(self.engine.track_harmony[i])
            ts.eq_btn.setChecked(self.engine.track_pultec_enabled[i])

            spread_mode = self.engine.track_spread[i]
            ts.spread_btn.setChecked(spread_mode > 0)
            ts.spread_btn.setText(["SPREAD", "DRUM", "BASS", "GUITAR"][spread_mode])
            
            chroma_mode = self.engine.track_chroma[i]
            ts.chroma_btn.setChecked(chroma_mode > 0)
            ts.chroma_btn.setText(["CHROMA", "DARK", "SPARKLE", "WARM"][chroma_mode])
            
            self.btn_loop.setChecked(self.engine.loop_enabled)
            self.timeline.envelopes.clear()


    def _get_workspace(self):
        """Retrieve the default workspace directory, or prompt the user to set it."""
        settings = QSettings("StationMaster", "DAW")
        workspace = settings.value("workspace_dir", "")
        if not workspace or not os.path.isdir(workspace):
            workspace = QFileDialog.getExistingDirectory(self, "Select Default Save Space (Workspace) for Projects")
            if workspace:
                settings.setValue("workspace_dir", workspace)
        return workspace

    def _save_proj(self):
        workspace = self._get_workspace()
        if not workspace:
            return  # User cancelled workspace selection
            
        # Ableton approach: we ask for a project *name*, and we create a folder for it in the workspace
        name, ok = QInputDialog.getText(self, "Save Project", "Project Name:", text=self.pm.project_name)
        if ok and name:
            if not name.strip().lower().endswith("project"):
                name = name.strip() + " Project"
            
            project_path = os.path.join(workspace, name)
            try:
                self.pm.save_project(project_path)
                self._update_title()
                QMessageBox.information(self, "Saved", f"Project saved to folder:\n{project_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not save: {e}")


    def _new_proj(self):
        """Reset engine and all UI to a blank project state."""
        reply = QMessageBox.question(
            self, "New Project",
            "Clear all tracks and reset all settings?\nUnsaved work will be lost.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.engine.stop()
        with self.engine.lock:
            for i in range(4):
                self.engine.tracks[i] = []
                self.engine.track_volumes[i]    = 1.0
                self.engine.track_pans[i]       = 0.0
                self.engine.track_mutes[i]      = False
                self.engine.track_solos[i]      = False
                self.engine.track_eq_lo[i]      = 0.0
                self.engine.track_eq_hi[i]      = 0.0
                self.engine.track_tape[i]       = False
                self.engine.track_rev_send[i]   = 0.0
                self.engine.track_spread[i]     = 0
                self.engine.track_chroma[i]     = 0
                self.engine.track_harmony[i]    = False
                self.engine.track_harmony_mix[i]= 0.0
                self.engine.track_pultec_enabled[i]    = False
                self.engine.track_pultec_low_boost[i]  = 0.0
                self.engine.track_pultec_low_cut[i]    = 0.0
                self.engine.track_pultec_high_boost[i] = 0.0
                self.engine.track_pultec_high_cut[i]   = 0.0
            self.engine.master_volume   = 1.0
            self.engine.master_eq_lo    = 0.0
            self.engine.master_eq_hi    = 0.0
            self.engine.loop_enabled    = False
            self.engine.current_frame   = 0
            self.engine._seek_request   = 0
        self.pm.project_dir = None
        self.setWindowTitle("STATION MASTER 4-TRACK")
        self.timeline.envelopes.clear()
        self.timeline.selected_clip = None
        self._sync_ui_to_engine()
        self._push_undo_snapshot()
        self.timeline.update()

    def _update_title(self):
        """Set window title to reflect the currently loaded project, or the default."""
        name = getattr(self.pm, "project_name", None)
        if name and name != "Untitled":
            self.setWindowTitle(f"STATION MASTER 4-TRACK  —  {name}")
        else:
            self.setWindowTitle("STATION MASTER 4-TRACK")

    def _load_proj(self):
        workspace = self._get_workspace()
        if not workspace:
            return
            
        # Ableton approach: select the project *folder* itself
        d = QFileDialog.getExistingDirectory(self, "Select Project Folder", workspace)
        if d:
            try:
                self.pm.load_project(d)
                self._sync_ui_to_engine()
                self._update_title()
                QMessageBox.information(self, "Loaded", f"Project loaded from folder:\n{d}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not load: {e}")

    def _bounce(self):
        if self.engine.get_max_length() == 0:
            QMessageBox.warning(self, "Empty", "There is no audio to bounce.")
            return
        f, _ = QFileDialog.getSaveFileName(self, "Bounce Output", "", "WAV (*.wav);;FLAC (*.flac);;MP3 (*.mp3)")
        if f:
            fmt = "WAV"
            if f.lower().endswith(".mp3"): fmt = "MP3"
            elif f.lower().endswith(".flac"): fmt = "FLAC"
            try:
                self.pm.bounce_mix(f, format=fmt)
                QMessageBox.information(self, "Bounced", f"Successfully bounced to {f}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not bounce: {e}")

    def _sum_tracks(self):
        if self.engine.is_playing or self.engine.is_recording:
            QMessageBox.warning(self, "Transport Active", "Stop the transport before summing tracks.")
            return
            
        dlg = SumTracksDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            sources, dest, delete = dlg.get_selection()
            if not sources:
                QMessageBox.warning(self, "No Sources", "You must select at least one source track.")
                return
            if dest in sources:
                QMessageBox.warning(self, "Invalid Destination", "Destination track cannot be one of the source tracks.")
                return
                
            # Warn if dest is not empty
            if len(self.engine.tracks[dest]) > 0:
                reply = QMessageBox.question(
                    self, "Destination Not Empty",
                    f"Track {dest+1} already contains clips. Overwrite?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    return
            
            success = self.engine.sum_tracks_offline(sources, dest)
            if success:
                if delete:
                    with self.engine.lock:
                        for s in sources:
                            self.engine.tracks[s] = []
                            self.engine.track_eq_lo[s] = 0.0
                            self.engine.track_eq_hi[s] = 0.0
                            self.engine.track_tape[s] = False
                            
                self.timeline.selected_clip = None
                self.timeline.selected_track = -1
                self.timeline.envelopes.clear()
                self._push_undo_snapshot()
                self._sync_ui_to_engine()
                self.timeline.update()
                QMessageBox.information(self, "Success", f"Tracks summed to Track {dest+1}.")
            else:
                QMessageBox.warning(self, "Empty", "The selected source tracks contained no audio.")

    def _screenshot(self):
        """Capture a screenshot of the main window and save it."""
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"station_screenshot_{now}.png"
        
        # Determine save directory: Project folder > ~/Pictures/Screenshots > ~
        save_dir = self.pm.project_dir
        if not save_dir or not os.path.exists(save_dir):
            save_dir = os.path.expanduser("~/Pictures/Screenshots")
            if not os.path.exists(save_dir):
                save_dir = os.path.expanduser("~")
        
        filepath = os.path.join(save_dir, filename)
        
        try:
            # Grab the window as a pixmap
            pixmap = self.grab()
            if pixmap.save(filepath, "PNG"):
                QMessageBox.information(self, "Screenshot Captured", f"Screenshot saved to:\n{filepath}")
            else:
                raise Exception("Failed to save pixmap.")
        except Exception as e:
            QMessageBox.critical(self, "Screenshot Error", f"Could not capture screenshot: {e}")

    def _toggle_logging(self, checked):
        root_logger = logging.getLogger()
        if checked:
            log_dir = os.path.join(os.path.dirname(__file__), "logs")
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_file = os.path.join(log_dir, f"session_{timestamp}.log")
            
            # File Handler
            self._log_handler = logging.FileHandler(log_file)
            formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
            self._log_handler.setFormatter(formatter)
            
            # Console Handler (Bug fix: communicating jack shit)
            self._console_handler = logging.StreamHandler(sys.stdout)
            self._console_handler.setFormatter(formatter)
            
            root_logger.setLevel(logging.DEBUG)
            root_logger.addHandler(self._log_handler)
            root_logger.addHandler(self._console_handler)
            
            logging.info("--- LOGGING STARTED ---")
            print(f"Logging to: {log_file}")
            self.btn_log.setText("DIAGNOSTICS: ON")
            # Styling already handled by stylesheet in __init__
        else:
            if self._log_handler:
                logging.info("--- LOGGING STOPPED ---")
                root_logger.removeHandler(self._log_handler)
                self._log_handler.close()
                self._log_handler = None
            
            if self._console_handler:
                root_logger.removeHandler(self._console_handler)
                self._console_handler = None
            
            self.btn_log.setText("DIAGNOSTICS: OFF")

    def closeEvent(self, event):
        """Clean up tethered synths on close."""
        for i in list(self.synth_procs.keys()):
            self._close_synth_for_track(i)
        self.engine.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MT50MainWindow()
    w.show()
    sys.exit(app.exec())
