"""Small narrative lexicon.

The console cannot ask a model for a judgement on every sentence without
paying a round trip per tick, so the fast path is a lexicon.  It is used for
three things:

* the mock provider, so the demo steers visibly with no model at all
* the auditor's tone / tension / pace readouts
* fallback resolution of arbitrary pole words (``tender``, ``somber``, ...)

Poles are pairs: everything at +1 belongs to the left word, -1 to the right.
Missing poles fall back to a spelling + morphology match against the text,
which is weak but never lies about what it measured.
"""

from __future__ import annotations

import math
import re
from collections import Counter

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]+")

# pole -> (positive words, negative words)
AXES: dict[str, tuple[set[str], set[str]]] = {
    "tender": (
        {"gentle", "soft", "warm", "tender", "hold", "held", "hand", "hands", "brush",
         "whisper", "whispered", "quiet", "quietly", "close", "dear", "kind", "care",
         "cradle", "breathe", "breath", "skin", "palm", "linger", "slow", "tenderly",
         "hush", "comfort", "smooth", "murmur", "silk", "tremble", "ache", "fond"},
        {"savage", "rip", "tear", "cold", "hard", "brutal", "grip", "shove", "snarl",
         "cruel", "sharp", "cut", "blade", "blood", "hurt", "violent", "harsh", "ice",
         "stone", "iron", "seize", "crush", "bite", "snap", "glare"},
    ),
    "somber": (
        {"dark", "grey", "gray", "shadow", "shadows", "ash", "silent", "hollow", "grief",
         "mourn", "mourning", "quiet", "dim", "cold", "dust", "faded", "weary", "sorrow",
         "heavy", "still", "grave", "tomb", "ruin", "faded", "wan", "pale", "loss"},
        {"bright", "gold", "golden", "laugh", "laughter", "sun", "sunlit", "warm", "joy",
         "delight", "glow", "gleam", "silver", "bright", "sing", "song", "radiant", "alive"},
    ),
    "tense": (
        {"crack", "snap", "thunder", "scream", "shout", "run", "ran", "chase", "blood",
         "blade", "grip", "shatter", "burst", "sudden", "violent", "fear", "panic",
         "threat", "slam", "shiver", "tremble", "clench", "hunt", "danger", "storm"},
        {"calm", "still", "slow", "easy", "gentle", "rest", "peace", "quiet", "soft",
         "settle", "breathe", "warm", "lull", "drift", "smooth", "safe", "hush"},
    ),
    "action": (
        {"ran", "run", "grabbed", "slammed", "tore", "shoved", "struck", "leapt", "leaped",
         "dashed", "spun", "lunged", "scooped", "seized", "pulled", "pushed", "shattered",
         "burst", "charged", "dove", "sprang", "wrenched", "hurled", "smash", "fought"},
        {"thought", "remembered", "wondered", "felt", "seemed", "considered", "imagined",
         "reflected", "noticed", "considered", "dwelled", "pondered", "dreamed"},
    ),
    "wonder": (
        {"vast", "ancient", "glowing", "luminous", "marvel", "awe", "whisper", "silver",
         "moon", "starlight", "shimmer", "endless", "sacred", "ritual", "hum", "lullaby",
         "light", "magic", "mystery", "mysterious", "unearthly", "otherworldly"},
        {"dull", "grey", "gray", "ordinary", "plain", "flat", "bored", "tired", "dust",
         "grimy", "cheap", "small", "mean", "squalid"},
    ),
    "warm": (
        {"warm", "gold", "honey", "amber", "sun", "glow", "kind", "laugh", "home", "hearth",
         "bread", "soft", "bright", "smile", "open", "alive"},
        {"cold", "ice", "frost", "grey", "gray", "steel", "iron", "stone", "empty", "bleak",
         "bitter", "numb", "dead", "hollow"},
    ),
}

# words that move the tension needle without belonging to an axis
STRESS = {
    "thunder", "storm", "crack", "shatter", "scream", "blood", "blade", "knife", "fear",
    "panic", "danger", "threat", "violent", "rage", "fury", "burn", "crash", "slam",
    "grip", "clench", "shiver", "tremble", "dark", "dead", "death", "hunt", "chase",
    "wind", "howl", "cold", "hard", "sharp", "rip", "tear",
}
CALM = {
    "gentle", "soft", "quiet", "still", "slow", "calm", "rest", "peace", "warm", "moon",
    "moonlight", "silver", "hush", "drift", "breathe", "settle", "smooth", "easy", "safe",
    "sleep", "light", "lull", "tender",
}
ACTION_VERBS = AXES["action"][0]
ABSTRACT = {
    "memory", "memories", "thought", "mind", "time", "silence", "shadow", "shadows",
    "legend", "legend", "story", "feeling", "sense", "wonder", "fear", "hope", "grief",
    "weight", "centuries", "distance", "darkness", "light", "quiet", "stillness",
    "presence", "recognition", "whisper",
}

