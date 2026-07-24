"""Markdown / longform splitting — shared by Obsidian ingest, doc re-ingest, and similar paths."""

from __future__ import annotations

import re


def _collapse_styled_doubles(text: str) -> str:
    """
    Collapse typography artifacts where almost every character is duplicated,
    e.g. "CCoonncclluussiióónn" -> "Conclusión".
    """
    s = text.strip()
    if len(s) < 6:
        return s

    pair_count = 0
    i = 0
    out: list[str] = []
    while i < len(s):
        if i + 1 < len(s) and s[i] == s[i + 1] and s[i].isalpha():
            out.append(s[i])
            pair_count += 1
            i += 2
            continue
        out.append(s[i])
        i += 1

    alpha_chars = sum(1 for ch in s if ch.isalpha())
    if alpha_chars >= 6 and pair_count * 2 >= int(alpha_chars * 0.7):
        return "".join(out)
    return s


def _is_garbage_title(title: str) -> bool:
    t = title.strip()
    if not t:
        return True
    if not re.search(r"[A-Za-zÁÉÍÓÚáéíóúÑñÜü]", t):
        return True
    if re.match(r"^(date|response)\b\s*:?", t, flags=re.IGNORECASE):
        return True
    if t.count("|") >= 2:
        return True
    if any(ch in t for ch in ("│", "─", "┌", "┐", "└", "┘")):
        return True
    if re.fullmatch(r"[A-Z0-9][A-Z0-9 .,:;_()\[\]/-]*[.:;\])-]?", t) and len(t.split()) <= 2:
        return True
    return False


def normalize_section_title(note_stem: str, section_title: str) -> str:
    t = re.sub(r"\s+", " ", section_title.strip())
    t = _collapse_styled_doubles(t)
    t = t.strip(" -|:\t")
    if _is_garbage_title(t):
        return note_stem
    return t


def chunk_by_sections(content: str, title: str) -> list[tuple[str, str]]:
    """Split by ## / ### headers into (section_title, body)."""
    parts = re.split(r"^(#{1,3} .+)$", content, flags=re.MULTILINE)
    chunks: list[tuple[str, str]] = []
    current_header = title
    current_body: list[str] = []

    for part in parts:
        part_stripped = part.strip()
        if not part_stripped:
            continue
        if re.match(r"^#{1,3} .+$", part_stripped):
            body = "\n".join(current_body).strip()
            if len(body.split()) > 60:
                chunks.append((current_header, body))
            current_header = re.sub(r"^#+\s*", "", part_stripped)
            current_body = []
        else:
            current_body.append(part)

    body = "\n".join(current_body).strip()
    if len(body.split()) > 60:
        chunks.append((current_header, body))

    return chunks if chunks else [(title, content)]


def chunk_by_paragraphs(
    content: str, title: str, *, target_words: int
) -> list[tuple[str, str]]:
    """Merge paragraphs until each chunk is about ``target_words``."""
    paras = [p.strip() for p in re.split(r"\n{2,}", content) if p.strip()]
    if not paras:
        return [(title, content)]
    out: list[tuple[str, str]] = []
    buf: list[str] = []
    n = 0
    idx = 1
    for p in paras:
        buf.append(p)
        n += len(p.split())
        if n >= target_words:
            body = "\n\n".join(buf).strip()
            if len(body.split()) > 60:
                out.append((f"{title} (part {idx})", body))
                idx += 1
            buf = []
            n = 0
    if buf:
        body = "\n\n".join(buf).strip()
        if len(body.split()) > 60:
            out.append((f"{title} (part {idx})", body))
    return out if out else [(title, content)]


def refine_chunks_for_word_limit(
    section_chunks: list[tuple[str, str]],
    note_stem: str,
    *,
    word_threshold: int,
) -> list[tuple[str, str]]:
    """Sub-split sections whose body exceeds ``word_threshold`` words."""
    if not section_chunks:
        return [(note_stem, "")]
    tw = max(400, word_threshold // 2)
    out: list[tuple[str, str]] = []
    for sec_title, body in section_chunks:
        if not body.strip():
            continue
        st = normalize_section_title(note_stem, sec_title)
        wc = len(body.split())
        if wc <= word_threshold:
            out.append((st, body))
            continue
        base = st if st == note_stem else f"{note_stem} — {st}"
        out.extend(chunk_by_paragraphs(body, base, target_words=tw))
    return out if out else [(note_stem, section_chunks[0][1])]
