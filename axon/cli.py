"""CLI argument parsing and main entry point."""

import warnings
warnings.filterwarnings("ignore")

import argparse
import io
import json
import sys
import termios
import tty
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image

from axon.generator import generate_image
from axon.logo import animate_logo, render_logo
from axon.renderer import load_lut, render_image, render_preview
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

_DITHERS = [
    ("Clean", "none"),
    ("Grain", "floyd"),
    ("Grid", "ordered"),
]

_POSTERS = [
    ("Off", 0),
    ("Light", 4),
    ("Heavy", 2),
]


def _scan_palettes():
    """Scan palettes/ folder for LUT PNG files.

    Returns list of (name, remap_or_none). First entry is always ("None", None).
    """
    palettes = [("None", None)]
    lut_dir = Path(__file__).resolve().parent.parent / "palettes"
    if lut_dir.is_dir():
        for png in sorted(lut_dir.glob("*.png")):
            try:
                remap = load_lut(str(png))
                name = png.stem.capitalize()
                palettes.append((name, remap))
            except Exception:
                continue
    return palettes


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


def _yes_no_menu(label: str, default: int = 1) -> bool:
    """Show a horizontal Yes/No menu. Returns True if Yes selected."""
    dim = "\033[38;5;238m"
    light_brown = "\033[38;5;137m"
    white = "\033[38;5;231m"
    reset = "\033[0m"
    sel = default  # 0=Yes, 1=No

    def _draw():
        options = ["Yes", "No"]
        parts = []
        for i, name in enumerate(options):
            if i == sel:
                parts.append(f"{light_brown}>{white} {name}{reset}")
            else:
                parts.append(f"  {dim}{name}{reset}")
        return f"  {light_brown}{label}:{reset}  " + "  ".join(parts)

    sys.stdout.write("\033[?25l")
    sys.stdout.write(_draw())
    sys.stdout.flush()

    try:
        while True:
            key = _read_key()
            if key in ("quit", "enter"):
                break
            prev = sel
            if key == "left" and sel > 0:
                sel -= 1
            elif key == "right" and sel < 1:
                sel += 1
            if sel != prev:
                sys.stdout.write(f"\r\033[2K{_draw()}")
                sys.stdout.flush()
    finally:
        sys.stdout.write("\033[?25h\n")
        sys.stdout.flush()

    # Clear menu line and show confirmed choice
    confirmed = "yes" if sel == 0 else "no"
    sys.stdout.write(f"\033[1A\033[2K  {dim}{label}:{reset}  {confirmed}\n")
    sys.stdout.flush()

    return sel == 0


