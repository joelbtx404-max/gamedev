# Repository Guidelines

## Project Structure & Module Organization
- `retroarch_capture.py` – primary capture loop; handles window detection, screen grabs, agent orchestration, and local stat caching.
- `pokeapi_tool.py` – PokeAPI function tools registered with the Agents SDK. Each tool caches responses and respects `POKEAPI_BASE_URL`.
- `static/images/` – default screenshot sink; keep large artifacts out of version control.
- `reference/` – upstream OpenAI and PokéAPI docs; treat as read-only.
- `test_manual.py`, `agentssdk_test.py` – scripted smoke checks for API calls and the Agents SDK bootstrap.

## Build, Test, and Development Commands
- `python -m venv venv && source venv/bin/activate` – create and enter the local virtual environment.
- `pip install -r requirements.txt` – install `openai`, `openai-agents`, `requests`, and supporting libs.
- `python retroarch_capture.py` – run the full capture + analysis loop using the configured model and tools.
- `python test_manual.py` – send a static frame through the Responses API to validate prompting and parsing.
- `python agentssdk_test.py` – verify the Agents SDK wiring outside the capture loop.

## Coding Style & Naming Conventions
- Python 3.11+, 4-space indentation, type hints on all public functions, and concise inline comments where behavior is non-obvious.
- Keep identifiers snake_case; tool names should mirror their API target (e.g., `fetch_move_details`).
- Maintain ASCII output unless upstream files require otherwise; prefer f-strings and explicit error messaging.

## Testing Guidelines
- Favor targeted scripts over broad suites: run `python test_manual.py` after prompt or tool tweaks, and exercise `python retroarch_capture.py` for end-to-end validation.
- When adding new tools, introduce a focused script or fixture demonstrating the call sequence; name it `test_<feature>.py`.
- Capture logs showing tool invocations when debugging eagerness; redact API keys from shared output.

## Commit & Pull Request Guidelines
- Follow the existing history: short, imperative subject lines (`Add`, `Update`, `Fix`). Group related changes into a single commit.
- PRs should include: overview of behavior changes, testing evidence (commands + results), and screenshots or logs for UI/CLI output when relevant.
- Link to any reference docs updated in `reference/` and call out configuration changes to `.env` or `requirements.txt`.

## Configuration & Security Notes
- Copy `env.example` to `.env`; populate `OPENAI_API_KEY`, `MODEL`, and optional `POKEAPI_BASE_URL` for proxies.
- Never commit real keys or screenshots containing private data. Use throwaway captures for docs and reviews.
