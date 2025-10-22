# RetroArch Analysis Stream

RetroArch Analysis Stream captures live RetroArch gameplay on macOS, routes each frame through the OpenAI Agents SDK, and serves real-time insights through a lightweight Flask dashboard. The web UI focuses on live summaries, a Pokédex that persists recent sightings, and a chat endpoint that can run independently of the capture loop. The project is published under the MIT License and is intended for open-source experimentation.

## Features

- Automated RetroArch window capture with macOS AppleScript fallbacks.
- Frame analysis and battle summaries generated with OpenAI Agents plus PokéAPI helper tools.
- Streaming Server-Sent Events feeds for raw analyses (`/stream/analysis`) and aggregated summaries (`/stream/summaries`).
- Responsive web dashboard (vanilla JS + CSS) with dark/light theming and accent colors (`#FACC15`, `#2563EB`) tuned for accessible contrast.
- Built-in Pokédex cache that updates when the analysis stream reports new combatants.
- Standalone chat microservice (`chat_app.py`) that reuses the same agent stack without depending on the capture thread.

## Prerequisites

- macOS with screen recording and accessibility permissions granted to your terminal/IDE.
- Python 3.11 or newer.
- An OpenAI-compatible API key (set via `OPENAI_API_KEY`).
- RetroArch running in a visible window if you want to exercise the capture pipeline.

## Getting Started

Clone the repository and install dependencies into a virtual environment:

```bash
git clone https://github.com/joelb/game_analyzer.git
cd game_analyzer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file (copy from any local template if you have one) and populate at least:

```
OPENAI_API_KEY=sk-...
# Optional overrides
# MODEL=gpt-5
# OPENAI_BASE_URL=https://api.openai.com/v1
# CAPTURE_SOURCE=RetroArch
# SCREENSHOT_INTERVAL_SECONDS=2
# SUMMARY_INTERVAL=5
# STREAM_UI_PORT=5050
```

## Running the Services

- **Capture loop only**  
  ```bash
  python retroarch_capture.py
  ```

- **Capture loop + web dashboard**  
  ```bash
  python retroarch_capture.py --web
  # Visit http://localhost:5050 (configurable via STREAM_UI_HOST/PORT)
  ```

- **Chat-only microservice**  
  ```bash
  python chat_app.py
  # POST {"message": "..."} to http://localhost:5052/api/chat
  ```

- **Flask entrypoint for production hosting**  
  ```bash
  python web_app.py
  # or FLASK_APP=web_app.py flask run
  ```

The web UI renders live summaries and Pokédex updates. The raw analysis stream is still available at `/stream/analysis` for external clients even though the default UI omits the frame cards.

## Configuration Reference

| Variable | Purpose | Default |
| --- | --- | --- |
| `OPENAI_API_KEY` | Required API key | _none_ |
| `OPENAI_BASE_URL` | Alternate OpenAI-compatible base URL | `https://api.openai.com/v1` |
| `MODEL` | Primary agent model | `gpt-5` |
| `CAPTURE_SOURCE` | macOS window title to target | `RetroArch` |
| `SCREENSHOT_INTERVAL_SECONDS` | Seconds between captures | `2` |
| `SCREENSHOTS_DIR` | Output directory for screenshots | `static/images` |
| `SUMMARY_INTERVAL` / `SUMMARY_EVERY` | Captures per summary event | `5` |
| `STREAM_UI_HOST` | Bind address for dashboard | `0.0.0.0` |
| `STREAM_UI_PORT` / `WEB_APP_PORT` | Port for dashboard | `5050` |
| `CHAT_PORT` | Port when running `chat_app.py` | `5052` |
| `POKEAPI_TOOL_DEBUG` | Set to `1` to log tool traffic | unset |
| `SUMMARY_TTS_ENABLED` | Enable summary speech synthesis | `1` |
| `SUMMARY_TTS_MODEL` | OpenAI model for speech | `gpt-4o-mini-tts` |
| `SUMMARY_TTS_VOICE` | Speech voice preset | `coral` |
| `SUMMARY_TTS_FORMAT` | Output audio format | `mp3` |

## API & Streaming Endpoints

- `POST /api/chat`  
  Request: `{"message": "Who counters Bulbasaur?"}`  
  Response: `{"response": "...", "timestamp": "2024-10-22T12:34:56Z"}`

- `GET /stream/analysis` (SSE)  
  Emits frame-level analysis objects with metadata and relative asset paths.

- `GET /stream/summaries` (SSE)  
  Emits narrative recaps every `SUMMARY_INTERVAL` captures and includes optional audio references when TTS is enabled.

All payload formats are stable and match the structures used by the existing frontend.

## Project Layout

```
game_analyzer/
├── retroarch_capture.py     # Capture loop, Agents pipeline, web factory
├── web_app.py               # Flask entrypoint for hosting
├── chat_app.py              # Standalone chat service
├── pokeapi_tool.py          # PokéAPI tool wrappers for Agents
├── templates/index.html     # Dashboard template
├── static/                  # CSS, audio assets, placeholder imagery
├── test_chat.py             # Chat regression helper
├── test_window_detection.py # AppleScript window detection helper
└── README.md
```

## Development & Testing

Automated tests are minimal because the capture loop relies on screen access, but you can run the helpers:

```bash
python test_chat.py              # Exercises the chat pipeline
python test_window_detection.py  # Confirms RetroArch window detection
```

If you add pytest-based suites, install `pytest` in your environment and run `python -m pytest`.

## Troubleshooting

- **RetroArch window not found** – ensure RetroArch is visible, run `python test_window_detection.py`, or adjust `CAPTURE_SOURCE`.
- **Permission errors** – grant screen recording and accessibility rights under System Settings → Privacy & Security.
- **Unexpected agent output** – set `POKEAPI_TOOL_DEBUG=1` to log tool traffic and inspect raw responses.
- **Chat endpoint down** – confirm the API key is set; the chat workflow runs independently of the capture loop, so you can debug it without live gameplay.

## License

This project is released under the [MIT License](LICENSE). Contributions are welcome via pull requests or issues.
