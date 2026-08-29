import fitz  # PyMuPDF
from PIL import Image

from .config import (
    DIMENSION_FONT,
    DIMENSION_FONT_COLOR,
    DIMENSION_GAP,
    DIMENSION_LINE_GAP,
    IMAGE_WIDTH_FRACTION,
    SIDE_PADDING,
    TOP_BOTTOM_PADDING,
)

REPEAT_HEADER_GAP = 8  # blank gap between repeated letterhead/table-header and resumed content


def _image_size(image_path, target_width):
    """Return (width, height) scaled to target_width, preserving aspect ratio."""
    with Image.open(image_path) as im:
        iw, ih = im.size
    aspect = iw / ih if ih else 1
    return target_width, target_width / aspect


def _draw_dimensions(page, img_rect, match):
    """List any user-entered a/b/c values as "a = <value>" text stacked to
    the RIGHT of the picture — never overlaid on it, so it can't collide
    with that diagram's own lines/arrows no matter how it's laid out.
    Blank values are skipped — not every diagram has all three (e.g. a
    plain both-ends rope has no eye to label 'a'/'c' on).
    """
    labels = []
    for letter in ("a", "b", "c"):
        value = match.get(f"dim_{letter}")
        if value:
            labels.append(f"{letter} = {value}")
    if not labels:
        return

    font_size = max(8.0, min(13.0, img_rect.height * 0.16))
    line_height = font_size + DIMENSION_LINE_GAP
    block_height = len(labels) * line_height - DIMENSION_LINE_GAP
    x = img_rect.x1 + DIMENSION_GAP
    y = img_rect.y0 + (img_rect.height - block_height) / 2 + font_size

    for label in labels:
        page.insert_text(
            (x, y),
            label,
            fontsize=font_size,
            fontname=DIMENSION_FONT,
            color=DIMENSION_FONT_COLOR,
        )
        y += line_height


def _header_row_signature(cells):
    """Normalize a table row's cell texts for lenient repeat-header
    comparison — case/whitespace can drift between a template's pages
    (e.g. "QTY" vs "Qty")."""
    return tuple((c or "").strip().lower() for c in cells)


def _detect_repeat_header(src_page, page_w):
    """Find the letterhead (logo/name/address block) and the item table's
    own column-header row on a source page, so continuation pages (created
    when pagination overflows) can repeat just those two — never the
    customer-specific "TO:"/"Information"/Payment/Currency block between
    them. Returns (letterhead_rect, table_header_rect); either is None if
    not confidently detected (continuation pages then just skip repeating
    whichever part is missing, rather than erroring).

    The letterhead is identified by the topmost thin, nearly-full-width
    horizontal rule most invoice templates draw under the company
    name/address block — everything above that line is the letterhead.
    """
    letterhead_rect = None
    best_y = None
    for d in src_page.get_drawings():
        r = d.get("rect")
        if r is None or r.height > 2 or r.width < 0.8 * page_w:
            continue
        if best_y is None or r.y0 < best_y:
            best_y = r.y0
            letterhead_rect = fitz.Rect(0, 0, page_w, r.y0)

    table_header_rect = None
    tables = src_page.find_tables()
    if tables.tables:
        first_table = tables.tables[0]
        if first_table.rows:
            table_header_rect = fitz.Rect(first_table.rows[0].bbox)

    return letterhead_rect, table_header_rect


def _draw_repeat_header(page, src, page_number, page_w, letterhead_rect, table_header_rect):
    """Draw the repeated letterhead + table-header at the top of a fresh
    continuation page. Returns the y-coordinate where normal content
    should resume.
    """
    cursor_dst_y = 0.0
    if letterhead_rect is not None:
        h = letterhead_rect.height
        dst_rect = fitz.Rect(0, cursor_dst_y, page_w, cursor_dst_y + h)
        page.show_pdf_page(dst_rect, src, page_number, clip=letterhead_rect)
        cursor_dst_y += h + REPEAT_HEADER_GAP
    if table_header_rect is not None:
        h = table_header_rect.height
        dst_rect = fitz.Rect(0, cursor_dst_y, page_w, cursor_dst_y + h)
        page.show_pdf_page(dst_rect, src, page_number, clip=table_header_rect)
        cursor_dst_y += h + REPEAT_HEADER_GAP
    return cursor_dst_y


