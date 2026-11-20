"""The storyboard rule against invented testimonials (plan §8 step 2, §11), checked in code.

The storyboard prompt already forbids first-person claims of use, experience or results,
reviews, ratings and awards unless the brief supplies them. This module is the backstop:
it flags lines that still break the rule. The pipeline regenerates the storyboard once
with the flagged lines as feedback; lines still flagged after that are shown to the user
to edit, and Approve is refused while any remain. DB-free and deterministic.

A claim is "supplied by the brief" when the brief itself contains a claim sentence that
the flagged line closely follows (most of its content words come from that sentence) and
the line adds no number the brief does not have.
"""

from __future__ import annotations

import re

from ..models import Brief, Storyboard, StoryboardFlag

_QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})
# "I" only: a brand speaking as "we" ("we use organic cotton") is not a testimonial.
_SUBJ = r"\bi(?:'ve| have|'d| had)?(?: (?:really|honestly|just|literally|actually|never|always|also))?"

_FIRST_PERSON_USE = re.compile(
    _SUBJ + r"(?: been)? (?:use|used|using|tried|trying|tested|testing|wear|wore|worn|wearing|bought|ordered|"
    r"switched|started|ditched|replaced)\b"
)
_FIRST_PERSON_EXPERIENCE = re.compile(
    _SUBJ + r" (?:love|loved|swear by|recommend|recommended|noticed|saw|felt|lost|gained|can't live without|"
    r"can't stop|won't go back|would never)\b"
    r"|\b(?:i'm|i am) (?:obsessed|hooked|in love|never going back|so happy|amazed)\b"
    r"|\bnever going back\b"
    r"|\b(?:changed|transformed|saved|fixed|cleared up|upgraded) (?:my|our)\b"
    r"|\b(?:works?|worked) (?:for|on) (?:me|us)\b"
    r"|\b(?:my|our) (?:go-to|favou?rite|holy grail|new obsession|secret weapon)\b"
    r"|\bmy (?:\w+ ){0,2}(?:cleared|improved|transformed|healed|disappeared|vanished)\b"
    r"|\bmy (?:\w+ ){0,2}(?:feels?|looks?|is|are|got) (?:(?:so|much|way|a lot) )*"
    r"(?:better|softer|stronger|faster|clearer|smoother|younger|healthier)\b"
)
_RESULTS_OVER_TIME = re.compile(
    r"\b(?:for|after|in|since|within) (?:just |only |about |over )?"
    r"(?:\d+|a|one|two|three|four|five|six|seven|eight|nine|ten|several|a few|a couple of) "
    r"(?:days?|weeks?|months?|years?)\b"
)
_REVIEWS = re.compile(
    r"\b(?:\d(?:\.\d)?|five|four)[- ]?stars?\b"
    r"|\b(?:customers|users|buyers|people|everyone|fans|reviewers|athletes|players|experts|dermatologists|doctors) "
    r"(?:say|says|love|loves|rave|swear|agree|recommend)\b"
    r"|\b\d[\d,.]*\s*k?\+? (?:happy |satisfied )?(?:customers|users|buyers|reviews|players)\b"
    r"|\b(?:reviews?|testimonials?|rated)\b"
    r"|\"[^\"]{3,}\"\s*[-–—]\s*[A-Za-z]"
)
_AWARDS = re.compile(
    r"\bbest[- ]?sell(?:ing|er)|\baward[- ]winning|#1\b|\bnumber one\b|\bno\. ?1\b|\bclinically (?:proven|tested)"
)

RULES: list[tuple[re.Pattern[str], str]] = [
    (_FIRST_PERSON_USE, "First-person claim of use. Keep it only if the brief states it."),
    (_FIRST_PERSON_EXPERIENCE, "First-person claim of experience or results. Keep it only if the brief states it."),
    (_RESULTS_OVER_TIME, "Claim of results over time. Keep it only if the brief states it."),
    (_REVIEWS, "Review, rating or testimonial language. Use only real quotes from the brief."),
    (_AWARDS, "Award, ranking or proof claim. Keep it only if the brief states it."),
]

_STOP = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "you",
    "your",
    "are",
    "was",
    "but",
    "not",
    "have",
    "has",
    "had",
    "its",
    "it's",
    "just",
    "from",
    "they",
    "them",
    "their",
    "our",
    "out",
    "all",
    "now",
    "get",
    "got",
    "can",
    "will",
    "one",
    "too",
    "very",
    "really",
    "been",
    "into",
    "than",
    "then",
    "what",
    "when",
    "how",
}
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD = re.compile(r"[a-z0-9']+")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def _norm(text: str) -> str:
    return (text or "").translate(_QUOTES).lower()


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text or "") if s.strip()]


def _content_words(text: str) -> set[str]:
    return {w for w in _WORD.findall(_norm(text)) if len(w) >= 3 and w not in _STOP}


def claim_reason(sentence: str) -> str | None:
    """The first rule a sentence breaks, or None."""
    text = _norm(sentence)
    for pattern, reason in RULES:
        if pattern.search(text):
            return reason
    return None


def _brief_claims(brief: Brief) -> list[str]:
    text = "\n".join([brief.description, brief.audience, brief.offer])
    return [s for s in _sentences(text) if claim_reason(s)]


def _supplied(sentence: str, brief_claims: list[str], brief_numbers: set[str]) -> bool:
    if not brief_claims:
        return False
    if set(_NUMBER.findall(sentence)) - brief_numbers:
        return False  # a figure the brief does not have is invented
    words = _content_words(sentence)
    if not words:
        return False
    return any(len(words & _content_words(c)) / len(words) >= 0.5 for c in brief_claims)


def _fields(board: Storyboard) -> list[tuple[str, str]]:
    out = [("title", board.title), ("cta_text", board.cta_text)]
    for i, scene in enumerate(board.scenes):
        out += [
            (f"scenes.{i}.description", scene.description),
            (f"scenes.{i}.voiceover", scene.voiceover),
            (f"scenes.{i}.on_screen_text", scene.on_screen_text),
        ]
    out += [(f"hooks.{i}.text", hook.text) for i, hook in enumerate(board.hooks)]
    return out


def flag_testimonials(board: Storyboard, brief: Brief) -> list[StoryboardFlag]:
    """Every storyboard line with a claim of use, experience, results, reviews or awards
    that the brief does not supply. Prompts sent to the image and video models are not
    checked: they are never shown or spoken."""
    claims = _brief_claims(brief)
    numbers = set(_NUMBER.findall("\n".join([brief.description, brief.audience, brief.offer])))
    flags: list[StoryboardFlag] = []
    for field, text in _fields(board):
        for sentence in _sentences(text):
            reason = claim_reason(sentence)
            if reason and not _supplied(sentence, claims, numbers):
                flags.append(StoryboardFlag(field=field, text=sentence, reason=reason))
    return flags


def fix_instructions(flags: list[StoryboardFlag]) -> str:
    """Feedback for the one regeneration: the lines to rewrite and why."""
    lines = "\n".join(f'- {f.field}: "{f.text}" ({f.reason})' for f in flags)
    return (
        "Your previous storyboard broke the testimonial rule in these lines. Write the storyboard again and "
        "rewrite them without first-person claims of use, experience or results, reviews, ratings, awards or "
        f"time-based results that the brief does not state:\n{lines}"
    )
