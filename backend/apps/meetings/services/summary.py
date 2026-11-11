"""MeetTask local meeting summary v4 (TextRank + formal minutes). No LLM, no network, no training data.

Input : normalized transcript sentences, the extracted action items, the meeting record, participant names.
Output: dict with summary, mom, discussion_points, decisions (the AIOutput text fields).

Each section of the minutes has its own job, and a sentence is used in ONE place only:
  Summary      a short overview of the whole meeting: what it was about (the purpose that was spoken, the agenda,
               or the main topics), the headline progress, the remaining work, and how many decisions and actions.
  Discussion   the important points, split into progress updates, concerns and other points.
  Decisions    explicit agreements ("we decided / agreed ...").
  Action items the tasks found, with owner, due date and priority.
  Open issues  unresolved questions, and tasks still missing an owner or a deadline.

Cleaning that happens first: greetings, thank-yous, goodbyes and housekeeping ("can you hear me", "let's start") are
removed, repeated stutters are collapsed, and first-person sentences are rewritten in the third person.

How sentences are chosen (TextRank): every usable sentence is a node; two sentences are linked by how much
vocabulary they share (TF-IDF cosine); PageRank over that graph scores each sentence by how central it is to the
meeting's themes. The walk is biased towards decisions, problems and deadlines. Near-duplicates are skipped, and
anything already used in one section is never repeated in another.

The method is unsupervised: nothing is trained. A labelled dataset is only used to MEASURE quality
(see `manage.py eval_summary`). Nothing is invented; every statement comes from the transcript or the meeting
record, and the wording around it is fixed templates. Contact details are left out.
"""
import math
import re
from functools import lru_cache
from collections import Counter
from datetime import date

MODEL_NAME = "local-summary-v4-textrank"
MAX_DISCUSSION = 10
MAX_DECISIONS = 6
MAX_OPEN = 5
MAX_REMAINING = 6
MIN_WORDS, MAX_WORDS = 5, 45
MAX_NODES = 600          # longest transcripts are trimmed to their best-looking sentences before ranking
DAMPING = 0.85           # PageRank damping factor (the usual value)
EDGE_MIN = 0.08          # similarities below this are treated as "not related"
DUPLICATE = 0.5          # two sentences sharing this share of their key words count as the same point

STOPWORDS = set("""
a an the and or but if then so of to in on at by for with from as is are was were be been being am do does did
have has had will would shall should can could may might must i you he she it we they me him her us them my your
his its our their this that these those there here what which who whom when where why how not no yes yeah okay ok
just also very really about into over after before up down out again more most some any all each than too
um uh hmm well like right sure thanks thank please going get got let lets know think mean say said
didn don doesn wasn isn aren haven hasn hadn won wouldn couldn shouldn wanna gonna gotta yep yeah mm huh
mine myself yourself yours ours ourselves themselves himself herself itself other others
""".split())
GENERIC = set("""meeting team thing things need needs time week month today tomorrow work working new one two good make made
use used able discuss discussed discussion talk talked everyone everybody something someone nobody anything
status update updates point points item items part way lot kind stuff guys""".split())

DECISION_RX = re.compile(
    r"\b(?:we (?:have )?(?:decided|agreed|resolved|concluded|approved|confirmed|settled)|(?:it was|is|was) (?:decided|agreed|approved|confirmed)|"
    r"(?:decision|agreement) (?:is|was)|let'?s go with|we(?:'ll| will) go with|going with|final decision|approved|"
    r"agreed (?:to|that|on)|decided (?:to|that|on)|moving forward|from now on|the plan is)\b", re.I)
ISSUE_RX = re.compile(r"\b(?:fail\w*|bugs?|issues?|problems?|delay\w*|block\w*|risks?|concerns?|errors?|broken|unstable|"
                      r"not stable|late|behind|missing|cannot|crash\w*|slow|outage|complain\w*|challeng\w*|difficult\w*)\b", re.I)
STATUS_RX = re.compile(r"\b(?:done|complete[d]?|finished|ready|deployed|resolved|fixed|implemented|launched|released|"
                       r"in progress|on track|progress|working|achieved|delivered|built)\b", re.I)
OPEN_RX = re.compile(r"\b(?:nobody|no one|not sure|unclear|to be confirmed|tbd|pending|waiting (?:for|on)|yet to|"
                     r"not yet|unresolved|open question|still need|haven'?t (?:decided|confirmed)|undecided|"
                     r"not confirmed|nobody confirmed)\b", re.I)
DEADLINE_HINT_RX = re.compile(r"\b(?:by|before|until|due|deadline|tomorrow|today|monday|tuesday|wednesday|thursday|"
                              r"friday|saturday|sunday|next week|next month|end of)\b", re.I)
CONTACT_RX = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|\b(?:https?://|www\.)\S+|(?<!\d)(?:\+?\d[\d\s-]{8,}\d)(?!\d)|"
                        r"\b\d{5}-\d{7}-\d\b", re.I)
NEXT_MEETING_RX = re.compile(r"\bnext (?:meeting|catch[- ]?up|sync|retro|review|stand-?up|session|call)\b", re.I)
# Pronouns that must never appear in the minutes: they are written about the meeting, not in anyone's voice.
VOICE_RX = re.compile(r"\b(?:i|i'm|i'll|i've|i'd|me|my|mine|myself|we|we're|we'll|we've|we'd|us|our|ours|ourselves|"
                      r"you|you're|you'll|you've|your|yours|yourself)\b|[\"\u201c\u201d]", re.I)
