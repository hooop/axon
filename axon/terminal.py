"""Terminal size detection."""

import shutil


def get_terminal_width() -> int:
    """Return the current terminal width in columns."""
    return shutil.get_terminal_size().columns
