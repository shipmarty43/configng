"""Local storage and text handling shared by the mesh mailboxes."""
from contextlib import closing, contextmanager
import sqlite3
import unicodedata


@contextmanager
def database(state):
    with closing(sqlite3.connect(state / "mailbox.sqlite", timeout=10)) as db:
        db.row_factory = sqlite3.Row
        with db:
            yield db


def display(value, multiline=False):
    # Keep message data out of terminal control sequences and dialog's markup.
    text = "".join(c if (c == "\n" and multiline) or c.isprintable() else " " for c in value)
    return text if multiline else text.replace("\\", "＼")


def user_text(value, limit, required=True):
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError("Text is empty.")
    if len(value.encode("utf-8")) > limit or any(
            unicodedata.category(c) == "Cc" and c not in "\n\t" for c in value):
        raise ValueError(f"Enter UTF-8 text of at most {limit} bytes without control characters.")
    return value
