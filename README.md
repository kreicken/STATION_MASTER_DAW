# Station Master 4-Track DAW

**Station Master 4-Track** is a high-performance, retro-styled hybrid digital audio workstation (DAW) for Linux built purely in Python. It features a 4-track recording timeline, level metering, and real-time DSP effects (EQ, Tape Saturation, Reverb, Delay) using NumPy and Pedalboard.

It also supports native "tethering" with the **Golden Bull Synthesizer**, launching it as a child process and routing virtual audio dynamically.

---

## 🛠️ Installation (Debian/Ubuntu Linux)

You can install all dependencies and set up a Desktop Launcher automatically using the installer script, or install manually.

### Option A: Automated Installation (Recommended)
This will install system audio packages, set up a python virtual environment, install requirements, and create a Desktop launcher:
```bash
git clone https://github.com/kreicken/STATION_MASTER_DAW.git
cd STATION_MASTER_DAW
chmod +x install.sh
./install.sh
```

### Option B: Manual Installation
1. Install system packages:
```bash
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv libportaudio2 libasound2-dev ffmpeg
```
2. Clone, setup virtual environment, and install dependencies:
```bash
git clone https://github.com/kreicken/STATION_MASTER_DAW.git
cd STATION_MASTER_DAW
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

---

## 🎹 Running the DAW

With your virtual environment active, run the main GUI application:
```bash
python3 main.py
```

## 📜 License
Released under the Creative Commons Zero v1.0 Universal (CC0-1.0) license.
