"""Concept extraction for sling/rigging descriptions.

Real quotation text is often Indonesian shorthand (e.g. "1 sisi thimble,
1 sisi polos") rather than the full English "Kata Baku" sentence it maps
to ("...with thimble eye at one end and tappered / plain (seizing) at
the other end"). This module pulls out a set of normalized "concept"
tokens from any description text — English or Indonesian — so a quotation
line and a Kata Baku entry can be compared by concept overlap instead of
requiring literal substring equality.
"""
import re

# Ordered isn't semantically required (each concept is an independent
# OR-check), but grouped by category for readability.
_CONCEPT_PATTERNS = {
    # Sling category
    "mechanical_splice_sling": ["mechanical splice sling"],
    "hand_splice_sling": ["hand splice sling"],
    "wire_rope_sling": ["wire rope sling"],
    "chain_sling": ["chain sling", "rantai"],
    "steel_wire_rope_sling": ["steel wire rope sling"],

    # Leg count (multi-leg rigging assemblies)
    "five_legs": ["five legs", "5 legs", "kaki 5"],
    "four_legs": ["four legs", "4 legs", "kaki 4"],
    "three_legs": ["three legs", "3 legs", "kaki 3"],
    "double_legs": ["double legs", "double leg", "2 legs", "kaki 2"],
    "single_leg": ["single leg", "1 leg", "kaki 1"],

    # End terminations
    "solid_thimble_eye": ["solid thimble eye"],
    "thimble_socket": ["thimble socket"],
    "thimble_eye": ["thimble eye", "sisi thimble", "mata thimble", "thimble"],
    "soft_eye": ["soft eye", "sisi soft eye", "mata soft"],
    "stop_end": ["stop end"],
    "open_spelter_socket": ["open spelter socket"],
    "close_spelter_socket": ["close spelter socket"],
    "tappered_plain_seizing": [
        "tappered / plain (seizing)", "tappered/plain(seizing)",
        "tapered", "tappered", "plain", "seizing", "polos", "sisi polos",
    ],

    # Chain accessories
    "sling_hook": ["sling hook"],
    "safety_hook": ["safety hook"],
    "grab_hook": ["grab hook"],
    "single_basket": ["single basket"],
}

# "hand splice" as an END descriptor (Kata Baku item 12) is distinct from
# "hand splice sling" as the sling CATEGORY — only fire this one when not
# immediately followed by "sling".
_HAND_SPLICE_END_RE = re.compile(r"hand splice(?!\s+sling)")

CATEGORY_CONCEPTS = {
    "mechanical_splice_sling",
    "hand_splice_sling",
    "wire_rope_sling",
    "chain_sling",
    "steel_wire_rope_sling",
}


def normalize(text):
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def extract_concepts(text):
    """Return the set of concept names present in the (already-lowercase-able) text."""
    norm = normalize(text)
    concepts = set()

    for concept, triggers in _CONCEPT_PATTERNS.items():
        if any(trigger in norm for trigger in triggers):
            concepts.add(concept)

    if _HAND_SPLICE_END_RE.search(norm):
        concepts.add("hand_splice_end")

    return concepts
