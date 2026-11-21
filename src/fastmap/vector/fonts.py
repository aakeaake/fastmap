"""Noto Sans fonts (SIL OFL, see fonts/OFL.txt) embedded in the PDF for map labels."""

from __future__ import annotations

from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT_DIR = Path(__file__).resolve().parent / "fonts"
_FONTS = {
    "Noto Sans Regular": "NotoSans-Regular",
    "Noto Sans Bold": "NotoSans-Bold",
    "Noto Sans Italic": "NotoSans-Italic",
}
DEFAULT_FONT = "NotoSans-Regular"


def register_fonts() -> None:
    """Register the Noto Sans faces with ReportLab (idempotent)."""
    registered = set(pdfmetrics.getRegisteredFontNames())
    for name in _FONTS.values():
        if name not in registered:
            pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / f"{name}.ttf")))


def font_for(stack: list[str]) -> str:
    """Registered font name for a style ``text-font`` stack; unknown -> Regular."""
    register_fonts()
    for entry in stack or []:
        if entry in _FONTS:
            return _FONTS[entry]
    return DEFAULT_FONT
