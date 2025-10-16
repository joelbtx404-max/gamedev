import argparse
import asyncio
import base64
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

from dotenv import load_dotenv
from flask import Flask, Response, render_template, stream_with_context, request, jsonify
from pokeapi_tool import (
    fetch_pokemon_profile, 
    fetch_pokemon_gender,
    fetch_pokemon_abilities,
    fetch_pokemon_moves,
    fetch_pokemon_types,
    fetch_pokemon_items,
    fetch_pokemon_locations,
    pull_latest_pokemon_calls
)

try:
    from agents import Agent, ModelSettings, Runner
except Exception as exc:  # pragma: no cover
    print("openai-agents is required. pip install openai-agents", file=sys.stderr)
    raise

# Ensure environment variables from .env are available whenever this module is imported.
load_dotenv()


def load_config():
    load_dotenv()
    port_env = os.getenv("STREAM_UI_PORT") or os.getenv("WEB_APP_PORT")
    if port_env:
        try:
            ui_port = int(port_env)
        except ValueError as exc:  # pragma: no cover - configuration error
            raise RuntimeError("STREAM_UI_PORT/WEB_APP_PORT must be an integer") from exc
    else:
        ui_port = 5050

    summary_interval_env = os.getenv("SUMMARY_INTERVAL") or os.getenv("SUMMARY_EVERY")
    if summary_interval_env:
        try:
            summary_interval = int(summary_interval_env)
        except ValueError as exc:  # pragma: no cover - configuration error
            raise RuntimeError("SUMMARY_INTERVAL must be an integer") from exc
        if summary_interval <= 0:
            raise RuntimeError("SUMMARY_INTERVAL must be >= 1")
    else:
        summary_interval = 5

    cfg = {
        "interval": float(os.getenv("SCREENSHOT_INTERVAL_SECONDS", "2")),
        "app_name": os.getenv("CAPTURE_SOURCE", "RetroArch"),
        "model": os.getenv("MODEL", "gpt-5"),
        "api_key": os.getenv("OPENAI_API_KEY"),
        "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "out_dir": Path(os.getenv("SCREENSHOTS_DIR", str(Path(__file__).resolve().parent / "static" / "images"))).resolve(),
        "ui_host": os.getenv("STREAM_UI_HOST", "0.0.0.0"),
        "ui_port": ui_port,
        "summary_interval": summary_interval,
    }
    missing = [k for k in ("api_key",) if not cfg[k]]
    if missing:
        raise RuntimeError(f"Missing required env var(s): {', '.join(missing)}")
    return cfg


def ensure_out_dir(path: Path, clear: bool = False) -> None:
    """Ensure the screenshot output directory exists and optionally purge old captures."""
    path.mkdir(parents=True, exist_ok=True)
    if not clear:
        return
    for item in path.iterdir():
        try:
            if item.is_file() or item.is_symlink():
                item.unlink()
            else:
                shutil.rmtree(item)
        except Exception as exc:  # pragma: no cover
            print(f"Failed to remove stale capture '{item}': {exc}")


def list_all_windows() -> list[tuple[str, str]]:
    """
    Return a list of (process_name, window_name) for all visible windows.
    Useful for debugging window detection issues.
    """
    script = '''
    tell application "System Events"
        set windowList to {}
        repeat with proc in (every process whose visible is true)
            set procName to name of proc
            try
                repeat with win in (windows of proc)
                    set winName to name of win
                    set end of windowList to procName & " | " & winName
                end repeat
            end try
        end repeat
        return windowList
    end tell
    '''
    try:
        result = subprocess.run([
            "osascript", "-e", script
        ], capture_output=True, text=True, check=True)
        out = result.stdout.strip()
        if not out:
            return []
        # Parse the list format from AppleScript
        items = out.split(", ")
        windows = []
        for item in items:
            if " | " in item:
                parts = item.split(" | ", 1)
                windows.append((parts[0].strip(), parts[1].strip()))
        return windows
    except Exception:
        return []


