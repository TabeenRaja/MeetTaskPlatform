"""MeetTask local task extraction v1. No LLM, no network, no meeting summary: action items only.

Input : the normalized transcript sentences, the meeting's participants and the meeting date.
Output: a list of action items shaped like ActionItemSchema (title, assignee, deadline, priority, ...).

How it works (everything is deterministic and explainable):
  1. spaCy parses every sentence (tokens, part of speech, dependency tree, named entities).
  2. A DependencyMatcher finds verbs that carry a commitment or request ("will send", "needs to review",
     "is going to fix", "can you update", "agreed to prepare"). A Matcher finds lexical cues
     (acknowledgements, "make sure", "action item", hedges, urgency, group subjects).
  3. The dependency tree gives WHO (the subject, the person addressed, the controlled subject of
     "ask Sara to ...") and WHAT (the verb phrase, without modals, dates and filler).
  4. Dates are found in the clause and resolved with our own weekday logic plus dateparser, always
     relative to the meeting date.
  5. Rules reject non-tasks: past tense, negation, questions, hypotheticals, inanimate or external subjects,
     stative verbs ("will be fine", "will see").
  6. A confidence level and a plain-language note explain every uncertain choice, so the manager can review.
"""
import logging
import re
import threading
from collections import deque
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from functools import lru_cache

logger = logging.getLogger(__name__)

VERSION = "1.0"
MODEL_NAME = "spacy-rules-v1"
MAX_SENTENCES = 4000
_LOCK = threading.RLock()

# ----------------------------------------------------------------------------------------------
# Vocabulary
# ----------------------------------------------------------------------------------------------
STRONG_MODALS = {"will", "shall", "must"}
MEDIUM_MODALS = {"should", "ought"}
WEAK_MODALS = {"can", "could", "may", "might"}
ALL_MODALS = STRONG_MODALS | MEDIUM_MODALS | WEAK_MODALS | {"would"}   # "would" only counts in "would you ...?"

# head verb that takes "to + verb": value = strength of the commitment it expresses
CONTROL = {
    "need": "STRONG", "have": "STRONG", "promise": "STRONG", "agree": "STRONG", "commit": "STRONG",
    "volunteer": "STRONG", "offer": "MEDIUM", "plan": "MEDIUM", "intend": "MEDIUM", "aim": "MEDIUM",
    "want": "WEAK", "try": "WEAK", "hope": "WEAK", "expect": "WEAK", "propose": "WEAK",
    "ask": "MEDIUM", "tell": "MEDIUM", "request": "MEDIUM", "remind": "MEDIUM", "require": "MEDIUM",
    "get": "MEDIUM", "let": "MEDIUM", "assign": "MEDIUM", "allow": "WEAK", "like": "WEAK", "prefer": "WEAK",
    "remember": "MEDIUM", "forget": "MEDIUM", "ensure": "MEDIUM", "responsible": "MEDIUM",
}
# these hand the work to someone else: the controlled verb belongs to the object ("ask Sara to review")
DELEGATION = {"ask", "tell", "request", "remind", "require", "get", "let", "assign", "allow", "want", "like", "need",
              "expect", "prefer", "have"}

# Verbs that never describe work somebody can be assigned.
STATIVE = {
    "be", "seem", "appear", "become", "remain", "exist", "happen", "occur", "depend", "matter", "mean", "cost",
    "see", "know", "think", "believe", "hope", "wish", "love", "hate", "understand", "realize", "realise", "feel",
    "wonder", "guess", "suppose", "imagine", "disagree", "say", "mention", "discuss", "talk", "speak", "wait",
    "sound", "come", "hear", "notice", "recall", "fail", "succeed", "worry", "last", "increase", "decrease",
    "agree", "recognize", "recognise", "like", "prefer", "want", "need", "expect", "plan", "try", "decide", "intend",
    "aim", "propose", "offer", "promise", "commit", "volunteer", "ask", "tell", "request", "remind", "require",
    "allow", "let", "care", "stay", "change", "go", "look", "work", "take", "keep", "get", "make", "do", "give",
    "have", "help", "deal", "put",
}
# Light verbs are real actions only with an object ("do the testing", "make a call") ...
LIGHT_WITH_OBJECT = {"do", "make", "give", "take", "get", "have", "keep", "put", "ask", "tell", "remind", "request",
                     "offer", "propose", "plan", "try", "change", "need", "want"}
# ... or with a particle ("work on", "look into", "go through", "deal with", "help with").
LIGHT_WITH_PARTICLE = {"work": {"on", "with"}, "look": {"into", "at", "over", "through", "after", "for"},
                       "go": {"through", "over", "ahead", "back"}, "deal": {"with"}, "help": {"with", "out"},
                       "take": {"care", "over"}, "keep": {"up"}, "get": {"back", "ready", "started", "going"},
                       "come": {"up"}, "follow": {"up"}, "talk": {"to", "with"}, "speak": {"to", "with"}}
VAGUE_OBJECTS = {"it", "this", "that", "them", "these", "those", "something", "things", "stuff", "one"}
ROLE_WORDS = {"manager", "lead", "designer", "developer", "tester", "engineer", "admin", "administrator",
              "accountant", "analyst", "owner", "director", "supervisor", "coordinator", "officer"}

GROUP_WORDS = {"we", "everyone", "everybody", "all", "team", "someone", "somebody", "anyone", "anybody", "nobody",
               "us", "folks", "guys"}
INTERNAL_GROUPS = {"team", "qa", "dev", "devs", "developers", "engineering", "design", "designers", "backend",
                   "frontend", "devops", "finance", "hr", "management", "marketing", "sales", "support", "ops",
                   "department", "testing", "testers"}
EXTERNAL_WORDS = {"client", "customer", "vendor", "supplier", "user", "users", "company", "partner", "they",
                  "it", "that", "this", "which", "there", "boss", "contractor", "agency", "customers", "clients"}

ACK_RX = re.compile(r"^\W*(?:yes|yeah|yep|yup|sure|okay|ok|alright|all right|absolutely|of course|certainly|"
                    r"no problem|sounds good|will do|got it|understood|noted|right|fine|definitely|cool)\b", re.I)
COMMIT_AFTER_ACK_RX = re.compile(r"\b(?:i(?:'ll| will| can| shall| am going to| 'm going to)|will do|let me|"
                                 r"i(?:'ve| have) got it|i(?:'m| am) on it|on it|consider it done|leave it to me)\b", re.I)
URGENT_RX = re.compile(r"\b(?:urgent(?:ly)?|asap|as soon as possible|immediately|right away|right now|critical(?:ly)?|"
                       r"top priority|high priority|first thing|highest priority|blocker|blocking|without delay|"
                       r"at once|priority one|p0|p1)\b", re.I)
LOW_PRIO_RX = re.compile(r"\b(?:no rush|low priority|when you (?:can|get a chance|have time|are free|have a moment)|"
                         r"whenever (?:you can|possible|you(?:'re| are) free)|eventually|if time permits|nice to have|"
                         r"not urgent|at your convenience|sometime|some time|down the line)\b", re.I)
HEDGE_RX = re.compile(r"\b(?:maybe|perhaps|probably|possibly|i think|i guess|i suppose|might want to|not sure|"
                      r"we could|could be|it would be nice|would be good|at some point|some day|someday)\b", re.I)
COND_START_RX = re.compile(r"^\W*(?:if|unless|in case|provided|assuming|suppose|what if|whether|once|as long as)\b", re.I)
FILLER_RX = re.compile(r"\b(?:um+|uh+|erm+|er|hmm+|ah+|uhm+|you know|i mean|sort of|kind of)\b[,.]?\s*", re.I)
LEADING_DISCOURSE_RX = re.compile(r"^\W*(?:(?:and|so|but|also|then|well|okay|ok|right|alright|now|anyway|yeah|yes|sure|"
                                  r"first(?:ly)?|next|finally|lastly|plus|oh)\b[,\s]*)+", re.I)
MARKER_RX = re.compile(r"\b(?:action items?|action points?|to-?do|next steps?|follow[- ]ups?|takeaways?)\b[:\-]?\s*", re.I)

