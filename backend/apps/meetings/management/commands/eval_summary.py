"""Measure the quality of the meeting summary on real recorded meetings (QMSum), and preview the minutes.

Get the QMSum corpus (real AMI / ICSI / parliament meetings, each with a human-written summary):
  git clone --depth 1 https://github.com/Yale-LILY/QMSum
  python manage.py eval_summary --dir QMSum/data/ALL/test
  python manage.py eval_summary --dir QMSum/data/ALL/val --show 1        # also print one full set of minutes

Two scores are printed, each ROUGE-1 / ROUGE-2 F1 against the human summary of the whole meeting (word and word-pair
overlap; higher is better):
  summary only        the short overview section (about 25 words, so it scores low by design)
  summary + discussion everything the minutes say about the content (about 200 words)
The templated opening sentence is left out so only content is judged. The summariser is unsupervised (TextRank), so
this data is used to MEASURE it, never to train it. ROUGE rewards overlap and length, not professional structure, so use
the numbers to compare versions of summary.py against each other, and judge the minutes themselves by reading them
(--show). The QMSum transcripts are raw spontaneous speech and much messier than Whisper output."""
import glob
import json
import os
import re
from collections import Counter
from types import SimpleNamespace

from django.core.management.base import BaseCommand, CommandError

from apps.meetings.services import summary


def clean(t):
    t = re.sub(r"\{[^}]*\}|<[^>]*>", "", t)
    t = re.sub(r"\s+([.,?!;:])", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def _tokens(s):
    return re.findall(r"[a-z0-9]+", s.lower())


def rouge_f1(hyp, ref, n):
    def grams(t):
        return Counter(tuple(t[i:i + n]) for i in range(len(t) - n + 1))
    h, r = grams(_tokens(hyp)), grams(_tokens(ref))
    overlap = sum((h & r).values())
    if not overlap:
        return 0.0
    p, rec = overlap / sum(h.values()), overlap / sum(r.values())
    return 2 * p * rec / (p + rec)


def content_of(summary_text):
    """The summary without its templated first sentence ("This meeting ... was held on ...")."""
    return " ".join(summary_text.split(". ")[1:]) if ". " in summary_text else summary_text


class Command(BaseCommand):
    help = "Score the meeting summary against human summaries (QMSum JSON files)."

    def add_arguments(self, p):
        p.add_argument("--dir", required=True)
        p.add_argument("--show", type=int, default=0, help="print the full minutes for this many meetings")

    def handle(self, *a, **o):
        files = sorted(glob.glob(os.path.join(o["dir"], "*.json")))
        if not files:
            raise CommandError("No .json files found in that folder.")
        stub = SimpleNamespace(id=1, title="", scheduled_at=None, location="", description="", manager=None, project=None)
        r1, r2, a1, a2, words, shown = [], [], [], [], [], 0
        for f in files:
            d = json.load(open(f, encoding="utf-8"))
            ref = next((q["answer"] for q in d.get("general_query_list", []) if "whole meeting" in q["query"].lower()), None)
            if not ref:
                continue
            sents = [clean(x["content"]) for x in d["meeting_transcripts"]]
            sents = [s for s in sents if len(s.split()) >= 2]
            out = summary.build_summary(sents, [], stub, [])
            hyp = content_of(out["summary"])
            both = hyp + " " + " ".join(out["discussion_points"])
            r1.append(rouge_f1(hyp, ref, 1))
            r2.append(rouge_f1(hyp, ref, 2))
            a1.append(rouge_f1(both, ref, 1))
            a2.append(rouge_f1(both, ref, 2))
            words.append((len(_tokens(hyp)), len(_tokens(both))))
            if shown < o["show"]:
                shown += 1
                self.stdout.write(f"\n===== {os.path.basename(f)} =====\n{out['mom']}\n")
        n = len(r1)
        if not n:
            raise CommandError("None of the files had a 'Summarize the whole meeting' reference.")
        self.stdout.write(f"\n{n} meetings   summariser: {summary.MODEL_NAME}")
        self.stdout.write(f"summary only          ROUGE-1 F1: {100 * sum(r1) / n:.1f}   ROUGE-2 F1: {100 * sum(r2) / n:.1f}   "
                          f"average length: {sum(w[0] for w in words) / n:.0f} words")
        self.stdout.write(f"summary + discussion  ROUGE-1 F1: {100 * sum(a1) / n:.1f}   ROUGE-2 F1: {100 * sum(a2) / n:.1f}   "
                          f"average length: {sum(w[1] for w in words) / n:.0f} words")