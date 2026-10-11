from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
import unicodedata

import fitz  # PyMuPDF

TOC_KEYWORDS = (
    "indice",
    "ÍNDICE",
    "índice",
    "tabla de contenidos",
    "tabla de contenido",
    "contenido",
    "sumario",
    "contents",
    "table of contents",
    "summary",
)

ENTRY_RE = re.compile(
    r"^(?P<title>.+?)"
    r"(?:\.{2,}|·{2,}|…{2,}|\s{2,})\s*"
    r"(?P<page>\d{1,4})\s*$"
)

TRAILING_PAGE_RE = re.compile(r"^(?P<title>.+?)\s+(?P<page>\d{1,4})\s*$")

NUMBERING_RE = re.compile(r"^\s*((?:\d+\.)+\d*|\d+|[A-Z]\.|[IVXLCDM]+\.)\s+")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("•", " ").replace("·", " ")
    return re.sub(r"\s+", " ", text).strip().casefold()


def _clean_title(text: str) -> str:
    text = re.sub(r"\.{2,}\s*$", "", text)
    text = re.sub(r"·{2,}\s*$", "", text)
    text = re.sub(r"…{2,}\s*$", "", text)
    return re.sub(r"\s+", " ", text).strip(" .·…")


def _page_lines(page: fitz.Page) -> list[dict]:
    """Extract visual text lines with their left indentation."""
    lines: list[dict] = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(span.get("text", "") for span in spans).strip()
            if text:
                x0 = min((span.get("bbox", [0])[0] for span in spans), default=0)
                y0 = min((span.get("bbox", [0, 0])[1] for span in spans), default=0)
                lines.append({"text": text, "x0": x0, "y0": y0})
    lines.sort(key=lambda item: (item["y0"], item["x0"]))
    return lines


def _looks_like_toc_page(lines: list[dict]) -> bool:
    joined = _norm(" ".join(item["text"] for item in lines[:80]))
    keyword = any(_norm(word) in joined for word in TOC_KEYWORDS)
    candidates = sum(1 for item in lines if ENTRY_RE.match(item["text"]) or TRAILING_PAGE_RE.match(item["text"]))
    return keyword or candidates >= 4


def _parse_entry(text: str):
    text = re.sub(r"\s+", " ", text).strip()
    match = ENTRY_RE.match(text) or TRAILING_PAGE_RE.match(text)
    if not match:
        return None
    title = _clean_title(match.group("title"))
    if len(title) < 2:
        return None
    page = int(match.group("page"))
    if page < 1:
        return None
    # Avoid parsing obvious page headers/footers that are just a number.
    if not re.search(r"[A-Za-zÀ-ÿ]", title):
        return None
    return {"title": title, "page": page}


def _parse_toc_pages(doc: fitz.Document, page_indexes: list[int]):
    entries = []
    pending = None
    for pno in page_indexes:
        lines = _page_lines(doc[pno])
        for line in lines:
            text = line["text"]
            entry = _parse_entry(text)
            if entry:
                if pending:
                    pending["title"] = _clean_title(pending["title"])
                    if pending.get("title"):
                        entries.append(pending)
                    pending = None
                entry["x0"] = line["x0"]
                entries.append(entry)
            else:
                # A wrapped TOC title is commonly followed by its page number on the next line.
                if len(text) >= 3 and len(text) < 140:
                    if pending and len(pending["title"]) < 120:
                        pending["title"] += " " + text
                    else:
                        pending = {"title": text, "page": None, "x0": line["x0"]}
        if pending and pending.get("page") is not None:
            entries.append(pending)
            pending = None

    # Filter noisy lines and de-duplicate adjacent repeats.
    clean = []
    seen = set()
    for item in entries:
        if item.get("page") is None:
            continue
        title = _clean_title(item["title"])
        if len(title) < 2 or len(title) > 180:
            continue
        key = (_norm(title), item["page"])
        if key in seen:
            continue
        seen.add(key)
        item["title"] = title
        clean.append(item)
    return clean


def _infer_levels(entries: list[dict]) -> list[list]:
    # Strong signal: hierarchical numbering (1, 1.1, 1.1.1, etc.).
    levels = []
    indents = [item.get("x0", 0) for item in entries]
    indent_values = []
    for x in indents:
        if not any(abs(x - existing) <= 10 for existing in indent_values):
            indent_values.append(x)
    indent_values.sort()

    for item in entries:
        title = item["title"]
        match = NUMBERING_RE.match(title)
        if match:
            prefix = match.group(1)
            if "." in prefix:
                level = min(prefix.strip(".").count(".") + 1, 8)
            else:
                level = 1
        else:
            # Map indentation to a compact 1..4 hierarchy.
            x = item.get("x0", 0)
            nearest = min(range(len(indent_values)), key=lambda i: abs(indent_values[i] - x)) if indent_values else 0
            level = min(nearest + 1, 4)
        levels.append(level)

    return [[level, item["title"], item["page"]] for level, item in zip(levels, entries)]


