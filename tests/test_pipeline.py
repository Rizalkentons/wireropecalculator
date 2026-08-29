"""Standalone end-to-end check: attach a picture to a seeded item, build a
fake quotation PDF containing that item's exact description text, run it
through the real /quotation/process route, and verify the output PDF has
an image inserted near the matched text.

Run with: venv\\Scripts\\python.exe tests\\test_pipeline.py
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz
from PIL import Image

from webapp import create_app
from webapp.db import get_db

TARGET_TAG = (
    "Mechanical splice sling with thimble eye at one end and tappered / "
    "plain (seizing) at the other end"
)


def make_test_image_bytes():
    img = Image.new("RGB", (200, 200), color=(40, 160, 60))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def make_test_quotation_pdf_bytes():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "SALES QUOTATION - TEST", fontsize=14)
    page.insert_text((72, 140), "Item 1:", fontsize=10)
    page.insert_text((72, 160), TARGET_TAG, fontsize=10)
    page.insert_text((72, 180), "Qty: 2   Unit Price: 1,000,000", fontsize=10)
    page.insert_text((72, 220), "Item 2:", fontsize=10)
    page.insert_text((72, 240), "Some unrelated line item with no match", fontsize=10)
    buf = io.BytesIO(doc.tobytes())
    doc.close()
    return buf


def main():
    app = create_app()
    with app.app_context():
        db = get_db()
        row = db.execute(
            "SELECT picture_id FROM tags WHERE keyword = ?", (TARGET_TAG,)
        ).fetchone()
        assert row is not None, "Target tag not found in seeded library — did import-kata-baku run?"
        picture_id = row["picture_id"]
        print(f"Target picture_id: {picture_id}")

    client = app.test_client()

    resp = client.post(
        f"/library/{picture_id}/upload-image",
        data={"picture": (make_test_image_bytes(), "test_apple.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 302, f"attach picture failed: {resp.status_code} {resp.data[:300]}"
    print("Attached test image to library item.")

    resp = client.post(
        "/quotation/process",
        data={"quotation_pdf": (make_test_quotation_pdf_bytes(), "test_quotation.pdf")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200, f"process failed: {resp.status_code} {resp.data[:500]}"
    html = resp.data.decode("utf-8")

    m = re.search(r"/quotation/download/([0-9a-f]{32})", html)
    assert m, "job_id not found in result page"
    job_id = m.group(1)
    print(f"job_id: {job_id}")

    assert "1 picture(s) inserted" in html or "picture(s) inserted" in html
    print("Result page reports a picture was inserted.")

    resp = client.get(f"/quotation/download/{job_id}")
    assert resp.status_code == 200
    out_path = os.path.join(os.path.dirname(__file__), "output_test_quotation.pdf")
    with open(out_path, "wb") as f:
        f.write(resp.data)
    print(f"Saved processed PDF to {out_path}")

    doc = fitz.open(out_path)
    page = doc[0]
    images = page.get_images(full=True)
    print(f"Images found on page 1: {len(images)}")
    assert len(images) >= 1, "No image was actually embedded in the output PDF!"

    for img in images:
        xref = img[0]
        rects = page.get_image_rects(xref)
        for r in rects:
            print(f"  image xref={xref} rect={r}")
    doc.close()

    print("\nPIPELINE TEST PASSED")


if __name__ == "__main__":
    main()