def osascript_get_bounds(app_name: str) -> tuple[int, int, int, int] | None:
    """
    Return (x, y, width, height) of the front window of app_name.
    Uses AppleScript via osascript. Returns None if not available.
    """
    script = f'''
    tell application "System Events"
        if exists process "{app_name}" then
            tell process "{app_name}"
                if exists window 1 then
                    set b to bounds of window 1
                    return b
                else
                    return "NO_WINDOW"
                end if
            end tell
        else
            return "NO_PROCESS"
        end if
    end tell
    '''
    try:
        result = subprocess.run([
            "osascript", "-e", script
        ], capture_output=True, text=True, check=True)
        out = result.stdout.strip()
        if out in ("NO_WINDOW", "NO_PROCESS", ""):
            return None
        # AppleScript bounds are: left, top, right, bottom
        parts = [int(p.strip()) for p in out.replace("{", "").replace("}", "").split(",")]
        if len(parts) != 4:
            return None
        left, top, right, bottom = parts
        width = max(0, right - left)
        height = max(0, bottom - top)
        if width == 0 or height == 0:
            return None
        return left, top, width, height
    except subprocess.CalledProcessError:
        return None
    except Exception:
        return None


def screencapture_png(out_path: Path, rect: tuple[int, int, int, int] | None) -> bool:
    """
    Capture a region (x,y,w,h) if rect is provided; otherwise full screen.
    Requires macOS 'screencapture' CLI.
    """
    try:
        if rect:
            x, y, w, h = rect
            cmd = [
                "screencapture", "-x", "-t", "png", f"-R{x},{y},{w},{h}", str(out_path),
            ]
        else:
            cmd = ["screencapture", "-x", "-t", "png", str(out_path)]
        subprocess.run(cmd, check=True)
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception as exc:
        print(f"Capture failed: {exc}")
        return False


