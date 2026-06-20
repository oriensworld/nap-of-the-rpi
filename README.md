# nap-of-the-rpi

A Raspberry Pi 4 device that detects nearby humans, triggers a configurable laser, reports weather via text-to-speech, and accepts voice commands.

## Features

- **Human detection** — HC-SR501 PIR sensor with configurable cooldown
- **Laser reaction** — 3 patterns (solid, blink, pulse) triggered on detection
- **Weather announcements** — fetches from OpenWeatherMap, speaks via Piper TTS
- **Voice commands** — offline wake word ("hey pi") + commands via Vosk STT
- **Bluetooth speaker** — outputs to JBL Flip 6 (or any BT speaker) with 3.5mm fallback

## Hardware

| Component | Purpose | ~Price |
|-----------|---------|--------|
| Raspberry Pi 4 (4GB) Starter Kit | Main computer | $130 |
| HC-SR501 PIR sensor | Human detection (infrared) | $2-3 |
| KY-008 laser module (650nm) | Visual alert/deterrent | $2-3 |
| 220Ω resistor | GPIO protection for laser | $1 |
| Breadboard + jumper wires | Prototyping connections | $8 |
| USB microphone | Voice command input | (any USB mic) |
| Bluetooth speaker | Audio output (e.g., JBL Flip 6) | (any BT speaker) |

## Wiring

```
Raspberry Pi 4 GPIO (BCM numbering)
─────────────────────────────────────
GPIO 17  ← HC-SR501 OUT (signal)
GPIO 18  → KY-008 Signal (via 220Ω resistor)
5V       → HC-SR501 VCC, KY-008 VCC
GND      → HC-SR501 GND, KY-008 GND
USB      → USB Microphone
Bluetooth → Speaker (paired via scripts/pair_bluetooth.sh)
```

## Software Setup

### Prerequisites

- Raspberry Pi OS Bookworm (or any Debian-based Linux)
- Internet connection (for initial setup only — runs offline after)

### 1. Clone the repository

```bash
git clone https://github.com/nap-of-the-earth/nap-of-the-rpi.git
cd nap-of-the-rpi
```

### 2. Run the setup script

```bash
bash setup.sh
```

This installs:
- System packages (libportaudio2, bluetooth, pulseaudio-module-bluetooth)
- uv (Python package manager)
- Python dependencies (via `uv sync`)
- Vosk speech model (~40MB)
- Piper TTS voice model

### 3. Configure

```bash
cp config.example.yaml config.yaml
```

Edit `config.yaml`:
- Set your OpenWeatherMap API key (get one free at [openweathermap.org](https://openweathermap.org/api))
- Adjust your location
- Customize laser pattern, cooldown, wake word, etc.

```yaml
weather:
  api_key: "your-api-key-here"  # Or use env var: "${WEATHER_API_KEY}"
  location: "Your City,US"

laser:
  pattern: "blink"  # Options: solid, blink, pulse

voice:
  wake_word: "hey pi"
```

### 4. Pair Bluetooth speaker

```bash
bash scripts/pair_bluetooth.sh "JBL Flip 6"
```

### 5. Run

```bash
uv run python main.py
```

### 6. (Optional) Install as system service

```bash
sudo bash scripts/install_service.sh
```

This makes it auto-start on boot with systemd watchdog monitoring.

## Usage

### Automatic mode
Walk near the device → PIR detects you → laser activates + weather announced.

### Voice commands
Say the wake word followed by a command:

| Say | Action |
|-----|--------|
| "hey pi weather" | Announce current weather |
| "hey pi what's the weather" | Same as above |
| "hey pi laser on" | Enable laser |
| "hey pi laser off" | Disable laser |

### Configuration

All settings in `config.yaml` — no code editing needed:

| Setting | Default | Description |
|---------|---------|-------------|
| `pir.cooldown_seconds` | 10 | Min seconds between triggers |
| `laser.pattern` | blink | solid, blink, or pulse |
| `laser.duration_seconds` | 3.0 | How long laser stays active |
| `weather.units` | imperial | imperial (°F) or metric (°C) |
| `voice.wake_word` | hey pi | Custom wake word |
| `audio.bluetooth_device` | JBL Flip 6 | Your speaker name |
| `audio.fallback_to_jack` | true | Use 3.5mm if BT unavailable |

## Development

### Running tests

```bash
uv run pytest             # All tests
uv run pytest -v          # Verbose
uv run pytest tests/test_event_bus.py  # Single file
```

### Linting

```bash
uv run ruff check .       # Check
uv run ruff check --fix . # Auto-fix
```

### Project structure

```
├── main.py              # Entry point (wires modules to event bus)
├── config.example.yaml  # Configuration template
├── pyproject.toml       # Dependencies and tool config
├── setup.sh             # First-time Pi setup
├── core/
│   ├── event_bus.py     # Pub/sub event system
│   └── config.py        # YAML config loader
├── modules/
│   ├── pir_sensor.py    # PIR human detection
│   ├── laser_controller.py  # Laser patterns (solid/blink/pulse)
│   ├── weather_service.py   # OpenWeatherMap API
│   ├── tts_speaker.py      # Piper TTS + Bluetooth audio
│   └── voice_command.py     # Vosk wake word + commands
├── utils/
│   ├── logger.py        # Rotating file logger
│   └── bluetooth.py     # BT connection helper
├── tests/               # Unit + integration tests
└── scripts/
    ├── install_service.sh   # systemd service installer
    └── pair_bluetooth.sh    # BT speaker pairing
```

### Architecture

Event-driven design — modules communicate via pub/sub events, not direct calls:

```
PIR Sensor ──→ "human_detected" ──→ Laser Controller
                                ──→ Weather Service ──→ "weather_ready" ──→ TTS Speaker
Voice Command ──→ "command_weather" ──→ Weather Service
              ──→ "command_laser_on/off" ──→ Laser Controller
```

## Troubleshooting

**Tests fail with `ModuleNotFoundError`**
Use `uv run pytest` instead of plain `pytest`. The project dependencies are in the `.venv` managed by uv.

**"Weather data is currently unavailable"**
Check your API key in `config.yaml` and internet connection. The free OpenWeatherMap tier allows 1000 calls/day.

**Bluetooth speaker won't connect**
1. Make sure the speaker is in pairing mode
2. Run `bash scripts/pair_bluetooth.sh "Your Speaker Name"`
3. Check with `bluetoothctl info` to verify pairing

**PIR sensor triggers too often**
Increase `pir.cooldown_seconds` in config.yaml. Also check the physical potentiometers on the HC-SR501 module (sensitivity and delay).

**Laser doesn't turn on**
1. Check wiring (GPIO 18 → 220Ω resistor → KY-008 signal)
2. Verify with `uv run python -c "from gpiozero import LED; led = LED(18); led.on()"`

**Voice commands not recognized**
1. Check USB mic is connected: `arecord -l`
2. Ensure Vosk model is downloaded: `ls models/vosk-model-small-en-us/`
3. Speak clearly, close to the mic, after the wake word

## License

MIT
