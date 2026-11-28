"""Kling weak spots (strategy plan A1, D31), found in code so the writer cannot miss them. DB-free.

The writer decides the safe version; code only flags a user's action that names a known weak spot,
and asks the writer once more when a flagged scene comes back without a swap. A live run of golden
03 (22 Nov 2026) showed why: with the rule only in the instructions, the real writer kept "he
throws the hoodie to his friend in the crowd" and even timed the hoodie flying through the air.
"""

from __future__ import annotations

import re

# (what Kling does badly, words that name it)
WEAK_SPOTS: list[tuple[str, re.Pattern[str]]] = [
    ("throws and catches", re.compile(r"\b(throw|throws|threw|thrown|throwing|toss|tosses|tossed|tossing|"
                                      r"catch|catches|caught|catching|fling|flings|flung|hurl|hurls|hurled)\b", re.I)),
    ("pouring and liquids in motion", re.compile(r"\b(pour|pours|poured|pouring|splash\w*|spill\w*|"
                                                 r"drips?|dripping|squirts?)\b", re.I)),
    ("fast spins and big jumps", re.compile(r"\b(spins?|spinning|twirls?|twirling|flips?|flipping|backflips?|"
                                            r"somersaults?|cartwheels?|leaps?|leaping)\b", re.I)),
    ("things changing shape", re.compile(r"\b(unfolds?|unfolding|transforms?|transforming|morphs?|morphing|"
                                         r"melts?|melting|inflates?|inflating|shatters?|explodes?)\b", re.I)),
    ("text, logos or screens with words", re.compile(r"\b(types?|typing|texting|scrolls? (?:through|on)|"
                                                     r"reads? (?:the )?(?:screen|label|sign))\b", re.I)),
    # The real Sport theme check (28 Nov 2026): the writer added "a quick dribble stop" on its own.
    ("ball control and kicks", re.compile(r"\b(dribbl\w*|kicks?|kicked|kicking|juggl\w*|keepy[- ]?upp?ys?|"
                                          r"volley(?:s|ed|ing)?|heads? the ball|headers?|"
                                          r"shoots? (?:the ball|at goal)|scores? (?:a|the) goal|"
                                          r"bounc\w* (?:a|the) ball|pass(?:es)? the ball)\b", re.I)),
    ("hands handling small parts", re.compile(r"\b(screws?|unscrews?|threads? (?:a|the)|ties? (?:a|the|his|her) "
                                              r"(?:lace|laces|knot)|assembles?|clips? (?:in|on))\b", re.I)),
]  # fmt: skip


def weak_spot(action: str) -> str:
    """The first Kling weak spot the action names, in plain words, or "" when there is none."""
    for name, rx in WEAK_SPOTS:
        if rx.search(action or ""):
            return name
    return ""
