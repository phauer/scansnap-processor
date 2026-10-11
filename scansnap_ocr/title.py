"""Extract document date and generate title from OCR text."""

import re
from datetime import date, datetime
from pathlib import Path

from .config import FALLBACK_TITLE, MAX_TITLE_WORDS, NEW_SCAN_PATTERN, TITLE_ENGINE

# German month names → month number
GERMAN_MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "april": 4,
    "mai": 5, "juni": 6, "juli": 7, "august": 8,
    "september": 9, "oktober": 10, "november": 11, "dezember": 12,
}

# Date patterns (ordered by specificity)
DATE_PATTERNS = [
    # DD.MM.YYYY
    (re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b"), "dmy4"),
    # DD.MM.YY
    (re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2})\b"), "dmy2"),
    # D. Month YYYY
    (re.compile(
        r"\b(\d{1,2})\.\s*("
        + "|".join(GERMAN_MONTHS.keys())
        + r")\s+(\d{4})\b",
        re.IGNORECASE,
    ), "written"),
]

# Document type keywords (German)
DOCUMENT_TYPES = {
    "Rechnung": ["rechnung", "rechnungs"],
    "Quittung": ["quittung"],
    "Mahnung": ["mahnung"],
    "Bußgeldbescheid": ["bußgeldbescheid", "busgeldbescheid", "bußgeld"],
    "Bescheid": ["bescheid"],
    "Anhörung": ["anhörung", "anhorung", "anhörungsbogen"],
    "Kündigung": ["kündigung", "kundigung"],
    "Mitteilung": ["mitteilung"],
    "Benachrichtigung": ["benachrichtigung"],
    "Vertrag": ["vertrag", "mietvertrag", "kaufvertrag", "arbeitsvertrag"],
    "Angebot": ["angebot"],
    "Auftrag": ["auftrag"],
    "Bestellung": ["bestellung"],
    "Bescheinigung": ["bescheinigung"],
    "Zeugnis": ["zeugnis"],
    "Attest": ["attest"],
    "Antrag": ["antrag"],
    "SEPA": ["sepa", "lastschriftmandat", "mandatsreferenz"],
    "Arztbrief": ["arztbrief"],
    "Befund": ["befund"],
    "Rezept": ["rezept"],
}

# Company suffixes to help identify sender
COMPANY_SUFFIXES = re.compile(
    r"\b\w+(?:\s+\w+){0,3}\s+(?:GmbH|AG|e\.V\.|eG|KG|OHG|SE|mbH|Co\.|Ltd\.?|Inc\.?)\b",
    re.IGNORECASE,
)

# Noise patterns to strip from potential titles
NOISE_PATTERNS = [
    re.compile(r"\b\d{5}\b"),  # postal codes
    re.compile(r"\b\d{2,4}[-/]\d{2,4}[-/]\d{2,4}\b"),  # dates in title
    re.compile(r"\bTel\.?\s*[:.]?\s*[\d\s/+-]+", re.IGNORECASE),
    re.compile(r"\bFax\.?\s*[:.]?\s*[\d\s/+-]+", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),  # email
    re.compile(r"\bwww\.\S+", re.IGNORECASE),
    re.compile(r"\bhttp\S+", re.IGNORECASE),
    re.compile(r"\bStraße\b|\bStr\.\b|\bWeg\b|\bPlatz\b|\bAllee\b", re.IGNORECASE),
]

# Filesystem-unsafe characters
UNSAFE_CHARS = re.compile(r'[/\\:*?"<>|]')


def extract_date(text: str, scan_filename: str | None = None) -> date | None:
    """Extract the most likely document date from OCR text.

    Prefers dates near the top of the text. Falls back to scan date from filename.
    """
    lines = text.split("\n")
    candidates = []

    for line_idx, line in enumerate(lines):
        for pattern, fmt in DATE_PATTERNS:
            for match in pattern.finditer(line):
                try:
                    d = _parse_date_match(match, fmt)
                    if d and _is_reasonable_date(d):
                        # Lower index = higher priority (closer to top)
                        candidates.append((line_idx, d))
                except (ValueError, KeyError):
                    continue

    if candidates:
        # Return the date closest to the top of the document
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    # Fallback: parse scan date from filename
    if scan_filename:
        return _parse_scan_date(scan_filename)

    return None


def _parse_date_match(match, fmt: str) -> date | None:
    """Parse a regex match into a date."""
    if fmt == "dmy4":
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    elif fmt == "dmy2":
        day, month = int(match.group(1)), int(match.group(2))
        year = int(match.group(3))
        year += 2000 if year < 100 else 0
    elif fmt == "written":
        day = int(match.group(1))
        month = GERMAN_MONTHS[match.group(2).lower()]
        year = int(match.group(3))
    else:
        return None

    return date(year, month, day)


def _is_reasonable_date(d: date) -> bool:
    """Check if a date is within a reasonable range."""
    today = date.today()
    min_date = date(1990, 1, 1)
    max_date = date(today.year + 1, 12, 31)
    return min_date <= d <= max_date


