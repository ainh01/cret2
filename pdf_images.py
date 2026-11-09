"""Pull figures out of a PDF for the lesson pipeline.

A Word-exported datasheet stores the logo as a repeated image and the real
diagrams as vectors. Tables are vectors too, so only a "Figure N" caption, a
large unique raster, or a scanned page becomes an image. Everything extracted
here is kept; the caller does not rank or drop it.
"""

import json
import re

import pymupdf


HEADER_BOTTOM = 78.0
FOOTER_TOP = 715.0
CONTENT_X0 = 36.0
MIN_RASTER_AREA = 30_000.0
MIN_RASTER_HEIGHT = 80.0
MIN_FIGURE_AREA = 8_000.0
RENDER_ZOOM = 2.0
SCAN_COVER = 0.65
CAPTION_RE = re.compile(r"^figure\s+(\d+)\b", re.IGNORECASE)
HEADING_RE = re.compile(r"^\d+(?:\.\d+)+\.?\s+\S")
TOC_LEADER_RE = re.compile(r"\.{3,}")


def is_pdf(path, filename=""):
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return True
    try:
        with open(path, "rb") as handle:
            return handle.read(5) == b"%PDF-"
    except OSError:
        return False


def lines_of(page):
    found = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines") or []:
            text = "".join(span["text"] for span in line.get("spans") or []).strip()
            if not text:
                continue
            sizes = [span.get("size") or 0 for span in line.get("spans") or []]
            found.append({
                "text": text,
                "bbox": pymupdf.Rect(line["bbox"]),
                "size": max(sizes) if sizes else 0,
            })
    found.sort(key=lambda item: (round(item["bbox"].y0, 1), item["bbox"].x0))
    return found


def in_margin(rect):
    return rect.y1 <= HEADER_BOTTOM or rect.y0 >= FOOTER_TOP


def is_rule(rect):
    return (rect.height < 1.6 and rect.width > 180) or (rect.width < 1.6 and rect.height > 180)


def pixmap_png(pix):
    if pix.n >= 4:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    return pix.tobytes("png")


def render_clip(page, clip):
    pix = page.get_pixmap(matrix=pymupdf.Matrix(RENDER_ZOOM, RENDER_ZOOM), clip=clip, alpha=False)
    return pixmap_png(pix)


def render_page(page):
    pix = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
    return pixmap_png(pix)


def is_scan_page(page):
    if len(page.get_text("text").strip()) >= 80:
        return False
    area = page.rect.get_area() or 1
    for info in page.get_image_info():
        bbox = pymupdf.Rect(info["bbox"])
        if bbox.get_area() >= area * SCAN_COVER:
            return True
    return False


def ocr_text(page):
    try:
        textpage = page.get_textpage_ocr(language="vie+eng", dpi=120, full=True)
        return (textpage.extractText() or "").strip()
    except Exception:
        return ""


def raster_placements(doc):
    placements = {}
    for page_index, page in enumerate(doc):
        for info in page.get_image_info(xrefs=True):
            xref = info.get("xref") or 0
            if not xref:
                continue
            bbox = pymupdf.Rect(info["bbox"])
            placements.setdefault(xref, []).append({"page": page_index + 1, "bbox": bbox})
    kept = []
    for xref, spots in placements.items():
        areas = [spot["bbox"].get_area() for spot in spots]
        heights = [spot["bbox"].height for spot in spots]
        if len(spots) >= 3 or max(areas) < MIN_RASTER_AREA or max(heights) < MIN_RASTER_HEIGHT:
            continue
        if all(in_margin(spot["bbox"]) for spot in spots):
            continue
        for spot in spots:
            if in_margin(spot["bbox"]) or spot["bbox"].get_area() < MIN_RASTER_AREA:
                continue
            kept.append({"xref": xref, "page": spot["page"], "bbox": spot["bbox"]})
    return kept


def save_raster(doc, xref):
    extracted = doc.extract_image(xref)
    raw = extracted.get("image") or b""
    if extracted.get("smask") or not raw:
        pix = pymupdf.Pixmap(doc, xref)
        return pixmap_png(pix)
    if raw.startswith(b"\x89PNG") or raw.startswith(b"\xff\xd8\xff") or (raw.startswith(b"RIFF") and raw[8:12] == b"WEBP"):
        return raw if raw.startswith(b"\x89PNG") or raw.startswith(b"\xff\xd8\xff") else pixmap_png(pymupdf.Pixmap(doc, xref))
    return pixmap_png(pymupdf.Pixmap(doc, xref))


