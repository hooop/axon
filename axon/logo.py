"""AXON logo as half-block ANSI art with fade-in animation."""

import random
import sys
import time

# 4 rows x 19 cols pixel grid.
_LOGO = [
    "000100000000000000",
    "001101010011000110",
    "010100100100101001",
    "100101010011001001",
]

LOGO_HEIGHT = (len(_LOGO) + 1) // 2  # half-block lines

# Grayscale ramp from dark to white (ANSI 256 indices).
_FADE_STEPS = [232, 233, 234, 235, 237, 239, 241, 243, 245, 247, 249, 251, 253, 255, 231]


def _move_to(row, col):
    """Move cursor to (row, col) — 1-based."""
    sys.stdout.write(f"\033[{row};{col}H")


def _render_cell(row, col, top, bot, color, offset_row, offset_col):
    """Render a single half-block cell at its screen position."""
    fg = f"\033[38;5;{color}m"
    bg = f"\033[48;5;{color}m"
    reset = "\033[0m"

    screen_row = offset_row + row // 2 + 1
    screen_col = offset_col + col + 1

    _move_to(screen_row, screen_col)

    if top and bot:
        sys.stdout.write(f"{fg}{bg}\u2580{reset}")
    elif top:
        sys.stdout.write(f"{fg}\u2580{reset}")
    elif bot:
        sys.stdout.write(f"{fg}\u2584{reset}")


def animate_logo(offset_row=1, offset_col=2, delay=0.02):
    """Animate the logo: pixels appear in random order, each fading dark→white."""
    rows = len(_LOGO)
    width = len(_LOGO[0]) if rows > 0 else 0
    empty = "0" * width

    # Collect all active pixels as (half-block row, col, has_top, has_bot).
    cells = []
    for y in range(0, rows, 2):
        top = _LOGO[y]
        bot = _LOGO[y + 1] if y + 1 < rows else empty
        for x in range(width):
            t = top[x] == "1"
            b = bot[x] == "1"
            if t or b:
                cells.append((y, x, t, b))

    random.shuffle(cells)

    # Hide cursor during animation.
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()

    # Animate each pixel with a fade-in.
    for y, x, t, b in cells:
        for step in _FADE_STEPS:
            _render_cell(y, x, t, b, step, offset_row, offset_col)
            sys.stdout.flush()
            time.sleep(delay / len(_FADE_STEPS))
        # Final white render.
        _render_cell(y, x, t, b, 231, offset_row, offset_col)
        sys.stdout.flush()

    # Show cursor again.
    sys.stdout.write("\033[?25h")
    sys.stdout.flush()


def render_logo(green=46):
    """Render the logo statically (for non-interactive use)."""
    fg = f"\033[38;5;{green}m"
    bg = f"\033[48;5;{green}m"
    reset = "\033[0m"

    rows = len(_LOGO)
    width = len(_LOGO[0]) if rows > 0 else 0
    empty = "0" * width

    lines = []
    for y in range(0, rows, 2):
        top = _LOGO[y]
        bot = _LOGO[y + 1] if y + 1 < rows else empty
        parts = []
        for x in range(len(top)):
            t, b = top[x] == "1", bot[x] == "1"
            if t and b:
                parts.append(f"{fg}{bg}\u2580{reset}")
            elif t:
                parts.append(f"{fg}\u2580{reset}")
            elif b:
                parts.append(f"{fg}\u2584{reset}")
            else:
                parts.append(" ")
        lines.append("".join(parts))
    return "\n".join(lines)
