# RetroArch Game Capture & Analysis

A Python tool that captures screenshots from RetroArch gameplay and uses OpenAI's vision API to provide real-time game state analysis with periodic summaries.

## Features

- 🎮 Automatic RetroArch window capture (macOS)
- 🤖 AI-powered game state analysis using OpenAI Vision API
- 📊 Structured JSON output for easy parsing
- 📝 Automatic summaries every 10 captures
- ⚙️ Configurable capture intervals and models
- 🔌 Compatible with OpenAI and OpenAI-compatible APIs (xAI, etc.)

## Requirements

- Python 3.11+
- macOS (uses `screencapture` and AppleScript)
- OpenAI API key (or compatible API)
- macOS Accessibility permissions for Terminal/IDE (for window detection)

## Installation

1. **Clone and setup:**
```bash
cd game_annotation
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. **Configure environment:**
```bash
cp env.example .env
# Edit .env and add your OPENAI_API_KEY
```

3. **Test window detection (optional but recommended):**
```bash
python test_window_detection.py
```
This will verify that RetroArch can be detected and show you a list of all available windows if detection fails.

4. **Run:**
```bash
python retroarch_capture.py
```

## Configuration

Edit `.env` file with these options:

- `OPENAI_API_KEY` - Your OpenAI API key (required)
- `OPENAI_BASE_URL` - API base URL (default: https://api.openai.com/v1)
  - For xAI: `https://api.x.ai/v1`
- `MODEL` - Model to use (default: gpt-4o)
  - OpenAI: `gpt-4o`, `gpt-4-turbo`, `gpt-4o-mini`
  - xAI: `grok-4`, `grok-beta`
- `CAPTURE_SOURCE` - Application to capture (default: RetroArch)
- `SCREENSHOT_INTERVAL_SECONDS` - Seconds between captures (default: 5)
- `SCREENSHOTS_DIR` - Output directory (default: ./static/images)

## Output Format

### Frame Analysis (JSON)
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

### Summary (Every 10 Captures)
After every 10 successful captures, the system generates a concise summary of gameplay progression focusing on battles, level ups, and location changes.

## Usage Examples

### Basic Usage
```bash
# Start capturing with default settings
python retroarch_capture.py
```

### Using xAI/Grok
```bash
# In your .env file:
OPENAI_API_KEY=xai-your-key-here
OPENAI_BASE_URL=https://api.x.ai/v1
MODEL=grok-4
```

### Custom Interval
```bash
# In your .env file:
SCREENSHOT_INTERVAL_SECONDS=10
```

## How It Works

1. **Window Detection**: Uses AppleScript to find RetroArch window bounds
2. **Screenshot Capture**: Captures the RetroArch window using macOS `screencapture`
3. **AI Analysis**: Sends screenshot to OpenAI Vision API with structured prompt
4. **JSON Parsing**: Extracts game state data (characters, HP, scene, etc.)
5. **Summary Generation**: Every 20 captures, generates a gameplay summary

## Troubleshooting

**"RetroArch window not found"**
- Make sure RetroArch is running and visible
- Run `python test_window_detection.py` to see all available windows
- Set `CAPTURE_SOURCE` in your `.env` to match the exact process name
- The tool falls back to full-screen capture if window detection fails

**JSON parsing errors**
- The tool attempts to extract JSON from markdown code blocks
- Raw responses are shown if parsing fails completely

**API errors**
- Verify your `OPENAI_API_KEY` is correct
- Check `OPENAI_BASE_URL` if using non-OpenAI APIs
- Ensure your API has vision/image capabilities

**Permission issues (macOS)**
- If window detection doesn't work, you may need to grant accessibility permissions
- Go to: System Preferences > Security & Privacy > Privacy > Accessibility
- Add Terminal (or your IDE) to the allowed apps list
- You may need to restart your terminal/IDE after granting permissions

## File Structure

```
game_annotation/
├── retroarch_capture.py    # Main capture script
├── requirements.txt         # Python dependencies
├── env.example             # Environment template
├── README.md               # This file
├── static/
│   └── images/            # Screenshot output
└── venv/                  # Virtual environment
```

## Dependencies

- `openai` - OpenAI Python SDK
- `python-dotenv` - Environment variable management

## License

MIT