URGENCY_WORDS = {"urgent", "urgently", "asap", "immediately", "critical", "critically", "priority", "blocker", "blocking"}
ADVERB_DROP = {"definitely", "probably", "really", "just", "also", "then", "first", "actually", "basically", "simply",
               "maybe", "perhaps", "certainly", "surely", "still", "already", "now", "later", "soon", "quickly",
               "urgently", "immediately", "asap", "please", "kindly", "sure", "okay", "ok", "yeah", "yes", "so", "well",
               "totally", "absolutely", "gladly", "happily", "personally", "ourselves", "myself", "yourself"}

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
WEEKDAY_RX = r"(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)(?:day|sday|nesday|rsday|urday)?"
MONTH_RX = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
            r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
NUM_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
             "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30}

DEADLINE_RX = re.compile(
    r"(?P<lead>\b(?:by|before|until|till|on|due|for|this|next|coming|within|in|no later than|latest by|"
    r"first thing|at the latest)\b\s+)?"
    r"(?P<core>(?<![A-Za-z0-9])(?:"
    r"(?:the\s+)?end of (?:the\s+)?(?:(?:this|next|the)\s+)?(?:day|week|month|year|today|business day)"
    r"|\bcob\b|\beod\b|\beow\b|\bclose of business\b|\bend of day\b"
    r"|(?:the\s+)?day after tomorrow|tomorrow(?:\s+(?:morning|afternoon|evening|night))?|today|tonight"
    r"|(?:(?:this|next|coming)\s+)?" + WEEKDAY_RX + r"(?:\s+(?:morning|afternoon|evening|night))?"
    r"|(?:(?:this|next|coming)\s+(?:week|month|quarter|year))|(?:the\s+)?(?:following|coming)\s+(?:week|month)"
    r"|(?:the\s+)?\d{1,2}(?:st|nd|rd|th)(?:\s+of)?(?:\s+(?:this|next)\s+month|\s+" + MONTH_RX + r")?"
    r"|" + MONTH_RX + r"\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?"
    r"|\d{1,2}\s+" + MONTH_RX + r"(?:,?\s+\d{4})?"
    r"|\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?"
    r"|\d{4}-\d{2}-\d{2}"
    r"|(?:(?:a|an|one|two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen|twenty|thirty|\d+)\s+"
    r"(?:business\s+|working\s+)?(?:day|days|week|weeks|month|months|hour|hours))"
    r"))\b", re.I)


# ----------------------------------------------------------------------------------------------
# Dates: our own resolver for the phrases people actually say in meetings, dateparser for calendar dates
# ----------------------------------------------------------------------------------------------
def _end_of_week(base):
    return base + timedelta(days=(4 - base.weekday()) % 7)          # Friday


def _next_weekday(base, wd, *, strictly_after=True):
    ahead = (wd - base.weekday()) % 7
    if ahead == 0 and strictly_after:
        ahead = 7
    return base + timedelta(days=ahead)


def _num(word):
    word = word.lower()
    return NUM_WORDS.get(word) or (int(word) if word.isdigit() else None)


def resolve_date(lead, core, base):
    """Return (date, note) for one deadline phrase, or None when it is not a usable deadline.
    base is the meeting's local date. note explains an approximate reading (or '')."""
    lead = (lead or "").strip().lower()
    low = re.sub(r"\s+", " ", core.strip().lower())
    low = re.sub(r"^the ", "", low)

    # durations: "in three days" / "within 2 weeks" are deadlines, "for two days" is just how long it takes
    m = re.fullmatch(r"(\w+) (?:business |working )?(day|days|week|weeks|month|months|hour|hours)", low)
    if m and _num(m.group(1)) is not None:
        n = _num(m.group(1))
        if lead not in ("in", "within", "no later than", "at the latest"):
            return None
        unit = m.group(2)
        if unit.startswith("hour"):
            return base, ""
        days = n * (1 if unit.startswith("day") else 7 if unit.startswith("week") else 30)
        return base + timedelta(days=days), "" if unit.startswith("day") else f"'{n} {unit}' counted from the meeting date."
    if low in ("eod", "end of day", "end of the day", "end of today", "cob", "close of business",
               "end of business day"):
        return base, ""
    if low in ("today", "tonight"):
        return base, ""
    if low.startswith("tomorrow"):
        return base + timedelta(days=1), ""
    if low == "day after tomorrow":
        return base + timedelta(days=2), ""
    if low in ("eow", "end of week", "end of this week", "end of the week"):
        return _end_of_week(base), "'End of the week' read as Friday."
    if low == "end of next week":
        return _end_of_week(base) + timedelta(days=7), "'End of next week' read as Friday of next week."
    if low in ("end of month", "end of this month", "end of the month"):
        nxt = base.replace(day=28) + timedelta(days=4)
        return nxt - timedelta(days=nxt.day), ""
    if low == "end of next month":
        nxt = base.replace(day=28) + timedelta(days=4)
        nxt = (nxt - timedelta(days=nxt.day)) + timedelta(days=1)
        nxt2 = nxt.replace(day=28) + timedelta(days=4)
        return nxt2 - timedelta(days=nxt2.day), ""
    if re.fullmatch(r"end of (?:the |this )?year", low):
        return date(base.year, 12, 31), ""
    if low in ("this week",):
        return _end_of_week(base), "'This week' read as Friday."
    if low in ("next week", "following week", "coming week"):
        return _end_of_week(base) + timedelta(days=7), "'Next week' read as Friday of next week."
    if low in ("this month",):
        nxt = base.replace(day=28) + timedelta(days=4)
        return nxt - timedelta(days=nxt.day), "'This month' read as the last day of the month."
    if low in ("next month", "following month", "coming month"):
        nxt = base.replace(day=28) + timedelta(days=4)
        first = (nxt - timedelta(days=nxt.day)) + timedelta(days=1)
        nxt2 = first.replace(day=28) + timedelta(days=4)
        return nxt2 - timedelta(days=nxt2.day), "'Next month' read as the last day of next month."
    if re.fullmatch(r"(?:this|next|coming) (?:quarter|year)", low):
        return None
    wd = re.fullmatch(r"(?:(this|next|coming) )?(" + WEEKDAY_RX + r")(?: (?:morning|afternoon|evening|night))?", low)
    if wd:
        target = WEEKDAYS[wd.group(2)[:3]]
        which = wd.group(1)
        if which == "next":
            this_week = base - timedelta(days=base.weekday())
            result = this_week + timedelta(days=7 + target)
            return result, f"'Next {wd.group(2).title()}' read as {wd.group(2).title()} of next week."
        if which == "this":
            result = _next_weekday(base, target, strictly_after=False)
            return result, ""
        return _next_weekday(base, target), ""                   # "by Friday": the coming Friday
    om = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)(?: of)?(?: (this|next) month| (" + MONTH_RX + r"))?", low)
    if om:
        day = int(om.group(1))
        if not 1 <= day <= 31:
            return None
        if om.group(3):
            return _calendar(f"{day} {om.group(3)}", base)
        year, month = base.year, base.month
        if om.group(2) == "next":
            month += 1
        elif om.group(2) is None and day < base.day:
            month += 1                                           # "on the 5th" said on the 20th: next month
        if month > 12:
            year, month = year + 1, month - 12
        try:
            return date(year, month, day), ""
        except ValueError:
            return None
    return _calendar(low, base)


def _calendar(text, base):
    """Calendar dates ('October 30', '30 Oct', '30/10', '2026-10-30') through dateparser."""
    try:
        import dateparser
    except ImportError:                                           # pragma: no cover
        return None
    d = dateparser.parse(text, settings={"RELATIVE_BASE": datetime(base.year, base.month, base.day, 12),
                                         "PREFER_DATES_FROM": "future", "DATE_ORDER": "DMY",
                                         "RETURN_AS_TIMEZONE_AWARE": False, "STRICT_PARSING": False})
    if not d:
        return None
    result = d.date()
    return result, ""