STOP = set("""a an the and or but if then than that this these those of in on at to from by
for with without into onto over under as is are was were be been being it its it's he she
they them his her their there here not no nor so yet do did does have has had will would
could should may might must you your i me my we our us one two three like about across
against before after while when where who whom which what how just very more most much
slightly almost only also still even again once all any each few many some such own same
""".split())


def words(text: str) -> list[str]:
    return [w.lower() for w in TOKEN_RE.findall(text)]


def axis_for(pole: str) -> tuple[set[str], set[str]] | None:
    p = pole.lower().strip()
    if p in AXES:
        return AXES[p]
    for key, val in AXES.items():
        if p.startswith(key[:5]) or key.startswith(p[:5]):
            return val
    return None


def pair_score(text: str, plus: str, minus: str) -> tuple[float, float]:
    """Split the evidence between the two poles of one vector.

    Laplace-smoothed so a single stray word cannot read as a 100% steer, and
    the two shares always sum to 1 — the console shows the winning side.
    """
    toks = [w for w in words(text) if w not in STOP]

    def hits(pole: str) -> int:
        axis = axis_for(pole)
        if axis is None:
            stem = pole.lower()[:6]
            return sum(1 for w in toks if w.startswith(stem))
        pos, _neg = axis
        return sum(1 for w in toks if w in pos)

    a, b = hits(plus), hits(minus)
    total = a + b + 2.0
    return (a + 1.0) / total, (b + 1.0) / total


def tension(text: str) -> float:
    toks = [w for w in words(text) if w not in STOP]
    if not toks:
        return 0.35
    s = sum(1 for w in toks if w in STRESS)
    c = sum(1 for w in toks if w in CALM)
    raw = 0.45 + 0.9 * (s / max(4, len(toks))) - 0.5 * (c / max(4, len(toks)))
    return max(0.0, min(1.0, raw))


def surprise(text: str, context: str) -> float:
    """Novelty of the last sentence against the prior text."""
    new = {w for w in words(text) if w not in STOP}
    old = {w for w in words(context) if w not in STOP}
    if not new:
        return 0.3
    unseen = len([w for w in new if w not in old]) / len(new)
    rare = sum(1 for w in new if len(w) > 8) / max(6, len(new))
    return max(0.0, min(1.0, 0.25 + 0.7 * unseen + 0.4 * rare))


def pace(text: str) -> float:
    """0 = compressed/dense, 1 = expansive."""
    sents = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]
    if not sents:
        return 0.5
    avg = sum(len(words(s)) for s in sents) / len(sents)
    return max(0.0, min(1.0, (avg - 8) / 30))


def mode(text: str) -> tuple[str, float]:
    """Dialogue / action / description split, returning the dominant one."""
    toks = words(text)
    if not toks:
        return "description", 0.5
    quotes = len(re.findall(r'[""][^""]{2,}[""]', text)) + text.count('"') // 2
    act = sum(1 for w in toks if w in ACTION_VERBS)
    abst = sum(1 for w in toks if w in ABSTRACT)
    desc = len(toks) - act - abst
    total = max(1, quotes * 12 + act + desc + 0.4 * abst)
    share = {"dialogue": quotes * 12 / total, "action": act / total, "description": desc / total}
    label = max(share, key=share.get)
    return label, min(0.99, share[label])


def entities(text: str) -> Counter:
    """Capitalised, non-sentence-initial tokens as candidate characters."""
    out: Counter = Counter()
    for sent in re.split(r"(?<=[.!?])\s+", text):
        toks = TOKEN_RE.findall(sent)
        for i, w in enumerate(toks):
            if i == 0:
                continue
            if w[0].isupper() and w.lower() not in STOP and len(w) > 2:
                out[w] += 1
    return out


def focus(text: str) -> tuple[str, float]:
    """Who owns the sentence: strongest named entity vs. the narrator."""
    ents = entities(text)
    if not ents:
        return "narrator", 0.5
    name, count = ents.most_common(1)[0]
    toks = max(1, len(words(text)))
    share = min(0.99, 0.5 + count / max(4, toks / 6))
    return name, share


def relevance(line: str, focus_text: str) -> float:
    """Cheap cosine between a line and the current generation window."""
    a = Counter(w for w in words(line) if w not in STOP)
    b = Counter(w for w in words(focus_text) if w not in STOP)
    if not a or not b:
        return 0.0
    dot = sum(a[k] * b.get(k, 0) for k in a)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def bucket_tension(v: float) -> str:
    return ("very relaxed" if v < 0.25 else "somewhat relaxed" if v < 0.45
            else "measured" if v < 0.62 else "somewhat strained" if v < 0.82
            else "very strained")


def bucket_surprise(v: float) -> str:
    return ("very expected" if v < 0.25 else "somewhat expected" if v < 0.45
            else "even" if v < 0.62 else "somewhat unexpected" if v < 0.82
            else "very unexpected")


def bucket_pace(v: float) -> str:
    return ("very compressed" if v < 0.2 else "somewhat compressed" if v < 0.45
            else "even" if v < 0.62 else "somewhat expansive" if v < 0.82
            else "very expansive")