def _find_toc_pages(doc: fitz.Document) -> list[int]:
    limit = min(doc.page_count, 60)
    scored = []
    for pno in range(limit):
        lines = _page_lines(doc[pno])
        if not lines:
            continue
        joined = _norm(" ".join(item["text"] for item in lines[:90]))
        keyword_score = 4 if any(_norm(word) in joined for word in TOC_KEYWORDS) else 0
        entry_score = sum(1 for item in lines if _parse_entry(item["text"]))
        score = keyword_score + min(entry_score, 8)
        if score >= 5:
            scored.append((pno, score, entry_score))

    if not scored:
        return []

    # Prefer the earliest strong cluster, normally the printed table of contents.
    scored.sort()
    chosen = [scored[0][0]]
    for pno, _, _ in scored[1:]:
        if pno <= chosen[-1] + 2:
            chosen.append(pno)
        elif pno > chosen[-1] + 4:
            break
    return chosen


def _build_page_text_index(doc: fitz.Document, start_page: int):
    index = []
    for pno in range(start_page, doc.page_count):
        lines = _page_lines(doc[pno])
        normalized = [_norm(line["text"]) for line in lines if _norm(line["text"])]
        index.append((pno, normalized))
    return index


def _resolve_pages(entries: list[dict], doc: fitz.Document, toc_pages: list[int]):
    if not entries:
        return []

    # First try to infer an exact printed-page -> PDF-page offset by locating headings.
    search_start = max(toc_pages) if toc_pages else 0
    page_lines = _build_page_text_index(doc, search_start)
    offset_votes = []

    for item in entries[:80]:
        title = _norm(item["title"])
        if len(title) < 4:
            continue
        tokens = title.split()
        needle = title
        if len(tokens) > 12:
            needle = " ".join(tokens[:12])
        candidates = []
        for pno, lines in page_lines:
            if needle in lines:
                candidates.append(pno)
        if candidates:
            physical = candidates[0]
            offset_votes.append(physical - (item["page"] - 1))

    offset = Counter(offset_votes).most_common(1)[0][0] if offset_votes else 0

    resolved = []
    for item in entries:
        pno = item["page"] - 1 + offset
        # Keep pages inside the PDF. If the inferred offset lands outside, use direct 1-based mapping.
        if pno < 0 or pno >= doc.page_count:
            pno = item["page"] - 1
        pno = max(0, min(doc.page_count - 1, pno))
        resolved.append([1, item["title"], pno + 1])
    return resolved


def add_bookmarks_from_toc(input_path: Path, output_path: Path, infer_hierarchy: bool = True) -> dict:
    try:
        doc = fitz.open(input_path)
    except Exception as exc:
        raise ValueError("El archivo no parece ser un PDF válido.") from exc

    if doc.page_count == 0:
        raise ValueError("El PDF no contiene páginas.")

    existing = doc.get_toc(simple=True)
    toc_pages = _find_toc_pages(doc)

    if not toc_pages:
        # Nothing to regenerate: preserve an existing outline, but still create a clean copy.
        doc.save(output_path, garbage=4, deflate=True)
        page_count = doc.page_count
        doc.close()
        return {
            "filename": f"{input_path.stem}_con_bookmarks.pdf",
            "bookmark_count": len(existing),
            "page_count": page_count,
            "toc_pages": 0,
            "message": "No se detectó una página de índice con texto. Se conservó el esquema existente (si lo había).",
        }

    entries = _parse_toc_pages(doc, toc_pages)
    if len(entries) < 2:
        doc.save(output_path, garbage=4, deflate=True)
        page_count = doc.page_count
        doc.close()
        return {
            "filename": f"{input_path.stem}_con_bookmarks.pdf",
            "bookmark_count": len(existing),
            "page_count": page_count,
            "toc_pages": len(toc_pages),
            "message": "Se detectó un posible índice, pero no se pudieron extraer suficientes entradas. Se conservó el esquema existente.",
        }

    toc = _resolve_pages(entries, doc, toc_pages)
    # Convert flat levels into a hierarchy based on numbering/indentation.
    hierarchical = _infer_levels(entries) if infer_hierarchy else [[1, item["title"], item["page"]] for item in entries]
    final_toc = []
    for level_item, resolved in zip(hierarchical, toc):
        final_toc.append([level_item[0], level_item[1], resolved[2]])

    doc.set_toc(final_toc, collapse=1)
    doc.set_metadata({**doc.metadata, "producer": "PDF Bookmark Maker / PyMuPDF"})
    doc.save(output_path, garbage=4, deflate=True)
    page_count = doc.page_count
    doc.close()

    return {
        "filename": f"{input_path.stem}_con_bookmarks.pdf",
        "bookmark_count": len(final_toc),
        "page_count": page_count,
        "toc_pages": len(toc_pages),
        "message": f"Se han generado {len(final_toc)} bookmarks a partir del índice.",
    }