def intersecting_drawings(page, band):
    chosen = []
    for drawing in page.get_drawings():
        rect = pymupdf.Rect(drawing["rect"])
        if rect.is_empty or rect.is_infinite or is_rule(rect) or in_margin(rect):
            continue
        if rect.intersects(band):
            chosen.append(drawing)
    return chosen


def table_like(drawings):
    curves = rects = 0
    for drawing in drawings:
        for item in drawing.get("items") or []:
            if item[0] == "c":
                curves += 1
            elif item[0] == "re":
                rects += 1
    if curves >= 6:
        return False
    return rects >= 20 and curves <= 2


def content_images(page, band, rasters, page_number):
    found = []
    for raster in rasters:
        if raster["page"] == page_number and raster["bbox"].intersects(band) and raster["bbox"].get_area() >= MIN_RASTER_AREA:
            found.append(raster)
    return found


def figure_clip(page, caption, previous_bottom, rasters, page_number):
    # Table captions are often close to a figure. Never consume their cells into
    # the figure crop, or they disappear from the ground-truth text.
    table_rects = []
    try:
        table_rects = [pymupdf.Rect(table.bbox) for table in page.find_tables().tables]
    except Exception:
        pass
    band_top = max(HEADER_BOTTOM, previous_bottom)
    for rect in table_rects:
        if rect.y1 < caption['bbox'].y0 and rect.y1 > band_top:
            band_top = rect.y1
    band = pymupdf.Rect(CONTENT_X0, band_top + 1, page.rect.width - CONTENT_X0, caption["bbox"].y1 + 2)
    drawings = intersecting_drawings(page, band)
    images = content_images(page, band, rasters, page_number)
    if table_like(drawings) and not images:
        return None
    ink = pymupdf.Rect()
    for drawing in drawings:
        ink.include_rect(drawing["rect"])
    for raster in images:
        ink.include_rect(raster["bbox"])
    upper = band_top
    for line in lines_of(page):
        if line["bbox"].y1 >= caption["bbox"].y0 - 1:
            break
        if line["bbox"].y1 <= upper or in_margin(line["bbox"]):
            continue
        if (not ink.is_empty) and line["bbox"].intersects(ink):
            continue
        if HEADING_RE.match(line["text"]) or line["size"] >= 14:
            upper = line["bbox"].y1
    union = pymupdf.Rect()
    for drawing in drawings:
        if drawing["rect"].y0 >= upper - 2:
            union.include_rect(drawing["rect"])
    for raster in images:
        if raster["bbox"].y0 >= upper - 2:
            union.include_rect(raster["bbox"])
    for line in lines_of(page):
        if in_margin(line["bbox"]):
            continue
        center_y = (line["bbox"].y0 + line["bbox"].y1) / 2
        if upper + 1 <= center_y <= caption["bbox"].y1 + 2:
            union.include_rect(line["bbox"])
    if union.is_empty or union.get_area() < MIN_FIGURE_AREA or union.height < 40:
        return None
    union = pymupdf.Rect(union.x0 - 8, max(HEADER_BOTTOM, union.y0 - 6),
                         union.x1 + 8, min(FOOTER_TOP, union.y1 + 4))
    return union & page.rect


def covered_by_raster(clip, rasters, page_number):
    area = clip.get_area() or 1
    for raster in rasters:
        if raster["page"] != page_number:
            continue
        overlap = (raster["bbox"] & clip).get_area()
        if overlap / area >= 0.55 or overlap / max(raster["bbox"].get_area(), 1) >= 0.7:
            return raster
    return None


def page_body(page, figures):
    """Reading-order text. Figure labels stay out; a placeholder marks the spot."""
    clips = [figure["clip"] for figure in figures if figure.get("clip")]
    parts = []
    emitted = set()
    pending = [figure for figure in figures if not figure.get("caption_bbox")]
    pending.sort(key=lambda figure: figure["clip"].y0)

    def emit(figure):
        parts.append(f"[[fig:{figure['id']}]]")
        if figure.get("caption"):
            parts.append(figure["caption"])

    for line in lines_of(page):
        if in_margin(line["bbox"]):
            continue
        while pending and pending[0]["clip"].y0 <= line["bbox"].y0:
            emit(pending.pop(0))
        center = pymupdf.Point((line["bbox"].x0 + line["bbox"].x1) / 2,
                               (line["bbox"].y0 + line["bbox"].y1) / 2)
        caption = next((figure for figure in figures
                        if figure.get("caption_bbox") and figure["caption_bbox"].intersects(line["bbox"])
                        and CAPTION_RE.match(line["text"])), None)
        if caption and id(caption) not in emitted:
            emit(caption)
            emitted.add(id(caption))
            continue
        if any(clip.contains(center) for clip in clips):
            continue
        parts.append(line["text"])
    for figure in pending:
        emit(figure)
    return "\n".join(parts).strip()


