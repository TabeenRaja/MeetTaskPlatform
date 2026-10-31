"""MeetTask local meeting summary v2. No LLM, no network.

Input : normalized transcript sentences, the extracted action items, the meeting record, participant names.
Output: dict with summary, mom, discussion_points, decisions (the AIOutput text fields).

What changed from v1: the summary is no longer a paste of transcript sentences. It is written as a short
narrative in the third person ("The team decided to ...", "It was noted that ..."), built from
  * the meeting record (title, date, participants),
  * the main topics (most frequent terms, e.g. "Login Module", "Authentication"),
  * the strongest points, rewritten as reported speech,
  * the decisions, and
  * the tasks found (who owns what, what still has no owner).
The minutes are a structured document: details, agenda, summary, discussion grouped by topic, decisions,
action items, and open issues.

Nothing is invented. Every statement comes from the transcript or the meeting record; the wording around it
is fixed templates. Contact details (emails, phones, IDs) are left out.
"""
import re
from collections import Counter
from datetime import date

MODEL_NAME = "local-summary-v2"
MAX_DISCUSSION = 10
MAX_DECISIONS = 6
MAX_OPEN = 5
MIN_WORDS, MAX_WORDS = 5, 45

STOPWORDS = set("""
a an the and or but if then so of to in on at by for with from as is are was were be been being am do does did
have has had will would shall should can could may might must i you he she it we they me him her us them my your
his its our their this that these those there here what which who whom when where why how not no yes yeah okay ok
just also very really about into over after before up down out again more most some any all each than too
um uh hmm well like right sure thanks thank please going get got let lets know think mean say said
""".split())
GENERIC = set("""meeting team thing things need needs time week month today tomorrow work working new one two good make made
use used able discuss discussed discussion talk talked everyone everybody something someone nobody anything
status update updates point points item items part way lot kind""".split())

DECISION_RX = re.compile(
    r"\b(?:we (?:have )?(?:decided|agreed|resolved|concluded|approved|confirmed|settled)|(?:it was|is|was) (?:decided|agreed|approved|confirmed)|"
    r"(?:decision|agreement) (?:is|was)|let'?s go with|we(?:'ll| will) go with|going with|final decision|approved|"
    r"agreed (?:to|that|on)|decided (?:to|that|on)|moving forward|from now on|the plan is)\b", re.I)
ISSUE_RX = re.compile(r"\b(?:fail\w*|bugs?|issues?|problems?|delay\w*|block\w*|risks?|concerns?|errors?|broken|unstable|"
                      r"not stable|late|behind|missing|cannot|crash\w*|slow|outage|complain\w*)\b", re.I)
STATUS_RX = re.compile(r"\b(?:done|complete[d]?|finished|ready|deployed|resolved|fixed|implemented|launched|released|"
                       r"in progress|on track|progress)\b", re.I)
OPEN_RX = re.compile(r"\b(?:nobody|no one|not sure|unclear|to be confirmed|tbd|pending|waiting (?:for|on)|yet to|"
                     r"not yet|unresolved|open question|still need|haven'?t (?:decided|confirmed)|undecided|"
                     r"not confirmed|nobody confirmed)\b", re.I)
FILLER_RX = re.compile(r"^\W*(?:yes|yeah|yep|okay|ok|sure|alright|right|thanks|thank you|got it|sounds good|cool|"
                       r"hello|hi|hey|good (?:morning|afternoon|evening)|bye|goodbye)\b\W*$", re.I)
DEADLINE_HINT_RX = re.compile(r"\b(?:by|before|until|due|deadline|tomorrow|today|monday|tuesday|wednesday|thursday|"
                              r"friday|saturday|sunday|next week|next month|end of)\b", re.I)
CONTACT_RX = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|\b(?:https?://|www\.)\S+|(?<!\d)(?:\+?\d[\d\s-]{8,}\d)(?!\d)|"
                        r"\b\d{5}-\d{7}-\d\b", re.I)
SCAFFOLD_RX = re.compile(r"^\W*(?:(?:so|okay|ok|alright|right|now)\W+)*(?:let'?s (?:start|begin|get started|move on|wrap up|"
                         r"kick off|dive in|go ahead|recap)|moving on|next (?:topic|item)|that'?s (?:all|it)|"
                         r"i think that'?s (?:all|it)|can everyone|can you hear|welcome)\b", re.I)
LEAD_RX = re.compile(r"^\W*(?:(?:and|so|but|also|then|well|okay|ok|right|alright|now|anyway|yeah|yes|sure|actually|"
                     r"basically|first(?:ly)?|next|finally|lastly|plus|oh|um|uh)\b[,\s]*)+", re.I)
PERSONAL_RX = re.compile(r"\b(?:i|i'm|i'll|i've|me|my|you|your|you're)\b", re.I)
WORD_RX = re.compile(r"[A-Za-z][A-Za-z'\-]+")


