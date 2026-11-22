"""Embed palette images in a PDF as indexed images (one byte per pixel).

ReportLab's ``drawImage`` always stores an image as 8-bit RGB, so a 124-colour
map raster takes three bytes per pixel before compression. PDF's ``/Indexed``
colour space stores one byte per pixel plus a small colour table: the same
pixels, about 30 % smaller after Flate and faster to compress.

ReportLab has no public hook for a custom image object, so this module uses a
few of its internals (the image registration that ``Canvas.drawImage`` does);
tests pin the behaviour.
"""

from __future__ import annotations

import zlib

from PIL import Image
from reportlab.pdfbase import pdfdoc
from reportlab.pdfgen.canvas import Canvas, _digester


class _IndexedImage(pdfdoc.PDFImageXObject):
    def __init__(self, name: str, img: Image.Image, pixels: bytes) -> None:
        # PDFImageXObject's own __init__ loads RGB data; set only what format() needs
        self.name = name
        self.width, self.height = img.size
        # colour table entries: up to the highest index any pixel uses
        palette_size = max((i for _, i in img.getcolors(256) or []), default=255) + 1
        palette = bytes(img.getpalette("RGB")[: 3 * palette_size])
        # enc="raw": the table is binary, written as an escaped string, never re-encoded
        self.color_space = pdfdoc.PDFArray(
            [
                pdfdoc.PDFName("Indexed"),
                pdfdoc.PDFName("DeviceRGB"),
                palette_size - 1,
                pdfdoc.PDFString(palette, enc="raw"),
            ]
        )
        self.streamContent = zlib.compress(pixels)

    def format(self, document) -> bytes:
        stream = pdfdoc.PDFStream(content=self.streamContent)
        d = stream.dictionary
        d["Type"] = pdfdoc.PDFName("XObject")
        d["Subtype"] = pdfdoc.PDFName("Image")
        d["Width"] = self.width
        d["Height"] = self.height
        d["BitsPerComponent"] = 8
        d["ColorSpace"] = self.color_space
        d["Filter"] = pdfdoc.PDFArray([pdfdoc.PDFName("FlateDecode")])
        d["Length"] = len(self.streamContent)
        return stream.format(document)


def draw_palette_image(c: Canvas, img: Image.Image, x: float, y: float, w: float, h: float) -> None:
    """Draw a mode "P" image into the rectangle, stored as an indexed PDF image.

    Pixel indices must lie below the image's colour count (true for images from
    ``Image.quantize`` / ``convert("P", colors=n)``). Like ``drawImage``, the
    same image drawn twice is stored once.
    """
    if img.mode != "P":
        raise ValueError(f"expected a palette (mode P) image, got {img.mode}")
    pixels = img.tobytes()
    name = _digester(pixels + bytes(img.getpalette("RGB") or []))
    reg_name = c._doc.getXObjectName(name)
    if reg_name not in c._doc.idToObject:
        obj = _IndexedImage(name, img, pixels)
        c._setXObjects(obj)
        c._doc.Reference(obj, reg_name)
        c._doc.addForm(name, obj)
    c.saveState()
    c.translate(x, y)
    c.scale(w, h)
    c._code.append(f"/{reg_name} Do")
    c.restoreState()
    c._formsinuse.append(name)
    c._currentPageHasImages = 1  # as drawImage does