def page_tables(page, figures):
    """Supplement reading-order text with extracted table rows; extraction may be imperfect."""
    try:
        tables = page.find_tables().tables
    except Exception:
        return ''
    result = []
    for table in tables:
        bbox = pymupdf.Rect(table.bbox)
        if any(figure.get('clip') and bbox.intersects(figure['clip']) for figure in figures):
            continue
        try:
            rows = [[page.get_textbox(pymupdf.Rect(cell)).strip() if cell else ''
                     for cell in row.cells] for row in table.rows]
        except Exception:
            continue
        if len(rows) < 2 or max((len(row) for row in rows), default=0) < 2:
            continue
        result.append('Bảng trích xuất tự động (kiểm tra vị trí ô với PDF gốc):\n' +
                      '\n'.join(json.dumps([str(cell).strip() if cell is not None else '' for cell in row],
                                           ensure_ascii=False) for row in rows))
    return '\n\n'.join(result)


def digital_page(doc, page, page_number, rasters, next_id):
    captions = []
    for line in lines_of(page):
        if CAPTION_RE.match(line["text"]) and not TOC_LEADER_RE.search(line["text"]):
            captions.append(line)
    figures = []
    used = set()
    previous_bottom = HEADER_BOTTOM
    for caption in captions:
        clip = figure_clip(page, caption, previous_bottom, rasters, page_number)
        previous_bottom = caption["bbox"].y1
        if clip is None:
            continue
        figure_id = str(next_id)
        next_id += 1
        raster = covered_by_raster(clip, rasters, page_number)
        if raster is not None:
            data = save_raster(doc, raster["xref"])
            used.add(raster["xref"])
            kind_clip = raster["bbox"]
        else:
            data = render_clip(page, clip)
            kind_clip = clip
        figures.append({
            "id": figure_id,
            "bytes": data,
            "caption": caption["text"],
            "clip": kind_clip,
            "caption_bbox": caption["bbox"],
        })
    for raster in rasters:
        if raster["page"] != page_number or raster["xref"] in used:
            continue
        figure_id = str(next_id)
        next_id += 1
        figures.append({
            "id": figure_id,
            "bytes": save_raster(doc, raster["xref"]),
            "caption": "",
            "clip": raster["bbox"],
            "caption_bbox": None,
        })
        used.add(raster["xref"])
    figures.sort(key=lambda figure: figure["clip"].y0)
    body = page_body(page, figures)
    tables = page_tables(page, figures)
    return body + ('\n\n' + tables if tables else ''), figures, next_id


def extract(path):
    """Return (text, figures). Each figure is {id, bytes, caption}."""
    doc = pymupdf.open(path)
    try:
        rasters = raster_placements(doc)
        chunks = []
        figures = []
        next_id = 1
        for index, page in enumerate(doc):
            if is_scan_page(page):
                figure_id = str(next_id)
                next_id += 1
                caption = f"Trang {index + 1}"
                figures.append({"id": figure_id, "bytes": render_page(page), "caption": caption})
                text = ocr_text(page) or page.get_text("text").strip()
                chunks.append(f"[Trang PDF {index + 1}]\n[[fig:{figure_id}]]\n{caption}" + (f"\n{text}" if text else "\n[Không trích xuất được văn bản OCR; kiểm tra ảnh trang gốc.]"))
                continue
            text, page_figures, next_id = digital_page(doc, page, index + 1, rasters, next_id)
            figures.extend({"id": figure["id"], "bytes": figure["bytes"], "caption": figure["caption"]}
                           for figure in page_figures)
            if text:
                chunks.append(f'[Trang PDF {index + 1}]\n{text}')
        return "\n\n".join(chunks).strip(), figures
    finally:
        doc.close()
