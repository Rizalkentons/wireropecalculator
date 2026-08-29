import fitz  # PyMuPDF


def _get_occluding_rects(page, min_channel=0.95):
    """(rect, seqno) for white (or near-white) filled shapes on the page.

    Some quotation-generating software "overrides" a description field by
    painting a white rectangle over the old auto-generated text and then
    drawing the new text on top — both text runs remain in the PDF's
    content stream and are extractable. Geometry alone can't tell them
    apart (the new text often sits inside the same rectangle's area too),
    so we keep the rect's draw order (seqno) to compare against each
    character's own seqno: only text drawn BEFORE the rectangle is
    actually hidden by it.
    """
    rects = []
    for draw in page.get_drawings():
        fill = draw.get("fill")
        if not fill or len(fill) < 3:
            continue
        if all(c >= min_channel for c in fill[:3]):
            rects.append((draw["rect"], draw.get("seqno", 0)))
    return rects


def _get_visible_chars(page):
    """All visible (unicode_codepoint, bbox) pairs on the page, in stream
    order, with characters hidden under a later-drawn white rectangle
    excluded. bbox is a plain 4-tuple.
    """
    occluding = _get_occluding_rects(page)
    visible = []
    for rec in page.get_texttrace():
        rec_seqno = rec.get("seqno", 0)
        for ch in rec.get("chars", []):
            cp, _glyph, _origin, bbox = ch
            char_rect = fitz.Rect(bbox)
            area = char_rect.get_area()
            hidden = False
            if area > 0:
                for rect, rect_seqno in occluding:
                    if rect_seqno <= rec_seqno:
                        continue  # rect drawn before this char — can't hide it
                    if (char_rect & rect).get_area() / area >= 0.8:
                        hidden = True
                        break
            if not hidden:
                visible.append((cp, bbox))
    return visible


def _chars_to_text(chars):
    """Join (codepoint, bbox) chars into a readable string: group into
    visual lines by y-position, chars left-to-right within each line,
    lines joined top-to-bottom with a space (matches how a wrapped cell's
    lines were previously joined).
    """
    if not chars:
        return ""

    chars = sorted(chars, key=lambda c: (round(c[1][1], 0), c[1][0]))
    lines = []
    current_line = [chars[0]]
    current_y = chars[0][1][1]
    for cp, bbox in chars[1:]:
        if abs(bbox[1] - current_y) > 3:
            lines.append(current_line)
            current_line = []
            current_y = bbox[1]
        current_line.append((cp, bbox))
    lines.append(current_line)

    line_texts = []
    for line in lines:
        line = sorted(line, key=lambda c: c[1][0])
        line_texts.append("".join(chr(cp) for cp, _ in line).strip())
    return " ".join(t for t in line_texts if t)


def _extract_table_rows(page):
    """Return (text, row_bbox, description_col_x) using PyMuPDF's table
    detector, with each row's text rebuilt from visible characters only
    (see _get_visible_chars) so leftover text hidden under a white
    "cover-up" rectangle doesn't get merged into the real description.

    Real quotation templates often draw a full-width "product description"
    row (all 6 columns merged into one cell) above several plain line-item
    rows (No/Description/Qty/Unit/Unit Price/Total each populated). Table
    detection reconstructs a wrapped multi-line cell as one string, which
    plain block/line text extraction does not reliably do — a wrapped cell
    can be split across multiple text blocks by the PDF generator.

    Also returns, per row, the x-range of the "Description" column itself
    (found from the header row's cell boundaries) — used to horizontally
    align an inserted picture with that column instead of the full
    (often full-width-merged) row bbox.

    description_col_x is an (x0, x1) tuple, or None if no
    "Description"-named column was found.
    """
    rows_out = []
    visible_chars = _get_visible_chars(page)
    tables = page.find_tables()
    for table in tables.tables:
        desc_col_x = None
        header_names = [str(n or "").strip().lower() for n in table.header.names]
        if "description" in header_names:
            col_idx = header_names.index("description")
            header_cells = table.rows[0].cells if table.rows else None
            if header_cells and col_idx < len(header_cells) and header_cells[col_idx]:
                cell = header_cells[col_idx]
                desc_col_x = (cell[0], cell[2])

        for row_cells in table.rows:
            row_bbox = fitz.Rect(row_cells.bbox)
            row_chars = [
                (cp, bbox)
                for cp, bbox in visible_chars
                if row_bbox.contains(fitz.Point((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2))
            ]
            text = _chars_to_text(row_chars)
            if not text:
                continue
            rows_out.append((text, tuple(row_bbox), desc_col_x))
    return rows_out


def extract_lines_with_bbox(pdf_path):
    """Return a list of (page_number, text, bbox, description_col_x) of
    matchable text regions.

    Prefers table-row extraction (reconstructs merged/wrapped cells
    correctly, and excludes text hidden under a white cover-up
    rectangle); for content outside any detected table, falls back to
    plain PyMuPDF block-level text (grouping wrapped lines within one
    block) — description_col_x is None in that fallback case.

    bbox is (x0, y0, x1, y1) in PDF point coordinates, matching what
    page.insert_image() expects on the same page. description_col_x is an
    (x0, x1) tuple for the Description column itself (narrower than bbox
    when the row is a full-width-merged cell), or None if unknown.
    """
    results = []
    doc = fitz.open(pdf_path)
    try:
        for page_number, page in enumerate(doc):
            table_rows = _extract_table_rows(page)
            for text, bbox, desc_col_x in table_rows:
                results.append((page_number, text, bbox, desc_col_x))

            if table_rows:
                continue  # this page's content is covered by its table(s)

            page_dict = page.get_text("dict")
            for block in page_dict.get("blocks", []):
                line_texts = []
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    line_text = "".join(span.get("text", "") for span in spans).strip()
                    if line_text:
                        line_texts.append(line_text)
                if not line_texts:
                    continue
                text = " ".join(line_texts)
                bbox = block.get("bbox")
                results.append((page_number, text, bbox, None))
    finally:
        doc.close()
    return results
