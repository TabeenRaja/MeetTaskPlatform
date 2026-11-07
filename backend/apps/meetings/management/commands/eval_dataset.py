"""Run the extractor over real recorded meetings and report how many tasks it invents.

Get the QMSum corpus (real AMI / ICSI / parliament meetings):  git clone --depth 1 https://github.com/Yale-LILY/QMSum
  python manage.py eval_dataset --dir QMSum/data/Product/test
  python manage.py eval_dataset --dir QMSum/data/Product/test --show 40      # also print 40 sample tasks to review by eye

There are no answer labels, so this measures NOISE (tasks per 1,000 words), not recall. Read the sample and judge it."""
import glob
import json
import os
import random
import re
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.meetings.services import extraction


def clean(t):
    t = re.sub(r"\{[^}]*\}|<[^>]*>", "", t)
    t = re.sub(r"\s+([.,?!;:])", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


class Command(BaseCommand):
    help = "Count the tasks the extractor finds in real meeting transcripts (QMSum JSON files)."

    def add_arguments(self, p):
        p.add_argument("--dir", required=True)
        p.add_argument("--show", type=int, default=0)

    def handle(self, *a, **o):
        files = sorted(glob.glob(os.path.join(o["dir"], "*.json")))
        if not files:
            raise CommandError("No .json files found in that folder.")
        words = total = 0
        allitems = []
        for f in files:
            d = json.load(open(f, encoding="utf-8"))
            sents = [clean(x["content"]) for x in d["meeting_transcripts"]]
            text = " ".join(s for s in sents if len(s.split()) >= 2)
            items = extraction.extract_action_items(text, [], date.today())
            words += len(text.split())
            total += len(items)
            allitems += items
        self.stdout.write(f"{len(files)} meetings, {words} words, {total} tasks found = {1000 * total / max(words, 1):.1f} per 1,000 words")
        random.seed(1)
        for it in random.sample(allitems, min(o["show"], len(allitems))):
            self.stdout.write(f"  - {it['title']}   <= {it['source_context'][:110]}")


