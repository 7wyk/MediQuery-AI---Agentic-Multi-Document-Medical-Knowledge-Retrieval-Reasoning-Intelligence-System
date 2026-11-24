"""Generate a concise conversation title from a user's first question.

Deliberately deterministic: a title is derived locally (no provider call, no
cost, no latency, no failure mode) and only ever produced once, when the
conversation is created.  Manually renamed titles are therefore never
overwritten by later messages.
"""

from __future__ import annotations

import re
from typing import List

MAX_WORDS = 7
MAX_CHARS = 64
DEFAULT_TITLE = "New chat"

# Longest first so the most specific lead-in wins.
_LEADING_PHRASES: List[str] = [
    "i would like to know",
    "i would like to understand",
    "i want to know",
    "i need to know",
    "explain the difference between",
    "explain the differences between",
    "explain the difference",
    "find the evidence supporting",
    "find the evidence for",
    "find evidence for",
    "compare the recommendations across",
    "compare recommendations across",
    "can you please",
    "could you please",
    "would you please",
    "summarise my",
    "summarize my",
    "summarise the",
    "summarize the",
    "tell me about",
    "explain to me",
    "what are the",
    "what is the",
    "what does the",
    "what are",
    "what is",
    "what does",
    "how do i",
    "how do you",
    "how can i",
    "how should",
    "how to",
    "can you",
    "could you",
    "would you",
    "please",
    "give me",
    "list the",
    "explain what",
    "explain how",
    "explain why",
    "explain",
    "summarise",
    "summarize",
    "compare",
    "describe",
]

_TRAILING_STOPWORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "is", "of",
    "on", "or", "the", "to", "with", "about", "vs", "versus",
}

_TITLE_CASE_ACRONYMS = {"hba1c", "bmi", "ecg", "ct", "mri", "who", "nice", "cdc", "uspstf"}


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _strip_leading(text: str) -> str:
    lowered = text.lower()
    for phrase in _LEADING_PHRASES:
        if not lowered.startswith(phrase):
            continue
        remainder = text[len(phrase) :].strip(" ,:;-—")
        # Keep the original question when stripping would leave a fragment.
        if len(remainder.split()) >= 2:
            return remainder
    return text


def _difference_to_comparison(text: str) -> str:
    match = re.match(
        r"^(?:explain\s+)?(?:the\s+)?diff(?:erence|erences) between (.+?) and (.+)$",
        text,
        re.I,
    )
    if not match:
        return text
    left = match.group(1).strip(" ,.")
    right = match.group(2).strip(" ,.")
    if not left or not right:
        return text
    return f"{left} vs {right}"


def _capitalise_first(text: str) -> str:
    if not text:
        return text
    for index, char in enumerate(text):
        if char.isalpha():
            return f"{text[:index]}{char.upper()}{text[index + 1:]}"
    return text


def _restore_acronyms(text: str) -> str:
    """Keep clinical acronyms readable while leaving the user's words intact."""

    def repl(match: re.Match) -> str:
        word = match.group(0)
        return word.upper() if word.lower() in _TITLE_CASE_ACRONYMS else word

    return re.sub(r"\b[A-Za-z]{2,7}\b", repl, text)


def generate_conversation_title(question: str, max_words: int = MAX_WORDS) -> str:
    """Return a 3-7 word title, never quoted and never longer than 64 chars."""

    text = _collapse(question.replace("\u2019", "'"))
    text = text.strip("\"'\u201c\u201d ")
    # Drop a trailing question mark or sentence punctuation.
    text = re.sub(r"[\s?.,;:!]+$", "", text)
    if not text:
        return DEFAULT_TITLE

    text = _strip_leading(_difference_to_comparison(text))
    text = _collapse(text).strip(" ,:;-")

    words = text.split()
    if not words:
        return DEFAULT_TITLE

    trimmed = words[:max_words]
    while len(trimmed) > 1 and trimmed[-1].lower() in _TRAILING_STOPWORDS:
        trimmed.pop()
    title = _restore_acronyms(_capitalise_first(" ".join(trimmed)))

    if len(title) > MAX_CHARS:
        title = title[:MAX_CHARS].rsplit(" ", 1)[0].rstrip(" ,;:-")
    title = title.strip("\"'\u201c\u201d ")
    if len(title) < 2:
        return DEFAULT_TITLE
    return title
