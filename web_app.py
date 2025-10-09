"""Compatibility entrypoint for serving the RetroArch capture web UI."""

from __future__ import annotations

from retroarch_capture import create_app, serve_web_app

app = create_app()


if __name__ == "__main__":
    try:
        serve_web_app()
    except KeyboardInterrupt:
        print("\nStopped.")
