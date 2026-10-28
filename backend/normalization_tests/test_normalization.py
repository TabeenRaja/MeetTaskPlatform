"""Run from backend: python -m unittest discover -s normalization_tests -v."""
import importlib.util
import random
import unittest
from unittest.mock import patch

from apps.meetings.services import normalization as n


CASES = [
    # Formatting, negation, identity and language preservation.
    ("  Sara   will not send it.\n Ali will finish it.  ", "Sara will not send it. Ali will finish it."),
    ("\tAli\r\nwill\u00a0not\u202fsend\u3000it. ", "Ali will not send it."),
    ("Cafe\u0301", "Café"),
    ("“Ali can’t send it ,Sara won’t finish by 4pm !”", '"Ali cannot send it, Sara will not finish by 4 PM!"'),
    ("Ali:hello,Sara;please listen!Thanks", "Ali: hello, Sara; please listen! Thanks"),
    ("Hello , Ali ; thank you !", "Hello, Ali; thank you!"),
    ("It is done .", "It is done."),
    ("Ali，please don’t send it！", "Ali, please do not send it!"),
    ("Sara’s report isn’t ready.", "Sara's report is not ready."),
    ("Um, uh, I I will do it.", "Um, uh, I I will do it."),
    ("No, no, do not send it.", "No, no, do not send it."),
    ("not not not not not", "not not not not not"),
    ("I'd send it if she'd agreed.", "I'd send it if she'd agreed."),
    ("He's ready; it's done.", "He's ready; it's done."),
    ("I ain't certain.", "I ain't certain."),
    ("We don ' t know.", "We don ' t know."),
    ("test suits and 12 bucks", "test suits and 12 bucks"),
    ("Sarah and Sara are different people.", "Sarah and Sara are different people."),
    ("send fifty thousand rupees", "send fifty thousand rupees"),
    ("Launch next Friday, not today.", "Launch next Friday, not today."),
    ("4pm", "4 PM"), ("04PM", "4 PM"), ("4:30pm", "4:30 PM"),
    ("12am", "12 AM"), ("12:00 AM", "12:00 AM"),
    ("4 p.m.", "4 p.m."), ("16:00", "16:00"),
    ("13pm", "13pm"), ("4:99pm", "4:99pm"), ("0am", "0am"),
    ("at 4pm.", "at 4 PM."),
    ("v4pm is a build identifier.", "v4pm is a build identifier."),
    ("Rs. 5,000.50", "Rs. 5,000.50"),
    ("$1,250.00 and -3.14 and +92", "$1,250.00 and -3.14 and +92"),
    ("1,000 1.000 1,25 1.25 1/2 5%", "1,000 1.000 1,25 1.25 1/2 5%"),
    ("1, 000 and 3 . 14", "1, 000 and 3 . 14"),
    ("03/04/2026 2026-10-28 28/10/2026", "03/04/2026 2026-10-28 28/10/2026"),
    ("03001234567 +92 300 1234567", "03001234567 +92 300 1234567"),
    ("12345-1234567-1 PK36SCBL0000001123456702", "12345-1234567-1 PK36SCBL0000001123456702"),
    ("Email sara+test@example.com", "Email sara+test@example.com"),
    ("https://example.com/a,b?x=1.2&at=4pm", "https://example.com/a,b?x=1.2&at=4pm"),
    ("www.example.com example.org example.com/a,b", "www.example.com example.org example.com/a,b"),
    ("127.0.0.1:8000 v1.2.3 MT-123 ISO-27001", "127.0.0.1:8000 v1.2.3 MT-123 ISO-27001"),
    ("Address: fe80::abcd:1234", "Address: fe80::abcd:1234"),
    ("Address: ::1 and 2001:db8::1", "Address: ::1 and 2001:db8::1"),
    (r"C:\Users\Sara\test.txt", r"C:\Users\Sara\test.txt"),
    ('"C:\\Users\\WALLED TRADERS\\file.txt"', '"C:\\Users\\WALLED TRADERS\\file.txt"'),
    ("/home/sara/file.txt", "/home/sara/file.txt"),
    ("C++ C# .NET x::y", "C++ C# .NET x::y"),
    ("Dr. Ali and Mr. Khan, e.g. a.m.", "Dr. Ali and Mr. Khan, e.g. a.m."),
    ("Use `don't  change(x,y)` please.", "Use `don't  change(x,y)` please."),
    ("```python\nprint('don’t',  3.14)\n```", "```python\nprint('don’t',  3.14)\n```"),
    ("Use `unclosed  code", "Use `unclosed  code"),
    ("[00:12] Speaker 1: do not send it.", "[00:12] Speaker 1: do not send it."),
    ("[inaudible] [Music] (laughs)", "[inaudible] [Music] (laughs)"),
    ("Wait... really?!", "Wait... really?!"),
    ("3–5 days, −2°C, 10-12 items", "3–5 days, −2°C, 10-12 items"),
    ("We need <div> &amp; HTML.", "We need <div> &amp; HTML."),
    ("علی کل آئے گا۔", "علی کل آئے گا۔"),
    ("٤pm and ４pm", "٤pm and ４pm"),
    ("İSN'T ıSn't iſn't", "İSN'T ıSn't iſn't"),
    ("علی،کل آئے گا؟", "علی، کل آئے گا؟"),
    ("می\u200cروم", "می\u200cروم"),
    ("👩\u200d💻 will join Ali.", "👩\u200d💻 will join Ali."),
    ("File ① uses ½ and ².", "File ① uses ½ and ²."),
    ("\ufeffAli will send it.", "Ali will send it."),
    ("Ali\ufeffwill\u200bnot\u2060send it.", "Ali will not send it."),
    ("co\u00adoperate", "cooperate"),
    ("Ali\x01will\x07not\x1bsend it.", "Ali will not send it."),
    ("Ali\u202ewill\u202c not send it.", "Aliwill not send it."),
    ("The word is \ufffdunclear.", "The word is \ufffdunclear."),
]


