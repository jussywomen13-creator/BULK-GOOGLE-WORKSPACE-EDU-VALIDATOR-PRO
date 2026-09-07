"""Email extraction, normalization, and deduplication helpers."""

import csv
import io
import re
from collections import OrderedDict

from validation import EXTRACT_RE, extract_domain, normalize_email


def extract_emails_from_text(text: str, source: str = "paste") -> list:
    """Extract all email-like strings from text, preserving original occurrences."""
    if not text:
        return []
    found = []
    for match in EXTRACT_RE.finditer(text):
        raw = match.group(0).strip()
        if raw:
            found.append({"raw_email": raw, "source": source})
    return found


def _decode_file(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="ignore")


def extract_emails_from_file(data: bytes, filename: str) -> list:
    """Extract emails from a TXT/CSV/other text file.

    For CSV/TSV, source preserves the row number where the email was found.
    """
    text = _decode_file(data)
    source_name = filename or "upload"
    lower_filename = source_name.lower()

    lines = text.splitlines()
    first_line = lines[0] if lines else ""
    tab_delimited = "\t" in first_line
    is_csv = lower_filename.endswith(".csv") or tab_delimited or ("," in first_line)

    if is_csv:
        results = []
        delimiter = "\t" if tab_delimited else ","
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        for idx, row in enumerate(rows, start=1):
            line = ",".join(row)
            source = f"{source_name}:row {idx}"
            results.extend(extract_emails_from_text(line, source=source))
        return results

    return extract_emails_from_text(text, source=source_name)


def normalize_and_dedupe(items: list) -> dict:
    """Normalize whitespace/lowercase, deduplicate, and return summary + rows.

    Returns:
        {
          "items": [{"raw_email", "normalized", "source", "is_duplicate",
                     "unique_key", "domain"}],
          "total", "unique", "duplicates"
        }
    """
    seen = OrderedDict()
    out = []
    duplicates = 0
    for item in items:
        raw = item.get("raw_email", "")
        source = item.get("source", "paste")
        normalized = normalize_email(raw)
        if not normalized:
            continue
        unique_key = normalized
        is_duplicate = unique_key in seen
        if is_duplicate:
            duplicates += 1
            out.append(
                {
                    "raw_email": raw,
                    "normalized": normalized,
                    "source": source,
                    "is_duplicate": True,
                    "unique_key": unique_key,
                    "domain": extract_domain(normalized),
                }
            )
        else:
            seen[unique_key] = True
            out.append(
                {
                    "raw_email": raw,
                    "normalized": normalized,
                    "source": source,
                    "is_duplicate": False,
                    "unique_key": unique_key,
                    "domain": extract_domain(normalized),
                }
            )
    return {
        "items": out,
        "total": len(out),
        "unique": len(seen),
        "duplicates": duplicates,
    }
