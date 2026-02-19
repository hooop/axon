"""Image generation via Google Gemini API."""

import io
import os
import random
import sys
import threading

from google import genai
from google.genai import types


GEMINI_MODEL = "gemini-2.5-flash-image"

_DUST_COLORS = [
    "\033[38;5;206m",
    "\033[38;5;51m",
    "\033[38;5;34m",
    "\033[38;5;26m",
]
_GRAY = "\033[38;5;180m"
_RESET = "\033[0m"
_HIDE_CURSOR = "\033[?25l"
_SHOW_CURSOR = "\033[?25h"
_DOT = "⸱"


def _spinner(stop_event: threading.Event) -> None:
    """Display a dust-particle loader while waiting."""
    sys.stderr.write(_HIDE_CURSOR)
    sys.stderr.write("\n")
    pad = "  "
    label = f"{pad}{_GRAY}Axon is dreaming{_RESET}"
    label_len = len(pad) + len("Axon is dreaming")

    try:
        while not stop_event.is_set():
            dots = "".join(random.choice(_DUST_COLORS) + _DOT for _ in range(15))
            sys.stderr.write(f"\r{label} {dots}{_RESET}")
            sys.stderr.flush()
            stop_event.wait(0.02)
    finally:
        sys.stderr.write(f"\r{' ' * (label_len + 1 + 30)}\r")
        sys.stderr.write(f"\033[1A\r")
        sys.stderr.write(_SHOW_CURSOR + _RESET)
        sys.stderr.flush()


def generate_image(prompt: str, width: int = 512, height: int = 512) -> bytes:
    """Generate an image from a text prompt using Google Gemini API.

    Requires GOOGLE_API_KEY environment variable to be set.
    Returns the raw image bytes (PNG).
    """
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise SystemExit(
            "Error: GOOGLE_API_KEY environment variable not set.\n"
            "Get your key at https://aistudio.google.com/apikey\n"
            "Then: export GOOGLE_API_KEY=AIza..."
        )

    client = genai.Client(api_key=api_key)

    stop = threading.Event()
    spinner_thread = threading.Thread(target=_spinner, args=(stop,), daemon=True)
    spinner_thread.start()

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )

        err = "\033[38;5;125m"
        if not response.parts:
            raise SystemExit(f"\n  {err}Gemini returned no image. The prompt may have been blocked.{_RESET}\n")

        for part in response.parts:
            if part.inline_data is not None:
                return part.inline_data.data

        raise SystemExit(f"\n  {err}Gemini returned no image.{_RESET}\n")

    except SystemExit:
        raise
    except Exception as exc:
        err = "\033[38;5;125m"
        msg = str(exc)
        if "503" in msg or "UNAVAILABLE" in msg:
            raise SystemExit(f"\n  {err}Gemini is busy right now. Try again in a moment.{_RESET}\n") from exc
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
            raise SystemExit(f"\n  {err}API quota exceeded. Wait a bit and retry.{_RESET}\n") from exc
        raise SystemExit(f"\n  {err}Something went wrong: {msg}{_RESET}\n") from exc
    finally:
        stop.set()
        spinner_thread.join()