PERSONAL_RX = re.compile(r"\b(?:i|i'm|i'll|i've|i'd|me|my)\b", re.I)
SECOND_PERSON_RX = re.compile(r"\b(?:you|your|you're|you'll|you've|yours)\b", re.I)
WORD_RX = re.compile(r"[A-Za-z][A-Za-z'\-]+")

# ---- greetings, thank-yous, goodbyes and meeting housekeeping (never minutes material) ----
_GROUP = r"(?:everyone|everybody|all|team|guys|folks|friends|colleagues)"
GREETING_LEAD_RX = re.compile(
    rf"^\W*(?:(?:good (?:morning|afternoon|evening)|hello|hi|hey|greetings|welcome(?: (?:to the meeting|back))?)"
    rf"(?:\s+{_GROUP})?\W+)+", re.I)
THANKS_LEAD_RX = re.compile(
    rf"^\W*(?:(?:okay|ok|so|alright|right|and)\W+)*(?:thank you|thanks)(?:\s+(?:so much|very much|again|{_GROUP}))*"
    r"(?:\s+for\s+(?:joining|attending|coming|your time|listening|today|being here|the update|that)(?:\s+\w+){0,2})?\W*", re.I)
THANKS_TAIL_RX = re.compile(
    rf"[,;.\s]*(?:and\s+)?(?:thank you|thanks)(?:\s+(?:so much|very much|again|{_GROUP}))*"
    r"(?:\s+for\s+(?:joining|attending|coming|your time|listening|today|being here|the update)(?:\s+\w+){0,2})?\W*$", re.I)
SOCIAL_RX = re.compile(
    r"\b(?:thank(?:s| you)|bye|goodbye|see you|take care|have a (?:great|good|nice|lovely)|good (?:morning|afternoon|evening|night)|"
    r"welcome (?:everyone|all|to the meeting|back)|nice to (?:meet|see)|hope (?:you|everyone)|"
    r"let'?s (?:begin|start|get started|wrap|conclude|end|close|call it|move on|kick off|dive in|go ahead|recap)|"
    r"that'?s (?:all|it)|we(?:'ll| will) (?:end|stop|close) here|meeting (?:is )?(?:adjourned|over|closed)|"
    r"end of (?:the )?meeting|(?:any|anything) (?:else|other business|questions)|over to you|moving on|next (?:topic|item)|"
    r"can everyone|can you (?:hear|see)|(?:hear|see) me|sorry (?:i'?m|for being) late|joining (?:us|today))\b", re.I)

# ---- spoken statement of purpose ("I want to discuss X", "today we will review X") ----
_PURPOSE_VERBS = (r"(?P<verb>discuss|talk about|review|go over|go through|cover|look at|update (?:you|everyone|the team) on|"
                  r"give (?:you |everyone )?an update on|check|present|share)")
PURPOSE_RXS = [
    re.compile(rf"^(?:so |okay |ok |well )?(?:i|we)(?:'d| would)? (?:want|like|wanted|need|am here|are here|'m here|'re here|have called this meeting)(?: to)? "
               rf"{_PURPOSE_VERBS}\s+(?P<x>.+)$", re.I),
    re.compile(rf"^(?:so |okay |ok |well )?(?:today|in this meeting|this meeting)[,\s]+(?:i|we)(?:'ll| will| are going to|'re going to| shall)? {_PURPOSE_VERBS}\s+(?P<x>.+)$", re.I),
    re.compile(rf"^(?:the )?(?:purpose|goal|objective|aim|agenda) of (?:this|today'?s) meeting is (?:to )?(?P<verb>)(?P<x>.+)$", re.I),
    re.compile(rf"^(?:today'?s |the )?agenda (?:for today )?is (?P<verb>)(?P<x>.+)$", re.I),
    re.compile(rf"^this meeting is (?:about|to) (?P<verb>)(?P<x>.+)$", re.I),
]
_GERUND = {"discuss": "discussing", "talk about": "discussing", "review": "reviewing", "go over": "reviewing",
           "go through": "reviewing", "cover": "covering", "look at": "reviewing", "check": "checking",
           "present": "presenting", "share": "sharing"}

