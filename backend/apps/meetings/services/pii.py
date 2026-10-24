import re

# Custom formats (Pakistan CNIC / phone, cards, IBAN) applied before Presidio.
PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("CNIC", re.compile(r"\b\d{5}-\d{7}-\d\b")),
    ("PHONE_NUMBER", re.compile(r"(?<!\d)(?:\+92|0)3\d{2}[- ]?\d{7}(?!\d)")),
    ("CARD_NUMBER", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")),
]

_analyzer = None
PRESIDIO_ENTITIES = ["EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "IBAN_CODE", "US_SSN", "IP_ADDRESS", "PERSON"]


def _get_analyzer():
    global _analyzer
    if _analyzer is None:
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import NlpEngineProvider
            nlp = NlpEngineProvider(nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}]}).create_engine()
            _analyzer = AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])
        except Exception:
            _analyzer = False  # Presidio unavailable; regex layer still runs
    return _analyzer or None


def _name_pattern(name):
    """Whole-word match that also tolerates speech-to-text splitting a name, e.g. 'saraw13' heard as 'Sara W13' or 'sara-w-13'.
    Only names of 5+ letters/digits get the tolerant form; shorter ones stay an exact whole-word match to avoid false hits."""
    chars = re.sub(r"[\W_]+", "", name)
    if len(chars) >= 5 and re.fullmatch(r"[A-Za-z0-9]+", chars):
        return r"(?<![A-Za-z0-9])" + r"[\s._-]{0,2}".join(re.escape(c) for c in chars) + r"(?![A-Za-z0-9])"
    return rf"\b{re.escape(name)}\b"


def pseudonymize(text, participants):
    """participants: list of (user, pseudonym). Replaces full names, then first names."""
    names = []
    for user, ps in participants:
        full = user.get_full_name().strip()
        if full:
            names.append((full, ps))
            for part in full.split():
                if len(part) > 2:
                    names.append((part, ps))
        names.append((user.username, ps))
        letters = re.sub(r"\d+", "", re.sub(r"[\W_]+", "", user.username))
        if len(letters) >= 4 and letters.lower() != user.username.lower():
            names.append((letters, ps))          # "saraw13" -> "saraw"
        if len(letters) >= 5:
            names.append((letters[:-1], ps))     # "saraw" -> "sara" (first name + initial)
    for name, ps in sorted(names, key=lambda x: -len(x[0])):
        text = re.sub(_name_pattern(name), ps, text, flags=re.IGNORECASE)
    return text


# Speech-to-text writes things as it hears them: "ali dot test at the rate of gmail dot com", "0300 1234 for 67".
# These patterns catch the spoken forms that the plain regexes above cannot see.
_DOT = r"(?:\.|\s+dot\s+)"
SPOKEN_EMAIL = [
    # "name at the rate of domain.com" / "name at the rate domain dot com"
    re.compile(rf"[\w+-]+(?:{_DOT}[\w+-]+)*\s+at\s+the\s+rate(?:\s+of)?\s+[\w-]+(?:{_DOT}[A-Za-z]{{2,}})+", re.IGNORECASE),
    # "name dot x at domain dot com" (the local part itself is spoken with "dot")
    re.compile(rf"[\w+-]+(?:\s+dot\s+[\w+-]+)+\s+at\s+[\w-]+(?:{_DOT}[A-Za-z]{{2,}})+", re.IGNORECASE),
    # "name at gmail dot com" for the big mail providers
    re.compile(rf"[\w+.-]+\s+at\s+(?:gmail|yahoo|outlook|hotmail|icloud|live)(?:{_DOT}com)", re.IGNORECASE),
]
_NUM_WORDS = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "for": "4",
              "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}
_TOKEN = rf"(?:\+?\d+|\b(?:{'|'.join(_NUM_WORDS)})\b)"
SPOKEN_NUMBER = re.compile(rf"(?<!\w)(?<!\d\.){_TOKEN}(?:[\s,-]+{_TOKEN})+(?!\w)(?!\.\d)", re.IGNORECASE)


def _mask_spoken_numbers(text):
    """A run of digits and number words ("0300 1234 for 67", "zero three zero zero ...") with 10+ digits is a phone number."""
    def sub(m):
        digits = "".join(_NUM_WORDS.get(t.lower(), t) for t in re.findall(r"\+?\d+|[A-Za-z]+", m.group(0)))
        digits = re.sub(r"\D", "", digits)
        return "[PHONE_NUMBER]" if 10 <= len(digits) <= 15 else m.group(0)
    return SPOKEN_NUMBER.sub(sub, text)


