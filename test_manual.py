#!/usr/bin/env python3
import base64
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# Configuration
api_key = os.getenv("OPENAI_API_KEY")
base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
model = "gpt-5"  # Using GPT-5 with Responses API
image_path = Path("static/images/manual_test.png")

if not api_key:
    print("Error: OPENAI_API_KEY not found in .env file")
    exit(1)

if not image_path.exists():
    print(f"Error: Image not found at {image_path}")
    exit(1)

# Encode image
print(f"Reading image from: {image_path}")
with open(image_path, "rb") as f:
    b64_image = base64.b64encode(f.read()).decode("utf-8")

print(f"Using model: {model}")
print(f"Base URL: {base_url}")
print("\nSending request to OpenAI...\n")

# Create client and make request
client = OpenAI(api_key=api_key, base_url=base_url, timeout=60)


def extract_output_text(response) -> str:
    try:
        text = getattr(response, "output_text", None)
        if isinstance(text, str) and text.strip():
            return text
    except Exception:
        pass
    parts = []
    try:
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                t = getattr(content, "text", None)
                if t:
                    parts.append(t)
    except Exception:
        pass
    if not parts:
        try:
            choices = getattr(response, "choices", None)
            if choices:
                msg = choices[0].message
                if isinstance(msg, dict):
                    parts.append(str(msg.get("content", "")))
                else:
                    parts.append(str(getattr(msg, "content", "")))
        except Exception:
            pass
    return "".join(parts).strip()

prompt = """IMPORTANT: Analyze ONLY the RetroArch game window. Ignore any code editors, desktop elements, or other applications.
Focus exclusively on the game content displayed in RetroArch.
Respond with ONLY a JSON object (no markdown, no extra text).
The JSON must have these fields:
- game_name: string (e.g., 'Pokemon Black', 'Pokemon HeartGold')
- scene: string (brief description: 'battle', 'overworld', 'menu', etc.)
- characters: array of objects with {name: string, level: int, hp_current: int, hp_max: int, status: string}
- environment: string (brief description of the environment/setting)
- notable_events: string (any significant action happening, or 'none')
Example: {"game_name": "Pokemon Black", "scene": "battle", "characters": [{"name": "Tepig", "level": 6, "hp_current": 21, "hp_max": 25, "status": "normal"}], "environment": "grassy field", "notable_events": "Player's turn to select action"}"""

response = client.responses.create(
    model=model,
    input=[
        {"role": "system", "content": "You are a game analysis assistant that provides structured JSON data about gameplay."},
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": f"data:image/png;base64,{b64_image}", "detail": "high"}
            ]
        }
    ],
    reasoning={"effort": "minimal"}
)

# Parse and display result
content = extract_output_text(response)

print("=" * 60)
print("RESPONSE:")
print("=" * 60)

try:
    # Try to parse as JSON
    data = json.loads(content)
    print(json.dumps(data, indent=2))
except json.JSONDecodeError:
    # Try extracting from markdown
    if content.strip().startswith("```"):
        lines = content.strip().split("\n")
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
            print(json.dumps(data, indent=2))
        except json.JSONDecodeError:
            print("Raw response:")
            print(content)
    else:
        print("Raw response:")
        print(content)

print("\n" + "=" * 60)
try:
    print(f"Tokens used: {response.usage.total_tokens}")
except Exception:
    pass
print("=" * 60)

