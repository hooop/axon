"""Convert a PIL Image to a half-block ANSI string for terminal display (256 colors)."""

import math
from pathlib import Path
from typing import Optional

from PIL import Image

# The 6x6x6 color cube in the 256-color palette starts at index 16.
# Each axis (R, G, B) has 6 levels: 0, 95, 135, 175, 215, 255.
_CUBE_VALUES = (0, 95, 135, 175, 215, 255)

# Grayscale ramp: indices 232–255, values 8, 18, 28, ..., 238
_GRAY_VALUES = tuple(8 + 10 * i for i in range(24))


# ---------------------------------------------------------------------------
# RGB → CIE-Lab conversion (pure Python, no numpy)
# ---------------------------------------------------------------------------

def _srgb_to_linear(c):
    """Convert sRGB 0-255 to linear 0-1."""
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _rgb_to_lab(r, g, b):
    """Convert sRGB (0-255) to CIE-Lab."""
    # linearize
    lr = _srgb_to_linear(r)
    lg = _srgb_to_linear(g)
    lb = _srgb_to_linear(b)
    # RGB to XYZ (D65)
    x = lr * 0.4124564 + lg * 0.3575761 + lb * 0.1804375
    y = lr * 0.2126729 + lg * 0.7151522 + lb * 0.0721750
    z = lr * 0.0193339 + lg * 0.1191920 + lb * 0.9503041
    # normalize to D65 white point
    x /= 0.95047
    z /= 1.08883
    # XYZ to Lab
    def f(t):
        return t ** (1/3) if t > 0.008856 else 7.787 * t + 16/116
    fx, fy, fz = f(x), f(y), f(z)
    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b_val = 200.0 * (fy - fz)
    return L, a, b_val