def _parse_scan_date(filename: str) -> date | None:
    """Parse scan date from a ScanSnap filename like 20260328111052.pdf."""
    name = Path(filename).stem
    match = NEW_SCAN_PATTERN.match(Path(filename).name)
    if match:
        name = match.group(1)
    elif re.match(r"^\d{14}$", name):
        pass  # bare 14-digit name
    else:
        return None

    try:
        return datetime.strptime(name[:8], "%Y%m%d").date()
    except ValueError:
        return None


def generate_title(text: str) -> str:
    """Generate a concise document title from OCR text.

    Dispatches on ``TITLE_ENGINE``: with the default "llm" engine it asks the
    local LLM (see :mod:`scansnap_ocr.llm_titler`) to read the text, and falls
    back to the keyword heuristic when the LLM is unavailable, fails, or returns
    nothing. With "heuristic" it uses the keyword titler directly.
    """
    if TITLE_ENGINE == "llm":
        from .llm_titler import generate_llm_title

        llm_title = generate_llm_title(text)
        if llm_title:
            return llm_title

    return heuristic_title(text)


def heuristic_title(text: str) -> str:
    """Generate a title from OCR text using keyword/regex heuristics.

    Returns a sanitized string suitable for use in filenames. This is the
    always-available fallback for :func:`generate_title`.
    """
    if not text or not text.strip():
        return FALLBACK_TITLE

    doc_type = _identify_document_type(text)
    sender = _identify_sender(text)

    parts = []
    if sender:
        parts.append(sender)
    if doc_type:
        parts.append(doc_type)

    # Add optional context: look for distinctive keywords after doc type
    context = _extract_context(text, doc_type, sender)
    if context:
        parts.append(context)

    if not parts:
        return FALLBACK_TITLE

    title = " ".join(parts)
    title = _sanitize_title(title)
    title = _cap_words(title, MAX_TITLE_WORDS)

    return title if title.strip() else FALLBACK_TITLE


def _identify_document_type(text: str) -> str | None:
    """Find the document type keyword in the text."""
    text_lower = text.lower()
    for doc_type, keywords in DOCUMENT_TYPES.items():
        for kw in keywords:
            if kw in text_lower:
                return doc_type
    return None


def _identify_sender(text: str) -> str | None:
    """Identify the sender/company from the top ~20% of the text."""
    lines = text.split("\n")
    top_lines = lines[:max(len(lines) // 5, 10)]
    top_text = "\n".join(top_lines)

    # Try to find company with suffix (GmbH, AG, etc.)
    match = COMPANY_SUFFIXES.search(top_text)
    if match:
        sender = match.group(0).strip()
        # Clean up
        sender = _clean_sender(sender)
        if sender and len(sender) > 2:
            return sender

    # Fallback: use the most prominent non-empty line in the top area
    for line in top_lines:
        line = line.strip()
        if not line or len(line) < 3:
            continue
        # Skip lines that look like addresses, dates, or noise
        if re.match(r"^\d", line):
            continue
        if any(p.search(line) for p in NOISE_PATTERNS):
            continue
        # Use first substantial line as sender
        words = line.split()
        if 1 <= len(words) <= 5:
            return _clean_sender(line)

    return None


def _clean_sender(sender: str) -> str:
    """Clean up a sender name."""
    # Remove noise patterns
    for pattern in NOISE_PATTERNS:
        sender = pattern.sub("", sender)
    sender = sender.strip(" ,.-;:")
    return sender


def _extract_context(text: str, doc_type: str | None, sender: str | None) -> str | None:
    """Extract optional context words that add meaning to the title."""
    text_lower = text.lower()

    # Look for distinctive keywords that aren't already in doc_type or sender
    context_keywords = [
        "Mandatsreferenz", "Lastschrift", "Überweisung",
        "Impfung", "Vorsorge", "Zahnarzt",
        "Miete", "Nebenkosten", "Kaution",
        "Strom", "Gas", "Wasser", "Internet",
        "Versicherung", "Beitrag",
        "Gehalt", "Lohn",
        "Steuer", "Steuererklärung",
        "Kindergeld", "Elterngeld",
    ]

    already_used = set()
    if doc_type:
        already_used.update(doc_type.lower().split())
    if sender:
        already_used.update(sender.lower().split())

    for kw in context_keywords:
        if kw.lower() in text_lower and kw.lower() not in already_used:
            return kw

    return None


def _sanitize_title(title: str) -> str:
    """Remove filesystem-unsafe characters."""
    title = UNSAFE_CHARS.sub("", title)
    # Collapse multiple spaces
    title = re.sub(r"\s+", " ", title).strip()
    return title


def _cap_words(title: str, max_words: int) -> str:
    """Cap a title at max_words."""
    words = title.split()
    if len(words) <= max_words:
        return title
    return " ".join(words[:max_words])


def format_filename(doc_date: date, title: str) -> str:
    """Format a filename as 'YYMMDD Title.pdf'."""
    date_str = doc_date.strftime("%y%m%d")
    return f"{date_str} {title}.pdf"


def resolve_filename_conflict(folder: Path, filename: str) -> str:
    """If filename exists in folder, append _001, _002, etc."""
    target = folder / filename
    if not target.exists():
        return filename

    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 1
    while True:
        new_name = f"{stem}_{counter:03d}{suffix}"
        if not (folder / new_name).exists():
            return new_name
        counter += 1
