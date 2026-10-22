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
PRESIDIO_ENTITIES = ["EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "IBAN_CODE", "US_SSN", "IP_ADDRESS"]


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
    for name, ps in sorted(names, key=lambda x: -len(x[0])):
        text = re.sub(rf"\b{re.escape(name)}\b", ps, text, flags=re.IGNORECASE)
    return text


def mask_pii(text):
    for label, rx in PATTERNS:
        text = rx.sub(f"[{label}]", text)
    analyzer = _get_analyzer()
    if analyzer:
        results = analyzer.analyze(text=text, entities=PRESIDIO_ENTITIES, language="en")
        for r in sorted(results, key=lambda r: r.start, reverse=True):
            text = text[:r.start] + f"[{r.entity_type}]" + text[r.end:]
    return text


def sanitize(text, participants):
    """Best-effort de-identification. Not guaranteed to catch all PII."""
    return mask_pii(pseudonymize(text, participants))