def encode_image_b64(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def build_agents(model_name: str) -> tuple[Agent, Agent]:
    """Create analysis and summary Agents using default Agents SDK configuration."""

    analysis_instructions = (
        "You are a game analysis assistant that provides structured JSON about the on-screen Pokémon gameplay. "
        "Identify the game state from the RetroArch window and output only the required JSON schema.\n\n"
        "<persistence>\n"
        "- You are an agent; continue until the frame is fully analyzed and the JSON schema is ready.\n"
        "- Finalize only after the battle flow and verification checks below are satisfied.\n"
        "- When uncertain, make the most reasonable inference from the frame or fetched data and record any uncertainty inside the JSON text fields.\n"
        "- Do not ask the user for clarification; document assumptions, act on them, and adjust if new evidence appears.\n"
        "</persistence>\n\n"
        "<context_gathering>\n"
        "Goal: Capture enough frame context to populate every JSON field accurately.\n\n"
        "Method:\n"
        "- Start with a broad scan to decide whether the scene is a battle.\n"
        "- Sweep the UI to read Pokémon names, HP bars, levels, and status icons before zooming into details.\n"
        "- Reuse cached knowledge from prior frames when the same Pokémon reappears, but revalidate HP and status each frame.\n"
        "- Avoid redundant passes; if a detail stays unreadable, flag it instead of looping indefinitely.\n\n"
        "Early stop criteria:\n"
        "- Battle state classification is complete.\n"
        "- Each combatant is named or explicitly marked unreadable.\n"
        "- Required HP and status details are captured or noted as unknown.\n\n"
        "Escalate once:\n"
        "- If names, HP, or status indicators conflict, run one focused re-check before moving on.\n\n"
        "Depth:\n"
        "- Track only details needed for the schema (names, levels, HP fractions, status effects, notable events).\n\n"
        "Loop:\n"
        "- Frame scan -> minimal plan -> execute tool calls -> fill JSON.\n"
        "- Revisit recognition only if verification fails or new uncertainty appears.\n"
        "</context_gathering>\n\n"
        "<tool_preambles>\n"
        "- Before the first tool call, restate the battle analysis goal and list the Pokémon you will query with fetch_pokemon_profile.\n"
        "- Outline a concise plan for this frame covering battle detection, roster capture, tool calls, and JSON assembly.\n"
        "- When issuing each tool call, note internally which Pokémon you are enriching and why.\n"
        "- Keep these preambles internal; the final assistant message must remain pure JSON.\n"
        "- After tool calls finish, confirm internally that the plan is complete before composing the JSON.\n"
        "</tool_preambles>\n\n"
        "<verification>\n"
        "- Confirm every Pokémon name in the JSON triggered exactly one fetch_pokemon_profile call this frame or was marked unreadable.\n"
        "- Validate that the JSON matches the schema exactly with no extra keys or narrative text.\n"
        "- Re-check HP and status entries against the screenshot before finalizing.\n"
        "</verification>\n\n"
        "<efficiency>\n"
        "- Operate decisively: avoid duplicate tool calls and ignore UI elements unrelated to the schema.\n"
        "- Prefer action over indecisive loops; once checks pass, finalize promptly.\n"
        "</efficiency>\n\n"
        "Battle flow you MUST follow:\n"
        "1. Detect whether the frame is a battle.\n"
        "2. List every clearly readable Pokémon name participating in the battle.\n"
        "3. For each identified Pokémon, call fetch_pokemon_profile(name) exactly once during this frame. No other tool calls are available.\n"
        "4. Integrate the fetched data (stats, types, abilities) into your reasoning before writing the final JSON.\n\n"
        "Tool rule: fetch_pokemon_profile is the ONLY tool available (budget 10 calls per frame). Never include tool outputs in your final message.\n\n"
        "Respond with ONLY a JSON object (no markdown, no extra text). The JSON must have these fields: "
        "game_name (string), scene (string), characters (array of {name, level, hp_current, hp_max, status}), "
        "environment (string), notable_events (string)."
    )
    summary_instructions = (
        "You are a game progress summarizer. Produce 2–3 sentences highlighting the battle context and referencing any Pokémon stats, types, or abilities fetched via fetch_pokemon_profile that influenced the outcome."
    )

    analysis_agent = Agent(
        name="GameAnalyzer",
        instructions=analysis_instructions,
        tools=[fetch_pokemon_profile],
        model_settings=ModelSettings(
            tool_choice="required",
        ),
    )
    summary_agent = Agent(name="GameSummarizer", instructions=summary_instructions)

    return analysis_agent, summary_agent


def build_chat_agent(model_name: str) -> Agent:
    """Create a PokéAPI chat agent with all available tools."""
    
    chat_instructions = (
        "You are a helpful PokéAPI assistant that can answer questions about Pokémon using the PokéAPI. "
        "You have access to various PokéAPI endpoints including:\n"
        "- Pokémon profiles (stats, types, abilities, moves)\n"
        "- Gender ratios\n"
        "- Ability details\n"
        "- Move information\n"
        "- Type effectiveness\n"
        "- Items and locations\n\n"
        "Always use the appropriate tool to fetch data and provide comprehensive answers. "
        "If a user asks about something not available in PokéAPI, politely explain the limitations. "
        "Format your responses in a clear, conversational manner."
    )
    
    return Agent(
        name="PokéAPIChat",
        instructions=chat_instructions,
        tools=[
            fetch_pokemon_profile,
            fetch_pokemon_gender,
            fetch_pokemon_abilities,
            fetch_pokemon_moves,
            fetch_pokemon_types,
            fetch_pokemon_items,
            fetch_pokemon_locations,
        ],
        model_settings=ModelSettings(
            tool_choice="auto",
        ),
    )


def process_chat_message(agent: Agent, message: str) -> str:
    """Process a chat message using the PokéAPI agent."""
    def _run_sync() -> Any:
        return Runner.run_sync(
            agent,
            input=message,
        )

    try:
        run = _run_sync()
    except RuntimeError as exc:
        error_text = str(exc).lower()
        if "no current event loop" not in error_text and "event loop is closed" not in error_text:
            raise
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            run = _run_sync()
        finally:
            asyncio.set_event_loop(None)
            loop.close()
    return extract_final_output(run)


def build_analysis_prompt() -> str:
    """Return the base analysis prompt for frame evaluation."""
    return (
        "IMPORTANT: Analyze ONLY the RetroArch game window. Ignore any code editors, desktop elements, or other applications. "
        "Focus exclusively on the game content displayed in RetroArch.\n"
        "Before calling tools, emit a brief tool preamble (internal only) that restates the battle goal and lists the Pokémon you will query via fetch_pokemon_profile. "
        "Call fetch_pokemon_profile proactively (budget 10 per frame) for each clearly identified Pokémon in the battle. No other tools are available. "
        "Do not include any preamble or tool outputs in your final message.\n\n"
        "Respond with ONLY a JSON object (no markdown, no extra text). The JSON must have these fields:\n"
        "- game_name: string (e.g., 'Pokemon Black', 'Pokemon HeartGold')\n"
        "- scene: string (brief description: 'battle', 'overworld', 'menu', etc.)\n"
        "- characters: array of objects with {name: string, level: int, hp_current: int, hp_max: int, status: string}\n"
        "- environment: string (brief description of the environment/setting)\n"
        "- notable_events: string (any significant action happening, or 'none')\n"
        "Example: {\"game_name\": \"Pokemon Black\", \"scene\": \"battle\", \"characters\": [{\"name\": \"Tepig\", \"level\": 6, \"hp_current\": 21, \"hp_max\": 25, \"status\": \"normal\"}], \"environment\": \"grassy field\", \"notable_events\": \"Player's turn to select action\"}"
    )


def _emit(handlers: Iterable[Callable[[dict[str, Any]], None]], payload: dict[str, Any]) -> None:
    for handler in handlers:
        try:
            handler(payload)
        except Exception as exc:  # pragma: no cover
            print(f"Callback error: {exc}", file=sys.stderr)


def _relative_image_path(path: Path) -> str:
    try:
        rel = path.relative_to(Path(__file__).resolve().parent)
        return str(rel).replace(os.sep, "/")
    except ValueError:
        return str(path)


def _default_analysis_handler(payload: dict[str, Any]) -> None:
    if payload.get("type") != "analysis":
        return

    timestamp = payload.get("timestamp", "")
    data = payload.get("data") or {}
    print(f"[{timestamp}] Frame Analysis:\n{json.dumps(data, indent=2)}\n")

    meta = payload.get("meta") or {}
    battle_detected = str(meta.get("battle_detected", False)).lower()
    participants = meta.get("participants") or []
    participants_str = " vs. ".join(participants) if participants else "none"
    tool_state = "called successfully" if meta.get("tool_called") else "not called"
    stats_integrated = str(meta.get("stats_integrated", False)).lower()

    print("=== Agent Battle Flow Log ===")
    print(f"Battle detected -> {battle_detected}")
    print(f"Participants identified -> {participants_str}")
    print(f"pokeapi_tool (pokemon endpoint) -> {tool_state}")
    print(f"Stats integrated -> {stats_integrated}")
    print("=== Verification ===")
    print("Tool usage restricted to Pokémon endpoint -> confirmed\n")

    capture_index = payload.get("capture_index")
    if capture_index is not None:
        print(f"DEBUG: Capture count: {capture_index}\n")


def _default_summary_handler(payload: dict[str, Any]) -> None:
    if payload.get("type") != "summary":
        return

    interval = payload.get("interval")
    window = payload.get("window")
    new_frames = payload.get("delta", window)
    capture_total = payload.get("capture_total", window or 0)
    timestamp = payload.get("timestamp", "")
    summary = payload.get("summary", "")

    print("=" * 60)
    headline = "UPDATED CUMULATIVE SUMMARY"
    if interval:
        headline += f" (every {interval} captures)"
    details: list[str] = []
    if new_frames:
        details.append(f"new frames: {new_frames}")
    details.append(f"total captures: {capture_total}")
    detail_str = " | ".join(details)
    print(f"{headline} | {detail_str}")
    print("=" * 60)
    print(f"[{timestamp}] Summary:\n{summary}\n")
    print("=" * 60 + "\n")


def _default_error_handler(payload: dict[str, Any]) -> None:
    message = payload.get("message", "Analysis error")
    timestamp = payload.get("timestamp")
    prefix = f"[{timestamp}] " if timestamp else ""
    print(f"{prefix}{message}")

    raw = payload.get("raw")
    if raw:
        print(f"{raw}\n")


class BroadcastChannel:
    """Lightweight pub/sub channel backed by per-subscriber queues."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue[Dict[str, Any]]] = []

    def subscribe(self) -> queue.Queue[Dict[str, Any]]:
        subscriber: queue.Queue[Dict[str, Any]] = queue.Queue()
        with self._lock:
            self._subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[Dict[str, Any]]) -> None:
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def publish(self, payload: Dict[str, Any]) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber.put(payload)


analysis_channel = BroadcastChannel()
summary_channel = BroadcastChannel()
_capture_thread: threading.Thread | None = None
_capture_lock = threading.Lock()


def _event_response(channel: BroadcastChannel) -> Response:
    def generator() -> Any:
        q = channel.subscribe()
        try:
            while True:
                try:
                    payload = q.get(timeout=10)
                except queue.Empty:
                    yield ": keep-alive\n\n"
                    continue
                yield f"data: {json.dumps(payload)}\n\n"
        finally:
            channel.unsubscribe(q)

    response = Response(stream_with_context(generator()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response

def extract_final_output(run_result) -> str:
    """Extract final string output from an Agents SDK run result."""
    try:
        out = getattr(run_result, "final_output", None)
        if isinstance(out, str):
            return out
        if out is not None:
            return str(out)
    except Exception:
        pass
    return ""


def analyze_image(agent: Agent, image_path: Path, prompt: str) -> str:
    # Use structured multimodal content so the image is not tokenized as text.
    # This adheres to Agents SDK/Responses input item guidelines.
    b64 = encode_image_b64(image_path)
    user_message = {
        "role": "user",
        "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": f"data:image/png;base64,{b64}", "detail": "high"},
        ],
    }

    run = Runner.run_sync(
        agent,
        input=[user_message],
    )
    return extract_final_output(run)


def generate_summary(agent: Agent, analyses: list[dict], previous_summary: str = "") -> str:
    """Generate or update a cumulative summary based on new analyses."""

    latest_count = len(analyses)
    prompt_parts: list[str] = [
        "You are maintaining a cumulative summary of an ongoing Pokémon gameplay session.",
        "Incorporate the new frame analyses into the running summary while preserving important context from earlier notes.",
    ]

    if previous_summary:
        prompt_parts.append("Current cumulative summary:\n" + previous_summary)
    else:
        prompt_parts.append("Current cumulative summary: (none yet – begin one now.)")

    prompt_parts.append(f"New frame analyses to integrate ({latest_count}):")
    for i, analysis in enumerate(analyses, 1):
        prompt_parts.append(f"Frame +{i}:\n{json.dumps(analysis, indent=2)}")

    prompt_parts.append(
        "Respond with the refreshed cumulative summary (3-4 sentences). "
        "Highlight major events, progress, battles, party updates, and notable location changes without repeating irrelevant details."
    )

    summary_text = "\n\n".join(prompt_parts)

    if latest_count == 0:
        return previous_summary

    run = Runner.run_sync(
        agent,
        input=summary_text,
    )
    output = extract_final_output(run).strip()
    return output or previous_summary


def run_capture_loop(
    cfg: dict[str, Any],
    analysis_agent: Agent,
    summary_agent: Agent,
    prompt: str,
    *,
    analysis_handlers: Optional[Iterable[Callable[[dict[str, Any]], None]]] = None,
    summary_handlers: Optional[Iterable[Callable[[dict[str, Any]], None]]] = None,
    error_handlers: Optional[Iterable[Callable[[dict[str, Any]], None]]] = None,
    stop_event: Optional[Any] = None,
) -> None:
    """Run the continuous capture loop, emitting payloads via the provided handlers."""

    handlers_analysis = list(analysis_handlers) if analysis_handlers else [_default_analysis_handler]
    handlers_summary = list(summary_handlers) if summary_handlers else [_default_summary_handler]
    handlers_error = list(error_handlers) if error_handlers else [_default_error_handler]

    summary_interval = int(cfg.get("summary_interval", 5) or 5)
    if summary_interval <= 0:
        summary_interval = 5

    recent_analyses: list[dict[str, Any]] = []
    capture_count = 0
    cumulative_summary = ""
    last_summary_len = 0

    while True:
        if stop_event is not None and hasattr(stop_event, "is_set"):
            try:
                if stop_event.is_set():
                    break
            except Exception:  # pragma: no cover
                pass

        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = cfg["out_dir"] / f"retroarch_{now}.png"

        bounds = osascript_get_bounds(cfg["app_name"])  # None -> full screen
        if bounds is None:
            if capture_count == 0:
                print(f"WARNING: '{cfg['app_name']}' window not found, falling back to full screen capture.")
                print(f"Run 'python test_window_detection.py' to troubleshoot.\n")
        else:
            if capture_count == 0:
                x, y, w, h = bounds
                print(f"✓ Detected '{cfg['app_name']}' window: {w}x{h} at ({x}, {y})\n")

        ok = screencapture_png(out_path, bounds)
        if not ok:
            _emit(
                handlers_error,
                {
                    "type": "analysis_error",
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "message": "Screenshot failed; retrying after interval...",
                    "image_path": _relative_image_path(out_path),
                },
            )
            time.sleep(cfg["interval"])
            continue

        try:
            content = analyze_image(analysis_agent, out_path, prompt)
        except Exception as exc:
            _emit(
                handlers_error,
                {
                    "type": "analysis_error",
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "message": f"Analysis error: {exc}",
                    "image_path": _relative_image_path(out_path),
                },
            )
            time.sleep(cfg["interval"])
            continue

        data: dict[str, Any] | None = None
        parsed_successfully = False

        try:
            data = json.loads(content)
            parsed_successfully = True
        except json.JSONDecodeError:
            content_stripped = content.strip()
            if content_stripped.startswith("```"):
                lines = content_stripped.split("\n")
                json_lines: list[str] = []
                in_json = False
                for line in lines:
                    if line.startswith("```"):
                        if in_json:
                            break
                        in_json = True
                        continue
                    if in_json:
                        json_lines.append(line)
                try:
                    data = json.loads("\n".join(json_lines))
                    parsed_successfully = True
                except json.JSONDecodeError:
                    parsed_successfully = False

        timestamp = datetime.now().isoformat(timespec="seconds")
        image_relative = _relative_image_path(out_path)

        if parsed_successfully and data is not None:
            latest_calls = pull_latest_pokemon_calls()
            scene_text = str(data.get("scene", "")).lower()
            battle_detected = "battle" in scene_text
            participants = [
                str((ch or {}).get("name", "")).strip()
                for ch in (data.get("characters") or [])
                if str((ch or {}).get("name", "")).strip()
            ]
            call_names = {
                str(name).lower()
                for entry in latest_calls
                for name in entry.get("names", [])
            }
            tool_called = bool(latest_calls)
            stats_integrated = (
                battle_detected
                and bool(participants)
                and all(name.lower() in call_names for name in participants)
            )

            recent_analyses.append(data)
            capture_count += 1

            analysis_payload = {
                "type": "analysis",
                "timestamp": timestamp,
                "image_path": image_relative,
                "data": data,
                "raw": content,
                "capture_index": capture_count,
                "meta": {
                    "battle_detected": battle_detected,
                    "participants": participants,
                    "tool_called": tool_called,
                    "stats_integrated": stats_integrated,
                    "latest_calls": latest_calls,
                },
            }
            _emit(handlers_analysis, analysis_payload)

            if capture_count % summary_interval == 0:
                new_entries = recent_analyses[last_summary_len:]
                if new_entries:
                    try:
                        summary = generate_summary(summary_agent, new_entries, cumulative_summary)
                        cumulative_summary = summary
                        last_summary_len = len(recent_analyses)
                        summary_timestamp = datetime.now().isoformat(timespec="seconds")
                        summary_payload = {
                            "type": "summary",
                            "timestamp": summary_timestamp,
                            "summary": cumulative_summary,
                            "capture_total": capture_count,
                            "window": len(new_entries),
                            "delta": len(new_entries),
                            "interval": summary_interval,
                            "cumulative": True,
                        }
                        _emit(handlers_summary, summary_payload)
                    except Exception as exc:
                        _emit(
                            handlers_error,
                            {
                                "type": "analysis_error",
                                "timestamp": datetime.now().isoformat(timespec="seconds"),
                                "message": f"Summary generation error: {exc}",
                            },
                        )
        else:
            _emit(
                handlers_error,
                {
                    "type": "analysis_error",
                    "timestamp": timestamp,
                    "message": "Failed to parse JSON. Raw response:",
                    "raw": content,
                    "image_path": image_relative,
                },
            )

        time.sleep(cfg["interval"])

def start_capture_thread(
    cfg: dict[str, Any],
    analysis_agent: Agent,
    summary_agent: Agent,
    prompt: str,
) -> None:
    """Ensure the capture loop runs in a daemon thread for streaming."""

    global _capture_thread

    ensure_out_dir(cfg["out_dir"], clear=False)

    with _capture_lock:
        if _capture_thread and _capture_thread.is_alive():
            return

        def handle_analysis(payload: Dict[str, Any]) -> None:
            analysis_channel.publish(payload)

        def handle_summary(payload: Dict[str, Any]) -> None:
            summary_channel.publish(payload)

        def handle_error(payload: Dict[str, Any]) -> None:
            analysis_channel.publish(payload)

        def loop() -> None:
            # Set up event loop for this thread so async operations work
            asyncio.set_event_loop(asyncio.new_event_loop())
            run_capture_loop(
                cfg,
                analysis_agent,
                summary_agent,
                prompt,
                analysis_handlers=[handle_analysis],
                summary_handlers=[handle_summary],
                error_handlers=[handle_error],
            )

        _capture_thread = threading.Thread(target=loop, name="capture-loop", daemon=True)
        _capture_thread.start()


def _create_web_app(
    cfg: dict[str, Any],
    analysis_agent: Agent,
    summary_agent: Agent,
    prompt: str,
) -> Flask:
    app = Flask(__name__)
    
    # Create chat agent
    chat_agent = build_chat_agent(cfg["model"])

    def ensure_thread() -> None:
        start_capture_thread(cfg, analysis_agent, summary_agent, prompt)

    @app.route("/")
    def index() -> str:
        ensure_thread()
        return render_template("index.html")

    @app.route("/stream/analysis")
    def stream_analysis() -> Response:
        ensure_thread()
        return _event_response(analysis_channel)

    @app.route("/stream/summaries")
    def stream_summaries() -> Response:
        ensure_thread()
        return _event_response(summary_channel)

    @app.route("/api/chat", methods=["POST"])
    def chat_endpoint():
        """Handle chat messages and return PokéAPI responses."""
        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "No JSON data provided"}), 400
                
            message = data.get("message", "")
            if not message:
                return jsonify({"error": "No message provided"}), 400
            response = process_chat_message(chat_agent, message)
            
            return jsonify({
                "response": response,
                "timestamp": datetime.now().isoformat()
            })
        except Exception as e:
            return jsonify({"error": f"Chat error: {str(e)}"}), 500

    return app


def serve_web_app(
    cfg: Optional[dict[str, Any]] = None,
    analysis_agent: Optional[Agent] = None,
    summary_agent: Optional[Agent] = None,
    prompt: Optional[str] = None,
) -> None:
    """Launch the streaming web UI alongside the capture loop."""

    cfg = cfg or load_config()
    if analysis_agent is None or summary_agent is None:
        analysis_agent, summary_agent = build_agents(cfg["model"])
    if prompt is None:
        prompt = build_analysis_prompt()

    ensure_out_dir(cfg["out_dir"], clear=True)

    host = cfg["ui_host"]
    port = cfg["ui_port"]

    app = _create_web_app(cfg, analysis_agent, summary_agent, prompt)

    start_capture_thread(cfg, analysis_agent, summary_agent, prompt)

    print(f"Streaming UI available at http://{host}:{port}")
    app.run(host=host, port=port, debug=False)


def create_app() -> Flask:
    """Flask factory for `flask run`. Ensures capture loop starts once."""

    cfg = load_config()
    ensure_out_dir(cfg["out_dir"], clear=True)
    analysis_agent, summary_agent = build_agents(cfg["model"])
    prompt = build_analysis_prompt()

    os.environ.setdefault("FLASK_RUN_HOST", cfg["ui_host"])
    os.environ.setdefault("FLASK_RUN_PORT", str(cfg["ui_port"]))

    start_capture_thread(cfg, analysis_agent, summary_agent, prompt)
    return _create_web_app(cfg, analysis_agent, summary_agent, prompt)


def main() -> None:
    parser = argparse.ArgumentParser(description="RetroArch capture loop and streaming UI")
    parser.add_argument(
        "--web",
        action="store_true",
        help="Run the streaming web UI instead of the CLI logger",
    )
    parser.add_argument(
        "--ui-host",
        help="Override STREAM_UI_HOST when running the web UI",
    )
    parser.add_argument(
        "--ui-port",
        type=int,
        help="Override STREAM_UI_PORT when running the web UI",
    )
    args = parser.parse_args()

    cfg = load_config()
    if args.ui_host:
        cfg["ui_host"] = args.ui_host
    if args.ui_port is not None:
        cfg["ui_port"] = args.ui_port

    analysis_agent, summary_agent = build_agents(cfg["model"])
    prompt = build_analysis_prompt()

    if args.web:
        serve_web_app(cfg, analysis_agent, summary_agent, prompt)
        return

    ensure_out_dir(cfg["out_dir"], clear=True)

    print(f"Capturing from app: {cfg['app_name']} every {cfg['interval']}s using model {cfg['model']}")
    print(f"Saving screenshots to: {cfg['out_dir']}")
    print(f"Generating cumulative summary every {cfg['summary_interval']} captures\n")

    run_capture_loop(cfg, analysis_agent, summary_agent, prompt)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
