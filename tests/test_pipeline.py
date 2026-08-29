"""End-to-end checks for the quotation pipeline.

Runs the real HTTP routes (login -> upload -> dimensions -> generate ->
download) through Flask's test client, plus the input-handling edge cases
that used to return raw 500 pages.

Everything happens inside a throwaway temp directory, so this never reads
or writes the real picture library or database — an earlier version of
this file did, and running it silently overwrote a real diagram.

Run with: venv\\Scripts\\python.exe tests\\test_pipeline.py
"""
import io
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz
from PIL import Image

TAG = "Mechanical splice sling with thimble eye on both end"
PASSWORD = "test-password"

passed = failed = 0


def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label} {detail}")


def make_png(color=(40, 160, 60)):
    buf = io.BytesIO()
    Image.new("RGB", (400, 120), color=color).save(buf, format="PNG")
    buf.seek(0)
    return buf


def make_quotation_pdf(text=TAG):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "QUOTATION - TEST", fontsize=14)
    page.insert_text((72, 160), text, fontsize=10)
    page.insert_text((72, 180), "1  Some material  2.00  PCS  1,000  2,000", fontsize=10)
    buf = io.BytesIO(doc.tobytes())
    doc.close()
    return buf


def login(client):
    return client.post("/login", data={"password": PASSWORD}, follow_redirects=False)


def main():
    from webapp import create_app

    data_dir = tempfile.mkdtemp(prefix="wirerope_test_")
    os.environ["DATA_DIR"] = data_dir
    try:
        app = create_app({"SITE_PASSWORD": PASSWORD, "SECRET_KEY": "test", "TESTING": True})
        client = app.test_client()

        print("\n[auth]")
        check("anonymous request redirects to login",
              client.get("/", follow_redirects=False).status_code == 302)
        check("wrong password is rejected",
              "Wrong password" in client.post(
                  "/login", data={"password": "nope"}).data.decode())
        check("correct password logs in", login(client).status_code == 302)
        check("home reachable once logged in", client.get("/").status_code == 200)

        r = client.post("/login?next=https://evil.example/phish",
                        data={"password": PASSWORD}, follow_redirects=False)
        check("open redirect is blocked",
              not (r.headers.get("Location") or "").startswith("http"),
              f"-> {r.headers.get('Location')!r}")

        print("\n[library upload validation]")
        r = client.post("/library/upload",
                        data={"picture": (make_png(), "にほん.jpg"), "tags": TAG},
                        content_type="multipart/form-data")
        check("non-ASCII filename accepted (no 500)", r.status_code == 302,
              f"-> {r.status_code}")

        r = client.post("/library/upload",
                        data={"picture": (io.BytesIO(b"not an image"), "fake.jpg"),
                              "tags": "junk"},
                        content_type="multipart/form-data")
        check("non-image file rejected at upload", r.status_code == 302)
        check("rejected file left no library entry",
              "junk" not in client.get("/library/").data.decode())

        print("\n[quotation pipeline]")
        r = client.post("/quotation/process",
                        data={"quotation_pdf": (make_quotation_pdf(), "q.pdf")},
                        content_type="multipart/form-data")
        check("process returns dimensions page", r.status_code == 200)
        m = re.search(r"/quotation/generate/([0-9a-f]{32})", r.data.decode())
        check("dimensions page exposes a job id", m is not None)

        job_id = m.group(1)
        r = client.post(f"/quotation/generate/{job_id}",
                        data={"a_0": "15 cm", "b_0": "10 meter"})
        check("generate succeeds", r.status_code == 200)
        check("result reports an inserted picture",
              "1 picture(s) inserted" in r.data.decode(), )

        pdf = client.get(f"/quotation/download/{job_id}").data
        doc = fitz.open(stream=pdf, filetype="pdf")
        check("output PDF has exactly 1 page", len(doc) == 1, f"-> {len(doc)}")
        check("output PDF actually embeds an image", len(doc[0].get_images(full=True)) >= 1)
        text = doc[0].get_text()
        check("dimension labels drawn into the PDF",
              "a = 15 cm" in text and "b = 10 meter" in text)
        doc.close()

        print("\n[bad input handling]")
        r = client.post("/quotation/process",
                        data={"quotation_pdf": (io.BytesIO(b"not a pdf"), "broken.pdf")},
                        content_type="multipart/form-data",
                        follow_redirects=True)
        check("corrupt PDF shows a message, not a 500",
              r.status_code == 200 and "could not be read as a PDF" in r.data.decode(),
              f"-> {r.status_code}")

        blank = fitz.open()
        blank.new_page()
        buf = io.BytesIO(blank.tobytes())
        blank.close()
        r = client.post("/quotation/process",
                        data={"quotation_pdf": (buf, "scan.pdf")},
                        content_type="multipart/form-data")
        check("PDF with no matching text still succeeds", r.status_code == 200)

        check("unknown page returns friendly 404",
              client.get("/definitely-not-a-page").status_code == 404)
    finally:
        os.environ.pop("DATA_DIR", None)
        shutil.rmtree(data_dir, ignore_errors=True)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