def _idx_to_rgb(idx: int):
    """Convert an ANSI 256 index back to RGB."""
    if idx >= 232:
        gv = _GRAY_VALUES[idx - 232]
        return gv, gv, gv
    i = idx - 16
    return _CUBE_VALUES[i // 36], _CUBE_VALUES[(i % 36) // 6], _CUBE_VALUES[i % 6]


# Pre-compute Lab values for ANSI colors 16-255
_PALETTE_LAB = []
for _i in range(16, 256):
    _PALETTE_LAB.append(_rgb_to_lab(*_idx_to_rgb(_i)))
_PALETTE_LAB = tuple(_PALETTE_LAB)


# Flatten palette Lab into separate L, a, b lists for faster iteration
_PAL_L = tuple(lab[0] for lab in _PALETTE_LAB)
_PAL_A = tuple(lab[1] for lab in _PALETTE_LAB)
_PAL_B = tuple(lab[2] for lab in _PALETTE_LAB)
_PAL_COUNT = len(_PALETTE_LAB)


def _lab_nearest(L, a, b_val):
    """Find the closest ANSI 256 index (16-255) for a Lab color."""
    best = 0
    best_dist = float("inf")
    pal_l, pal_a, pal_b = _PAL_L, _PAL_A, _PAL_B
    for i in range(_PAL_COUNT):
        dL = L - pal_l[i]
        da = a - pal_a[i]
        db = b_val - pal_b[i]
        d = dL * dL + da * da + db * db
        if d < best_dist:
            best_dist = d
            best = i
    return best + 16


# Pre-compute RGB→ANSI256 lookup table using Lab matching.
# Sampled every _LUT_STEP values per channel, then looked up at render time.
_LUT_STEP = 8
_LUT_SIZE = 256 // _LUT_STEP  # 32

_RGB_TO_256_LUT = [[[0] * _LUT_SIZE for _ in range(_LUT_SIZE)] for _ in range(_LUT_SIZE)]
for _ri in range(_LUT_SIZE):
    for _gi in range(_LUT_SIZE):
        for _bi in range(_LUT_SIZE):
            _L, _a, _bv = _rgb_to_lab(
                min(_ri * _LUT_STEP, 255),
                min(_gi * _LUT_STEP, 255),
                min(_bi * _LUT_STEP, 255),
            )
            _RGB_TO_256_LUT[_ri][_gi][_bi] = _lab_nearest(_L, _a, _bv)


def _rgb_to_256(r: int, g: int, b: int) -> int:
    """Map an RGB value to the closest ANSI 256-color index (Lab-based LUT)."""
    return _RGB_TO_256_LUT[r // _LUT_STEP][g // _LUT_STEP][b // _LUT_STEP]


def load_lut(path: str) -> list:
    """Load a palette LUT from a PNG file (16x16 grid, 32x32 swatches).

    Returns a remap table of 256 entries: remap[original_index] = new_index.
    """
    img = Image.open(path).convert("RGB")
    pixels = img.load()
    w, h = img.size
    swatch_w = w // 16
    swatch_h = h // 16
    cx = swatch_w // 2
    cy = swatch_h // 2

    remap = [0] * 256
    for idx in range(256):
        row, col = idx // 16, idx % 16
        r, g, b = pixels[col * swatch_w + cx, row * swatch_h + cy]
        remap[idx] = _rgb_to_256(r, g, b)
    return remap


def make_remap(palette_rgb):
    """Build a 256→256 remap table that restricts output to the given RGB palette.

    palette_rgb: list of (r, g, b) tuples defining the allowed colors.
    For each ANSI 256 color, finds the nearest palette color, then its nearest ANSI 256 index.
    """
    # Pre-compute ANSI index for each palette color
    palette_idx = [_rgb_to_256(r, g, b) for r, g, b in palette_rgb]
    # Pre-compute RGB for each palette entry (snapped to ANSI)
    palette_ansi_rgb = [_idx_to_rgb(idx) for idx in palette_idx]

    remap = [0] * 256
    for i in range(256):
        r, g, b = _idx_to_rgb(i)
        best = 0
        best_dist = float("inf")
        for j, (pr, pg, pb) in enumerate(palette_rgb):
            d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
            if d < best_dist:
                best_dist = d
                best = j
        remap[i] = palette_idx[best]
    return remap


def _apply_remap(idx_grid, remap):
    """Apply a 256→256 remap table to an index grid in place."""
    for y in range(len(idx_grid)):
        for x in range(len(idx_grid[0])):
            idx_grid[y][x] = remap[idx_grid[y][x]]


# Bayer 4x4 threshold matrix, normalized to [-0.5, 0.5) range
_BAYER_4x4 = [
    [ 0/16 - 0.5,  8/16 - 0.5,  2/16 - 0.5, 10/16 - 0.5],
    [12/16 - 0.5,  4/16 - 0.5, 14/16 - 0.5,  6/16 - 0.5],
    [ 3/16 - 0.5, 11/16 - 0.5,  1/16 - 0.5,  9/16 - 0.5],
    [15/16 - 0.5,  7/16 - 0.5, 13/16 - 0.5,  5/16 - 0.5],
]


def _posterize(img: Image.Image, levels: int) -> Image.Image:
    """Reduce color levels per channel. levels=4 → 4 levels, levels=2 → 2 levels."""
    factor = 256 // levels
    pixels = img.load()
    w, h = img.size
    out = img.copy()
    out_pixels = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b = pixels[x, y]
            out_pixels[x, y] = (
                (r // factor) * factor + factor // 2,
                (g // factor) * factor + factor // 2,
                (b // factor) * factor + factor // 2,
            )
    return out


def _build_idx_grid(img: Image.Image, dither: str = "none", remap: Optional[list] = None, poster: int = 0):
    """Build a 2D grid of ANSI 256 color indices from a PIL RGB image.

    dither: "none", "floyd" (Floyd-Steinberg), or "ordered" (Bayer 4x4).
    remap: optional 256-entry remap table (from load_lut).
    poster: 0=off, or number of levels per channel (e.g. 4, 2).
    Returns list[list[int]] of shape [height][width].
    """
    if poster > 0:
        img = _posterize(img, poster)
    w, h = img.size
    pixels = img.load()

    if dither == "floyd":
        # Work on float copy for error diffusion
        buf = [[(0.0, 0.0, 0.0)] * w for _ in range(h)]
        for y in range(h):
            for x in range(w):
                buf[y][x] = tuple(float(c) for c in pixels[x, y])

        grid = [[0] * w for _ in range(h)]
        for y in range(h):
            for x in range(w):
                r, g, b = buf[y][x]
                cr = max(0, min(255, round(r)))
                cg = max(0, min(255, round(g)))
                cb = max(0, min(255, round(b)))
                idx = _rgb_to_256(cr, cg, cb)
                grid[y][x] = idx
                pr, pg, pb = _idx_to_rgb(idx)
                er, eg, eb = r - pr, g - pg, b - pb
                if x + 1 < w:
                    buf[y][x+1] = (buf[y][x+1][0] + er*7/16,
                                   buf[y][x+1][1] + eg*7/16,
                                   buf[y][x+1][2] + eb*7/16)
                if y + 1 < h:
                    if x - 1 >= 0:
                        buf[y+1][x-1] = (buf[y+1][x-1][0] + er*3/16,
                                         buf[y+1][x-1][1] + eg*3/16,
                                         buf[y+1][x-1][2] + eb*3/16)
                    buf[y+1][x] = (buf[y+1][x][0] + er*5/16,
                                   buf[y+1][x][1] + eg*5/16,
                                   buf[y+1][x][2] + eb*5/16)
                    if x + 1 < w:
                        buf[y+1][x+1] = (buf[y+1][x+1][0] + er*1/16,
                                         buf[y+1][x+1][1] + eg*1/16,
                                         buf[y+1][x+1][2] + eb*1/16)

    elif dither == "ordered":
        spread = 32  # amplitude of the Bayer offset
        grid = [[0] * w for _ in range(h)]
        for y in range(h):
            for x in range(w):
                r, g, b = pixels[x, y]
                offset = _BAYER_4x4[y % 4][x % 4] * spread
                cr = max(0, min(255, round(r + offset)))
                cg = max(0, min(255, round(g + offset)))
                cb = max(0, min(255, round(b + offset)))
                grid[y][x] = _rgb_to_256(cr, cg, cb)

    else:  # "none"
        grid = [[0] * w for _ in range(h)]
        for y in range(h):
            for x in range(w):
                grid[y][x] = _rgb_to_256(*pixels[x, y])

    if remap:
        _apply_remap(grid, remap)
    return grid


def render_image(image: Image.Image, columns: int, border: bool = False, caption: str = None, resample=Image.LANCZOS, dither: str = "none", remap: Optional[list] = None, poster: int = 0, glyph: str = "\u2580") -> str:
    """Render an image as 256-color ANSI text using Unicode half-block characters.

    Each character cell encodes two vertical pixels:
    - top pixel as foreground color (U+2580 ▀)
    - bottom pixel as background color
    """
    if border:
        pad = 1  # side border thickness in columns
        inner = columns - pad * 2
    else:
        pad = 0
        inner = columns

    rows = inner  # keep square aspect for image area
    if rows % 2 != 0:
        rows += 1
    img = image.convert("RGB").resize((inner, rows), resample)
    idx_grid = _build_idx_grid(img, dither, remap, poster)

    white = "\033[48;5;231m"
    reset = "\033[0m"
    border_char = " "

    lines: list[str] = []

    if border:
        lines.append(white + border_char * columns + reset)

    for y in range(0, rows, 2):
        parts: list[str] = []
        if border:
            parts.append(white + border_char * pad)
        for x in range(inner):
            fg = idx_grid[y][x]
            bg = idx_grid[y + 1][x]
            parts.append(f"\033[38;5;{fg};48;5;{bg}m{glyph}")
        if border:
            parts.append(white + border_char * pad)
        lines.append("".join(parts) + reset)

    if border:
        if caption:
            lines.append(white + border_char * columns + reset)
            text = caption[:columns - pad * 2]
            padding = columns - pad * 2 - len(text)
            left = padding // 2
            right = padding - left
            black = "\033[38;5;232m"
            lines.append(white + border_char * pad + black + border_char * left + text + border_char * right + reset + white + border_char * pad + reset)
            lines.append(white + border_char * columns + reset)
        else:
            for _ in range(4):
                lines.append(white + border_char * columns + reset)

    return "\n".join(lines)


def render_preview(image: Image.Image, columns: int, scale: int = 8, resample=Image.LANCZOS, dither: str = "none", remap: Optional[list] = None, poster: int = 0) -> Image.Image:
    """Render a scaled-up preview showing the exact 256-color terminal output.

    Returns a PIL Image where each terminal pixel is a (scale x scale) block.
    """
    rows = columns
    if rows % 2 != 0:
        rows += 1
    img = image.convert("RGB").resize((columns, rows), resample)
    idx_grid = _build_idx_grid(img, dither, remap, poster)

    preview = Image.new("RGB", (columns * scale, rows * scale))
    preview_pixels = preview.load()

    for y in range(rows):
        for x in range(columns):
            r, g, b = _idx_to_rgb(idx_grid[y][x])
            for dy in range(scale):
                for dx in range(scale):
                    preview_pixels[x * scale + dx, y * scale + dy] = (r, g, b)

    return preview