# ---- remaining work ----
_NOUN = r"(?P<x>[A-Za-z][\w' -]{2,50}?)"
REMAINING_RXS = [
    re.compile(r"^(?:and |also |so |but |however |currently )*(?:the |our )?" + _NOUN +
               r" (?:is|are|was|were|remains|remain) (?:still |currently |also |yet )?(?:pending|incomplete|outstanding|remaining|left|"
               r"in progress|under development|being (?:developed|worked on)|not (?:yet |fully )?(?:done|complete[d]?|finished|ready|started|"
               r"implemented|developed|working))\b", re.I),
    re.compile(r"\b(?:still |also )*(?:need|needs|have|has|got) to (?:finish|complete|finalize|finalise|build|develop|work on|improve|"
               r"implement|fix|write|prepare|do|test|set up|coordinate|add|create|update|integrate|design|polish)\s+"
               r"(?:the |our |all the |all |some )?" + _NOUN + r"(?:\s+(?:by|before|until|this|next|today|tomorrow|soon|as well|too|yet)\b.*)?(?:[.,;]|$)", re.I),
]
REMAINING_LIST_RX = re.compile(r"\bremaining (?:work|tasks?|items?|things?|features?)\s*(?:include|includes|are|is|:)\s+(?P<x>.+)$", re.I)
_GERUND_TITLE = {"complete": "completing", "finish": "finishing", "finalize": "finalizing", "finalise": "finalising",
                 "prepare": "preparing", "update": "updating", "send": "sending", "write": "writing", "review": "reviewing",
                 "check": "checking", "create": "creating", "build": "building", "develop": "developing", "fix": "fixing",
                 "test": "testing", "implement": "implementing", "coordinate": "coordinating", "arrange": "arranging",
                 "schedule": "scheduling", "book": "booking", "submit": "submitting", "share": "sharing", "draft": "drafting",
                 "deploy": "deploying", "improve": "improving", "add": "adding", "design": "designing", "set up": "setting up",
                 "setup": "setting up", "handle": "handling", "follow up": "following up", "work on": "working on",
                 "look into": "looking into", "take care of": "taking care of", "call": "calling", "email": "emailing",
                 "discuss": "discussing", "present": "presenting", "upload": "uploading", "renew": "renewing",
                 "investigate": "investigating", "confirm": "confirming", "ask": "asking", "make": "making", "run": "running"}


# ----------------------------------------------------------------------------------------------
# Words and de-duplication
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


def _similar(a, b, threshold=DUPLICATE):
    wa, wb = set(map(_stem, _content_words(a))), set(map(_stem, _content_words(b)))
    if not wa or not wb:
        return False
    return len(wa & wb) / min(len(wa), len(wb)) >= threshold


def _is_social(sentence):
    """A short sentence that is only a greeting, thank-you, goodbye or housekeeping line."""
    s = sentence.strip()
    return len(_words(s)) <= 14 and bool(SOCIAL_RX.search(s))


_DISCOURSE = {"yeah", "yep", "yes", "okay", "ok", "um", "uh", "mm", "hmm", "huh", "right", "like", "well", "oh", "so", "just"}


def _noisy(sentence):
    """Spoken noise rather than a statement: lots of 'yeah / okay / um' or the same few words over and over."""
    w = _words(sentence)
    if not w:
        return True
    return sum(x in _DISCOURSE for x in w) / len(w) >= 0.2 or len(set(w)) / len(w) < 0.6


def _usable(sentence):
    s = sentence.strip()
    n = len(_words(s))
    if n < MIN_WORDS or n > MAX_WORDS:
        return False
    return not (s.endswith("?") or _is_social(s) or CONTACT_RX.search(s) or SECOND_PERSON_RX.search(s) or _noisy(s))


def _collapse_repeats(s):
    """'thank you everyone for joining, thank you everyone for joining today' -> one copy. Longest phrase first."""
    for n in range(6, 0, -1):
        s = re.sub(r"\b((?:\w+[ ]+){%d}\w+)(?:[,;.]?[ ]+\1\b)+" % (n - 1), r"\1", s, flags=re.I)
    return s


def _prepare(sentences):
    """Remove greetings, thank-yous and goodbyes; collapse stutters. Sentences that were only social are dropped."""
    out = []
    for raw in sentences:
        s = _collapse_repeats(re.sub(r"\s+", " ", raw).strip())
        s = GREETING_LEAD_RX.sub("", s).strip()
        s = THANKS_LEAD_RX.sub("", s).strip()
        s = THANKS_TAIL_RX.sub("", s).strip()
        if len(_words(s)) < 3 or _is_social(s):
            continue
        out.append(s)
    return out