def find_deadline(text, base):
    """Return (iso_date, phrase, note) for the first usable deadline in text, else (None, '', '')."""
    for m in DEADLINE_RX.finditer(text):
        core = m.group("core")
        if not core:
            continue
        got = resolve_date(m.group("lead"), core, base)
        if not got:
            continue
        d, note = got
        if d < base:
            return None, m.group(0).strip(), "The deadline phrase points to a date in the past, so it was ignored."
        if d > base + timedelta(days=366):
            return None, m.group(0).strip(), "The deadline phrase points more than a year ahead, so it was ignored."
        return d.isoformat(), m.group(0).strip(), note
    return None, "", ""


# ----------------------------------------------------------------------------------------------
# Participants and names
# ----------------------------------------------------------------------------------------------
def people_from_users(users):
    """users: objects with id, get_full_name(), username (Django users). Returns plain dicts."""
    people = []
    for u in users:
        full = (u.get_full_name() or "").strip()
        username = getattr(u, "username", "") or ""
        letters = re.sub(r"\d+", "", re.sub(r"[\W_]+", "", username))
        aliases = set()
        if full:
            aliases.add(full)
            aliases.update(p for p in full.split() if len(p) >= 2)
        if letters and len(letters) >= 3:
            aliases.add(letters)
        if username:
            aliases.add(username)
        people.append({"id": u.id, "name": full or username, "aliases": sorted(aliases, key=str.lower)})
    return people


class NameIndex:
    def __init__(self, people):
        self.people = people
        self.by_alias = {}
        for p in people:
            for a in p["aliases"]:
                for key in {self._k(a)} | ({self._k(x) for x in a.split()} if " " in a else set()):
                    if len(key) >= 2:
                        self.by_alias.setdefault(key, set()).add(p["id"])
        self.names = {p["id"]: p["name"] for p in people}

    @staticmethod
    def _k(s):
        return re.sub(r"[^a-z0-9]", "", s.lower())

    def exact(self, text):
        return self.by_alias.get(self._k(text), set())

    def fuzzy(self, text, threshold=0.86):
        key = self._k(text)
        if len(key) < 4:
            return set()
        scored = {}
        for alias, ids in self.by_alias.items():
            if len(alias) < 4 or abs(len(alias) - len(key)) > 2:
                continue
            r = SequenceMatcher(None, key, alias).ratio()
            if r >= threshold:
                for i in ids:
                    scored[i] = max(scored.get(i, 0), r)
        if not scored:
            return set()
        ranked = sorted(scored.items(), key=lambda kv: -kv[1])
        if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < 0.06:
            return set(i for i, _ in ranked[:2])                 # too close to call: ambiguous
        return {ranked[0][0]}


# ----------------------------------------------------------------------------------------------
# spaCy pipeline, matchers
# ----------------------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_nlp():
    import spacy
    try:
        nlp = spacy.load("en_core_web_sm")
    except OSError as exc:
        raise RuntimeError("English model missing. Run: python -m spacy download en_core_web_sm") from exc
    nlp.max_length = 2_000_000
    return nlp


@lru_cache(maxsize=1)
def _matchers():
    from spacy.matcher import DependencyMatcher, Matcher
    nlp = get_nlp()
    dm = DependencyMatcher(nlp.vocab)
    dm.add("MODAL", [[
        {"RIGHT_ID": "v", "RIGHT_ATTRS": {"POS": {"IN": ["VERB", "AUX"]}}},
        {"LEFT_ID": "v", "REL_OP": ">", "RIGHT_ID": "m",
         "RIGHT_ATTRS": {"DEP": "aux", "LEMMA": {"IN": sorted(ALL_MODALS)}}}]])
    dm.add("GOING_TO", [[
        {"RIGHT_ID": "h", "RIGHT_ATTRS": {"LEMMA": "go", "TAG": "VBG"}},
        {"LEFT_ID": "h", "REL_OP": ">", "RIGHT_ID": "v", "RIGHT_ATTRS": {"DEP": "xcomp", "POS": "VERB"}}]])
    dm.add("CONTROL", [[
        {"RIGHT_ID": "h", "RIGHT_ATTRS": {"LEMMA": {"IN": sorted(CONTROL)}, "POS": {"IN": ["VERB", "AUX", "ADJ"]}}},
        {"LEFT_ID": "h", "REL_OP": ">", "RIGHT_ID": "v",
         "RIGHT_ATTRS": {"DEP": {"IN": ["xcomp", "ccomp", "advcl"]}, "POS": "VERB"}}]])

    m = Matcher(nlp.vocab)
    m.add("ACK", [
        [{"LOWER": {"IN": ["sure", "okay", "ok", "yes", "yeah", "yep", "yup", "alright", "absolutely", "certainly",
                           "definitely", "understood", "noted", "cool"]}}],
        [{"LOWER": "will"}, {"LOWER": "do"}], [{"LOWER": "of"}, {"LOWER": "course"}],
        [{"LOWER": "no"}, {"LOWER": "problem"}], [{"LOWER": "got"}, {"LOWER": "it"}],
        [{"LOWER": "sounds"}, {"LOWER": "good"}]])
    m.add("MAKE_SURE", [
        [{"LEMMA": "make"}, {"LOWER": "sure"}], [{"LOWER": "be"}, {"LOWER": "sure"}],
        [{"LEMMA": "ensure"}], [{"LEMMA": "remember"}, {"LOWER": "to"}],
        [{"LOWER": {"IN": ["do", "does"]}}, {"LOWER": {"IN": ["n't", "not"]}}, {"LEMMA": "forget"}],
        [{"LEMMA": "see"}, {"LOWER": "to"}, {"LOWER": "it"}]])
    m.add("MARKER", [
        [{"LOWER": "action"}, {"LOWER": {"IN": ["item", "items", "point", "points"]}}],
        [{"LOWER": {"IN": ["todo", "to-do"]}}], [{"LOWER": "next"}, {"LOWER": {"IN": ["step", "steps"]}}],
        [{"LOWER": "takeaway"}], [{"LOWER": "follow"}, {"LOWER": "-", "OP": "?"}, {"LOWER": "up"}]])
    m.add("TAKE_ON", [[{"LOWER": {"IN": ["i", "we"]}}, {"LOWER": {"IN": ["'ll", "will"]}}, {"LOWER": "take"}],
                      [{"LOWER": "i"}, {"LOWER": "'m"}, {"LOWER": "on"}, {"LOWER": "it"}],
                      [{"LOWER": "leave"}, {"LOWER": "it"}, {"LOWER": "to"}, {"LOWER": "me"}]])
    return nlp, dm, m


# ----------------------------------------------------------------------------------------------
# Small helpers on spaCy tokens
# ----------------------------------------------------------------------------------------------
def _subtree_ids(tok, skip=()):
    out = set()
    stack = [tok]
    while stack:
        t = stack.pop()
        out.add(t.i)
        for c in t.children:
            if c.i not in skip:
                stack.append(c)
    return out


def _children(tok, *deps):
    return [c for c in tok.children if c.dep_ in deps]


def _first_alpha(span_text):
    for i, ch in enumerate(span_text):
        if ch.isalpha():
            return i
    return 0


def _has_object(v):
    return any(c.dep_ in ("dobj", "obj", "dative", "pobj", "attr", "oprd") or
               (c.dep_ == "prep" and any(g.dep_ in ("pobj", "pcomp") for g in c.children)) or c.dep_ == "ccomp"
               for c in v.children)


def _particles(v):
    return {c.lower_ for c in v.children if c.dep_ in ("prt", "prep", "advmod", "dobj", "obj")} | \
           {g.lower_ for c in v.children if c.dep_ == "dobj" for g in [c]}


def is_action_verb(v):
    """True when the verb can name work. Stative verbs never count; light verbs need an object or particle."""
    lem = v.lemma_.lower()
    if lem in LIGHT_WITH_PARTICLE and any(c.lower_ in LIGHT_WITH_PARTICLE[lem] and c.dep_ in ("prep", "prt", "dobj", "advmod")
                                          for c in v.children):
        return True
    if lem in LIGHT_WITH_PARTICLE and lem == "take":
        if any(c.dep_ == "dobj" and c.lemma_.lower() in {"care", "charge", "ownership", "lead", "responsibility",
                                                          "action", "note", "notes", "minutes", "look", "over"}
               for c in v.children):
            return True
    if lem in LIGHT_WITH_OBJECT and lem not in ("need", "want", "plan", "try", "offer", "propose", "change"):
        return any(c.dep_ in ("dobj", "obj") for c in v.children)
    if lem in STATIVE:
        return False
    return True


