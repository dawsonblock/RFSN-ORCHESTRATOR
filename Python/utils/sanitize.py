# Python/utils/sanitize.py
import re

_ALLOWED = re.compile(r"[^A-Za-z0-9_ -]+")

def safe_filename_token(name: str, *, max_len: int = 64) -> str:
    """
    Converts an untrusted display name into a safe filename token.
    Keeps only A-Z a-z 0-9 space _ -
    """
    if not name:
        return "unknown"
    s = name.strip()
    # Replace unsafe characters with underscore
    s = _ALLOWED.sub("_", s)
    # Strip leading/trailing special chars
    s = s.strip(" ._-/\\")
    if not s:
        return "unknown"
    return s[:max_len]
