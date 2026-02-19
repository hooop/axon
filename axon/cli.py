"""CLI argument parsing and main entry point."""

import warnings
warnings.filterwarnings("ignore")

import argparse
import io
import sys
import termios
import tty
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image

from axon.generator import generate_image
from axon.logo import animate_logo, render_logo
from axon.renderer import render_image
from axon.terminal import get_terminal_width


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="axon",
        description="Generate an image from a text prompt and display it in the terminal.",
    )
    parser.add_argument("prompt", nargs="?", default=None, help="Text prompt describing the image to generate")
    parser.add_argument(
        "--width",
        type=int,
        default=0,
        help="Terminal columns to use for rendering (default: auto-detect)",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=768,
        choices=[512, 768, 1024],
        help="Generated image resolution (default: 768)",
    )
    parser.add_argument(
        "--pola",
        action="store_true",
        help="Add a polaroid-style white border around the image",
    )
    parser.add_argument(
        "--caption",
        type=str,
        default=None,
        help="Caption text on the polaroid border (requires --pola)",
    )
    return parser.parse_args()


_FILTERS = [
    ("Silk", Image.LANCZOS),
    ("Soft", Image.BILINEAR),
    ("Crisp", Image.BICUBIC),
    ("Raw", Image.NEAREST),
]


def _read_key():
    """Read a single keypress (handles arrow keys)."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            ch2 = sys.stdin.read(1)
            if ch2 == "[":
                ch3 = sys.stdin.read(1)
                if ch3 == "A":
                    return "up"
                if ch3 == "B":
                    return "down"
                if ch3 == "C":
                    return "right"
                if ch3 == "D":
                    return "left"
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "q" or ch == "\x03":  # q or Ctrl-C
            return "quit"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _image_height(columns: int, border: bool, caption: Optional[str]) -> int:
    """Calculate the number of terminal lines an image render occupies."""
    inner = columns - 2 if border else columns
    rows = inner
    if rows % 2 != 0:
        rows += 1
    lines = rows // 2
    if border:
        lines += 1  # top border
        if caption:
            lines += 3  # spacer + caption + bottom
        else:
            lines += 4  # bottom padding
    return lines


def _generate_and_display(prompt: str, columns: int, size: int,
                          pola: bool, caption: Optional[str]) -> None:
    """Generate an image and display it in the terminal."""
    dim = "\033[38;5;238m"
    light_brown = "\033[38;5;137m"
    reset = "\033[0m"

    image_bytes = generate_image(prompt, width=size, height=size)
    image = Image.open(io.BytesIO(image_bytes))

    selected = 0
    img_lines = _image_height(columns, pola, caption)
    # total = blank line + image + blank line + menu line
    total_lines = 1 + img_lines + 1 + 1

    def _menu_str():
        white = "\033[38;5;231m"
        parts = []
        for i, (name, _) in enumerate(_FILTERS):
            if i == selected:
                parts.append(f"{light_brown}>{white} {name}{reset}")
            else:
                parts.append(f"  {dim}{name}{reset}")
        return "  " + "  ".join(parts)

    def _draw_all():
        """Draw image + blank + menu. Cursor ends on menu line."""
        _, resample = _FILTERS[selected]
        sys.stdout.write("\n")
        rendered = render_image(image, columns, border=pola, caption=caption, resample=resample)
        sys.stdout.write(rendered)
        sys.stdout.write(f"\n\n{_menu_str()}")
        sys.stdout.flush()

    # First render
    sys.stdout.write("\033[?25l")
    _draw_all()

    try:
        while True:
            key = _read_key()

            if key in ("quit", "enter"):
                break

            prev = selected
            if key == "left" and selected > 0:
                selected -= 1
            elif key == "right" and selected < len(_FILTERS) - 1:
                selected += 1

            if selected != prev:
                # Cursor is on the menu line. Move up to start of block:
                # menu line + blank line + image lines + blank line = total_lines
                sys.stdout.write(f"\033[{total_lines - 1}A\r")
                _draw_all()
    finally:
        sys.stdout.write("\033[?25h\n")
        sys.stdout.flush()

    # Clear menu line
    sys.stdout.write(f"\033[1A\033[2K\r")
    sys.stdout.flush()

    # Save
    gallery = Path.home() / "axon_gallery"
    gallery.mkdir(exist_ok=True)
    filename = f"axon_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.png"
    filepath = gallery / filename
    filepath.write_bytes(image_bytes)

    print(f"  {dim}Saved:{reset} {filepath}")
    print()


def _interactive() -> None:
    """Interactive mode: logo, config, prompt."""
    columns = get_terminal_width()
    green = "\033[38;5;46m"
    light_brown = "\033[38;5;137m"
    dim = "\033[38;5;238m"
    reset = "\033[0m"

    # Clear screen and animate logo
    print("\033[2J\033[H", end="", flush=True)
  
    # Animate logo into the reserved space
    animate_logo(offset_row=1, offset_col=2)

    # Move cursor below subtitle
    print(f"\033[5;1H", end="", flush=True)
    print(f"  {light_brown}Neural Terminal{reset}")
    print()

    # Config
    max_width = min(columns, 100)
    print(f"  {light_brown}Size:{reset}  ", end="", flush=True)
    width_input = input().strip()
    if width_input.isdigit() and 20 <= int(width_input) <= max_width:
        render_width = int(width_input)
    else:
        render_width = max_width
    print(f"\033[1A\033[2K  {dim}Size:{reset}  {render_width}", flush=True)

    print(f"  {light_brown}Pola:{reset}  ", end="", flush=True)
    pola_input = input().strip().lower()
    pola = pola_input in ("y", "yes", "1", "true")
    display_pola = "yes" if pola else "no"
    print(f"\033[1A\033[2K  {dim}Pola:{reset}  {display_pola}", flush=True)

    caption = None
    if pola:
        print(f"  {light_brown}Caption:{reset} ", end="", flush=True)
        caption_input = input().strip()
        caption = caption_input if caption_input else None
        display_caption = caption_input if caption_input else "none"
        print(f"\033[1A\033[2K  {dim}Caption:{reset} {display_caption}", flush=True)

    print()
    print(f"  {light_brown}>{reset} ", end="", flush=True)
    try:
        prompt = input().strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if not prompt:
        print("  No prompt given.")
        return

    _generate_and_display(prompt, render_width, 768, pola, caption)


def main() -> None:
    args = parse_args()

    if args.prompt is None:
        _interactive()
        return

    columns = args.width if args.width > 0 else get_terminal_width()
    _generate_and_display(args.prompt, columns, args.size, args.pola, args.caption)