class NormalizationRulesTests(unittest.TestCase):
    def test_cases(self):
        for raw, expected in CASES:
            with self.subTest(raw=raw):
                self.assertEqual(n.clean_text(raw), expected)

    def test_negative_contractions(self):
        for raw, expected in n._NEGATIVES.items():
            for source, target in [(raw, expected), (raw.upper(), expected.upper()), (raw.capitalize(), expected.capitalize())]:
                with self.subTest(source=source):
                    self.assertEqual(n.clean_text(source), target)

    def test_idempotence(self):
        for raw, _ in CASES:
            with self.subTest(raw=raw):
                once = n.clean_text(raw)
                self.assertEqual(n.clean_text(once), once)

    def test_invalid_types(self):
        for value in [None, b"hello", 123, [], {}, True]:
            with self.subTest(value=value), self.assertRaises(TypeError):
                n.clean_text(value)

    def test_empty_or_unreadable(self):
        for value in ["", " \n\t", "\x00\ufeff", "...?!", "\u200b", "👩\u200d💻"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                n.clean_text(value)

    def test_surrogates_rejected(self):
        with self.assertRaisesRegex(ValueError, "surrogate"):
            n.clean_text("Ali\ud800")

    def test_nul_rejected_before_original_text_reaches_postgres(self):
        with self.assertRaisesRegex(ValueError, "PostgreSQL"):
            n.normalize_transcript("Ali\x00will not send it.")

    def test_limit_rejects_without_truncating(self):
        with self.assertRaisesRegex(ValueError, "limit"):
            n.clean_text("a" * (n.MAX_INPUT_CHARS + 1))

    def test_whitespace_variations_are_stable(self):
        rng = random.Random(42)
        words = ["Sara", "will", "not", "send", "03001234567", "today."]
        for _ in range(250):
            raw = "  " + "".join(word + rng.choice([" ", "   ", "\t", "\r\n", "\u00a0"]) for word in words)
            self.assertEqual(n.clean_text(raw), " ".join(words))

    def test_numeric_identifiers_are_preserved(self):
        rng = random.Random(17)
        for _ in range(250):
            phone = "03" + "".join(str(rng.randrange(10)) for _ in range(9))
            value = f"Rs. {rng.randrange(1, 10000):,}.{rng.randrange(100):02d}"
            raw = f"Sara: {phone}, total {value}."
            self.assertEqual(n.clean_text(raw), raw)

    def test_no_silent_semantic_correction(self):
        raw = "Sarah ran test suits; the 12 bucks aren't resolved by next Friday."
        self.assertEqual(n.clean_text(raw), "Sarah ran test suits; the 12 bucks are not resolved by next Friday.")

    def test_mixed_content_is_idempotent(self):
        rng = random.Random(872)
        parts = ["Sara", "will not", "can’t", "won't", "4pm", "3.14", "Rs. 5,000.50", "03/04/2026", "v1.2.3", "a@example.com", "https://example.com/a,b?x=1", "`don’t  edit(x,y)`", "fe80::abcd:1234", "علی", "x::y", "C++", "..."]
        gaps = [" ", "  ", "\n", " , ", ";", ":", "!", "？"]
        for _ in range(2000):
            raw = "".join(rng.choice(parts) + rng.choice(gaps) for _ in range(rng.randint(1, 10)))
            if not any(c.isalnum() for c in raw):
                with self.assertRaises(ValueError):
                    n.clean_text(raw)
            else:
                once = n.clean_text(raw)
                self.assertEqual(n.clean_text(once), once)


def has_model():
    return importlib.util.find_spec("en_core_web_sm") is not None


@unittest.skipUnless(has_model(), "Install en_core_web_sm to run model integration tests")
class ModelIntegrationTests(unittest.TestCase):
    def test_real_segmentation_and_original_preservation(self):
        raw = "  Sara can’t send it today.   Ali will finish it by Friday.  "
        r = n.normalize_transcript(raw)
        self.assertEqual(r["original_text"], raw)
        self.assertEqual(r["normalized_text"], "Sara cannot send it today. Ali will finish it by Friday.")
        self.assertEqual(r["sentences"], ["Sara cannot send it today.", "Ali will finish it by Friday."])
        self.assertEqual(r["segmentation_method"], "spacy_parser")
        self.assertNotIn("action_items", r)
        self.assertNotIn("entities", r)

    def test_warning_report(self):
        r = n.normalize_transcript("I'd send it on 03/04/2026, not tomorrow. The time is 13pm. [inaudible]")
        codes = {w["code"] for w in r["warnings"]}
        self.assertTrue({"ambiguous_contractions_preserved", "ambiguous_numeric_dates_preserved", "relative_dates_preserved", "invalid_time_preserved", "audio_uncertainty_markers_preserved"} <= codes)

    def test_changed_rules_report(self):
        r = n.normalize_transcript("  Sara can’t do it ,Ali won’t finish by 4pm !  ")
        rules = {c["rule"] for c in r["changes"]}
        self.assertTrue({"negative_contractions_expanded", "am_pm_format_standardized", "spaces_before_punctuation_removed"} <= rules)

    def test_long_input_uses_bounded_segmentation_without_losing_text(self):
        raw = "Ali will not send the report. " * 1600
        r = n.normalize_transcript(raw)
        self.assertEqual(r["normalized_text"], raw.strip())
        self.assertEqual(len(r["sentences"]), 1600)
        self.assertEqual(r["segmentation_method"], "spacy_sentencizer_long_input")
        self.assertIn("long_input_rule_based_segmentation", {w["code"] for w in r["warnings"]})

    def test_protected_code_in_normalized_text(self):
        raw = "Use `don't  call(x,y)` please. Ali won't call it."
        r = n.normalize_transcript(raw)
        self.assertIn("`don't  call(x,y)`", r["normalized_text"])
        self.assertIn("will not", r["normalized_text"])

    def test_repeat_call_has_identical_text_and_sentences(self):
        first = n.normalize_transcript("Sara can’t send it ,Ali will finish by 4pm !")
        second = n.normalize_transcript(first["normalized_text"])
        self.assertEqual(first["normalized_text"], second["normalized_text"])
        self.assertEqual(first["sentences"], second["sentences"])


if __name__ == "__main__":
    unittest.main()
