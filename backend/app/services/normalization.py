import re


EMPTY_VALUES = {"", "nan", "none", "null", "n/a", "na"}


def clean_text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in EMPTY_VALUES:
        return None
    return text


def normalize_key(value) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def normalize_label(value) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    return re.sub(r"\s+", " ", text.lower()).strip()
