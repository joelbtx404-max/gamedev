#!/usr/bin/env python3
"""
Simple test script to verify RetroArch window detection on macOS.
Run this before starting the capture loop to ensure window detection works.
"""

import os
import sys
from pathlib import Path

# Add the current directory to the path so we can import retroarch_capture
sys.path.insert(0, str(Path(__file__).parent))

from retroarch_capture import osascript_get_bounds, list_all_windows
from dotenv import load_dotenv


def main():
    print("=" * 60)
    print("RetroArch Window Detection Test")
    print("=" * 60)
    print()
    
    # Load environment variables
    load_dotenv()
    app_name = os.getenv("CAPTURE_SOURCE", "RetroArch")
    
    print(f"Looking for process: '{app_name}'")
    print()
    
    # Try to detect the window
    bounds = osascript_get_bounds(app_name)
    
    if bounds:
        x, y, w, h = bounds
        print("✅ SUCCESS! Window detected:")
        print(f"   Position: ({x}, {y})")
        print(f"   Size: {w}x{h} pixels")
        print()
        print("Your window detection is working correctly!")
    else:
        print("❌ Window not found!")
        print()
        print("Listing all available windows on your system:")
        print("-" * 60)
        
        windows = list_all_windows()
        if windows:
            for i, (proc_name, win_name) in enumerate(windows, 1):
                print(f"{i:2d}. Process: '{proc_name}'")
                print(f"    Window:  '{win_name}'")
            
            print()
            print("To fix this:")
            print("1. Find RetroArch in the list above")
            print("2. Note the exact process name")
            print("3. Set CAPTURE_SOURCE in your .env file to match")
            print()
            print("Example:")
            print('  CAPTURE_SOURCE="RetroArch"')
        else:
            print("(No windows detected - AppleScript may need permissions)")
            print()
            print("Troubleshooting:")
            print("1. Grant Terminal/IDE permissions in System Preferences")
            print("2. Go to: System Preferences > Security & Privacy > Accessibility")
            print("3. Add your terminal or IDE to the list")
    
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()

