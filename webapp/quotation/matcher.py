import re

from .concepts import CATEGORY_CONCEPTS, extract_concepts


def _normalize(text):
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _substring_match(norm_text, normalized_entries):
    """Exact/literal pass: tag text found verbatim inside the line text."""
    candidates = [
        (norm_tag, picture_id)
        for norm_tag, picture_id in normalized_entries
        if norm_tag in norm_text
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda c: (-len(c[0]), c[1]))
    best_tag, best_picture_id = candidates[0]
    return best_tag, best_picture_id


def _concept_match(text, entries_with_concepts, min_jaccard=0.4):
    """Fallback pass: match by overlap of extracted concepts (splice type,
    end terminations, leg count, ...), for shorthand/translated text that
    doesn't literally contain the library tag's wording.
    """
    text_concepts = extract_concepts(text)
    if not text_concepts or not (text_concepts & CATEGORY_CONCEPTS):
        return None  # nothing recognizable, or no sling/chain category mentioned

    best = None  # (jaccard, overlap_count, -picture_id) for max(), tag, picture_id
    for tag, picture_id, candidate_concepts in entries_with_concepts:
        if not candidate_concepts or not (candidate_concepts & CATEGORY_CONCEPTS):
            continue
        # Category must actually agree — don't cross-match a chain sling
        # description against a wire-rope-sling quotation line, etc.
        if not (text_concepts & CATEGORY_CONCEPTS) & (candidate_concepts & CATEGORY_CONCEPTS):
            continue

        intersection = text_concepts & candidate_concepts
        union = text_concepts | candidate_concepts
        jaccard = len(intersection) / len(union) if union else 0

        key = (jaccard, len(intersection), -picture_id)
        if best is None or key > best[0]:
            best = (key, tag, picture_id)

    if best is None or best[0][0] < min_jaccard:
        return None
    return best[1], best[2]


def match_items_to_pictures(lines, library_entries):
    """Match extracted text lines to library pictures.

    Two passes per line: (1) literal substring containment of a library
    tag, which handles exact/manually-tagged entries; (2) if that finds
    nothing, a concept-overlap fallback that understands Indonesian
    shorthand and partial phrasing against the long Kata Baku descriptions.

    lines: list of (page_number, text, bbox, description_col_x)
    library_entries: list of dicts with "id" and "tags" (list of keyword strings)

    Returns a list of dicts: {page_number, text, bbox, description_col_x,
    picture_id, matched_tag}. One match per line (first/best match only);
    lines with no match are skipped.
    """
    normalized_entries = []
    entries_with_concepts = []
    for entry in library_entries:
        for tag in entry["tags"]:
            norm_tag = _normalize(tag)
            if norm_tag:
                normalized_entries.append((norm_tag, entry["id"]))
            entries_with_concepts.append((tag, entry["id"], extract_concepts(tag)))

    matches = []
    for page_number, text, bbox, description_col_x in lines:
        norm_text = _normalize(text)
        if not norm_text:
            continue

        result = _substring_match(norm_text, normalized_entries)
        if result is None:
            result = _concept_match(text, entries_with_concepts)
        if result is None:
            continue

        best_tag, best_picture_id = result
        matches.append(
            {
                "page_number": page_number,
                "text": text,
                "bbox": bbox,
                "description_col_x": description_col_x,
                "picture_id": best_picture_id,
                "matched_tag": best_tag,
            }
        )

    return matches