def _merge_overlapping_bands(y_ranges):
    """Merge (y0, y1) ranges that truly overlap (not just touch) into
    consolidated bands. Needed because PyMuPDF's table.rows can include
    overlapping bboxes for a merged-cell layout — e.g. a "notes" cell that
    spans the full height of several narrower sub-rows (Total/PPN/Grand
    Total) stacked beside it. Treating those as separate sequential blocks
    would count that vertical space 2-3x over. A tolerance of 0.5pt avoids
    merging normal adjacent rows that just happen to touch exactly at a
    shared boundary (row N's y1 == row N+1's y0).
    """
    if not y_ranges:
        return []
    ranges = sorted(y_ranges)
    merged = [list(ranges[0])]
    for y0, y1 in ranges[1:]:
        last = merged[-1]
        if y0 < last[1] - 0.5:
            last[1] = max(last[1], y1)
        else:
            merged.append([y0, y1])
    return [tuple(b) for b in merged]


def _content_bottom(src_page, min_y, page_h, padding=8.0):
    """Lowest y-coordinate of any real content (text or drawing) at or
    below min_y — NOT page_h itself, since a source page's printable
    content (e.g. footer notes/signature) usually ends well before the
    physical page bottom, leaving a lot of blank trailing space. Using
    page_h directly would count that blank space as part of the last
    "content" block, which then can't fit remaining room on a page and
    gets pushed onto a needless extra page. Returns min_y (nothing found)
    up to page_h, plus a little padding so the last line isn't clipped.
    """
    max_y = min_y
    for block in src_page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span["bbox"][1] >= min_y - 0.5:
                    max_y = max(max_y, span["bbox"][3])
    for dr in src_page.get_drawings():
        r = dr.get("rect")
        if r is not None and r.y0 >= min_y - 0.5:
            max_y = max(max_y, r.y1)
    return min(max_y + padding, page_h)


def _build_blocks(
    src_page, page_matches, picture_paths, page_w, page_h, target_width, top_bottom_padding,
    canonical_header_signature=None,
):
    """Break a source page's content into an ordered top-to-bottom list of
    placeable "blocks", used by the pagination pass to decide where page
    breaks fall — a block is never split across a page break.

    When the page has a detected table, blocks are built at ROW
    granularity (every row — matched or not — is its own small block,
    with a matched row's picture bundled into the same block as that row
    so they can never be separated onto different pages). This matters:
    without row granularity, "everything after the last match" would be
    ONE big block (material rows + subtotal + totals + footer), and that
    single block would get pushed onto a whole new page as soon as it
    didn't fit the remaining space — even if only a little of it overflowed.

    Falls back to coarser match-based blocks (one block per gap between
    matches) when no table is detected on the page.

    canonical_header_signature: if given, and this page's ENTIRE table is
    a single row whose cell text matches it (see _header_row_signature),
    that row is dropped rather than turned into a content block — it's a
    redundant column-header row some templates bake into every page (e.g.
    a footer-only page), and the real one is already repeated at the top
    of the output page via _draw_repeat_header. Only applies when the
    table has exactly one row — a page whose matching header row is
    followed by real data rows is left completely alone.
    """
    tables = src_page.find_tables()
    row_bboxes = [tuple(r.bbox) for r in tables.tables[0].rows] if tables.tables else []

    if not row_bboxes:
        blocks = []
        cursor_src_y = 0.0
        for m in page_matches:
            insert_at_y = m["bbox"][1]
            strip_h = insert_at_y - cursor_src_y
            if strip_h > 0:
                blocks.append({
                    "type": "content",
                    "src_y0": cursor_src_y,
                    "src_y1": insert_at_y,
                    "height": strip_h,
                })
            cursor_src_y = insert_at_y

            img_w, img_h = _image_size(picture_paths[m["picture_id"]], target_width)
            blocks.append({
                "type": "image",
                "match": m,
                "img_w": img_w,
                "img_h": img_h,
                "height": img_h + 2 * top_bottom_padding,
            })

        content_bottom = _content_bottom(src_page, cursor_src_y, page_h)
        remaining_h = content_bottom - cursor_src_y
        if remaining_h > 0:
            blocks.append({
                "type": "content",
                "src_y0": cursor_src_y,
                "src_y1": content_bottom,
                "height": remaining_h,
            })
        return blocks

    bands = _merge_overlapping_bands([(r[1], r[3]) for r in row_bboxes])

    def _match_for_band(band_y0, band_y1):
        for m in page_matches:
            mid_y = (m["bbox"][1] + m["bbox"][3]) / 2
            if band_y0 <= mid_y <= band_y1:
                return m
        return None

    skip_redundant_header = (
        len(bands) == 1
        and canonical_header_signature is not None
        and _header_row_signature(tables.tables[0].extract()[0]) == canonical_header_signature
    )

    blocks = []
    table_top = bands[0][0]
    if table_top > 0:
        blocks.append({"type": "content", "src_y0": 0.0, "src_y1": table_top, "height": table_top})
    cursor_src_y = table_top

    for i, (row_y0, row_y1) in enumerate(bands):
        row_h = row_y1 - row_y0
        m = _match_for_band(row_y0, row_y1)
        if i == 0 and skip_redundant_header:
            pass  # this page's entire table is just a repeated header row — drop it
        elif m:
            img_w, img_h = _image_size(picture_paths[m["picture_id"]], target_width)
            blocks.append({
                "type": "image_and_row",
                "match": m,
                "img_w": img_w,
                "img_h": img_h,
                "row_src_y0": row_y0,
                "row_src_y1": row_y1,
                "height": img_h + 2 * top_bottom_padding + row_h,
            })
        else:
            blocks.append({"type": "content", "src_y0": row_y0, "src_y1": row_y1, "height": row_h})
        cursor_src_y = row_y1

    content_bottom = _content_bottom(src_page, cursor_src_y, page_h)
    remaining_h = content_bottom - cursor_src_y
    if remaining_h > 0:
        blocks.append({"type": "content", "src_y0": cursor_src_y, "src_y1": content_bottom, "height": remaining_h})

    return blocks


