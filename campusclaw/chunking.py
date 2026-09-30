import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    text: str
    index: int
    start: int
    end: int
    offset_basis: str = "original_text"


_URL = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_HEADINGS = re.compile(r"(?m)^(#{1,3})[ \t]+.+$")


def split_text(text, strategy=None):
    strategy = dict(strategy or {})
    name = strategy.get("name", "auto")
    if name == "auto":
        return _window(text, 800, 80, "original_text")
    if name == "custom":
        return _custom(text, strategy)
    if name == "hierarchy":
        return _hierarchy(text)
    raise ValueError("unsupported chunk strategy")


def _preferred_end(text, start, limit):
    hard_end = min(len(text), start + limit)
    if hard_end == len(text):
        return hard_end
    floor = start + max(1, limit // 2)
    candidates = []
    for delimiter in ("\n\n", "\n", "。"):
        position = text.rfind(delimiter, floor, hard_end + 1)
        if position >= floor:
            candidates.append(position + len(delimiter))
    return max(candidates, default=hard_end)


def _window(text, maximum, overlap, basis, base_offset=0):
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = _preferred_end(text, start, maximum)
        if end <= start:
            end = min(len(text), start + maximum)
        value = text[start:end]
        if value:
            chunks.append(Chunk(value, len(chunks), base_offset + start, base_offset + end, basis))
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def _custom(text, strategy):
    maximum = strategy.get("max_length", 800)
    overlap_ratio = strategy.get("overlap_ratio", 0.1)
    delimiter_name = strategy.get("delimiter", "newline")
    if not isinstance(maximum, int) or not 100 <= maximum <= 2000:
        raise ValueError("max_length must be between 100 and 2000")
    if not isinstance(overlap_ratio, (int, float)) or not 0 <= overlap_ratio <= 0.5:
        raise ValueError("overlap_ratio must be between 0 and 0.5")
    delimiters = {"newline": "\n", "blankline": "\n\n", "sentence": "。"}
    if delimiter_name not in delimiters:
        raise ValueError("unsupported delimiter")
    processed = text
    changed = False
    if strategy.get("remove_urls_emails"):
        processed = _EMAIL.sub("", _URL.sub("", processed))
        changed = True
    if strategy.get("collapse_whitespace"):
        processed = re.sub(r"\s+", " ", processed).strip()
        changed = True
    delimiter = delimiters[delimiter_name]
    return _delimiter_window(
        processed, maximum, int(maximum * overlap_ratio), delimiter,
        "processed_text" if changed else "original_text",
    )


def _delimiter_window(text, maximum, overlap, delimiter, basis):
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        hard_end = min(len(text), start + maximum)
        end = hard_end
        if hard_end < len(text):
            position = text.rfind(delimiter, start + 1, hard_end + 1)
            if position > start:
                end = position + len(delimiter)
        chunks.append(Chunk(text[start:end], len(chunks), start, end, basis))
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def _hierarchy(text):
    matches = list(_HEADINGS.finditer(text))
    if not matches:
        return _window(text, 800, 80, "original_text")
    boundaries = [0]
    boundaries.extend(match.start() for match in matches if match.start() > 0)
    boundaries.append(len(text))
    output = []
    for start, end in zip(boundaries, boundaries[1:]):
        section = text[start:end]
        for chunk in _window(section, 800, 80, "original_text", start):
            output.append(Chunk(chunk.text, len(output), chunk.start, chunk.end, chunk.offset_basis))
    return output
