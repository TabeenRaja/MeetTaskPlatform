"""Score the task extractor against a labelled test file. No Whisper, database or server needed.

  python manage.py eval_extraction                       # runs apps/meetings/extraction_tests/cases.json
  python manage.py eval_extraction --verbose             # also lists every task that was found
  python manage.py eval_extraction --file my_cases.json
  python manage.py eval_extraction --case 3              # one case only (numbers start at 1)

Each case in the file: {"name", "date", "people": ["Ali Khan", ...], "text", "expected": [...]}.
An expected task: {"keywords": ["invoice"], "owner": "Ali Khan" or null, "deadline": "2026-11-06" or null,
                   "optional": true}   (optional = either outcome is fine; "deadline" left out = not checked)
Add a case with "expected": [] to check that a text produces NO tasks.
A found task matches when its title contains ALL keywords. Any found task that matches nothing is a false alarm."""
import json
import os
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.meetings.services import extraction

DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "extraction_tests", "cases.json")


def _people(names):
    return [{"id": i + 1, "name": n, "aliases": [n] + n.split()} for i, n in enumerate(names)]


def _title(t):
    return (t.get("title") or "").lower()


def score_case(case):
    base = date.fromisoformat(case.get("date") or date.today().isoformat())
    found = extraction.extract_action_items(case["text"], _people(case.get("people", [])), base)
    used, rows = set(), []
    for exp in case.get("expected", []):
        kws = [k.lower() for k in exp["keywords"]]
        hit = next((i for i, f in enumerate(found) if i not in used and all(k in _title(f) for k in kws)), None)
        row = {"exp": exp, "found": None, "owner_ok": None, "deadline_ok": None}
        if hit is not None:
            used.add(hit)
            f = found[hit]
            row["found"] = f
            if "owner" in exp:
                row["owner_ok"] = (f.get("assignee") or None) == exp["owner"]
            if "deadline" in exp:
                row["deadline_ok"] = (str(f.get("deadline")) if f.get("deadline") else None) == exp["deadline"]
        rows.append(row)
    opt_hit = {i for r, i in ((r, next((j for j, f in enumerate(found) if r["found"] is f), None)) for r in rows) if i is not None}
    extras = [f for i, f in enumerate(found) if i not in used]
    return found, rows, extras


class Command(BaseCommand):
    help = "Score task extraction against a labelled test file."

    def add_arguments(self, p):
        p.add_argument("--file", default=DEFAULT)
        p.add_argument("--verbose", action="store_true")
        p.add_argument("--case", type=int)

    def handle(self, *a, **o):
        try:
            cases = json.load(open(o["file"], encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CommandError(f"Cannot read {o['file']}: {exc}")
        if o.get("case"):
            cases = [cases[o["case"] - 1]]
        T = dict(exp=0, hit=0, miss=0, owner=0, owner_ok=0, dl=0, dl_ok=0, extra=0, found=0)
        problems = []
        for n, case in enumerate(cases, 1):
            found, rows, extras = score_case(case)
            extras = [f for f in extras]
            req = [r for r in rows if not r["exp"].get("optional")]
            opt = [r for r in rows if r["exp"].get("optional")]
            # optional tasks that were found are fine; optional ones that were not found are fine too.
            T["exp"] += len(req)
            T["found"] += len(found)
            tag = case.get("name", f"case {n}")
            line = []
            for r in req:
                if r["found"] is None:
                    T["miss"] += 1
                    line.append(f"  MISSED   {r['exp']['keywords']} (owner {r['exp'].get('owner')}, due {r['exp'].get('deadline', '-')})")
                    continue
                T["hit"] += 1
                if r["owner_ok"] is not None:
                    T["owner"] += 1
                    T["owner_ok"] += bool(r["owner_ok"])
                    if not r["owner_ok"]:
                        line.append(f"  OWNER    {r['found']['title']!r}: got {r['found'].get('assignee')!r}, want {r['exp'].get('owner')!r}")
                if r["deadline_ok"] is not None:
                    T["dl"] += 1
                    T["dl_ok"] += bool(r["deadline_ok"])
                    if not r["deadline_ok"]:
                        line.append(f"  DEADLINE {r['found']['title']!r}: got {r['found'].get('deadline')!r}, want {r['exp'].get('deadline')!r}")
            for f in extras:
                T["extra"] += 1
                line.append(f"  FALSE    {f['title']!r} (owner {f.get('assignee')}, due {f.get('deadline')}) from: {f.get('source_context', '')[:90]!r}")
            if o["verbose"]:
                self.stdout.write(f"[{n}] {tag}: {len(found)} found")
                for f in found:
                    self.stdout.write(f"     - {f['title']} | {f.get('assignee') or '-'} | {f.get('deadline') or '-'} | {f.get('confidence')}")
            if line:
                problems.append((n, tag, line))
        for n, tag, line in problems:
            self.stdout.write(f"\n[{n}] {tag}")
            for l in line:
                self.stdout.write(l)
        def pct(a, b):
            return "n/a" if not b else f"{100 * a / b:.0f}%"
        prec = T["hit"] / (T["hit"] + T["extra"]) if (T["hit"] + T["extra"]) else 0
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(f"Cases: {len(cases)}   expected tasks: {T['exp']}   found: {T['found']}")
        self.stdout.write(f"Recall (expected tasks found):      {pct(T['hit'], T['exp'])}  ({T['hit']}/{T['exp']})")
        self.stdout.write(f"Precision (found tasks that are right): {pct(T['hit'], T['hit'] + T['extra'])}  ({T['extra']} false alarms)")
        self.stdout.write(f"Right owner:    {pct(T['owner_ok'], T['owner'])}  ({T['owner_ok']}/{T['owner']})")
        self.stdout.write(f"Right deadline: {pct(T['dl_ok'], T['dl'])}  ({T['dl_ok']}/{T['dl']})")