# ----------------------------------------------------------------------------------------------
# Words, scoring, de-duplication
# ----------------------------------------------------------------------------------------------
def _words(sentence):
    return [w.lower() for w in WORD_RX.findall(sentence)]


def _content_words(sentence):
    return [w for w in _words(sentence) if w not in STOPWORDS and len(w) > 2]


def _stem(w):
    w = w.lower()
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[:-len(suf)]
    return w


def _usable(sentence):
    s = sentence.strip()
    n = len(_words(s))
    if n < MIN_WORDS or n > MAX_WORDS:
        return False
    return not (s.endswith("?") or FILLER_RX.match(s) or SCAFFOLD_RX.match(s) or CONTACT_RX.search(s))


def _similar(a, b, threshold=0.6):
    wa, wb = set(map(_stem, _content_words(a))), set(map(_stem, _content_words(b)))
    if not wa or not wb:
        return False
    return len(wa & wb) / min(len(wa), len(wb)) >= threshold


def _score_sentences(sentences):
    freq = Counter(_stem(w) for s in sentences for w in set(_content_words(s)))
    total = len(sentences)
    scored = []
    for i, s in enumerate(sentences):
        if not _usable(s):
            continue
        words = [_stem(w) for w in _content_words(s)]
        if not words:
            continue
        score = sum(freq[w] for w in words) / len(words)      # average importance: length alone does not win
        if DECISION_RX.search(s):
            score *= 1.4
        if ISSUE_RX.search(s):
            score *= 1.15
        if DEADLINE_HINT_RX.search(s):
            score *= 1.1
        if total > 6 and (i < max(2, total // 10) or i >= total - max(2, total // 10)):
            score *= 1.1
        scored.append((score, i, s))
    return scored


def _pick(scored, count, exclude=()):
    chosen = []
    for score, i, s in sorted(scored, key=lambda x: -x[0]):
        if len(chosen) >= count:
            break
        if any(_similar(s, e) for e in list(exclude) + [c[2] for c in chosen]):
            continue
        chosen.append((score, i, s))
    return sorted(chosen, key=lambda x: x[1])      # back into spoken order


# ----------------------------------------------------------------------------------------------
# Rewriting transcript sentences as reported speech
# ----------------------------------------------------------------------------------------------
_WE = [(r"we'll", "the team will"), (r"we've", "the team has"), (r"we're", "the team is"), (r"we are", "the team is"),
       (r"we were", "the team was"), (r"we have", "the team has"), (r"we need", "the team needs"),
       (r"we want", "the team wants"), (r"we do not", "the team does not"), (r"we don't", "the team does not"),
       (r"we", "the team"), (r"our", "the team's"), (r"us", "the team"), (r"ourselves", "themselves")]
_I = [(r"i'll", "a participant will"), (r"i'm", "a participant is"), (r"i am", "a participant is"),
      (r"i've", "a participant has"), (r"i have", "a participant has"), (r"i", "a participant"),
      (r"my", "their"), (r"me", "them")]
_COMMON_LEAD = {"the", "this", "that", "these", "those", "there", "it", "a", "an", "some", "our", "their", "we", "they",
                "one", "all", "most", "both", "no", "each", "any", "if", "when", "while", "since", "because", "after",
                "before", "although", "once", "as"}


def _tidy(s):
    s = re.sub(r"\s+", " ", s).strip()
    s = LEAD_RX.sub("", s).strip()
    return s.rstrip(" .;,:!") 


def _third_person(s, relaxed=False):
    for pat, rep in _WE + (_I if relaxed else []):
        s = re.sub(rf"\b{pat}\b", rep, s, flags=re.I)
    # subject-verb agreement after "the team": "the team think" -> "the team thinks"
    s = re.sub(r"\b(the team) (think|believe|know|feel|expect|agree|plan|hope|see|prefer|like|say|expect)\b",
               lambda m: f"{m.group(1)} {m.group(2)}s", s, flags=re.I)
    return s


def _cap(s):
    return s[:1].upper() + s[1:] if s else s


def _lower_first(s):
    first = s.split(" ", 1)[0]
    return (first.lower() + s[len(first):]) if first.lower() in _COMMON_LEAD else s


def _kind(s):
    if DECISION_RX.search(s):
        return "decision"
    if ISSUE_RX.search(s):
        return "issue"
    if STATUS_RX.search(s):
        return "status"
    return "plain"


def _rewrite(sentence, relaxed=False):
    """One transcript sentence -> one reported-speech sentence."""
    s = _tidy(sentence)
    kind = _kind(s)
    if kind == "decision":
        m = re.match(r"(?i)^(?:we|the team)\s+(?:have\s+|'ve\s+|all\s+)?(decided|agreed|resolved|concluded|confirmed|"
                     r"approved|settled)\b(.*)$", s)
        if m:
            return "The team " + m.group(1).lower() + m.group(2) + "."
        return _cap(_third_person(s, relaxed)) + "."
    body = _third_person(s, relaxed)
    if kind == "issue":
        return "It was noted that " + _lower_first(body) + "."
    if kind == "status":
        return "It was reported that " + _lower_first(body) + "."
    return _cap(body) + "."


# ----------------------------------------------------------------------------------------------
# Topics
# ----------------------------------------------------------------------------------------------
def _topics(sents, skip_words, max_topics=4):
    """sents: list of sentences. Returns ([(title, [sentence index, ...])], [leftover indices])."""
    n = len(sents)
    if n < 5:
        return [], list(range(n))
    surface, single, double = {}, {}, {}
    for idx, s in enumerate(sents):
        toks = [w for w in _words(s)]
        ok = [(w not in STOPWORDS and w not in GENERIC and w not in skip_words and len(w) > 2) for w in toks]
        for w, good in zip(toks, ok):
            if good:
                st = _stem(w)
                surface.setdefault(st, Counter())[w] += 1
                single.setdefault(st, set()).add(idx)
        for (a, ga), (b, gb) in zip(zip(toks, ok), zip(toks[1:], ok[1:])):
            if ga and gb:
                double.setdefault((_stem(a), _stem(b)), set()).add(idx)

    def name(st):
        return surface[st].most_common(1)[0][0]

    cands = [(len(v) * 1.5, " ".join(name(x) for x in k), v, set(k)) for k, v in double.items() if len(v) >= 2]
    cands += [(float(len(v)), name(k), v, {k}) for k, v in single.items() if len(v) >= 2]
    cands.sort(key=lambda c: (-c[0], c[1]))
    chosen, covered, used_stems = [], set(), set()
    for weight, title, idxs, stems in cands:
        if len(chosen) >= max_topics:
            break
        if stems <= used_stems or not (idxs - covered):
            continue
        chosen.append((title, idxs))
        covered |= idxs
        used_stems |= stems
    assigned, topics = set(), []
    for title, idxs in chosen:
        mine = sorted(i for i in idxs if i not in assigned)
        if mine:
            topics.append((title.title(), mine))
            assigned |= set(mine)
    return topics, [i for i in range(n) if i not in assigned]


# ----------------------------------------------------------------------------------------------
# Formatting helpers
# ----------------------------------------------------------------------------------------------
def _fmt_when(meeting):
    when = getattr(meeting, "scheduled_at", None)
    try:
        from django.utils import timezone
        return timezone.localtime(when).strftime("%A, %d %B %Y at %I:%M %p")
    except Exception:
        return str(when or "")


def _fmt_day(iso):
    try:
        return date.fromisoformat(iso).strftime("%a, %d %b %Y")
    except (TypeError, ValueError):
        return iso or "No deadline"


def _join(names):
    names = list(names)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def _task_line(a):
    owner = a.get("assignee") or "Not assigned"
    due = _fmt_day(a.get("deadline")) if a.get("deadline") else "No deadline"
    prio = (a.get("priority") or "MEDIUM").title()
    return f"{a['title'].rstrip('. ')} | Owner: {owner} | Due: {due} | Priority: {prio}"


# ----------------------------------------------------------------------------------------------
# Main entry
# ----------------------------------------------------------------------------------------------
def build_summary(sentences, action_items, meeting, participant_names):
    """Return {"summary", "mom", "discussion_points", "decisions"} for one meeting."""
    if isinstance(sentences, str):
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", sentences) if s.strip()]
    sentences = [s.strip() for s in sentences if s and s.strip()]
    names = [n for n in participant_names if n]
    skip_words = {p.lower() for n in names for p in re.split(r"\W+", n) if p}
    active = [a for a in (action_items or []) if not a.get("discard")]
    title = (getattr(meeting, "title", "") or "").strip()
    when = _fmt_when(meeting)

    scored = _score_sentences(sentences)
    # Sentences that are really tasks live under "Action items"; do not repeat them as discussion.
    task_texts = [a["title"] for a in active if len(_content_words(a["title"])) >= 2]
    pool = [x for x in scored if not any(_similar(x[2], t) for t in task_texts)]

    decision_sel = _pick([x for x in pool if DECISION_RX.search(x[2])], MAX_DECISIONS)
    decisions = [_rewrite(s) for _, _, s in decision_sel]

    taken = {i for _, i, _ in decision_sel}
    open_sel = _pick([x for x in pool if x[1] not in taken and OPEN_RX.search(x[2])], MAX_OPEN)
    taken |= {i for _, i, _ in open_sel}
    open_issues = [_rewrite(s) for _, _, s in open_sel]

    disc_pool = [x for x in pool if x[1] not in taken]
    plain = [x for x in disc_pool if not PERSONAL_RX.search(x[2])]
    if len(plain) < 3:                      # conversational meeting: allow "I ..." rewritten as "a participant ..."
        plain = disc_pool
    disc_sel = _pick(plain, MAX_DISCUSSION, exclude=[s for _, _, s in decision_sel])
    disc_sents = [s for _, _, s in disc_sel]
    disc_text = [_rewrite(s, relaxed=True) for s in disc_sents]

    topics, leftover = _topics(disc_sents, skip_words)
    topic_titles = [t for t, _ in topics]

    # ---- summary: a short narrative, not transcript lines
    if not disc_text and not decisions and not active:
        summary = "The transcript was too short to summarise."
    else:
        parts = []
        intro = "This meeting" + (f" ({title})" if title else "") + (f" was held on {when}" if when else " took place")
        intro += f" with {_join(names)}." if names else "."
        parts.append(intro)
        if topic_titles:
            parts.append("The discussion covered " + _join(t.lower() for t in topic_titles) + ".")
        ranked = sorted(zip(disc_text, disc_sel), key=lambda p: (_kind(p[1][2]) not in ("issue", "status"), -p[1][0]))
        key = sorted(ranked[:3], key=lambda p: p[1][1])
        parts.extend(t for t, _ in key)
        if decisions:
            parts.extend(decisions[:2])
            if len(decisions) > 2:
                parts.append(f"{_plural(len(decisions) - 2, 'further decision')} {'was' if len(decisions) == 3 else 'were'} recorded.")
        if active:
            owners = Counter(a.get("assignee") for a in active if a.get("assignee"))
            none = sum(1 for a in active if not a.get("assignee"))
            line = f"{_plural(len(active), 'follow-up task')} {'was' if len(active) == 1 else 'were'} identified"
            if owners:
                line += ", assigned to " + _join(f"{o} ({c})" for o, c in owners.items())
            if none:
                line += f"; {none} still {'needs' if none == 1 else 'need'} an owner"
            parts.append(line + ".")
        if open_issues:
            parts.append(f"{_plural(len(open_issues), 'open issue')} remain{'s' if len(open_issues) == 1 else ''} unresolved.")
        summary = " ".join(parts)

    # ---- minutes
    L = ["MINUTES OF MEETING", "=" * 18, ""]
    L += [f"Meeting: {title or 'Untitled meeting'}", f"Date and time: {when}"]
    if getattr(meeting, "location", ""):
        L.append(f"Location: {meeting.location}")
    project = getattr(getattr(meeting, "project", None), "name", "")
    if project:
        L.append(f"Project: {project}")
    manager = getattr(getattr(meeting, "manager", None), "display_name", "")
    if manager:
        L.append(f"Chaired by: {manager}")
    L.append("Participants: " + (", ".join(names) if names else "Not recorded"))

    L += ["", "1. AGENDA", (getattr(meeting, "description", "") or "").strip() or "No agenda was provided."]
    L += ["", "2. SUMMARY", summary]

    L += ["", "3. DISCUSSION"]
    if not disc_text:
        L.append("No discussion points were identified.")
    elif topics:
        for n, (t, idxs) in enumerate(topics, 1):
            L.append(f"3.{n} {t}")
            L += [f"   - {disc_text[i]}" for i in idxs]
        if leftover:
            L.append(f"3.{len(topics) + 1} Other points")
            L += [f"   - {disc_text[i]}" for i in leftover]
    else:
        L += [f"   - {t}" for t in disc_text]

    L += ["", "4. DECISIONS"]
    L += [f"   {i}. {d}" for i, d in enumerate(decisions, 1)] or ["No explicit decisions were recorded."]

    L += ["", "5. ACTION ITEMS"]
    L += [f"   {i}. {_task_line(a)}" for i, a in enumerate(active, 1)] or ["No action items were identified."]

    flagged = [f"Task without an owner: {a['title'].rstrip('. ')}" for a in active if not a.get("assignee")]
    flagged += [f"Task without a deadline: {a['title'].rstrip('. ')}" for a in active
                if a.get("assignee") and not a.get("deadline")]
    L += ["", "6. OPEN ISSUES AND FOLLOW-UPS"]
    L += [f"   - {t}" for t in open_issues + flagged] or ["None."]

    L += ["", "-" * 40,
          "Prepared automatically from the meeting transcript. Please review and correct before approval."]

    ordered = [i for _, idxs in topics for i in idxs] + leftover if topics else range(len(disc_text))
    discussion_points = [disc_text[i] for i in ordered]
    return {"summary": summary, "mom": "\n".join(L),
            "discussion_points": discussion_points, "decisions": decisions}