def _place_image(new_page, picture_paths, page_w, side_padding, top_bottom_padding, m, img_w, img_h, dst_y0):
    col_x = m.get("description_col_x")
    left_x = col_x[0] if col_x else m["bbox"][0]
    x0 = max(side_padding, min(left_x, page_w - side_padding - img_w))
    y0 = dst_y0 + top_bottom_padding
    img_rect = fitz.Rect(x0, y0, x0 + img_w, y0 + img_h)
    new_page.insert_image(img_rect, filename=picture_paths[m["picture_id"]], keep_proportion=True)
    _draw_dimensions(new_page, img_rect, m)


def insert_images(
    pdf_path,
    matches,
    picture_paths,
    output_path,
    width_fraction=IMAGE_WIDTH_FRACTION,
    side_padding=SIDE_PADDING,
    top_bottom_padding=TOP_BOTTOM_PADDING,
):
    """Rebuild the PDF with a new blank strip inserted directly above each
    matched row (never below it), containing that item's picture sized to
    `width_fraction` of the page width, left-aligned to the Description
    column itself (not centered on the full row, which is often merged
    across every column) — with everything below pushed down to make room.

    The WHOLE document is treated as one continuous flow of blocks (not
    reflowed one source page at a time): when content overflows a page,
    the next source page's content — even a page with no matches at all,
    like a trailing footer/signature page — flows into any spare room
    left on the current output page rather than always starting a new
    physical page. A page break only happens when content genuinely
    doesn't fit. Every output page is the SAME size as the "canonical"
    source page (the first one with a match) — never one taller page.

    Every output page after the first one that ends up containing at
    least one picture repeats the letterhead + the item table's column
    header row at the top (see _detect_repeat_header), skipping the
    customer-specific info block between them; a continuation page that
    holds no picture (e.g. one that's just leftover footer text) gets no
    repeated header at all. A page's own baked-in column-header row is
    dropped (not duplicated) if that page's entire table is just that one
    row (see _build_blocks's canonical_header_signature).

    The original page content (text, lines, everything) is copied via
    PyMuPDF's show_pdf_page in horizontal strips split at each insertion
    point, so it stays vector/text content — still selectable/searchable,
    not rasterized into an image.

    matches: list of dicts with "page_number", "bbox", "description_col_x", "picture_id"
    picture_paths: dict mapping picture_id -> absolute file path of the image
    """
    src = fitz.open(pdf_path)
    out = fitz.open()

    matches_by_page = {}
    for m in matches:
        if m["picture_id"] not in picture_paths:
            continue
        matches_by_page.setdefault(m["page_number"], []).append(m)

    try:
        if not matches_by_page:
            out.insert_pdf(src)
            out.save(output_path)
            return

        canonical_page_number = min(matches_by_page)
        canonical_src_page = src[canonical_page_number]
        page_w, page_h = canonical_src_page.rect.width, canonical_src_page.rect.height
        target_width = page_w * width_fraction

        letterhead_rect, table_header_rect = _detect_repeat_header(canonical_src_page, page_w)
        header_overhead = 0.0
        if letterhead_rect is not None:
            header_overhead += letterhead_rect.height + REPEAT_HEADER_GAP
        if table_header_rect is not None:
            header_overhead += table_header_rect.height + REPEAT_HEADER_GAP

        canonical_header_signature = None
        canonical_tables = canonical_src_page.find_tables()
        if canonical_tables.tables:
            canonical_header_signature = _header_row_signature(canonical_tables.tables[0].extract()[0])

        # ---- Pass 0: build one combined, ordered block list for the whole
        # document, each block tagged with which source page it came from
        # (needed since show_pdf_page's clip is page-specific, and blocks
        # from different source pages can now land in the same pagination
        # pass / even the same output page). ----
        all_blocks = []
        for page_number in range(len(src)):
            src_page = src[page_number]
            page_matches = sorted(
                matches_by_page.get(page_number, []), key=lambda m: m["bbox"][1]
            )
            page_blocks = _build_blocks(
                src_page, page_matches, picture_paths, page_w, page_h, target_width, top_bottom_padding,
                canonical_header_signature=(
                    None if page_number == canonical_page_number else canonical_header_signature
                ),
            )
            for block in page_blocks:
                block["src_page_number"] = page_number
            all_blocks.extend(page_blocks)

        # ---- Pass A: group blocks onto pages. Break BEFORE a block that
        # doesn't fit; never split a block itself (only exception: a
        # single block taller than a full page is still placed alone on
        # its own page). Every group after the first reserves
        # header_overhead out of its budget, whether or not it turns out
        # to need the header — cheap insurance against a group that
        # *does* need it silently overflowing past the page bottom. ----
        groups = [[]]
        group_height = 0.0
        for block in all_blocks:
            budget = page_h if len(groups) == 1 else page_h - header_overhead
            if group_height > 0 and group_height + block["height"] > budget:
                groups.append([])
                group_height = 0.0
            groups[-1].append(block)
            group_height += block["height"]

        # ---- Pass B: draw each group onto its own output page. ----
        for gi, group in enumerate(groups):
            new_page = out.new_page(width=page_w, height=page_h)
            has_picture = any(b["type"] in ("image", "image_and_row") for b in group)
            cursor_dst_y = 0.0
            if gi > 0 and has_picture:
                cursor_dst_y = _draw_repeat_header(
                    new_page, src, canonical_page_number, page_w, letterhead_rect, table_header_rect
                )

            for block in group:
                page_number = block["src_page_number"]

                if block["type"] == "content":
                    src_clip = fitz.Rect(0, block["src_y0"], page_w, block["src_y1"])
                    dst_rect = fitz.Rect(0, cursor_dst_y, page_w, cursor_dst_y + block["height"])
                    new_page.show_pdf_page(dst_rect, src, page_number, clip=src_clip)

                elif block["type"] == "image":
                    m = block["match"]
                    _place_image(
                        new_page, picture_paths, page_w, side_padding, top_bottom_padding,
                        m, block["img_w"], block["img_h"], cursor_dst_y,
                    )

                else:  # image_and_row
                    m = block["match"]
                    img_w, img_h = block["img_w"], block["img_h"]
                    _place_image(
                        new_page, picture_paths, page_w, side_padding, top_bottom_padding,
                        m, img_w, img_h, cursor_dst_y,
                    )
                    gap_h = img_h + 2 * top_bottom_padding
                    row_dst_y = cursor_dst_y + gap_h
                    row_h = block["row_src_y1"] - block["row_src_y0"]
                    src_clip = fitz.Rect(0, block["row_src_y0"], page_w, block["row_src_y1"])
                    dst_rect = fitz.Rect(0, row_dst_y, page_w, row_dst_y + row_h)
                    new_page.show_pdf_page(dst_rect, src, page_number, clip=src_clip)

                cursor_dst_y += block["height"]

        out.save(output_path)
    finally:
        src.close()
        out.close()
