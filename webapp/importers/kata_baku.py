"""One-time importer for the 'Kata Baku' reference spreadsheet.

The spreadsheet lists standardized sling/rigging item descriptions (one per
row, in column B, under a numbered "No" in column A) with an empty "Gambar"
(picture) column meant to be filled in by hand. This script seeds the
picture library with one placeholder entry per description (tag = the full
description text, no image yet), so the user only has to upload/attach a
photo for each item afterward instead of retyping 46 long descriptions.
"""
import re

import click
import openpyxl
from flask import current_app

from webapp.library import models


def _clean_description(raw):
    text = str(raw).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def read_descriptions(xlsx_path, sheet_name="Kata Baku"):
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb[sheet_name]

    descriptions = []
    rows = ws.iter_rows(min_row=1, min_col=1, max_col=2, values_only=True)
    for row in rows:
        no_value = row[0]
        deskripsi = row[1] if len(row) > 1 else None
        # Real item rows have a numeric "No"; this also skips the header
        # row itself (and any accidental repeats of it in the sheet).
        if not isinstance(no_value, (int, float)) or deskripsi is None:
            continue
        descriptions.append(_clean_description(deskripsi))
    wb.close()
    return descriptions


def import_kata_baku(xlsx_path):
    """Seed placeholder library entries for descriptions not already present.

    Returns (created_count, skipped_count).
    """
    descriptions = read_descriptions(xlsx_path)
    created, skipped = 0, 0
    for description in descriptions:
        if models.find_by_tag(description) is not None:
            skipped += 1
            continue
        models.add_placeholder([description])
        created += 1
    return created, skipped


@click.command("import-kata-baku")
@click.argument("xlsx_path", default="data/kata_baku_source.xlsx")
def import_kata_baku_command(xlsx_path):
    """Seed the picture library with descriptions from the Kata Baku dataset."""
    created, skipped = import_kata_baku(xlsx_path)
    click.echo(f"Created {created} new entries, skipped {skipped} already present.")


def init_app(app):
    app.cli.add_command(import_kata_baku_command)