def _generate_and_display(prompt: str, columns: int, size: int,
                          pola: bool, caption: Optional[str]) -> None:
    """Generate an image and display it in the terminal."""
    dim = "\033[38;5;238m"
    light_brown = "\033[38;5;137m"
    white = "\033[38;5;231m"
    reset = "\033[0m"

    image_bytes = generate_image(prompt, width=size, height=size)
    image = Image.open(io.BytesIO(image_bytes))

    palettes = _scan_palettes()

    # Settings state: [filter_index, dither_index, poster_index, palette_index]
    selected = [0, 0, 0, 0]
    active_row = 0
    settings = [
        ("Filter", _FILTERS),
        ("Texture", _DITHERS),
        ("Poster", _POSTERS),
        ("Palette", palettes),
    ]

    img_lines = _image_height(columns, pola, caption)
    # total = blank line + image + blank line + 2 menu lines
    menu_lines = len(settings)
    total_lines = 1 + img_lines + 1 + menu_lines

    def _menu_str():
        lines = []
        for row, (label, options) in enumerate(settings):
            active = row == active_row
            parts = []
            for i, (name, _) in enumerate(options):
                if i == selected[row]:
                    if active:
                        parts.append(f"{light_brown}>{white} {name}{reset}")
                    else:
                        parts.append(f"{dim}> {name}{reset}")
                else:
                    parts.append(f"  {dim}{name}{reset}")
            if active:
                lines.append(f"  {light_brown}{label}:{reset}  " + "  ".join(parts))
            else:
                lines.append(f"  {dim}{label}:{reset}  " + "  ".join(parts))
        return "\n".join(lines)

    def _current_resample():
        _, resample = _FILTERS[selected[0]]
        return resample

    def _current_dither():
        _, dither = _DITHERS[selected[1]]
        return dither

    def _current_poster():
        _, poster = _POSTERS[selected[2]]
        return poster

    def _current_remap():
        _, remap = palettes[selected[3]]
        return remap

    def _draw_all():
        """Draw image + blank + menu. Cursor ends on last menu line."""
        sys.stdout.write("\n")
        rendered = render_image(image, columns, border=pola, caption=caption,
                                resample=_current_resample(), dither=_current_dither(),
                                remap=_current_remap(), poster=_current_poster())
        sys.stdout.write(rendered)
        sys.stdout.write(f"\n\n{_menu_str()}")
        sys.stdout.flush()

    def _redraw_menu_only():
        """Redraw just the menu lines (cursor is on last menu line)."""
        # Move up to first menu line
        if menu_lines > 1:
            sys.stdout.write(f"\033[{menu_lines - 1}A\r")
        else:
            sys.stdout.write("\r")
        for i in range(menu_lines):
            sys.stdout.write(f"\033[2K")
            if i < menu_lines - 1:
                sys.stdout.write("\n")
        # Now cursor is on last menu line, move back to first
        if menu_lines > 1:
            sys.stdout.write(f"\033[{menu_lines - 1}A\r")
        else:
            sys.stdout.write("\r")
        sys.stdout.write(_menu_str())
        sys.stdout.flush()

    # First render
    sys.stdout.write("\033[?25l")
    _draw_all()

    try:
        while True:
            key = _read_key()

            if key in ("quit", "enter"):
                break

            if key == "up" and active_row > 0:
                active_row -= 1
                _redraw_menu_only()
            elif key == "down" and active_row < len(settings) - 1:
                active_row += 1
                _redraw_menu_only()
            elif key == "left" or key == "right":
                _, options = settings[active_row]
                prev = selected[active_row]
                if key == "left" and selected[active_row] > 0:
                    selected[active_row] -= 1
                elif key == "right" and selected[active_row] < len(options) - 1:
                    selected[active_row] += 1
                if selected[active_row] != prev:
                    # Value changed → re-render image + menu
                    sys.stdout.write(f"\033[{total_lines - 1}A\r")
                    _draw_all()
    finally:
        sys.stdout.write("\033[?25h\n")
        sys.stdout.flush()

    # Replace menu with confirmed choices
    filter_name, _ = _FILTERS[selected[0]]
    dither_name, _ = _DITHERS[selected[1]]
    poster_name, _ = _POSTERS[selected[2]]
    palette_name, _ = palettes[selected[3]]
    sys.stdout.write(f"\033[{menu_lines}A")
    for i in range(menu_lines):
        sys.stdout.write(f"\033[2K\n")
    sys.stdout.write(f"\033[{menu_lines}A")
    sys.stdout.write(f"  {dim}Filter:{reset} {filter_name}\n")
    sys.stdout.write(f"  {dim}Texture:{reset} {dither_name}\n")
    sys.stdout.write(f"  {dim}Poster:{reset} {poster_name}\n")
    sys.stdout.write(f"  {dim}Palette:{reset} {palette_name}\n")
    sys.stdout.flush()

    final_resample = _current_resample()
    final_dither = _current_dither()
    final_poster = _current_poster()
    final_remap = _current_remap()
    gallery = Path.home() / "axon_gallery"
    gallery.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')

    # Save menu
    do_save = _yes_no_menu("Save", default=0)
    if do_save:
        # Save original Gemini image
        png_path = gallery / f"axon_{timestamp}.png"
        png_path.write_bytes(image_bytes)
        print(f"  {dim}Original:{reset} {png_path}")

        # Save scaled-up 256-color preview
        preview = render_preview(image, columns, scale=8, resample=final_resample, dither=final_dither, remap=final_remap, poster=final_poster)
        preview_path = gallery / f"axon_{timestamp}_256.png"
        preview.save(preview_path)
        print(f"  {dim}Preview:{reset}  {preview_path}")

    # Export JSON menu
    do_export = _yes_no_menu("Export JSON", default=1)
    if do_export:
        rendered = render_image(image, columns, border=pola, caption=caption,
                                resample=final_resample, dither=final_dither,
                                remap=final_remap, poster=final_poster)
        lines = rendered.split("\n")
        json_data = {
            "width": columns,
            "height": len(lines),
            "lines": lines,
        }
        json_path = gallery / f"axon_{timestamp}.json"
        json_path.write_text(json.dumps(json_data, ensure_ascii=False))
        print(f"  {dim}Export:{reset}   {json_path}")

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
