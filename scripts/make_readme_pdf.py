#!/usr/bin/env python3
"""Render a Markdown file as a simple paginated PDF using AppKit/Quartz.

No external dependencies — uses PyObjC (AppKit, Quartz).
Cyrillic-safe: system fonts handle non-Latin glyphs.

Usage: python3 make_readme_pdf.py <input.md> <output.pdf>
"""

from __future__ import annotations

import sys

import AppKit
import Quartz

PAGE_W, PAGE_H = 595.0, 842.0  # A4 portrait
MARGIN = 54.0
BODY_SIZE = 10.0
LEADING = 13.5
PARA_GAP = 5.0
TEXT_WIDTH = PAGE_W - 2 * MARGIN
TEXT_HEIGHT = PAGE_H - 2 * MARGIN


def _clean_markdown(text: str) -> list[str]:
    """Strip common Markdown decorations, keep structure as a list of paragraphs."""
    paragraphs: list[str] = []
    buf: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped in ("---", "") or stripped.startswith("```"):
            if buf:
                paragraphs.append("\n".join(buf))
                buf = []
            continue
        if stripped.startswith("#"):
            if buf:
                paragraphs.append("\n".join(buf))
                buf = []
            paragraphs.append(stripped.lstrip("#").strip())
            continue
        if stripped.startswith(">"):
            buf.append(stripped.lstrip(">").strip())
            continue
        if stripped.startswith(("- ", "* ")):
            buf.append("  • " + stripped[2:].strip())
            continue
        buf.append(line)
    if buf:
        paragraphs.append("\n".join(buf))
    return paragraphs


def _attrs(size: float, bold: bool = False) -> dict:
    font_name = "Helvetica-Bold" if bold else "Helvetica"
    font = AppKit.NSFont.fontWithName_size_(font_name, size)
    if font is None:
        font = AppKit.NSFont.systemFontOfSize_(size)
    paragraph = AppKit.NSMutableParagraphStyle.alloc().init()
    paragraph.setLineSpacing_(2.0)
    return {
        AppKit.NSFontAttributeName: font,
        AppKit.NSForegroundColorAttributeName: AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.1, 0.1, 1.0),
        AppKit.NSParagraphStyleAttributeName: paragraph,
    }


def _wrap_height(text: str, attrs: dict) -> float:
    ns = AppKit.NSString.stringWithString_(text)
    rect = ns.boundingRectWithSize_options_attributes_(
        AppKit.NSMakeSize(TEXT_WIDTH, 1e9),
        AppKit.NSStringDrawingUsesLineFragmentOrigin,
        attrs,
    )
    return rect.size.height


def make_pdf(md_path: str, pdf_path: str) -> None:
    with open(md_path, encoding="utf-8") as f:
        text = f.read()
    paragraphs = _clean_markdown(text)
    if not paragraphs:
        paragraphs = [""]

    pdf_bytes = pdf_path.encode("utf-8")
    url = Quartz.CFURLCreateFromFileSystemRepresentation(None, pdf_bytes, len(pdf_bytes), False)
    media_box = Quartz.CGRectMake(0.0, 0.0, PAGE_W, PAGE_H)
    context = Quartz.CGPDFContextCreateWithURL(url, media_box, None)
    if context is None:
        raise RuntimeError(f"Could not create PDF context for {pdf_path}")

    ns_context = AppKit.NSGraphicsContext.graphicsContextWithGraphicsPort_flipped_(context, False)
    AppKit.NSGraphicsContext.setCurrentContext_(ns_context)

    # Build a list of (text, attrs, height) items
    items: list[tuple[str, dict, float]] = []
    for para in paragraphs:
        if para.strip().startswith(" ") or (len(para) < 80 and para.strip() and not para.startswith("  ")):
            is_heading = len(para.strip()) < 80 and not para.startswith("  ")
        else:
            is_heading = False
        size = 13.0 if is_heading else BODY_SIZE
        attrs = _attrs(size, bold=is_heading)
        height = _wrap_height(para, attrs)
        items.append((para, attrs, height))

    page = 0
    y = PAGE_H - MARGIN
    for para, attrs, height in items:
        block_height = height + PARA_GAP
        if y - block_height < MARGIN:
            Quartz.CGContextEndPage(context)
            page += 1
            y = PAGE_H - MARGIN
        if page == 0 or y == PAGE_H - MARGIN:
            Quartz.CGContextBeginPage(context, media_box)
            Quartz.CGContextSetRGBFillColor(context, 1.0, 1.0, 1.0, 1.0)
            Quartz.CGContextFillRect(context, media_box)
        draw_rect = AppKit.NSMakeRect(MARGIN, y - height, TEXT_WIDTH, height)
        AppKit.NSString.stringWithString_(para).drawInRect_withAttributes_(draw_rect, attrs)
        y -= block_height

    if page == 0 or y != PAGE_H - MARGIN:
        Quartz.CGContextEndPage(context)
    Quartz.CGContextFlush(context)
    Quartz.CGPDFContextClose(context)
    print(f"PDF written: {pdf_path} ({page + 1} page(s))")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 make_readme_pdf.py <input.md> <output.pdf>")
        sys.exit(1)
    make_pdf(sys.argv[1], sys.argv[2])
