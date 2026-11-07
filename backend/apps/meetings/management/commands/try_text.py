"""Type or paste any meeting text and see the tasks the extractor finds. For live demos.

  python manage.py try_text "Ali will send the invoice by Friday. Sara, please prepare the slides by 15 November."
  python manage.py try_text --people "Ali,Sara,Hamza" "Hamza will fix the login bug tomorrow."
  python manage.py try_text            (no text: it asks you to type it)

--people  names of the meeting participants, comma separated (default: Ali, Sara, Hamza, Bilal, Amna).
--date    the meeting date, YYYY-MM-DD (default: today). 'Friday' or 'tomorrow' are worked out from it."""
from datetime import date

from django.core.management.base import BaseCommand

from apps.meetings.services import extraction


class Command(BaseCommand):
    help = "Run the task extractor on text you type."

    def add_arguments(self, p):
        p.add_argument("text", nargs="?", default="")
        p.add_argument("--people", default="Ali,Sara,Hamza,Bilal,Amna")
        p.add_argument("--date", default="")

    def handle(self, *a, **o):
        text = o["text"] or input("Type the meeting text: ")
        names = [n.strip() for n in o["people"].split(",") if n.strip()]
        people = [{"id": i, "name": n, "aliases": [n] + n.split()} for i, n in enumerate(names, 1)]
        base = date.fromisoformat(o["date"]) if o["date"] else date.today()
        items = extraction.extract_action_items(text, people, base)
        self.stdout.write(f"\nMeeting date: {base:%a %d %b %Y}   Participants: {', '.join(names)}\n")
        if not items:
            self.stdout.write("No tasks found.")
        for n, it in enumerate(items, 1):
            self.stdout.write(f"\nTask {n}: {it['title']}")
            self.stdout.write(f"  Owner:      {it['assignee'] or 'not assigned'}")
            self.stdout.write(f"  Deadline:   {it['deadline'] or 'none'}")
            self.stdout.write(f"  Confidence: {it['confidence']}")
            if it["uncertainty_note"]:
                self.stdout.write(f"  Check:      {it['uncertainty_note']}")
