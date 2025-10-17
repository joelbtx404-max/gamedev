# RetroArch Game Analyzer

Capture RetroArch gameplay on macOS, analyze each frame with the OpenAI Agents SDK, and stream results through a live web UI and Pokedex-aware chat experience. The capture loop, streaming server, and chat workflow now run independently so the chat endpoint stays responsive even when the capture service is offline.

## Key Capabilities

- Automated RetroArch window capture with macOS AppleScript fallbacks.
- Frame-by-frame analysis and summaries driven by OpenAI Agents and the PokeAPI helper tools.
- Streaming Server-Sent Events feeds for analyses (`/stream/analysis`) and summaries (`/stream/summaries`).
- Built-in PokeAPI chat endpoint (`/api/chat`) that shares the same agent stack but no longer depends on the capture thread's asyncio loop.
- Dark-mode web dashboard with live analysis cards, rolling summaries, and a persistent Pokedex sidebar.
- Standalone Flask wrapper (`chat_app.py`) for lightweight chat-only deployments.

## Requirements

- macOS with accessibility permissions for your terminal or IDE (AppleScript + `screencapture`).
- Python 3.11 or newer.
- An OpenAI API key (or compatible API key/base URL).
- Optional: RetroArch running with a visible window for capture tests.

## Quick Start

1. **Create a virtual environment and install dependencies**
   ```bash
   cd game_analyzer
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure environment variables**

   Copy your local secrets file if you keep one (for example `cp .env.local .env`) and populate at least:

   ```
   OPENAI_API_KEY=sk-...
   # Optional overrides:
   # MODEL=gpt-4o
   # OPENAI_BASE_URL=https://api.openai.com/v1
   # CAPTURE_SOURCE=RetroArch
   # SCREENSHOT_INTERVAL_SECONDS=2
   # SUMMARY_INTERVAL=5
   # STREAM_UI_PORT=5050
   ```

   All services load `.env` automatically through `python-dotenv`.

3. **Verify window detection (recommended on first run)**
   ```bash
   python test_window_detection.py
   ```

4. **Choose a runtime mode**

   - Terminal capture loop with console logging:
     ```bash
     python retroarch_capture.py
     ```
   - Web streaming UI (live dashboard + chat):
     ```bash
     python retroarch_capture.py --web
     # Visit http://localhost:5050 (or your STREAM_UI_HOST/PORT)
     ```
   - Chat-only microservice:
     ```bash
     python chat_app.py
     # POST {"message": "..."} to http://localhost:5052/api/chat
     ```

## Runtime Overview

- **Capture loop** - runs in its own daemon thread and drives screenshot capture, Agent analysis, and summary generation. Screenshots land in `static/images` by default.
- **Streaming API** - the Flask app exposes two SSE endpoints (`/stream/analysis`, `/stream/summaries`) that the web dashboard and other clients can consume.
- **Chat service** - `POST /api/chat` responds with PokeAPI-backed insights using the shared agent configuration. The handler now works from any request thread without requiring access to the capture thread's asyncio loop.
- **Standalone web entrypoint** - `python web_app.py` (or `FLASK_APP=web_app.py flask run`) launches the same dashboard for hosting scenarios that rely on Flask's CLI.

## Configuration Reference (`.env`)

| Variable | Purpose | Default |
| --- | --- | --- |
| `OPENAI_API_KEY` | Required API key for the Agents SDK | _none_ |
| `OPENAI_BASE_URL` | Alternate API base (OpenAI-compatible) | `https://api.openai.com/v1` |
| `MODEL` | Agents model id | `gpt-5` |
| `CAPTURE_SOURCE` | macOS process/window name to target | `RetroArch` |
| `SCREENSHOT_INTERVAL_SECONDS` | Seconds between captures | `2` |
| `SCREENSHOTS_DIR` | Output directory for screenshots | `static/images` |
| `SUMMARY_INTERVAL` or `SUMMARY_EVERY` | Captures between summaries | `5` |
| `STREAM_UI_HOST` | Host for the web UI | `0.0.0.0` |
| `STREAM_UI_PORT` / `WEB_APP_PORT` | Port for the web UI | `5050` |
| `CHAT_PORT` | Port when running `chat_app.py` | `5052` |
| `POKEAPI_TOOL_DEBUG` | Set to `1` to log tool traffic | unset |
| `SUMMARY_TTS_ENABLED` | Toggle summary text-to-speech synthesis | `1` |
| `SUMMARY_TTS_MODEL` | OpenAI model used for summary speech | `gpt-4o-mini-tts` |
| `SUMMARY_TTS_VOICE` | Voice preset for summary speech | `coral` |
| `SUMMARY_TTS_FORMAT` | Desired audio format (falls back to mp3 currently) | `mp3` |

## API & Event Payloads

- **`POST /api/chat`** - `{ "message": "Who is Pikachu weak against?" }` -> `{ "response": "...", "timestamp": "..." }`
- **SSE `/stream/analysis`** - emits structured JSON payloads with battle detection metadata and relative screenshot paths.
- **SSE `/stream/summaries`** - fires every `SUMMARY_INTERVAL` captures with a concise progress narrative.

All endpoints preserve their previous response shapes so existing clients continue to work.

## Output Schema

Example frame analysis:
```json
{
  "game_name": "Pokemon Black",
  "scene": "battle",
  "characters": [
    {
      "name": "Tepig",
      "level": 6,
      "hp_current": 21,
      "hp_max": 25,
      "status": "normal"
    }
  ],
  "environment": "grassy field",
  "notable_events": "Player's turn to select action"
}
```

Summaries are short natural-language recaps keyed to the same capture cadence.

## Troubleshooting

- **"RetroArch window not found"** - ensure RetroArch is visible, run `python test_window_detection.py`, or set `CAPTURE_SOURCE` to the correct process name. The capture loop falls back to full-screen grabs if bounds cannot be resolved.
- **"Chat error: There is no current event loop..."** - update to the latest code (this README) which initializes a loop inside the chat worker when needed.
- **Permission errors** - macOS may prompt for screen recording and accessibility access; enable Terminal/IDE in System Settings -> Privacy & Security.
- **Unexpected JSON** - enable `POKEAPI_TOOL_DEBUG=1` to log agent tool calls and inspect the raw responses in the console.

## Testing

- Run the lightweight chat regression test:
  ```bash
  python test_chat.py
  ```
- Additional window detection checks live in `test_window_detection.py`. The capture loop relies on live screenshots, so no full unit suite exists yet.

## Project Layout

```
game_analyzer/
|--- retroarch_capture.py   # Capture loop, Agents pipeline, web factory
|--- web_app.py             # Gunicorn/Flask entrypoint
|--- chat_app.py            # Standalone chat microservice
|--- pokeapi_tool.py        # PokeAPI tool wrappers used by Agents
|--- templates/index.html   # Streaming dashboard UI
|--- static/                # CSS, JS, image output
|--- test_chat.py           # Chat regression helper
|--- test_window_detection.py
`--- README.md
```

## Next Steps

1. Populate `.env` with your `OPENAI_API_KEY`.
2. Launch `python retroarch_capture.py --web` and watch the dashboard populate while RetroArch runs.
3. Exercise `POST /api/chat` to confirm the chat service responds independently of the capture loop.
