from webapp.db import get_db


def get_pictures_with_tags():
    """Return all pictures, each with a list of its tag keywords."""
    db = get_db()
    pictures = db.execute(
        "SELECT id, filename, original_filename, created_at "
        "FROM pictures ORDER BY created_at DESC"
    ).fetchall()

    result = []
    for pic in pictures:
        tags = db.execute(
            "SELECT keyword FROM tags WHERE picture_id = ? ORDER BY id", (pic["id"],)
        ).fetchall()
        result.append(
            {
                "id": pic["id"],
                "filename": pic["filename"],
                "original_filename": pic["original_filename"],
                "created_at": pic["created_at"],
                "tags": [t["keyword"] for t in tags],
            }
        )
    return result


def get_picture(picture_id):
    db = get_db()
    pic = db.execute(
        "SELECT id, filename, original_filename, created_at FROM pictures WHERE id = ?",
        (picture_id,),
    ).fetchone()
    if pic is None:
        return None
    tags = db.execute(
        "SELECT keyword FROM tags WHERE picture_id = ? ORDER BY id", (picture_id,)
    ).fetchall()
    return {
        "id": pic["id"],
        "filename": pic["filename"],
        "original_filename": pic["original_filename"],
        "created_at": pic["created_at"],
        "tags": [t["keyword"] for t in tags],
    }


def add_picture(filename, original_filename, tags):
    db = get_db()
    cur = db.execute(
        "INSERT INTO pictures (filename, original_filename) VALUES (?, ?)",
        (filename, original_filename),
    )
    picture_id = cur.lastrowid
    _insert_tags(db, picture_id, tags)
    db.commit()
    return picture_id


def add_placeholder(tags):
    """Create a library entry with tags but no image yet (e.g. seeded from a dataset)."""
    db = get_db()
    cur = db.execute(
        "INSERT INTO pictures (filename, original_filename) VALUES (NULL, NULL)"
    )
    picture_id = cur.lastrowid
    _insert_tags(db, picture_id, tags)
    db.commit()
    return picture_id


def set_picture_file(picture_id, filename, original_filename):
    db = get_db()
    db.execute(
        "UPDATE pictures SET filename = ?, original_filename = ? WHERE id = ?",
        (filename, original_filename, picture_id),
    )
    db.commit()


def find_by_tag(keyword):
    db = get_db()
    row = db.execute(
        "SELECT picture_id FROM tags WHERE keyword = ?", (keyword,)
    ).fetchone()
    return row["picture_id"] if row else None


def update_tags(picture_id, tags):
    db = get_db()
    db.execute("DELETE FROM tags WHERE picture_id = ?", (picture_id,))
    _insert_tags(db, picture_id, tags)
    db.commit()


def delete_picture(picture_id):
    db = get_db()
    filename_row = db.execute(
        "SELECT filename FROM pictures WHERE id = ?", (picture_id,)
    ).fetchone()
    db.execute("DELETE FROM pictures WHERE id = ?", (picture_id,))
    db.commit()
    return filename_row["filename"] if filename_row else None


def _insert_tags(db, picture_id, tags):
    for keyword in tags:
        keyword = keyword.strip()
        if keyword:
            db.execute(
                "INSERT INTO tags (picture_id, keyword) VALUES (?, ?)",
                (picture_id, keyword),
            )
