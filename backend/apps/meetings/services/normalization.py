"""MeetTask local normalization v2. No masking, inference APIs or task extraction.

Drop-in replacement: original_text, normalized_text and sentences are unchanged
API keys. Extra changes/warnings are diagnostics, not extracted meeting facts.
"""
from collections import Counter
from functools import lru_cache
import logging
import re
import threading
import unicodedata

VERSION = "2.0"
MAX_INPUT_CHARS = 500_000
PARSER_MAX_CHARS = 40_000
_NLP_LOCK = threading.RLock()
logger = logging.getLogger(__name__)

# Only contractions with an unambiguous negative reading. Never expand 's/'d,
# remove negation, delete fillers, correct names or convert spoken numbers.
_NEGATIVES = {
    "can't": "cannot", "won't": "will not", "shan't": "shall not",
    "don't": "do not", "doesn't": "does not", "didn't": "did not",
    "isn't": "is not", "aren't": "are not", "wasn't": "was not",
    "weren't": "were not", "haven't": "have not", "hasn't": "has not",
    "hadn't": "had not", "wouldn't": "would not", "shouldn't": "should not",
    "couldn't": "could not", "mustn't": "must not", "needn't": "need not",
}
_NEGATIVE_RX = re.compile(r"\b(?ai:" + "|".join(map(re.escape, _NEGATIVES)) + r")\b")
_TYPOGRAPHY = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\uff0c": ",", "\uff1a": ":", "\uff1b": ";",
    "\uff01": "!", "\uff1f": "?",
})
_BIDI_CONTROLS = frozenset("\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
_TIME_PART = r"(?<![\w.])[0-9]{1,2}(?::[0-9]{2})?[ \t]*[ap]m(?!\w)"
_TIME_RX = re.compile(r"(?P<hour>[0-9]{1,2})(?::(?P<minute>[0-9]{2}))?[ \t]*(?P<ampm>[ap]m)", re.I)

# Protected spans are kept verbatim after Unicode/control cleanup. No placeholder
# strings are inserted, so real text can never collide with a placeholder.
# Ordering matters: code, URLs and paths must win over numbers inside them.
_SPAN_RX = re.compile(
    r"(?P<code>```[\s\S]*?(?:```|\Z)|`[^`\n]*(?:`|(?=\n|\Z)))"
    r'|(?P<quoted_path>"[A-Za-z]:\\[^"\n]*")'
    r"|(?P<url>(?:https?://|ftp://|www\.)[^\s<>\"`]+)"
    r"|(?P<email>[\w.+-]+@[\w-]+(?:\.[\w-]+)+)"
    r"|(?P<path>(?:[A-Za-z]:\\|\\\\)[^\s<>\"`]+|(?<!\w)/(?:[\w.~+-]+/)+[\w.~+-]*)"
    r"|(?P<ipv6>(?<!\w)(?:[0-9a-f]{0,4}:){2,}[0-9a-f:.]+(?:%[\w.-]+)?)"
    r"|(?P<domain>\b(?:[\w-]+\.)+[A-Za-z]{2,63}(?::\d+)?(?:/[^\s<>\"`]*)?)"
    r"|(?P<identifier>\b(?:[A-Za-z_]\w*(?:[-_.]\w+)+|[A-Za-z_]+\d[\w.-]*)\b|\b\w+(?:::\w+)+\b|\.NET\b|\bC\+\+|\bC#)"
    r"|(?P<abbreviation>\b(?:[A-Za-z]\.){2,}|\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|Rs)\.)"
    r"|(?P<time>" + _TIME_PART + r")"
    r"|(?P<number>\d+(?:[ \t]*[.,:/\-][ \t]*\d+)+(?:%)?|\d+(?:%)?)",
    re.I,
)


def _validate(text):
    if not isinstance(text, str):
        raise TypeError("Transcript must be a string; bytes, None and objects are not accepted.")
    if len(text) > MAX_INPUT_CHARS:
        raise ValueError(f"Transcript exceeds the {MAX_INPUT_CHARS:,}-character limit; split it before processing.")
    if "\x00" in text:
        # PostgreSQL rejects NUL even in the original_text field. Reject it here
        # instead of claiming success then failing when the exact input is saved.
        raise ValueError("Transcript contains NUL; PostgreSQL cannot store the unchanged original text.")
    if any(0xD800 <= ord(c) <= 0xDFFF for c in text):
        raise ValueError("Transcript contains invalid Unicode surrogate characters.")


def _unicode_cleanup(text, changes, warnings):
    normalized = unicodedata.normalize("NFC", text)
    if normalized != text:
        changes["unicode_nfc"] += 1
    output = []
    for index, char in enumerate(normalized):
        value = ord(char)
        if char == "\u00ad":  # discretionary soft hyphen, not a real hyphen/minus
            changes["soft_hyphens_removed"] += 1
        elif char in _BIDI_CONTROLS:
            changes["bidi_formatting_removed"] += 1
            warnings["bidi_formatting_present"] += 1
        elif char in {"\u200b", "\ufeff", "\u2060"}:
            # An internal invisible boundary is uncertain; do not join two words.
            output.append("" if char == "\ufeff" and index == 0 else " ")
            changes["invisible_boundaries_cleaned"] += 1
            warnings["invisible_boundary_review"] += 1
        elif (value < 32 and char not in "\t\n\r") or 0x7F <= value <= 0x9F:
            output.append(" ")
            changes["control_characters_replaced"] += 1
        else:
            # ZWJ, ZWNJ, combining marks, emoji selectors and Arabic letters stay.
            output.append(char)
            if unicodedata.category(char) == "Cf" and char not in {"\u200c", "\u200d"}:
                warnings["other_unicode_formatting_preserved"] += 1
    return "".join(output)


def _negative(match):
    word = match.group()
    replacement = _NEGATIVES[word.lower()]
    if word.isupper():
        return replacement.upper()
    if word[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement


def _plain_cleanup(text, changes):
    translated = text.translate(_TYPOGRAPHY)
    if translated != text:
        changes["typographic_punctuation_standardized"] += sum(a != b for a, b in zip(text, translated))
    text = re.sub(r"\s+", " ", translated)
    # Count actual altered runs rather than every existing single space.
    changed_runs = sum(m.group() != " " for m in re.finditer(r"\s+", translated))
    changes["whitespace_runs_cleaned"] += changed_runs
    text, count = _NEGATIVE_RX.subn(_negative, text)
    changes["negative_contractions_expanded"] += count
    # Never repair digit punctuation, versions, URLs or quoted code: protected above.
    text, count = re.subn(r" +(?=[.,;:!?،؛؟۔])", "", text)
    changes["spaces_before_punctuation_removed"] += count
    # A colon pair belongs to identifiers; don't split it. Full stops deliberately
    # excluded: report.Ali might be a domain, and 3.14 must never become 3. 14.
    text, count = re.subn(r"(?<=[,;:!?،؛؟])(?=[^\W\d_])", " ", text)
    changes["spaces_after_punctuation_added"] += count
    return text


def _scan_warnings(text, warnings):
    if "\ufffd" in text:
        warnings["replacement_characters_present"] += text.count("\ufffd")
    if re.search(r"\b(?:ain't|\w+'[sd])\b", text, re.I):
        warnings["ambiguous_contractions_preserved"] += 1
    if re.search(r"\b\w+\s+'\s*(?:t|s|d|ll|re|ve|m)\b", text, re.I):
        warnings["broken_contraction_preserved"] += 1
    if re.search(r"\b(?:today|tomorrow|yesterday|(?:next|this|last)\s+(?:week|month|year|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday))\b", text, re.I):
        warnings["relative_dates_preserved"] += 1
    for m in re.finditer(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})(?!\d)", text):
        a, b = int(m[1]), int(m[2])
        if 1 <= a <= 12 and 1 <= b <= 12 and a != b:
            warnings["ambiguous_numeric_dates_preserved"] += 1
    if re.search(r"\b(\w+)(?:\s+\1){4,}\b", text, re.I):
        warnings["possible_repetition_review"] += 1
    if re.search(r"\[(?:inaudible|unintelligible|music|silence|noise)[^\]]*\]|\((?:inaudible|unintelligible)\)", text, re.I):
        warnings["audio_uncertainty_markers_preserved"] += 1
    if any(c.isalpha() and "LATIN" not in unicodedata.name(c, "") for c in text):
        warnings["english_segmentation_non_latin_text"] += 1
    if any(text.count(a) != text.count(b) for a, b in [("(", ")"), ("[", "]"), ("{", "}")]):
        warnings["unbalanced_brackets_preserved"] += 1


def _prepare(text):
    _validate(text)
    changes, warnings = Counter(), Counter()
    text = _unicode_cleanup(text, changes, warnings)
    parts, end = [], 0
    for match in _SPAN_RX.finditer(text):
        parts.append(_plain_cleanup(text[end:match.start()], changes))
        token, kind = match.group(), match.lastgroup
        if kind == "time":
            t = _TIME_RX.fullmatch(token)
            hour, minute = int(t["hour"]), t["minute"]
            if 1 <= hour <= 12 and (minute is None or 0 <= int(minute) <= 59):
                token_new = f"{hour}" + (f":{minute}" if minute is not None else "") + f" {t['ampm'].upper()}"
                if token_new != token:
                    changes["am_pm_format_standardized"] += 1
                token = token_new
            else:
                warnings["invalid_time_preserved"] += 1
        elif kind == "number" and re.search(r"\d[ \t]+[.,:/\-]|[.,:/\-][ \t]+\d", token):
            warnings["spaced_numeric_expression_preserved"] += 1
        parts.append(token)
        end = match.end()
    parts.append(_plain_cleanup(text[end:], changes))
    joined = "".join(parts)
    normalized = joined.strip()
    if normalized != joined:
        changes["outer_whitespace_trimmed"] += 1
    if not normalized or not any(c.isalnum() for c in normalized):
        raise ValueError("Transcript contains no readable letters or numbers.")
    _scan_warnings(normalized, warnings)
    return normalized, changes, warnings


def clean_text(text: str) -> str:
    """Normalize text without loading spaCy. Same rules as normalize_transcript."""
    return _prepare(text)[0]


@lru_cache(maxsize=1)
def get_nlp():
    import spacy
    try:
        # Keep the parser; remove unrelated entity and lemma processing.
        return spacy.load("en_core_web_sm", exclude=["ner", "lemmatizer"])
    except OSError as exc:
        raise RuntimeError("English model missing. Run: python -m spacy download en_core_web_sm") from exc


@lru_cache(maxsize=1)
def _get_long_nlp():
    import spacy
    nlp = spacy.blank("en")
    # Contraction expansion can make output longer than the input limit.
    nlp.max_length = 2 * MAX_INPUT_CHARS + 1
    nlp.add_pipe("sentencizer", config={"punct_chars": [".", "!", "?", "؟", "۔", "…"]})
    return nlp


def normalize_transcript(text: str) -> dict:
    """Return normalized text + spaCy sentences + a transparent diagnostic report.

    Protected code/URLs/identifiers/numbers may retain intentional whitespace.
    Input over 500k chars is rejected, never truncated. Long text uses a lighter
    spaCy sentencizer to avoid parser memory spikes; the report discloses this.
    """
    normalized, changes, warnings = _prepare(text)
    with _NLP_LOCK:
        if len(normalized) > PARSER_MAX_CHARS:
            nlp = _get_long_nlp()
            method = "spacy_sentencizer_long_input"
            warnings["long_input_rule_based_segmentation"] += 1
        else:
            nlp = get_nlp()
            method = "spacy_parser"
        doc = nlp(normalized)
        sentences = [sent.text.strip() for sent in doc.sents if sent.text.strip()]
    if warnings:
        # Log codes/counts only, never meeting content or personal details.
        logger.info("Normalization review flags: %s", dict(warnings))
    return {
        "original_text": text,
        "normalized_text": normalized,
        "sentences": sentences,
        "changes": [{"rule": key, "count": count} for key, count in sorted(changes.items()) if count],
        "warnings": [{"code": key, "count": count} for key, count in sorted(warnings.items()) if count],
        "normalization_version": VERSION,
        "segmentation_method": method,
    }