def mask_pii(text):
    for label, rx in PATTERNS:
        text = rx.sub(f"[{label}]", text)
    for rx in SPOKEN_EMAIL:
        text = rx.sub("[EMAIL]", text)
    text = _mask_spoken_numbers(text)
    analyzer = _get_analyzer()
    if analyzer:
        results = analyzer.analyze(text=text, entities=PRESIDIO_ENTITIES, language="en")
        tags = [m.span() for m in re.finditer(r"\[[A-Z_]+\]", text)]  # tags we already inserted, e.g. [EMAIL]
        results = [r for r in results if not any(r.start < b and a < r.end for a, b in tags)]
        for r in sorted(results, key=lambda r: r.start, reverse=True):
            if r.entity_type == "PERSON" and re.fullmatch(r"P\d+", text[r.start:r.end].strip()):
                continue  # our own participant labels are not personal data
            text = text[:r.start] + f"[{r.entity_type}]" + text[r.end:]
    return text


def _fuzzy_pseudonymize(text, participants, threshold=0.86, margin=0.12):
    """Match clear Whisper first-name spelling variations BEFORE Presidio masks them.

    Conservative rules: only title-cased alphabetic words with >=4 letters;
    a single unique participant must beat the runner-up by `margin`.
    Ambiguous words stay unchanged for the general PII masker to handle.
    """
    from difflib import SequenceMatcher

    choices = {}
    for user, pseudonym in participants:
        full = (user.get_full_name() or '').strip()
        # Use registered FIRST names, not last names, to reduce accidental matches.
        first = full.split()[0] if full else ''
        if len(first) >= 4 and first.isalpha():
            choices.setdefault(first.casefold(), set()).add(pseudonym)

    unique = [(name, next(iter(labels))) for name, labels in choices.items() if len(labels) == 1]
    if not unique:
        return text

    # Avoid rewriting P-labels or [PII_PLACEHOLDER] tags.
    parts = re.split(r'(\[[A-Z][A-Z0-9_]*\]|\bP\d+\b)', text)

    def replace_token(match):
        word = match.group(0)
        if len(word) < 4 or not word[0].isupper() or not word[1:].islower():
            return word
        scores = sorted(
            ((SequenceMatcher(None, word.casefold(), name).ratio(), ps) for name, ps in unique),
            key=lambda pair: pair[0], reverse=True,
        )
        if not scores or scores[0][0] < threshold:
            return word
        if len(scores) > 1 and scores[0][0] - scores[1][0] < margin:
            return word
        return scores[0][1]

    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r'\b[A-Z][a-z]{3,}\b', replace_token, parts[i])
    return ''.join(parts)


def sanitize(text, participants):
    """Best-effort de-identification; only sanitized text should reach Gemini.

    Exact participant matching runs first, then cautious speech-to-text spelling
    correction (e.g. Sarah -> Sara's P-label), then generic PII masking.
    """
    text = pseudonymize(text or '', participants)
    text = _fuzzy_pseudonymize(text, participants)
    return mask_pii(text)


def _norm(s):
    return re.sub(r"[\W_]+", "", (s or "").lower())


def match_participant(label, links):
    """Turn the AI's assignee label into a participant's user id, or None.
    Accepts P-labels ("P1", "P1 (Sara)") and, as a fallback, a spoken name that clearly
    points to exactly one participant ("Sara", "Sara W13", "saraw13"). Ambiguous -> None."""
    raw = (label or "").strip()
    if not raw:
        return None
    m = re.search(r"\bP\d+\b", raw, flags=re.IGNORECASE)
    if m:
        for l in links:
            if l.pseudonym.upper() == m.group(0).upper():
                return l.user_id
    n = _norm(raw)
    if not n:
        return None
    hits = set()
    for l in links:
        u = l.user
        full = u.get_full_name() or ""
        letters = re.sub(r"\d+", "", _norm(u.username))
        cands = {_norm(u.username), _norm(full), letters, letters[:-1] if len(letters) > 4 else ""}
        cands |= {_norm(p) for p in full.split()}
        for c in cands:
            if c and (n == c or (len(n) >= 4 and len(c) >= 4 and (c.startswith(n) or n.startswith(c)))):
                hits.add(l.user_id)
    return hits.pop() if len(hits) == 1 else None


from difflib import SequenceMatcher

def suggest_participant(label, links, threshold=0.80):
    """Suggest a participant for slightly misspelled names."""
    raw = (label or "").strip().lower()

    if not raw or raw in {"unknown", "unresolved", "someone", "not specified"}:
        return None

    # Do not guess when the AI explicitly gives a P-label.
    if re.search(r"\bP\d+\b", raw, re.I):
        return None

    def normalize(value):
        return re.sub(r"[^a-z0-9]", "", value.lower())

    target = normalize(raw)
    if len(target) < 3:
        return None

    scores = []

    for link in links:
        user = link.user
        full = user.get_full_name() or ""

        candidates = [full, user.username]
        candidates += [p for p in full.split() if len(p) >= 3]

        score = max(
            (
                SequenceMatcher(None, target, normalize(name)).ratio()
                for name in candidates
                if normalize(name)
            ),
            default=0
        )

        scores.append((score, link.user_id))

    scores.sort(reverse=True)

    if not scores or scores[0][0] < threshold:
        return None

    # Avoid suggesting a name when two people are similarly likely.
    if len(scores) > 1 and scores[0][0] - scores[1][0] < 0.10:
        return None

    return scores[0][1]