# ----------------------------------------------------------------------------------------------
# The extractor
# ----------------------------------------------------------------------------------------------
LEVELS = ["LOW", "MEDIUM", "HIGH"]


def _up(level, n=1):
    return LEVELS[max(0, min(2, LEVELS.index(level) + n))]


class _Cand:
    __slots__ = ("v", "kind", "strength", "ctrl", "parent", "mark")

    def __init__(self, v, kind, strength, ctrl=None, parent=None, mark=False):
        self.v, self.kind, self.strength, self.ctrl, self.parent, self.mark = v, kind, strength, ctrl, parent, mark


class _Ctx:
    def __init__(self, names, base):
        self.names, self.base = names, base
        self.items = []
        self.pending = None
        self.pending_ttl = 0
        self.recent_people = deque(maxlen=4)      # (sentence_no, ids) of people named as subject/addressee
        self.last_object = ("", -10)
        self.sentence_no = 0


class Extractor:
    def __init__(self, people, base):
        self.nlp, self.dm, self.matcher = _matchers()
        self.ctx = _Ctx(NameIndex(people), base)

    # ---------------------------------------------------------------- mentions
    def _mentions(self, doc):
        names = self.ctx.names
        out, used = [], set()

        def add(s, e, ids):
            if ids and not (set(range(s, e)) & used):
                out.append({"s": s, "e": e, "ids": set(ids), "text": doc[s:e].text})
                used.update(range(s, e))

        for ent in doc.ents:
            if ent.label_ == "PERSON":
                add(ent.start, ent.end, names.exact(ent.text) or names.fuzzy(ent.text))
        for tok in doc:
            if tok.i in used or tok.is_punct or tok.pos_ in ("AUX", "DET", "ADP", "PRON", "SCONJ", "CCONJ", "NUM"):
                continue
            if not tok.text[:1].isupper() and tok.pos_ != "PROPN":
                continue
            if tok.i == 0 and tok.pos_ not in ("PROPN", "X") and tok.ent_type_ != "PERSON":
                if not names.exact(tok.text):
                    continue
            ids = names.exact(tok.text)
            if not ids and (tok.pos_ == "PROPN" or tok.ent_type_ == "PERSON"):
                ids = names.fuzzy(tok.text)
            add(tok.i, tok.i + 1, ids)
        out.sort(key=lambda m: m["s"])
        return out

    # ---------------------------------------------------------------- candidates
    def _candidates(self, doc, flags, mentions, is_question):
        cands = {}
        for match_id, toks in self.dm(doc):
            name = self.nlp.vocab.strings[match_id]
            if name == "MODAL":
                v, m = doc[toks[0]], doc[toks[1]]
                lem = m.lemma_.lower()
                if lem == "would":
                    if not (is_question and any(c.lower_ == "you" for c in v.children)):
                        continue
                    strength = "MEDIUM"
                else:
                    strength = "STRONG" if lem in STRONG_MODALS else "MEDIUM" if lem in MEDIUM_MODALS else "WEAK"
                kind = "modal"
                if is_question and lem in ("can", "could", "will", "would") and any(c.lower_ == "you" for c in v.children):
                    kind, strength = "request", "MEDIUM"
                cands[v.i] = _Cand(v, kind, strength)
            elif name == "GOING_TO":
                h, v = doc[toks[0]], doc[toks[1]]
                if v.dep_ == "xcomp" and any(c.dep_ == "aux" and c.lower_ == "to" for c in v.children):
                    cands.setdefault(v.i, _Cand(v, "modal", "STRONG", ctrl=h))
            elif name == "CONTROL":
                h, v = doc[toks[0]], doc[toks[1]]
                passive = v.tag_ == "VBN" and any(c.dep_ == "auxpass" for c in v.children)
                if v.dep_ not in ("xcomp", "ccomp") or (v.tag_ not in ("VB", "VBP") and not passive):
                    continue
                if not any(c.dep_ == "aux" and c.lower_ == "to" for c in v.children):
                    continue
                lem = h.lemma_.lower()
                if h.tag_ in ("VBD", "VBN") and lem not in ("agree", "promise", "commit", "volunteer", "offer", "ask",
                                                           "tell", "request", "remind", "require"):
                    continue                                   # "had to", "wanted to", "needed to": past, not a task
                if h.dep_ == "aux" or lem == "responsible":
                    continue
                prev = cands.get(v.i)
                strength = CONTROL[lem]
                if prev is None or LEVELS.index(strength) > LEVELS.index(prev.strength if prev.strength in LEVELS else "LOW"):
                    cands[v.i] = _Cand(v, "control", strength, ctrl=h)
        # "will need to send": the modal on the head makes the controlled verb a firm commitment
        for c in list(cands.values()):
            if c.ctrl is not None and c.ctrl.i in cands and cands[c.ctrl.i].strength == "STRONG":
                c.strength = "STRONG"
        for c in list(cands.values()):
            if c.v.lemma_.lower() in CONTROL and c.v.i in cands and any(
                    o.ctrl is not None and o.ctrl.i == c.v.i for o in cands.values()):
                cands.pop(c.v.i, None)                         # the head ("need") is the cue, not the task
        # "make sure Ali sends it", "remember to send"
        for lab, s, e in flags["spans"]:
            if lab == "MAKE_SURE":
                scan = list(doc[s:e]) + [t.head for t in doc[s:e]]
                for t in scan:
                    for ch in t.children:
                        if ch.dep_ in ("ccomp", "xcomp") and ch.pos_ == "VERB" and ch.i not in range(s, e):
                            cands[ch.i] = _Cand(ch, "make_sure", "MEDIUM", ctrl=t, mark=True)
                    if t.head.pos_ == "VERB" and t.dep_ in ("ccomp", "xcomp") and t.head.i not in range(s, e):
                        cands[t.head.i] = _Cand(t.head, "make_sure", "MEDIUM", ctrl=t, mark=True)
                for t in list(cands.values()):
                    if t.kind == "imperative" and any(t.v.i in range(s, e) for _ in [0]):
                        cands.pop(t.v.i, None)
        # "Ali to send the report by Friday" (action-list style)
        for m in mentions:
            e = m["e"]
            if e + 1 < len(doc) and doc[e].lower_ == "to" and doc[e + 1].tag_ == "VB" and doc[e + 1].i not in cands:
                if not any(t.dep_ in ("aux",) and t.pos_ == "AUX" for t in doc[:m["s"]]):
                    cands[doc[e + 1].i] = _Cand(doc[e + 1], "list", "MEDIUM")
        # imperatives: "Ali, please prepare the report", "Send the invoice by Friday."
        if not is_question:
            has_vocative = any(self._is_vocative(doc, m) for m in mentions)
            for sent in doc.sents:
                roots = [sent.root] + [c for c in sent.root.conjuncts if c.pos_ == "VERB"]
                for r in roots:
                    voc_idx = {i for m in mentions if self._is_vocative(doc, m) for i in range(m["s"], m["e"])}
                    if (r.pos_ == "VERB" and r.tag_ == "VB" and r.i not in cands
                            and not any(c.dep_ in ("nsubj", "nsubjpass", "expl") and c.i not in voc_idx for c in r.children)
                            and not any(c.dep_ == "aux" for c in r.children)):
                        polite = any(c.lower_ in ("please", "kindly") for c in r.children) or \
                            any(t.lower_ == "please" for t in sent)
                        urgent = bool(URGENT_RX.search(sent.text))
                        dated = bool(DEADLINE_RX.search(sent.text))
                        if has_vocative or polite or flags["marker"] or (dated and r.i == sent.root.i) or \
                                (urgent and r.i == sent.root.i):
                            cands[r.i] = _Cand(r, "imperative", "MEDIUM")
        # conjoined verbs inherit the cue: "will prepare the report and send it to Sara"
        for c in list(cands.values()):
            for cj in c.v.conjuncts:
                if cj.i == c.v.i or cj.i in cands or cj.pos_ != "VERB" or cj.i < c.v.i:
                    continue
                if any(x.dep_ in ("nsubj", "nsubjpass") for x in cj.children) or cj.tag_ not in ("VB", "VBP"):
                    continue
                if is_action_verb(cj) and (_has_object(cj) or any(x.dep_ in ("prt", "prep") or (x.dep_ == "advmod" and x.lower_ in ("back", "up", "out")) for x in cj.children)) and _has_object(c.v):
                    cands[cj.i] = _Cand(cj, c.kind, c.strength, ctrl=c.ctrl, parent=c)
        for lab, s, e in flags["spans"]:
            if lab == "MAKE_SURE":
                for i in range(s, e):
                    cands.pop(i, None)
        # "let's schedule a review", "responsible for testing the module"
        for t in doc:
            if t.lower_ == "let" and t.i + 1 < len(doc) and doc[t.i + 1].lower_ in ("'s", "us"):
                for ch in t.children:
                    if ch.dep_ in ("ccomp", "xcomp", "advcl") and ch.tag_ == "VB" and ch.lemma_.lower() not in (
                            "start", "begin", "get", "move", "talk", "discuss", "go", "see", "look", "continue", "wrap",
                            "kick", "hear", "say", "check", "recap", "proceed", "jump", "dive", "cover"):
                        cands[ch.i] = _Cand(ch, "list", "MEDIUM")
            if t.lemma_.lower() in ("responsible", "charge", "owner") and t.i + 1 < len(doc):
                for pr in t.children:
                    if pr.dep_ == "prep" and pr.lower_ in ("for", "of"):
                        for g in pr.children:
                            if g.dep_ == "pcomp" and g.pos_ == "VERB":
                                head = t.head if t.dep_ in ("acomp", "attr") else t
                                cands[g.i] = _Cand(g, "control", "STRONG", ctrl=head)
                if t.head.i == t.i - 1 or True:
                    pass
        if flags["marker"]:
            for c in cands.values():
                if c.strength != "STRONG":
                    c.strength = "STRONG"
        return cands

    @staticmethod
    def _is_vocative(doc, m):
        s, e = m["s"], m["e"]
        if s == 0 or (s <= 1 and doc[0].is_punct):
            return e < len(doc) and doc[e].text in (",", ":", "-", "—")
        if e < len(doc) and doc[e].text == "," and s > 0 and doc[s - 1].lower_ in ("hi", "hey", "okay", "ok", "so", "and",
                                                                                   "alright", "right", "well", "now", "also"):
            return True
        if s > 0 and doc[s - 1].text == "," and (e >= len(doc) or doc[e].is_punct):
            return True                                         # "Can you send it, Ali?"
        return False

    # ---------------------------------------------------------------- subjects
    def _subject_tokens(self, v, cand):
        """Tokens naming who does the action. Handles ctrl verbs ('ask Sara to ...'), conj, imperatives."""
        own = [c for c in v.children if c.dep_ in ("nsubj", "nsubjpass")]
        if own:
            return self._with_conj(own)
        ctrl = cand.ctrl
        if ctrl is not None:
            if ctrl.lemma_.lower() in DELEGATION:
                objs = [c for c in ctrl.children if c.dep_ in ("dobj", "obj", "dative", "iobj")]
                if objs:
                    return self._with_conj(objs)
            subs = [c for c in ctrl.children if c.dep_ in ("nsubj", "nsubjpass")]
            if subs:
                return self._with_conj(subs)
            if ctrl.dep_ in ("conj", "xcomp", "ccomp") and ctrl.head is not ctrl:
                subs = [c for c in ctrl.head.children if c.dep_ in ("nsubj", "nsubjpass")]
                if subs:
                    return self._with_conj(subs)
        if cand.parent is not None:
            return self._subject_tokens(cand.parent.v, cand.parent)
        if v.dep_ in ("conj", "xcomp"):
            subs = [c for c in v.head.children if c.dep_ in ("nsubj", "nsubjpass")]
            if subs:
                return self._with_conj(subs)
        return []

    @staticmethod
    def _with_conj(toks):
        out = []
        for t in toks:
            out.append(t)
            out.extend(c for c in t.conjuncts if c.i != t.i)
        return out

    def _vocative_ids(self, doc, mentions):
        for m in mentions:
            if self._is_vocative(doc, m):
                return set(m["ids"])
        return set()

    # ---------------------------------------------------------------- one sentence
    def feed(self, text):
        ctx = self.ctx
        ctx.sentence_no += 1
        raw = text
        text = self._clean(text)
        if len(text.split()) < 2:
            return
        doc = self.nlp(text)
        flags = self._flags(doc)
        mentions = self._mentions(doc)
        is_question = text.rstrip().endswith("?")
        sent_people = [m["ids"] for m in mentions]

        if ctx.pending_ttl > 0:
            ctx.pending_ttl -= 1
            if ctx.pending_ttl == 0:
                ctx.pending = None

        self._dl = self._deadlines(doc)
        cands = self._candidates(doc, flags, mentions, is_question)
        new_items = []
        hint = set(ctx.pending["_meta"]["addressee"]) if ctx.pending and ctx.pending["_meta"].get("addressee") else set()
        if not hint:
            no, ids = getattr(ctx, "addressed", (-10, set()))
            if ctx.sentence_no - no <= 2 and len(ids) == 1:
                hint = set(ids)
        for cand in sorted(cands.values(), key=lambda c: c.v.i):
            new_items.extend(self._build(doc, text, raw, cand, cands, flags, mentions, is_question, hint))

        # acknowledgement of a request: "Sure, I will do it by Friday."
        if ctx.pending is not None and not is_question:
            handled = False
            for it in list(new_items):
                if it["_meta"]["subject_kind"] in ("speaker", "none") and it["_meta"]["vague"] \
                        and it["_meta"]["kind"] in ("modal", "control"):
                    self._confirm(ctx.pending, it, raw)
                    new_items.remove(it)
                    handled = True
            if not handled and not new_items:
                n_words = len([t for t in doc if not t.is_punct])
                if flags["ack"] and n_words <= 14 and (n_words <= 3 or COMMIT_AFTER_ACK_RX.search(text)):
                    self._confirm(ctx.pending, None, raw, doc=doc, text=text)
                    handled = True
                elif not cands and n_words <= 7:
                    dl, phrase, note = find_deadline(text, ctx.base)
                    if dl and not ctx.pending["deadline"]:
                        ctx.pending["deadline"] = dl
                        ctx.pending["source_context"] = (ctx.pending["source_context"] + " " + raw.strip())[:400]
            if handled:
                ctx.pending = None
                ctx.pending_ttl = 0

        kept = []
        for it in new_items:
            unresolved = it["_meta"]["vague"] and "taken to mean" not in it["uncertainty_note"] and it["_meta"]["kind"] != "request"
            if unresolved:
                prev = ctx.items[-1] if ctx.items else None
                if prev is not None and it["deadline"] and not prev["deadline"] and ctx.sentence_no - prev["_meta"]["sent"] <= 2:
                    prev["deadline"] = it["deadline"]
                continue
            kept.append(it)
        new_items = kept
        for it in new_items:
            ctx.items.append(it)
            if it["_meta"]["kind"] in ("request", "imperative") and it["_meta"]["addressee"]:
                ctx.pending, ctx.pending_ttl = it, 2
            elif it["_meta"]["kind"] in ("request",):
                ctx.pending, ctx.pending_ttl = it, 2

        voc = self._vocative_ids(doc, mentions)
        if voc:
            ctx.addressed = (ctx.sentence_no, voc)
        # context for the next sentences
        for ids in sent_people:
            ctx.recent_people.append((ctx.sentence_no, ids))
        self._remember_object(doc, mentions)

    # ---------------------------------------------------------------- text helpers
    @staticmethod
    def _clean(text):
        t = FILLER_RX.sub("", text or "")
        t = re.sub(r"\b((?:\w+\s+){1,2}?)\1+", r"\1", t, flags=re.I) if False else t
        t = re.sub(r"\b(\w+)(?:\s+\1\b)+", r"\1", t, flags=re.I)                  # "I I will" -> "I will"
        t = re.sub(r"\b(\w+\s+\w+)(?:\s+\1\b)+", r"\1", t, flags=re.I)            # "I will I will" -> "I will"
        t = MARKER_RX.sub("", t) if False else t
        return re.sub(r"\s+", " ", t).strip()

    def _flags(self, doc):
        spans, labels = [], set()
        for mid, s, e in self.matcher(doc):
            lab = self.nlp.vocab.strings[mid]
            spans.append((lab, s, e))
            labels.add(lab)
        ack = any(lab == "ACK" and s <= 1 for lab, s, e in spans)
        toks = [t for t in doc if not t.is_punct]
        ack_only = ack and len(toks) <= 3
        return {"spans": spans, "ack": ack, "ack_only": ack_only, "marker": "MARKER" in labels,
                "make_sure": "MAKE_SURE" in labels, "take_on": "TAKE_ON" in labels}

    def _remember_object(self, doc, mentions):
        mention_idx = {i for m in mentions for i in range(m["s"], m["e"])}
        best = None
        for t in doc:
            if t.dep_ in ("dobj", "obj", "nsubjpass") and t.pos_ == "NOUN" and t.i not in mention_idx:
                best = doc[t.left_edge.i:t.right_edge.i + 1]
                if t.head.pos_ == "VERB":
                    pass
        if best is None:
            chunks = [c for c in doc.noun_chunks if c.root.pos_ == "NOUN" and c.root.i not in mention_idx
                      and not DEADLINE_RX.fullmatch(c.text.strip())]
            if chunks:
                best = chunks[-1]
        if best is not None:
            txt = re.sub(r"\s+", " ", best.text).strip(" ,.;:")
            if txt and DEADLINE_RX.fullmatch(txt.lower()) is None and txt.lower() not in ("meeting", "time", "week"):
                self.ctx.last_object = (txt, self.ctx.sentence_no)

    def _recent_single_person(self):
        ctx = self.ctx
        for no, ids in reversed(ctx.recent_people):
            if ctx.sentence_no - no <= 2 and len(ids) == 1:
                return set(ids)
        return set()

    # ---------------------------------------------------------------- subject classification
    _KIND_ORDER = ["speaker", "addressee", "pronoun3", "group", "role", "unmatched", "outsider", "inanimate"]

    def _classify_subject(self, toks, doc, mentions):
        """-> (kind, [id sets]). kind: person | speaker | addressee | pronoun3 | group | role | unmatched |
        outsider | inanimate | negated | none"""
        if not toks:
            return "none", []
        by_tok = {i: m for m in mentions for i in range(m["s"], m["e"])}
        sets, kinds = [], []
        for t in toks:
            if any(s.lower_ in ("no", "nobody", "never", "none", "neither") for s in t.subtree):
                return "negated", []
            m = by_tok.get(t.i)
            low, lem = t.lower_, t.lemma_.lower()
            if m is not None:
                sets.append(set(m["ids"]))
            elif low in ("i", "me", "myself"):
                kinds.append("speaker")
            elif low in ("you", "yourself"):
                kinds.append("addressee")
            elif low in ("he", "she"):
                kinds.append("pronoun3")
            elif low in GROUP_WORDS or low == "'s" or lem in INTERNAL_GROUPS:
                kinds.append("group")
            elif lem in ROLE_WORDS:
                kinds.append("role")
            elif t.ent_type_ == "PERSON":
                kinds.append("unmatched")
            elif low in EXTERNAL_WORDS or lem in EXTERNAL_WORDS:
                kinds.append("outsider")
            else:
                kinds.append("inanimate")
        if sets:
            return "person", sets
        for k in self._KIND_ORDER:
            if k in kinds:
                return k, []
        return "none", []

    # ---------------------------------------------------------------- deadlines
    def _deadlines(self, doc):
        out = []
        for m in DEADLINE_RX.finditer(doc.text):
            core = m.group("core")
            got = resolve_date(m.group("lead"), core, self.ctx.base) if core else None
            if not got:
                continue
            d, note = got
            s, e = m.start(), m.end()
            toks = {t.i for t in doc if t.idx < e and t.idx + len(t) > s}
            if not toks:
                continue
            if d < self.ctx.base:
                out.append({"toks": toks, "date": None, "note": "The deadline phrase points to a past date, so it was ignored.",
                            "phrase": m.group(0).strip(), "drop": False})
            elif d > self.ctx.base + timedelta(days=366):
                out.append({"toks": toks, "date": None, "note": "The deadline is more than a year away, so it was ignored.",
                            "phrase": m.group(0).strip(), "drop": False})
            else:
                out.append({"toks": toks, "date": d, "note": note, "phrase": m.group(0).strip(), "drop": True})
        return out

    def _region(self, v, cand, cands):
        skip = {c.v.i for c in cands.values() if c.v.i != v.i}

        def sub(tok):
            out, stack = set(), [tok]
            while stack:
                t = stack.pop()
                out.add(t.i)
                stack.extend(ch for ch in t.children if ch.i not in skip)
            return out

        reg = sub(v)
        if cand.ctrl is not None:
            reg |= sub(cand.ctrl)
        return reg

    # ---------------------------------------------------------------- title
    COND_MARKS = {"if", "unless", "whether", "provided", "assuming", "suppose", "lest"}
    REASON_MARKS = {"because", "since", "so", "as", "cause", "to"}

    def _title_parts(self, doc, v, drop, patient_toks):
        """Build (title, description) from the verb's own subtree."""
        skip = set(drop)
        reasons = []
        for c in v.children:
            if c.dep_ in ("nsubj", "nsubjpass", "expl", "aux", "auxpass", "neg", "punct", "cc", "conj", "intj", "csubj", "agent"):
                skip |= _subtree_ids(c) if c.dep_ in ("nsubj", "nsubjpass", "expl", "conj", "csubj", "agent") else {c.i}
            elif c.dep_ == "advcl":
                marks = {m.lower_ for m in c.children if m.dep_ == "mark"}
                if marks & {"because", "since", "so", "cause"} or any(
                        m.lower_ == "so" for m in doc[c.left_edge.i:c.i + 1]):
                    reasons.append(doc[c.left_edge.i:c.right_edge.i + 1].text)
                skip |= _subtree_ids(c)
            elif c.dep_ == "advmod" and (c.lower_ in ADVERB_DROP or c.lower_ in URGENCY_WORDS):
                skip.add(c.i)
        toks = [t for t in doc[v.i:v.right_edge.i + 1] if t.i not in skip and t.i in _subtree_ids(v)]
        toks = [t for t in toks if not (t.lower_ in ADVERB_DROP and t.dep_ == "advmod") and t.lower_ not in ("please", "kindly")]
        if not toks or toks[0].i != v.i:
            return "", ""
        words = []
        prev = None
        for t in toks:
            word = t.text
            if t.i == v.i and v.tag_ != "VB":
                word = v.lemma_
            if t.i == v.i and patient_toks:
                words.append(word)
                words.append(re.sub(r"^(?:the|a|an)\s+", lambda mm: mm.group(0).lower(), patient_toks.strip()))
                prev = t
                continue
            if prev is not None and t.i == prev.i + 1 and not prev.whitespace_ and not words[-1].endswith(" "):
                words[-1] += word
            else:
                words.append(word)
            prev = t
        title = " ".join(words)
        title = re.sub(r"\s+([,.;:!?%)])", r"\1", title)
        title = re.sub(r"\s+('s|n't)\b", r"\1", title)
        title = re.sub(r"[\s,;:\-]+$", "", title)
        # dangling function words left behind after a deadline was cut out
        title = re.sub(r"(?:\s+(?:by|on|before|until|till|for|in|at|to|and|or|the|a|an|this|next|of))+$", "", title, flags=re.I)
        title = title.strip(" .,")
        if "," in title and len(title.split()) > 14:
            title = title.split(",")[0]
        words = title.split()
        if len(words) > 22:
            title = " ".join(words[:22])
        title = title[:1].upper() + title[1:] if title else title
        reason = (reasons[0].strip(" ,.") if reasons else "")
        return title, (reason[:1].upper() + reason[1:] if reason else "")

    # ---------------------------------------------------------------- build items
    def _build(self, doc, text, raw, cand, cands, flags, mentions, is_question, hint):
        ctx = self.ctx
        v = cand.v
        if not is_action_verb(v):
            return []
        for h in [v] + ([cand.ctrl] if cand.ctrl is not None and cand.ctrl.lemma_.lower() != "forget" else []):
            if any(c.dep_ == "neg" for c in h.children):
                return []
        passive = any(c.dep_ == "auxpass" for c in v.children) or (v.tag_ == "VBN" and cand.kind != "imperative"
                                                                    and not any(c.lower_ in ("have", "has", "had") for c in v.children))
        if v.tag_ == "VBD" or (v.tag_ == "VBN" and not passive):
            return []
        if any(c.dep_ == "aux" and c.lower_ in ("have", "had", "'ve") for c in v.children):
            return []                                           # "should have sent": past
        # inside an if-clause
        a = v
        while a.head.i != a.i:
            if a.dep_ == "advcl" and any(m.dep_ == "mark" and m.lower_ in self.COND_MARKS for m in a.children):
                return []
            a = a.head
        cond_main = any(t.dep_ == "mark" and t.lower_ in self.COND_MARKS for t in doc) or bool(COND_START_RX.match(text))
        # past-time adverbials ("yesterday", "last week") mean this is a report, not a task
        if re.search(r"\b(?:yesterday|last (?:week|month|year|night|time)|earlier today|ago)\b", text, re.I) and cand.kind != "imperative":
            return []

        kind = cand.kind
        strength = cand.strength
        notes = []
        if strength == "WEAK" and HEDGE_RX.search(text) and kind != "request":
            return []
        if re.match(r"(?i)^\W*(?:we|someone)\s+(?:could|can|may|might)\b", text) and kind == "modal":
            return []                                             # an option being floated, not a task

        # ---- subject
        subj_toks = [] if passive else self._subject_tokens(v, cand)
        patient = ""
        if passive:
            ps = [c for c in v.children if c.dep_ == "nsubjpass"]
            if not ps and cand.ctrl is not None:
                ps = [c for c in cand.ctrl.children if c.dep_ in ("nsubj", "nsubjpass")]
            if ps and any(x.lower_ in ("no", "nobody", "nothing", "never", "none") for x in ps[0].subtree):
                return []
            if ps:
                p = ps[0]
                patient = doc[p.left_edge.i:p.right_edge.i + 1].text
                if p.lower_ in VAGUE_OBJECTS or p.lower_ in ("who", "which", "that"):
                    patient = ""
            agent = [g for c in v.children if c.dep_ == "agent" for g in c.children if g.dep_ == "pobj"]
            subj_toks = agent
        skind, sets = self._classify_subject(subj_toks, doc, mentions)
        if passive and not agent_exists(v):
            skind, sets = "none", []
        addressee = set()
        vocative = self._vocative_ids(doc, mentions)

        if is_question:
            if kind != "request":
                if kind == "modal" and skind == "person":
                    kind = "request"
                else:
                    return []
            if skind == "inanimate" or skind == "outsider" or skind == "group" or skind == "speaker":
                return []
        if skind in ("negated", "outsider", "inanimate"):
            return []
        if skind == "group" and (HEDGE_RX.search(text) or v.lemma_.lower() in ("meet", "gather", "reconvene", "catch")):
            return []
        if skind == "none" and vocative and kind in ("make_sure", "control") and not passive:
            skind, sets = "person", [set(vocative)]
        if kind == "list" and skind == "none":
            for m in mentions:
                if m["e"] < len(doc) and doc[m["e"]].lower_ == "to" and m["e"] + 1 == v.i:
                    skind, sets = "person", [set(m["ids"])]
            if skind == "none":
                skind = "group"
        elif kind == "imperative" or (skind == "none" and kind == "list"):
            skind = "person" if vocative else "none"
            sets = [set(vocative)] if vocative else []
        if skind == "none" and not passive and kind in ("modal", "control", "make_sure") and cand.ctrl is None and v.tag_ == "VB" \
                and not any(c.dep_ == "aux" for c in v.children):
            pass

        assignees = []            # list of (id or None, name or None)
        owner_note = ""
        if skind == "person":
            for ids in sets:
                if len(ids) == 1:
                    i = next(iter(ids))
                    assignees.append((i, ctx.names.names[i]))
                else:
                    assignees.append((None, None))
                    owner_note = "The name matches more than one participant, so please pick the right one."
        elif skind == "addressee":
            ids = vocative or self._recent_single_person()
            if len(ids) == 1:
                i = next(iter(ids))
                assignees.append((i, ctx.names.names[i]))
                addressee = {i}
                if not vocative:
                    owner_note = "The person was not named; taken from who was being talked to."
            else:
                assignees.append((None, None))
                owner_note = "Addressed to 'you' but the person is not named."
        elif skind == "speaker":
            if len(hint) == 1:
                i = next(iter(hint))
                assignees.append((i, ctx.names.names[i]))
                owner_note = "Speaker is not identified; taken from the person who was just spoken to."
            else:
                assignees.append((None, None))
                owner_note = "The speaker is not identified, so the owner is unknown."
        elif skind == "pronoun3":
            ids = self._recent_single_person()
            if len(ids) == 1:
                i = next(iter(ids))
                assignees.append((i, ctx.names.names[i]))
                owner_note = "'he/she' was matched to the person mentioned just before."
            else:
                assignees.append((None, None))
                owner_note = "'he/she' could not be matched to a participant."
        elif skind == "group":
            assignees.append((None, None))
            owner_note = "Said about a group ('we', 'team'), so there is no single owner."
        elif skind == "role":
            assignees.append((None, None))
            owner_note = "Assigned to a role, not a named participant."
        elif skind == "unmatched":
            nm = " ".join(t.text for t in subj_toks)
            assignees.append((None, None))
            owner_note = f"'{nm}' is not a participant of this meeting."
        else:
            assignees.append((None, None))
            if kind == "imperative":
                owner_note = "Nobody was named for this instruction."
            else:
                owner_note = "No clear owner in this sentence."
        if kind in ("request", "imperative") and assignees[0][0] is not None:
            addressee = {a[0] for a in assignees if a[0] is not None}

        # ---- strength tweaks
        if cand.ctrl is not None and cand.ctrl.lemma_.lower() in DELEGATION and skind == "person" and strength == "WEAK":
            strength = "MEDIUM"

        # ---- deadline
        region = self._region(v, cand, cands)
        dls = [d for d in self._dl if d["toks"] & region]
        if not dls and len(cands) == 1:
            dls = list(self._dl)
        dl = next((d for d in dls if d["date"]), None)
        dl_note = next((d["note"] for d in dls if d["note"] and not d["date"]), "")
        drop = set()
        for d in self._dl:
            if d["drop"] and d["toks"] & region:
                drop |= d["toks"]
        # vocative tokens
        for m in mentions:
            if self._is_vocative(doc, m):
                drop |= set(range(m["s"], m["e"]))
                if m["e"] < len(doc) and doc[m["e"]].text == ",":
                    drop.add(m["e"])
        if kind == "list":
            for m in mentions:
                if doc[m["e"]:m["e"] + 1].text.lower() == "to":
                    drop |= set(range(m["s"], m["e"] + 1))

        # ---- title
        obj_vague = False
        patient_text = patient
        dobj = next((c for c in v.children if c.dep_ in ("dobj", "obj")), None)
        replaced = ""
        if dobj is not None and dobj.lower_ in VAGUE_OBJECTS and not list(dobj.children):
            obj_vague = True
            last, no = ctx.last_object
            sib = v.head if v.dep_ == "conj" else None
            sib_obj = next((c for c in sib.children if c.dep_ in ("dobj", "obj")), None) if sib is not None else None
            if sib_obj is not None and sib_obj.lower_ not in VAGUE_OBJECTS:
                replaced = ("it", doc[sib_obj.left_edge.i:sib_obj.right_edge.i + 1].text)
            elif last and ctx.sentence_no - no <= 2 and v.lemma_.lower() not in ("do", "handle", "take"):
                replaced = ("it", last)
        title, desc = self._title_parts(doc, v, drop, patient_text)
        if not title or re.match(r"(?i)^get back to (?:you|us|me)\b", title):
            return []
        if replaced:
            title = re.sub(r"\b%s\b" % re.escape(dobj.text), "the " + replaced[1] if not re.match(r"(?i)(the|a|an|our|my|his|her|their|this|that)\b", replaced[1]) else replaced[1], title, count=1)
            notes.append(f"'{dobj.text}' was taken to mean '{replaced[1]}' from the previous sentence.")
            obj_vague = True
        if len(title.split()) < 2 and not obj_vague:
            return []
        vague = obj_vague or (v.lemma_.lower() == "do" and not _has_object(v))

        # ---- priority
        sent_text = text
        pr = "MEDIUM"
        if URGENT_RX.search(sent_text):
            pr = "HIGH"
        elif LOW_PRIO_RX.search(sent_text):
            pr = "LOW"
        due = dl["date"].isoformat() if dl else None
        if pr == "MEDIUM" and dl and (dl["date"] - ctx.base).days <= 1:
            pr = "HIGH"

        # ---- confidence
        base = {"STRONG": "HIGH", "MEDIUM": "MEDIUM", "WEAK": "LOW"}[strength]
        if flags["marker"]:
            base = "HIGH"
        if kind == "request":
            base = "MEDIUM"
            notes.append("This is a request; the answer has not been heard yet.")
        elif kind == "imperative":
            base = "HIGH" if skind == "person" else "MEDIUM"
        elif kind == "list":
            base = "HIGH"
        if strength == "WEAK" and kind not in ("request",):
            notes.append("Said as a wish or plan ('want to', 'try to'), not a firm commitment.")
        elif strength == "MEDIUM" and kind in ("modal", "control") and base == "MEDIUM" and skind != "group" \
                and not any("request" in n for n in notes):
            notes.append("Said as 'should/needs to', not a firm promise.")
        if HEDGE_RX.search(sent_text):
            base = _up(base, -1)
            notes.append("The wording is tentative (maybe/I think).")
        if cond_main:
            base = _up(base, -1)
            notes.append("This depends on a condition mentioned in the same sentence.")
        if skind in ("group",):
            base = "LOW"
        if assignees[0][0] is None:
            base = min(base, "MEDIUM", key=LEVELS.index) if skind != "group" else base
            if owner_note:
                notes.insert(0, owner_note)
        elif owner_note:
            notes.append(owner_note)
            base = min(base, "MEDIUM", key=LEVELS.index)
        if obj_vague and not replaced:
            base = "LOW"
            notes.append(f"It is not clear what '{dobj.text if dobj is not None else 'it'}' refers to.")
        if dl_note and not dl:
            notes.append(dl_note)
        elif dl and dl.get("note"):
            notes.append(dl["note"])
        if not dl and not any("past" in n or "year" in n for n in notes):
            pass

        items = []
        for aid, aname in assignees:
            items.append({
                "title": title, "description": desc, "assignee": aname, "assignee_id": aid,
                "deadline": due, "priority": pr, "confidence": base,
                "uncertainty_note": " ".join(dict.fromkeys(n for n in notes if n)),
                "source_context": raw.strip()[:400],
                "_meta": {"kind": kind, "subject_kind": skind, "vague": vague, "addressee": addressee,
                          "vi": v.i, "sent": ctx.sentence_no, "conj": {c.i for c in v.conjuncts} | ({v.head.i} if v.dep_ == "conj" else set()), "deadline_note": dl["note"] if dl else ""},
            })
        return items

    # ---------------------------------------------------------------- acknowledgement
    def _confirm(self, pend, it, raw, doc=None, text=""):
        ctx = self.ctx
        if it is not None:
            if it["deadline"] and not pend["deadline"]:
                pend["deadline"] = it["deadline"]
            if it["priority"] == "HIGH":
                pend["priority"] = "HIGH"
        elif text:
            dl, phrase, note = find_deadline(text, ctx.base)
            if dl and not pend["deadline"]:
                pend["deadline"] = dl
        if pend["assignee_id"] is not None:
            pend["confidence"] = "HIGH"
            pend["uncertainty_note"] = ""
        else:
            pend["confidence"] = "MEDIUM"
            pend["uncertainty_note"] = "Agreed, but no clear owner."
        pend["source_context"] = (pend["source_context"] + " " + raw.strip())[:400]
        pend["_meta"]["confirmed"] = True

    # ---------------------------------------------------------------- finish
    def finish(self):
        items = self._share_deadlines(self.ctx.items)
        items = self._dedupe(items)
        out = []
        for it in items:
            it = dict(it)
            it.pop("_meta", None)
            it["discard"] = False
            it["proof_required"] = False
            it["needs_review"] = it["assignee_id"] is None or not it["deadline"] or it["confidence"] == "LOW"
            out.append(it)
        return out

    @staticmethod
    def _share_deadlines(items):
        for it in items:
            if it["deadline"]:
                continue
            for o in items:
                if o is it or not o["deadline"] or o["_meta"]["sent"] != it["_meta"]["sent"]:
                    continue
                if o["_meta"]["vi"] in it["_meta"]["conj"] or it["_meta"]["vi"] in o["_meta"]["conj"]:
                    it["deadline"] = o["deadline"]
                    break
        return items

    @staticmethod
    def _key(title):
        return re.sub(r"[^a-z0-9 ]", "", title.lower()).split()

    def _dedupe(self, items):
        out = []
        for it in items:
            k = self._key(it["title"])
            hit = None
            for o in out:
                ko = self._key(o["title"])
                same_owner = it["assignee_id"] == o["assignee_id"] or it["assignee_id"] is None or o["assignee_id"] is None
                if not same_owner:
                    continue
                r = SequenceMatcher(None, " ".join(k), " ".join(ko)).ratio()
                contained = len(k) >= 3 and len(ko) >= 3 and (" ".join(k) in " ".join(ko) or " ".join(ko) in " ".join(k))
                if r >= 0.85 or contained:
                    hit = o
                    break
            if hit is None:
                out.append(it)
                continue
            for f in ("deadline", "assignee_id", "assignee"):
                if not hit[f] and it[f]:
                    hit[f] = it[f]
            if LEVELS.index(it["confidence"]) > LEVELS.index(hit["confidence"]):
                hit["confidence"], hit["uncertainty_note"] = it["confidence"], it["uncertainty_note"]
            if it["priority"] == "HIGH":
                hit["priority"] = "HIGH"
            if len(it["title"]) > len(hit["title"]) and it["assignee_id"] is not None:
                hit["title"] = it["title"]
            if it["source_context"] not in hit["source_context"]:
                hit["source_context"] = (hit["source_context"] + " " + it["source_context"])[:400]
        return out


def agent_exists(v):
    return any(c.dep_ == "agent" for c in v.children)


# ----------------------------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------------------------
def extract_action_items(sentences, people, meeting_date=None):
    """sentences: list of strings (or one big string). people: list from people_from_users().
    meeting_date: date/datetime/ISO string; deadlines are resolved relative to it. Returns list of dicts."""
    if isinstance(meeting_date, datetime):
        base = meeting_date.date()
    elif isinstance(meeting_date, date):
        base = meeting_date
    elif isinstance(meeting_date, str) and meeting_date:
        base = date.fromisoformat(meeting_date[:10])
    else:
        base = date.today()
    with _LOCK:
        ex = Extractor(people, base)
        if isinstance(sentences, str):
            nlp = ex.nlp
            sentences = [s.text.strip() for s in nlp(sentences).sents if s.text.strip()]
        for s in list(sentences)[:MAX_SENTENCES]:
            if isinstance(s, dict):
                s = s.get("text", "")
            if s and str(s).strip():
                ex.feed(str(s))
        return ex.finish()
