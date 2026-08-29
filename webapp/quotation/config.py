"""Tunables for how a matched item's picture gets inserted into the PDF.

A new blank strip is inserted directly above the matched description row
(never below it), and everything below is pushed down to make room. The
picture is left-aligned to the Description column itself (not centered
on the full row, which is often merged across every column).
"""
IMAGE_WIDTH_FRACTION = 0.5  # picture width = this fraction of the page width
SIDE_PADDING = 8            # inset from the strip's edges
TOP_BOTTOM_PADDING = 10     # blank margin above/below the picture within its strip

# The user-entered a/b/c dimension VALUES are listed as text to the
# RIGHT of the picture (not overlaid on it), so they never collide with
# the diagram's own lines/arrows regardless of that image's layout.
DIMENSION_GAP = 12       # gap between the picture's right edge and the text
DIMENSION_LINE_GAP = 4   # vertical gap between stacked a/b/c lines
DIMENSION_FONT_COLOR = (0, 0, 0)  # black
DIMENSION_FONT = "hebo"  # Helvetica-Bold
