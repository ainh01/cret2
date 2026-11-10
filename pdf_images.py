"""Extract source text, confirmed figures and non-publishable page evidence from PDFs."""

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
CAPTION_RE = re.compile(r"^(?:figure|fig\.?|hình|hinh)\s*(\d+)\b", re.IGNORECASE)
HEADING_RE = re.compile(r"^\d+(?:\.\d+)+\.?\s+\S")
TOC_LEADER_RE = re.compile(r"\.{3,}")
MAX_PAGE_EVIDENCE = 20


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
        if min(info.get('width', 0), info.get('height', 0)) < 32:
            continue
        if bbox.get_area() >= area * SCAN_COVER:
            return True
    return False


def ocr_text(page):
    try:
        textpage = page.get_textpage_ocr(language="vie+eng", dpi=120, full=True)
        return (textpage.extractText() or "").strip()
    except Exception:
        return ""


def smooth_gradient(doc, xref):
    """Smooth shading layers have no meaningful edges, even when stretched."""
    try:
        pix = pymupdf.Pixmap(doc, xref)
        if pix.width > 4096 or pix.height > 4096 or pix.n < 3:
            return False
        width, height = pix.width, pix.height
        if min(width, height) < 16:
            return True
        samples = edges = total_change = 0
        for y in range(0, height - 1, max(1, height // 64)):
            for x in range(0, width - 1, max(1, width // 64)):
                color = pix.pixel(x, y)
                for other in (pix.pixel(x + 1, y), pix.pixel(x, y + 1)):
                    samples += 1
                    change = max(abs(color[i] - other[i]) for i in range(3))
                    total_change += change
                    edges += change > 8
        # Solid-color diagrams are not necessarily backgrounds: require a
        # smooth but nonzero gradient in addition to the lack of sharp edges.
        return bool(samples) and .03 < total_change / samples < 3 and edges / samples < 0.0005
    except Exception:
        return False


def raster_placements(doc):
    placements = {}
    for page_index, page in enumerate(doc):
        for info in page.get_image_info(xrefs=True):
            xref = info.get("xref") or 0
            if not xref:
                continue
            bbox = pymupdf.Rect(info["bbox"])
            placements.setdefault(xref, []).append({"page": page_index + 1, "bbox": bbox,
                                                    "width": info.get("width", 0),
                                                    "height": info.get("height", 0),
                                                    "page_area": page.rect.get_area() or 1})
    kept = []
    for xref, spots in placements.items():
        gradient = None
        for spot in spots:
            bbox = spot['bbox']
            # One-pixel gradients are stretched over the slide, not illustrations.
            # Full-page layers are ambiguous and remain available as page evidence.
            if min(spot['width'], spot['height']) < 16:
                continue
            if in_margin(bbox) or bbox.get_area() < MIN_RASTER_AREA or bbox.height < MIN_RASTER_HEIGHT:
                continue
            if bbox.get_area() / spot['page_area'] > 0.45:
                continue
            if len(spots) >= 3 and bbox.width >= doc[spot['page'] - 1].rect.width * .8:
                continue
            if len(spots) >= 3 and bbox.y0 < doc[spot['page'] - 1].rect.height * .2 and bbox.width / max(bbox.height, 1) > 4:
                continue
            if gradient is None:
                gradient = smooth_gradient(doc, xref)
            if gradient:
                continue
            # Repetition alone is not enough to discard a meaningful image.
            kept.append({"xref": xref, "page": spot["page"], "bbox": bbox})
    return kept


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


def order_figures(figures):
    """Top-to-bottom rows, then left-to-right within vertically overlapping figures."""
    ordered = sorted(figures, key=lambda f: (f['clip'].y0, f['clip'].x0))
    rows = []
    for figure in ordered:
        rect = figure['clip']
        if rows:
            previous = rows[-1]
            overlap = min(previous['bottom'], rect.y1) - max(previous['top'], rect.y0)
            if overlap >= .5 * min(previous['bottom'] - previous['top'], rect.height):
                previous['items'].append(figure)
                previous['top'] = min(previous['top'], rect.y0)
                previous['bottom'] = max(previous['bottom'], rect.y1)
                continue
        rows.append({'top': rect.y0, 'bottom': rect.y1, 'items': [figure]})
    return [figure for row in rows for figure in sorted(row['items'], key=lambda f: f['clip'].x0)]


def page_body(page, figures):
    """Reading-order text with image markers; never discard overlapping evidence."""
    parts = []
    emitted = set()
    pending = [figure for figure in figures if not figure.get("caption_bbox")]
    pending = order_figures(pending)

    def emit(figure):
        parts.append(f"[[fig:{figure['id']}]]")
        if figure.get("caption"):
            parts.append(figure["caption"])

    for line in lines_of(page):
        while pending and pending[0]["clip"].y0 <= line["bbox"].y0:
            emit(pending.pop(0))
        caption = next((figure for figure in figures
                        if figure.get("caption_bbox") and figure["caption_bbox"].intersects(line["bbox"])
                        and CAPTION_RE.match(line["text"])), None)
        if caption and id(caption) not in emitted:
            emit(caption)
            emitted.add(id(caption))
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


def drawing_signature(drawing, page):
    r = pymupdf.Rect(drawing['rect'])
    # Rounded geometry and color identify repeated slide decoration, not a lone
    # repeated shape in the same diagram.
    return (round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1),
            tuple(round(x, 2) for x in (drawing.get('fill') or ())),
            tuple(round(x, 2) for x in (drawing.get('color') or ())),
            tuple(item[0] for item in drawing.get('items', [])[:100]),
            len(drawing.get('items', [])), round(page.rect.width), round(page.rect.height))


def repeated_drawings(doc):
    pages = {}
    for index, page in enumerate(doc):
        for drawing in page.get_drawings():
            key = drawing_signature(drawing, page)
            pages.setdefault(key, set()).add(index)
    return {key for key, indexes in pages.items() if len(indexes) >= 3}


def vector_figure_clips(page, excluded, existing):
    """Conservative geometric clusters; ambiguous content remains page evidence."""
    try:
        table_rects = [pymupdf.Rect(t.bbox) for t in page.find_tables().tables]
    except Exception:
        table_rects = []
    pieces = []
    drawings_on_page = page.get_drawings()
    if len(drawings_on_page) > 3000:
        return []
    for drawing in drawings_on_page:
        rect = pymupdf.Rect(drawing['rect'])
        if rect.is_infinite or drawing_signature(drawing, page) in excluded:
            continue
        if rect.width < 1 and rect.height < 1:
            continue
        if rect.width >= page.rect.width * .8 or rect.height >= page.rect.height * .8:
            continue
        if is_rule(rect) or in_margin(rect):
            continue
        if any((rect & table).get_area() / max(rect.get_area(), 1) > .5 for table in table_rects):
            continue
        expanded = pymupdf.Rect(rect.x0 - 5, rect.y0 - 5, rect.x1 + 5, rect.y1 + 5)
        pieces.append((expanded, drawing))
    groups = []
    for rect, drawing in pieces:
        overlapping = [i for i, (box, _) in enumerate(groups) if box.intersects(rect)]
        combined, members = pymupdf.Rect(rect), [drawing]
        for i in reversed(overlapping):
            box, drawings = groups.pop(i)
            combined.include_rect(box)
            members.extend(drawings)
        # Merge transitively when the union bridges previously separate groups.
        changed = True
        while changed:
            changed = False
            for i in range(len(groups) - 1, -1, -1):
                if combined.intersects(groups[i][0]):
                    box, drawings = groups.pop(i)
                    combined.include_rect(box)
                    members.extend(drawings)
                    changed = True
        groups.append((combined, members))
    clips = []
    for box, drawings in groups:
        box &= page.rect
        if box.get_area() < MIN_FIGURE_AREA or box.width < 65 or box.height < 45:
            continue
        if box.get_area() > page.rect.get_area() * .45:
            continue
        if table_like(drawings) or any(box.intersects(rect) for rect in table_rects):
            continue
        if any((box & r).get_area() / max(box.get_area(), 1) > .4 for r in existing):
            continue
        curves = sum(item[0] == 'c' for d in drawings for item in d.get('items', []))
        if curves < 4:
            continue
        intersecting_lines = [line for line in lines_of(page) if box.intersects(line['bbox'])]
        long_text = sum(len(line['text']) for line in intersecting_lines if len(line['text']) > 32)
        if long_text > 80 or any(re.match(r'^\d+(?:\.\d+)*\.?\s*\S', line['text'])
                                 and line['size'] >= 20 for line in intersecting_lines):
            continue
        # Avoid cutting a prose or formula line at the crop border. The page
        # render remains available when a diagram cannot be cleanly isolated.
        if any(not box.contains(line['bbox']) and len(line['text']) > 4
               and (box & line['bbox']).get_area() / max(line['bbox'].get_area(), 1) > .12
               for line in intersecting_lines):
            continue
        # Include short labels immediately beside the ink, but not long prose.
        nearby = pymupdf.Rect(box.x0 - 12, box.y0 - 12, box.x1 + 12, box.y1 + 12)
        for line in lines_of(page):
            if len(line['text']) <= 32 and nearby.intersects(line['bbox']):
                box.include_rect(line['bbox'])
        clips.append(box & page.rect)
    return sorted(clips, key=lambda r: (r.y0, r.x0))


def digital_page(doc, page, page_number, rasters, next_id, repeated=None):
    captions = []
    for line in lines_of(page):
        if CAPTION_RE.match(line["text"]) and not TOC_LEADER_RE.search(line["text"]):
            captions.append(line)
    figures = []
    previous_bottom = HEADER_BOTTOM
    for caption in captions:
        clip = figure_clip(page, caption, previous_bottom, rasters, page_number)
        previous_bottom = caption["bbox"].y1
        if clip is None:
            continue
        figures.append({
            "id": "",
            "bytes": render_clip(page, clip),
            "caption": caption["text"],
            "clip": clip,
            "caption_bbox": caption["bbox"],
        })
    for raster in rasters:
        if raster["page"] != page_number or any(
                f['clip'].intersects(raster['bbox']) and
                (f['clip'] & raster['bbox']).get_area() / max(raster['bbox'].get_area(), 1) >= .7
                for f in figures):
            continue
        figures.append({
            "id": "",
            "bytes": render_clip(page, raster["bbox"]),
            "caption": f"Hình, trang PDF {page_number}",
            "clip": raster["bbox"],
            "caption_bbox": None,
        })
    existing = [figure['clip'] for figure in figures]
    for clip in vector_figure_clips(page, repeated or set(), existing):
        figures.append({'id': '', 'bytes': render_clip(page, clip),
                        'caption': f'Sơ đồ, trang PDF {page_number}',
                        'clip': clip, 'caption_bbox': None})
    figures = order_figures(figures)
    for figure in figures:
        figure['id'] = str(next_id)
        figure['page'] = page_number
        figure['bbox'] = list(figure['clip'])
        next_id += 1
    body = page_body(page, figures)
    tables = page_tables(page, figures)
    return body + ('\n\n' + tables if tables else ''), figures, next_id


def extract(path, include_evidence=False):
    """Return text and figures, optionally with separate visual page evidence."""
    doc = pymupdf.open(path)
    try:
        rasters = raster_placements(doc)
        repeated = repeated_drawings(doc)
        chunks = []
        figures = []
        evidence = []
        next_id = 1
        for index, page in enumerate(doc):
            if is_scan_page(page):
                text = ocr_text(page) or page.get_text("text").strip()
                chunks.append(f"[Trang PDF {index + 1}]\n" + (text or "[Không trích xuất được văn bản OCR; kiểm tra ảnh trang gốc.]"))
                if include_evidence and len(evidence) < MAX_PAGE_EVIDENCE:
                    evidence.append({'page': index + 1, 'caption': f'Trang PDF {index + 1} (chỉ dùng làm nguồn)',
                                     'bytes': render_page(page)})
                elif include_evidence:
                    chunks[-1] += '\n[Không kèm ảnh trang này; cần kiểm tra PDF gốc.]'
                continue
            text, page_figures, next_id = digital_page(doc, page, index + 1, rasters, next_id, repeated)
            figures.extend({"id": figure["id"], "bytes": figure["bytes"], "caption": figure["caption"],
                            "page": figure['page'], "bbox": figure['bbox']} for figure in page_figures)
            # Equations, composite layers and vector drawings can be missing from
            # extracted text. The full page is evidence, never a numbered figure.
            if include_evidence:
                if len(evidence) < MAX_PAGE_EVIDENCE:
                    evidence.append({'page': index + 1, 'caption': f'Trang PDF {index + 1} (chỉ dùng làm nguồn)',
                                     'bytes': render_page(page)})
                else:
                    text += '\n[Không kèm ảnh trang này; cần kiểm tra PDF gốc.]'
            if text or include_evidence:
                chunks.append(f'[Trang PDF {index + 1}]\n{text}')
        result = ("\n\n".join(chunks).strip(), figures)
        return (*result, evidence) if include_evidence else result
    finally:
        doc.close()
