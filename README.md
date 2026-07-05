# Station Master 4-Track DAW

**Station Master 4-Track** is a high-performance, retro-styled hybrid digital audio workstation (DAW) for Linux built purely in Python. It features a 4-track recording timeline, level metering, and real-time DSP effects (EQ, Tape Saturation, Reverb, Delay) using NumPy and Pedalboard.

It also supports native "tethering" with the **Golden Bull Synthesizer**, launching it as a child process and routing virtual audio dynamically.

---

## 🛠️ Installation (Debian/Ubuntu Linux)

Follow these steps to set up and run the DAW on any Debian-based machine.

### 1. Install System Audio and Python Dependencies
Ensure you have the required audio backend and compression libraries installed on your system:
```bash
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv libportaudio2 libasound2-dev ffmpeg
```

### 2. Clone the Repository and Setup Virtual Environment
```bash
git clone https://github.com/kreicken/STATION_MASTER_DAW.git
cd STATION_MASTER_DAW
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
You can install the Python dependencies directly using pip:
```bash
pip install -e .
```
*(Or use `pip install -r pyproject.toml` if using a modern PEP-517/518 build tool).*

---

## 🎹 Running the DAW

With your virtual environment active, run the main GUI application:
```bash
python3 main.py
```

## 📜 License
Released under the Creative Commons Zero v1.0 Universal (CC0-1.0) license.