# ----------------------------------------------------------------------------------------------
# TextRank
# ----------------------------------------------------------------------------------------------
def _tfidf_vectors(sentences):
    """One {stem: weight} vector per sentence, unit length, weights = tf * idf."""
    docs = [Counter(_stem(w) for w in _content_words(s)) for s in sentences]
    df = Counter(t for d in docs for t in d)
    n = max(len(docs), 1)
    vecs = []
    for d in docs:
        v = {t: (1 + math.log(c)) * math.log(1 + n / df[t]) for t, c in d.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs.append({t: x / norm for t, x in v.items()})
    return vecs


def _similarity_graph(vecs):
    """Sparse, symmetric cosine-similarity graph: {i: {j: weight}}. Uses an inverted index so cost follows overlap,
    not n squared."""
    index = {}
    for i, v in enumerate(vecs):
        for t in v:
            index.setdefault(t, []).append(i)
    graph = {i: {} for i in range(len(vecs))}
    limit = max(30, len(vecs) // 3)           # a term found in a third of all sentences links nothing useful
    sims = {}
    for t, ids in index.items():
        if len(ids) < 2 or len(ids) > limit:
            continue
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                i, j = ids[a], ids[b]
                sims[(i, j)] = sims.get((i, j), 0.0) + vecs[i][t] * vecs[j][t]
    for (i, j), w in sims.items():
        if w >= EDGE_MIN:
            graph[i][j] = graph[j][i] = w
    return graph


def textrank(sentences, priors=None, damping=DAMPING, iterations=60, tol=1e-6):
    """Biased TextRank. Returns one score per sentence (they sum to 1).

    priors: optional list of non-negative starting weights (same length). A higher prior makes a sentence more
    likely to be reached by the random walk, so it ranks higher when the graph is otherwise a tie."""
    n = len(sentences)
    if n == 0:
        return []
    if n == 1:
        return [1.0]
    graph = _similarity_graph(_tfidf_vectors(sentences))
    p = list(priors) if priors else [1.0] * n
    total = sum(p) or 1.0
    p = [x / total for x in p]
    out_sum = {i: sum(nb.values()) for i, nb in graph.items()}
    rank = p[:]
    for _ in range(iterations):
        new = [(1 - damping) * p[i] for i in range(n)]
        dangling = sum(rank[i] for i in range(n) if out_sum[i] == 0)   # isolated sentences spread their weight by prior
        for i in range(n):
            if out_sum[i]:
                share = damping * rank[i] / out_sum[i]
                for j, w in graph[i].items():
                    new[j] += share * w
        if dangling:
            for i in range(n):
                new[i] += damping * dangling * p[i]
        delta = sum(abs(new[i] - rank[i]) for i in range(n))
        rank = new
        if delta < tol:
            break
    return rank


def _prior(sentence, index, total):
    """Starting weight for one sentence. Decisions, problems and commitments matter more; so do the opening and
    closing of the meeting where goals and wrap-ups are usually stated."""
    w = 1.0
    if DECISION_RX.search(sentence):
        w *= 2.0
    if ISSUE_RX.search(sentence):
        w *= 1.3
    if DEADLINE_HINT_RX.search(sentence):
        w *= 1.2
    edge = max(2, total // 10)
    if total > 6 and (index < edge or index >= total - edge):
        w *= 1.2
    return w


def _score_sentences(sentences):
    """[(score, original index, sentence)] for the usable sentences, scored with biased TextRank."""
    usable = [(i, s) for i, s in enumerate(sentences) if _usable(s) and _content_words(s)]
    if len(usable) > MAX_NODES:                      # keep the work bounded on very long recordings
        usable = usable[:MAX_NODES // 2] + usable[-MAX_NODES // 2:]
    if not usable:
        return []
    total = len(sentences)
    texts = [s for _, s in usable]
    ranks = textrank(texts, [_prior(s, i, total) for i, s in usable])
    return [(r, i, s) for r, (i, s) in zip(ranks, usable)]


def _third_person_ok(sentence):
    """True when the sentence, once rewritten for the minutes, has no I / we / you / quoted speech left in it."""
    return not VOICE_RX.search(_rewrite(sentence))


def _pick(scored, count, seen):
    """Highest-scoring sentences first, skipping anything that repeats a sentence already used anywhere
    (`seen` is updated in place); returned in spoken order."""
    chosen = []
    for score, i, s in sorted(scored, key=lambda x: -x[0]):
        if len(chosen) >= count:
            break
        if any(_similar(s, e) for e in seen) or not _third_person_ok(s):
            continue
        chosen.append((score, i, s))
        seen.append(s)
    return sorted(chosen, key=lambda x: x[1])


def _pick_formal(scored, count, seen):
    """Like _pick, but prefers sentences that do not need first-person rewriting; "I ..." sentences fill the rest."""
    plain = [x for x in scored if not PERSONAL_RX.search(x[2])]
    first = _pick(plain, count, seen)
    if len(first) >= count:
        return first
    rest = [x for x in scored if PERSONAL_RX.search(x[2])]
    return sorted(first + _pick(rest, count - len(first), seen), key=lambda x: x[1])


# ----------------------------------------------------------------------------------------------
# Rewriting transcript sentences as formal, reported speech
# ----------------------------------------------------------------------------------------------
_SLANG = [(r"\bgonna\b", "going to"), (r"\bwanna\b", "want to"), (r"\bgotta\b", "have to"), (r"\bkinda\b", "somewhat"),
          (r"\bcuz\b", "because")]
_CONTRACTIONS = [(r"won't", "will not"), (r"can't", "cannot"), (r"n't", " not"), (r"'re", " are"), (r"'ll", " will"),
                 (r"'ve", " have"), (r"'m", " am"), (r"let's", "the team should"), (r"let us", "the team should")]
_WE = [(r"we'll", "the team will"), (r"we've", "the team has"), (r"we're", "the team is"), (r"we are", "the team is"),
       (r"we were", "the team was"), (r"we have", "the team has"), (r"we need", "the team needs"),
       (r"we want", "the team wants"), (r"we do not", "the team does not"), (r"we don't", "the team does not"),
       (r"we", "the team"), (r"our", "the team's"), (r"ours", "the team's"), (r"us", "the team"), (r"ourselves", "themselves")]
_I = [(r"i'll", "a participant will"), (r"i'd", "a participant would"), (r"i'm", "a participant is"),
      (r"i am", "a participant is"), (r"i've", "a participant has"), (r"i have", "a participant has"),
      (r"i", "a participant"), (r"my", "their"), (r"me", "them")]
_COMMON_LEAD = {"the", "this", "that", "these", "those", "there", "it", "a", "an", "some", "our", "their", "we", "they",
                "one", "all", "most", "both", "no", "each", "any", "if", "when", "while", "since", "because", "after",
                "before", "although", "once", "as"}
_NO_S = {"will", "would", "can", "could", "should", "may", "might", "must", "shall", "was", "were", "did", "had", "has",
         "is", "been", "said", "went", "made", "took", "got", "saw", "found", "told", "thought", "knew", "felt", "came",
         "gave", "ran", "wrote", "began", "held", "kept", "left", "met", "paid", "sent", "set", "sat", "spent", "stood",
         "understood", "won", "heard", "brought", "built", "bought", "caught", "chose", "drew", "drove", "ate", "fell",
         "flew", "forgot", "grew", "hid", "hit", "hurt", "led", "lost", "meant", "rose", "sold", "shot", "shut", "sang",
         "slept", "spoke", "swam", "taught", "threw", "woke", "wore", "put", "cost", "cut", "let", "read", "done", "gone",
         "seen", "known", "given", "taken", "written", "eaten", "begun", "shown", "gotten", "become", "come", "run"}
_IRREGULAR_S = {"have": "has", "am": "is", "are": "is", "do": "does", "go": "goes", "haven't": "hasn't",
                "don't": "doesn't", "aren't": "isn't", "weren't": "wasn't", "wanna": "wants to", "gonna": "is going to",
                "gotta": "has to"}
_ADVERBS = r"(?:also|still|just|really|currently|already|always|never|usually|actually|probably|definitely|personally|only|even)"


def _agree(verb):
    v = verb.lower()
    if v in _IRREGULAR_S:
        return _IRREGULAR_S[v]
    if v in _NO_S or v.endswith("ed") or "'" in v:
        return verb
    if re.search(r"(?:s|sh|ch|x|z)$", v):
        return verb + "es"
    if re.search(r"[^aeiou]y$", v):
        return verb[:-1] + "ies"
    return verb + "s"


_SHORT_OK = {"go", "ok", "id", "ui", "ux", "qa", "hr", "pm", "ai", "ci", "cd", "db", "vm", "os", "pr", "it", "us", "uk",
             "eu", "tv", "pc", "ip", "up", "ad", "re", "vs", "ie", "eg"}


def _drop_false_starts(s):
    """Remove stumbled word fragments: 'jus just' -> 'just', 'decisi the endpoint decision' left alone unless obvious."""
    toks = s.split()
    out = []
    for i, t in enumerate(toks):
        core = re.sub(r"[^A-Za-z]", "", t).lower()
        nxt = re.sub(r"[^A-Za-z]", "", toks[i + 1]).lower() if i + 1 < len(toks) else ""
        if "'" in t or "’" in t:
            out.append(t)                                             # contractions are never fragments
            continue
        if core and core not in STOPWORDS and core not in _SHORT_OK and len(core) <= 6 and nxt and nxt.startswith(core) and len(nxt) > len(core):
            continue                                                  # a fragment of the next word
        if core and len(core) <= 2 and core not in STOPWORDS and core not in _SHORT_OK:
            continue                                                  # stray one or two letters ("e", "em")
        out.append(t)
    return " ".join(out)


def _tidy(s):
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^\W*(?:(?:and|so|but|also|then|well|okay|ok|right|alright|now|anyway|yeah|yes|sure|actually|basically|"
               r"first(?:ly)?|next|finally|lastly|plus|oh|um|uh)\b[,\s]*)+", "", s, flags=re.I).strip()
    s = re.sub(r"\b(?:um+|uh+|you know|i mean|kind of|sort of)\b[,\s]*", "", s, flags=re.I)   # spoken fillers
    s = re.sub(r"\s+", " ", s)
    s = _collapse_repeats(_drop_false_starts(s))
    return s.strip().rstrip(" .;,:!")


def _third_person(s):
    for pat, rep in _WE + _I:
        s = re.sub(rf"\b{pat}\b", rep, s, flags=re.I)
    # verb agreement: "the team think" -> "the team thinks", "a participant want" -> "a participant wants"
    s = re.sub(r"\b(the team) (think|believe|know|feel|expect|agree|plan|hope|see|prefer|like|say|want|need)\b",
               lambda m: f"{m.group(1)} {m.group(2)}s", s, flags=re.I)
    s = re.sub(rf"\b(a participant)((?: {_ADVERBS})*) ([\w']+)",
               lambda m: f"{m.group(1)}{m.group(2)} {_agree(m.group(3))}", s, flags=re.I)
    _team = {"are": "is", "were": "was", "have": "has", "do": "does", "don't": "does not", "haven't": "has not",
             "aren't": "is not", "weren't": "was not", "doesn't": "does not"}
    s = re.sub(r"\b(the team) (are|were|have|do|don't|haven't|aren't|weren't)\b",
               lambda m: f"{m.group(1)} {_team[m.group(2).lower()]}", s, flags=re.I)
    return s


def _formal(s):
    """Spell out contractions so the minutes read formally."""
    s = re.sub(r"(\w)\s+n't\b", r"\1n't", s)                  # tokenised "do n't" -> "don't"
    s = re.sub(r"\s+'(?=(?:re|ll|ve|m|d|s)\b)", "'", s)         # tokenised "we 're" -> "we're"
    for pat, rep in _SLANG:
        s = re.sub(pat, rep, s, flags=re.I)
    for pat, rep in _CONTRACTIONS:
        s = re.sub(pat, rep, s, flags=re.I)
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


def _neat(text):
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return re.sub(r"([.!?])(?:\s*[.,;])+", r"\1", text).strip()


@lru_cache(maxsize=4096)
def _rewrite(sentence):
    return _neat(_rewrite_raw(sentence))


def _rewrite_raw(sentence):
    """One transcript sentence -> one formal reported-speech sentence."""
    s = _tidy(sentence)
    kind = _kind(s)
    m = re.match(r"(?i)^(?:let'?s|let us|we(?:'ll| will)) go with\b(.*)$", s)
    if m:
        return "The team decided to go with" + m.group(1) + "."
    if kind == "decision":
        m = re.match(r"(?i)^(?:we|the team)\s+(?:have\s+|'ve\s+|all\s+)?(decided|agreed|resolved|concluded|confirmed|"
                     r"approved|settled)\b(.*)$", s)
        if m:
            return _formal("The team " + m.group(1).lower() + m.group(2)) + "."
        return _formal(_cap(_third_person(s))) + "."
    body = _third_person(_formal(s))
    if kind == "issue":
        return "It was noted that " + _lower_first(body) + "."
    if kind == "status":
        body = re.sub(r"^the team (?=\w)", "it ", body, flags=re.I)        # "The team reported that it has finished ..."
        return "The team reported that " + _lower_first(body) + "."
    return _cap(body) + "."


# ----------------------------------------------------------------------------------------------
# Purpose, remaining work, topics
# ----------------------------------------------------------------------------------------------
def _team_words(text):
    return re.sub(r"\bour\b", "the team's", text, flags=re.I)


def _spoken_purpose(sentences):
    """('discussing the current progress of the team's task management application', sentence index) or (None, None)."""
    for idx, s in enumerate(sentences):
        t = re.sub(r"\s+", " ", s).strip().rstrip(" .!")
        for rx in PURPOSE_RXS:
            m = rx.match(t)
            if not m:
                continue
            verb = re.sub(r"\s+", " ", (m.groupdict().get("verb") or "").lower()).strip()
            x = _team_words(m.group("x").strip())
            if len(_words(x)) < 2 or SECOND_PERSON_RX.search(x) or VOICE_RX.search(x):
                continue
            if verb.startswith("update") or verb.startswith("give"):
                lead = "providing an update on"
            else:
                lead = _GERUND.get(verb, "")
            return (f"{lead} {x}".strip(), idx)
    return None, None


def _clean_phrase(x):
    x = re.sub(r"\s+", " ", x).strip(" .,;:")
    x = re.sub(r"^(?:the|our|a|an|its|their|all the|all|some)\s+", "", x, flags=re.I)
    x = re.sub(r"\s+(?:yet|still|now|as well|too|today|this week|anymore)$", "", x, flags=re.I)
    words = x.split()
    if not (1 <= len(words) <= 7) or re.search(r"\b(?:i|you|we|it|this|that|they|he|she|there|nothing|everything|something|"
                                                r"my|me|mine|myself|our|ours|ourselves|us|your|yours|yourself)\b", x, re.I):
        return None
    return x


def _title_to_phrase(title):
    """'Prepare the technical documentation' -> 'preparing the technical documentation'."""
    t = re.sub(r"\s+", " ", title).strip().rstrip(". ")
    low = t.lower()
    for verb in sorted(_GERUND_TITLE, key=len, reverse=True):
        if low.startswith(verb + " "):
            return _GERUND_TITLE[verb] + t[len(verb):]
    return t[:1].lower() + t[1:]


def _remaining_work(sentences, actions):
    """Short phrases for the work still to do. Returns (phrases, indices of sentences they came from)."""
    found, used = [], set()

    def add(phrase):
        if phrase and not any(_similar(phrase, f, 0.6) for f in found):
            found.append(phrase)
            return True
        return False

    for idx, s in enumerate(sentences):
        t = _tidy(s)
        if _is_social(t) or t.endswith("?"):
            continue
        m = REMAINING_LIST_RX.search(t)
        if m:
            parts = [p for p in re.split(r",|;|\band\b", m.group("x")) if p.strip()]
            hit = False
            for p in parts:
                hit |= add(_clean_phrase(p))
            if hit:
                used.add(idx)
            continue
        for rx in REMAINING_RXS:
            m = rx.search(t)
            if m and add(_clean_phrase(m.group("x"))):
                used.add(idx)
                break
    for a in actions:
        if len(found) >= MAX_REMAINING:
            break
        add(_title_to_phrase(a["title"]))
    return found[:MAX_REMAINING], used


def _casing(sentences):
    """lower-case word -> the spelling used in the transcript when it has capitals inside (PostgreSQL, API)."""
    seen = {}
    for s in sentences:
        for w in WORD_RX.findall(s):
            if any(c.isupper() for c in w[1:]):
                seen.setdefault(w.lower(), w)
    return seen


_NUMBER_WORDS = set("one two three four five six seven eight nine ten eleven twelve twenty thirty forty fifty hundred "
                    "thousand first second third fourth fifth".split())


def _topics(sents, skip_words, max_topics=4, min_single=2):
    """sents: list of sentences. Returns ([(title, [sentence index, ...])], [leftover indices])."""
    n = len(sents)
    if n < 5:
        return [], list(range(n))
    surface, single, double = {}, {}, {}
    for idx, s in enumerate(sents):
        toks = [w for w in _words(s)]
        ok = [(w not in STOPWORDS and w not in GENERIC and w not in skip_words and len(w) > 3 and "'" not in w
               and w not in _NUMBER_WORDS) for w in toks]
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
    cands += [(float(len(v)), name(k), v, {k}) for k, v in single.items() if len(v) >= min_single]
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
            topics.append((title, mine))
            assigned |= set(mine)
    return topics, [i for i in range(n) if i not in assigned]


# ----------------------------------------------------------------------------------------------
# Formatting helpers
# ----------------------------------------------------------------------------------------------
def _local(when):
    try:
        from django.utils import timezone
        return timezone.localtime(when)
    except Exception:
        return when


def _fmt_date(meeting):
    when = _local(getattr(meeting, "scheduled_at", None))
    try:
        return when.strftime("%A, %d %B %Y")
    except Exception:
        return str(when or "")


def _fmt_time(meeting):
    when = _local(getattr(meeting, "scheduled_at", None))
    try:
        return when.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return ""


def _fmt_day(iso):
    try:
        return date.fromisoformat(iso).strftime("%a, %d %b %Y")
    except (TypeError, ValueError):
        return iso or "No deadline"


def _reference(meeting):
    mid = getattr(meeting, "id", None)
    when = getattr(meeting, "scheduled_at", None)
    try:
        stamp = when.strftime("%Y%m%d")
    except Exception:
        stamp = "00000000"
    return f"MOM-{stamp}-{mid:04d}" if isinstance(mid, int) else f"MOM-{stamp}"


def _join(names):
    names = list(names)
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def _plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def _action_block(n, a):
    """Two lines per action: what, then who / when / how urgent."""
    owner = a.get("assignee") or "Not assigned"
    due = _fmt_day(a.get("deadline")) if a.get("deadline") else "No deadline"
    prio = (a.get("priority") or "MEDIUM").title()
    return [f"   A{n}. {a['title'].rstrip('. ')}", f"        Owner: {owner}  |  Due: {due}  |  Priority: {prio}"]


def _agenda_lead(description):
    """The first sentence of the agenda as the end of 'The meeting focused on ...', or None."""
    first = re.split(r"(?<=[.!?])\s+", (description or "").strip())[0].strip().rstrip(" .")
    if not first or len(first) > 160:
        return None
    low = first.lower()
    for verb in sorted(_GERUND_TITLE, key=len, reverse=True):
        if low.startswith(verb + " "):
            return _GERUND_TITLE[verb] + first[len(verb):]
    return first[:1].lower() + first[1:] if not first[:2].isupper() else first


# ----------------------------------------------------------------------------------------------
# Main entry
# ----------------------------------------------------------------------------------------------
def build_summary(sentences, action_items, meeting, participant_names):
    """Return {"summary", "mom", "discussion_points", "decisions"} for one meeting."""
    if isinstance(sentences, str):
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", sentences) if s.strip()]
    sentences = _prepare([s.strip() for s in sentences if s and s.strip()])
    names = [n for n in participant_names if n]
    skip_words = {p.lower() for n in names for p in re.split(r"\W+", n) if p}
    active = [a for a in (action_items or []) if not a.get("discard")]
    title = (getattr(meeting, "title", "") or "").strip()
    when, at = _fmt_date(meeting), _fmt_time(meeting)
    casing = _casing(sentences)

    purpose, purpose_idx = _spoken_purpose(sentences)
    remaining, remaining_idx = _remaining_work(sentences, active)
    used_idx = set(remaining_idx) | ({purpose_idx} if purpose_idx is not None else set())

    scored = _score_sentences(sentences)
    task_texts = [a["title"] for a in active if len(_content_words(a["title"])) >= 2]
    # Sentences that are tasks (they live under Action items) or that already fed the summary are not reused.
    pool = [x for x in scored if x[1] not in used_idx and not any(_similar(x[2], t, 0.8) for t in task_texts)]

    seen = [sentences[i] for i in used_idx]                # nothing may repeat what the summary already says
    decision_sel = _pick(sorted([x for x in pool if DECISION_RX.search(x[2])], key=lambda x: -x[0]), MAX_DECISIONS, seen)
    decisions = [_rewrite(s) for _, _, s in decision_sel]
    taken = {i for _, i, _ in decision_sel}

    open_sel = _pick([x for x in pool if x[1] not in taken and OPEN_RX.search(x[2])], MAX_OPEN, seen)
    open_issues = [_rewrite(s) for _, _, s in open_sel]
    taken |= {i for _, i, _ in open_sel}

    next_sel = _pick([x for x in pool if x[1] not in taken and NEXT_MEETING_RX.search(x[2])], 2, seen)
    next_steps = [_rewrite(s) for _, _, s in next_sel]
    taken |= {i for _, i, _ in next_sel}

    rest = [x for x in pool if x[1] not in taken]
    progress_pool = [x for x in rest if STATUS_RX.search(x[2]) and not ISSUE_RX.search(x[2])]
    headline_sel = _pick_formal(progress_pool, 1, seen)           # one headline update goes in the summary
    headline = [_rewrite(s) for _, _, s in headline_sel]
    taken |= {i for _, i, _ in headline_sel}

    rest = [x for x in pool if x[1] not in taken]
    prog_sel = _pick_formal([x for x in rest if STATUS_RX.search(x[2]) and not ISSUE_RX.search(x[2])], 4, seen)
    taken |= {i for _, i, _ in prog_sel}
    concern_sel = _pick_formal([x for x in rest if x[1] not in taken and ISSUE_RX.search(x[2])], 4, seen)
    taken |= {i for _, i, _ in concern_sel}
    other_sel = _pick_formal([x for x in rest if x[1] not in taken], max(MAX_DISCUSSION - len(prog_sel) - len(concern_sel), 2), seen)
    groups = [("Progress updates", [_rewrite(s) for _, _, s in prog_sel]),
              ("Concerns and challenges", [_rewrite(s) for _, _, s in concern_sel]),
              ("Other points discussed", [_rewrite(s) for _, _, s in other_sel])]
    groups = [(name, items) for name, items in groups if items]
    discussion_points = [t for _, items in groups for t in items]

    # ---- summary: a short overview; it names the purpose, headline progress, remaining work and the counts
    focus = []
    if not purpose and not _agenda_lead(getattr(meeting, "description", "")):
        top = [s for _, _, s in sorted(scored, key=lambda x: -x[0])[:25]]
        topics, _ = _topics(top, skip_words, min_single=3)
        for t, _idxs in topics[:3]:
            focus.append(" ".join(casing.get(w, w) for w in t.split()))
    parts = []
    if purpose:
        parts.append(f"The meeting focused on {purpose}.")
    elif _agenda_lead(getattr(meeting, "description", "")):
        parts.append(f"The meeting focused on {_agenda_lead(meeting.description)}.")
    elif focus:
        parts.append(f"The meeting focused on {'reviewing progress on' if headline else 'discussing'} {_join(focus)}.")
    elif sentences:
        parts.append("The meeting covered the matters recorded below.")
    parts.extend(headline)
    if remaining:
        parts.append("Remaining work includes " + _join(remaining) + ".")
    counts = []
    if decisions:
        counts.append(f"{_plural(len(decisions), 'decision')} {'was' if len(decisions) == 1 else 'were'} recorded")
    if active:
        owners = Counter(a.get("assignee") for a in active if a.get("assignee"))
        none = sum(1 for a in active if not a.get("assignee"))
        line = f"{_plural(len(active), 'action item')} {'was' if len(active) == 1 else 'were'} assigned"
        if owners:
            line += " to " + _join(f"{o} ({c})" for o, c in owners.items())
        if none:
            line += f", with {none} still needing an owner"
        counts.append(line)
    if counts:
        parts.append(" and ".join(counts) + ".")
    if open_issues:
        parts.append(f"{_plural(len(open_issues), 'open issue')} remain{'s' if len(open_issues) == 1 else ''} unresolved.")
    summary = " ".join(parts) if parts else "The transcript was too short to summarise."

    # ---- minutes: formal layout
    manager = getattr(getattr(meeting, "manager", None), "display_name", "")
    project = getattr(getattr(meeting, "project", None), "name", "")
    location = getattr(meeting, "location", "") or ""
    L = ["MINUTES OF MEETING", "=" * 18, ""]
    L.append(f"Reference    : {_reference(meeting)}")
    L.append(f"Meeting      : {title or 'Untitled meeting'}")
    L.append(f"Date         : {when or 'Not recorded'}")
    if at:
        L.append(f"Time         : {at}")
    L.append(f"Venue        : {location or 'Not recorded'}")
    if project:
        L.append(f"Project      : {project}")
    if manager:
        L.append(f"Chairperson  : {manager}")
    L.append("Status       : Draft, pending approval by the chairperson")

    L += ["", "1. ATTENDEES"]
    L += [f"   {i}. {n}" for i, n in enumerate(names, 1)] or ["   Not recorded."]

    L += ["", "2. AGENDA", "   " + ((getattr(meeting, "description", "") or "").strip() or "No agenda was provided.")]
    L += ["", "3. SUMMARY", "   " + summary]

    L += ["", "4. DISCUSSION"]
    if groups:
        for n, (name, items) in enumerate(groups, 1):
            L.append(f"   4.{n} {name}")
            L += [f"        - {t}" for t in items]
    else:
        L.append("   The main points are covered in the summary above.")

    L += ["", "5. DECISIONS"]
    L += [f"   D{i}. {d}" for i, d in enumerate(decisions, 1)] or ["   No explicit decisions were recorded."]

    L += ["", "6. ACTION ITEMS"]
    if active:
        for i, a in enumerate(active, 1):
            L += _action_block(i, a)
    else:
        L.append("   No action items were identified.")

    flagged = [f"Task without an owner: {a['title'].rstrip('. ')}" for a in active if not a.get("assignee")]
    flagged += [f"Task without a deadline: {a['title'].rstrip('. ')}" for a in active
                if a.get("assignee") and not a.get("deadline")]
    L += ["", "7. OPEN ISSUES AND RISKS"]
    L += [f"   - {t}" for t in open_issues + flagged] or ["   None."]

    if next_steps:
        L += ["", "8. NEXT MEETING"]
        L += [f"   - {t}" for t in next_steps]

    L += ["", "-" * 40,
          "This draft was prepared automatically from the meeting transcript. It remains subject to review and "
          "correction by the chairperson before approval."]

    return {"summary": summary, "mom": "\n".join(L),
            "discussion_points": discussion_points, "decisions": decisions}