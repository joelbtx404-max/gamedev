import base64
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

try:
    from agents import Agent, Runner
except Exception as exc:  # pragma: no cover
    print("openai-agents is required. pip install openai-agents", file=sys.stderr)
    raise


def load_config():
    load_dotenv()
    cfg = {
        "interval": float(os.getenv("SCREENSHOT_INTERVAL_SECONDS", "5")),
        "app_name": os.getenv("CAPTURE_SOURCE", "RetroArch"),
        "model": os.getenv("MODEL", "gpt-5"),
        "api_key": os.getenv("OPENAI_API_KEY"),
        "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "out_dir": Path(os.getenv("SCREENSHOTS_DIR", str(Path(__file__).resolve().parent / "static" / "images"))).resolve(),
    }
    missing = [k for k in ("api_key",) if not cfg[k]]
    if missing:
        raise RuntimeError(f"Missing required env var(s): {', '.join(missing)}")
    return cfg


def ensure_out_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


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
        "You are a game analysis assistant that provides structured JSON data about gameplay. "
        "Respond with ONLY a JSON object (no markdown, no extra text). "
        "The JSON must have these fields: "
        "game_name (string), scene (string), characters (array of {name, level, hp_current, hp_max, status}), "
        "environment (string), notable_events (string)."
    )
    summary_instructions = (
        "You are a game progress summarizer that creates concise gameplay summaries. "
        "Keep it to 2-3 sentences focusing on what happened, progress, battles/encounters, level ups, and location changes."
    )

    analysis_agent = Agent(name="GameAnalyzer", instructions=analysis_instructions)
    summary_agent = Agent(name="GameSummarizer", instructions=summary_instructions)

    return analysis_agent, summary_agent


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
    b64 = encode_image_b64(image_path)
    # Agents SDK supports 'message' or plain strings; pass a single user message string.
    # Note: This embeds the image as a data URL in text. For true multimodal input, we can later
    # switch to item references per the SDK docs.
    run = Runner.run_sync(
        agent,
        input=(
            f"{prompt}\n\n"
            f"Image (data URL): data:image/png;base64,{b64}"
        ),
    )
    return extract_final_output(run)


def generate_summary(agent: Agent, analyses: list[dict]) -> str:
    """Generate a summary of the last 3 game analyses."""
    summary_text = "Here are the last 3 gameplay analyses:\n\n"
    for i, analysis in enumerate(analyses, 1):
        summary_text += f"Frame {i}:\n{json.dumps(analysis, indent=2)}\n\n"
    
    summary_text += (
        "Provide a brief summary of the gameplay progression. "
        "Focus on: what happened, any progress made, battles/encounters, level ups, location changes. "
        "Keep it concise (2-3 sentences)."
    )
    
    run = Runner.run_sync(
        agent,
        input=summary_text,
    )
    return extract_final_output(run)


def main():
    cfg = load_config()
    ensure_out_dir(cfg["out_dir"])

    analysis_agent, summary_agent = build_agents(cfg["model"])
    prompt = (
        "IMPORTANT: Analyze ONLY the RetroArch game window. Ignore any code editors, desktop elements, or other applications. "
        "Focus exclusively on the game content displayed in RetroArch. "
        "Respond with ONLY a JSON object (no markdown, no extra text). "
        "The JSON must have these fields:\n"
        "- game_name: string (e.g., 'Pokemon Black', 'Pokemon HeartGold')\n"
        "- scene: string (brief description: 'battle', 'overworld', 'menu', etc.)\n"
        "- characters: array of objects with {name: string, level: int, hp_current: int, hp_max: int, status: string}\n"
        "- environment: string (brief description of the environment/setting)\n"
        "- notable_events: string (any significant action happening, or 'none')\n"
        "Example: {\"game_name\": \"Pokemon Black\", \"scene\": \"battle\", \"characters\": [{\"name\": \"Tepig\", \"level\": 6, \"hp_current\": 21, \"hp_max\": 25, \"status\": \"normal\"}], \"environment\": \"grassy field\", \"notable_events\": \"Player's turn to select action\"}"
    )

    print(f"Capturing from app: {cfg['app_name']} every {cfg['interval']}s using model {cfg['model']}")
    print(f"Saving screenshots to: {cfg['out_dir']}")
    print("Generating summary after every 3 captures\n")

    recent_analyses = []
    capture_count = 0

    while True:
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = cfg["out_dir"] / f"retroarch_{now}.png"

        bounds = osascript_get_bounds(cfg["app_name"])  # None -> full screen
        if bounds is None:
            print("RetroArch window not found; capturing full screen.")

        ok = screencapture_png(out_path, bounds)
        if not ok:
            print("Screenshot failed; retrying after interval…")
            time.sleep(cfg["interval"])
            continue

        try:
            content = analyze_image(analysis_agent, out_path, prompt)
            # Try to parse as JSON
            data = None
            parsed_successfully = False
            
            try:
                data = json.loads(content)
                parsed_successfully = True
            except json.JSONDecodeError:
                # If not valid JSON, try to extract JSON from markdown code blocks
                content_stripped = content.strip()
                if content_stripped.startswith("```"):
                    lines = content_stripped.split("\n")
                    json_lines = []
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
                        pass
            
            # Display result
            timestamp = datetime.now().isoformat(timespec='seconds')
            if parsed_successfully and data:
                print(f"[{timestamp}] Frame Analysis:\n{json.dumps(data, indent=2)}\n")
                
                # Track successful analyses
                recent_analyses.append(data)
                capture_count += 1
                print(f"DEBUG: Capture count: {capture_count}")
                
                # Generate summary every 3 captures
                if capture_count % 3 == 0:
                    print("=" * 60)
                    print(f"GENERATING SUMMARY OF LAST 3 FRAMES (Total captures: {capture_count})...")
                    print("=" * 60)
                    try:
                        summary = generate_summary(summary_agent, recent_analyses[-3:])
                        summary_timestamp = datetime.now().isoformat(timespec='seconds')
                        print(f"[{summary_timestamp}] Summary:\n{summary}\n")
                        print("=" * 60 + "\n")
                    except Exception as exc:
                        print(f"Summary generation error: {exc}\n")
            else:
                print(f"[{timestamp}] Failed to parse JSON. Raw response:\n{content}\n")
                
        except Exception as exc:
            print(f"Analysis error: {exc}")

        time.sleep(cfg["interval"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")

