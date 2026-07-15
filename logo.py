"""
virgo ASCII logo — printed at startup.
Pure ASCII — works on every terminal.
Uses pyfiglet (optional; falls back to plain text).
"""

import sys

_LOGO = None


def _build_logo() -> str:
    try:
        import pyfiglet
        text = pyfiglet.figlet_format("VIRGO", font="banner3-D")
    except ImportError:
        text = (
            "__      _______ _____   _____  ____  \n"
            "\\ \\    / /_   _|  __ \\ / ____|/ __ \\ \n"
            " \\ \\  / /  | | | |__) | |  __| |  | |\n"
            "  \\ \\/ /   | | |  _  /| | |_ | |  | |\n"
            "   \\  /   _| |_| | \\ \\| |__| | |__| |\n"
            "    \\/    |_____|_|  \\_\\\\_____|\\____/ \n"
        )

    lines = text.rstrip("\n").split("\n")
    width = max(len(l) for l in lines)

    border = "+" + "-" * (width + 4) + "+"
    bottom = "+" + "=" * (width + 4) + "+"

    # Constellation accent bar — pure ASCII
    stars = (
        "    *   *   *   *   *   *   *   *   *   *   *   *   *   *   *"
    )

    tagline = "multi-agent state machine"
    phases = "discover -> plan -> code -> test -> fix"

    tag_pad = (width - len(tagline)) // 2
    phase_pad = (width - len(phases)) // 2

    out = []
    out.append(border)
    out.append("|  " + stars[:width] + "  |")
    out.append("|  " + " " * width + "  |")
    for line in lines:
        out.append("|  " + line.ljust(width) + "  |")
    out.append("|  " + " " * width + "  |")
    out.append("|  " + stars[:width] + "  |")
    out.append("|  " + " " * width + "  |")
    out.append("|  " + " " * tag_pad + tagline + " " * (width - tag_pad - len(tagline)) + "  |")
    out.append("|  " + " " * phase_pad + phases + " " * (width - phase_pad - len(phases)) + "  |")
    out.append("|  " + " " * width + "  |")
    out.append(bottom)
    return "\n".join(out)


def print_logo() -> None:
    """Print the virgo banner to stdout."""
    global _LOGO
    if _LOGO is None:
        _LOGO = _build_logo()
    print(_LOGO)


if __name__ == "__main__":
    print_logo()
