"""Convert a PIL Image to a half-block ANSI string for terminal display (256 colors)."""

from PIL import Image

# The 6x6x6 color cube in the 256-color palette starts at index 16.
# Each axis (R, G, B) has 6 levels: 0, 95, 135, 175, 215, 255.
_CUBE_VALUES = (0, 95, 135, 175, 215, 255)

# Grayscale ramp: indices 232–255, values 8, 18, 28, ..., 238
_GRAY_VALUES = tuple(8 + 10 * i for i in range(24))


def _rgb_to_256(r: int, g: int, b: int) -> int:
    """Map an RGB value to the closest ANSI 256-color index."""
    # Find best match in the 6x6x6 color cube
    def _closest_cube(v: int) -> int:
        best = 0
        for i, cv in enumerate(_CUBE_VALUES):
            if abs(v - cv) < abs(v - _CUBE_VALUES[best]):
                best = i
        return best

    ri, gi, bi = _closest_cube(r), _closest_cube(g), _closest_cube(b)
    cube_index = 16 + 36 * ri + 6 * gi + bi
    cube_dist = (
        (r - _CUBE_VALUES[ri]) ** 2
        + (g - _CUBE_VALUES[gi]) ** 2
        + (b - _CUBE_VALUES[bi]) ** 2
    )

    # Check if a grayscale shade is closer
    gray = round((r + g + b) / 3)
    best_gray_i = 0
    best_gray_dist = abs(gray - _GRAY_VALUES[0])
    for i, gv in enumerate(_GRAY_VALUES):
        d = abs(gray - gv)
        if d < best_gray_dist:
            best_gray_dist = d
            best_gray_i = i

    gv = _GRAY_VALUES[best_gray_i]
    gray_dist = (r - gv) ** 2 + (g - gv) ** 2 + (b - gv) ** 2

    if gray_dist < cube_dist:
        return 232 + best_gray_i
    return cube_index


def render_image(image: Image.Image, columns: int, border: bool = False, caption: str = None, resample=Image.LANCZOS) -> str:
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
    pixels = img.load()

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
            fg = _rgb_to_256(*pixels[x, y])
            bg = _rgb_to_256(*pixels[x, y + 1])
            parts.append(f"\033[38;5;{fg};48;5;{bg}m\u2580")
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
