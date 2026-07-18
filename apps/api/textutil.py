"""Prose helpers so unverified placeholder feature names read honestly.

A descriptive placeholder like "Unnamed emergent marsh complex (Bergen
County)" is a fine standalone label, but mid-sentence it reads like a
proper noun ("...crosses the buffer of Unnamed emergent marsh complex").
`prose_ref` converts it to common-noun phrasing for use inside sentences,
while verified real names are left untouched.
"""
from __future__ import annotations

import re


def prose_ref(name: str, verified: bool, article: bool = True) -> str:
    """Return a mid-sentence-friendly reference to a feature.

    Verified names are returned as-is (they are genuine proper nouns, which
    take no article: "...distance to Great Swamp..."). Unverified
    placeholders are lowercased, their trailing "(County X)" is rewritten to
    "in County X", and an indefinite article is prepended so the phrase reads
    as a description: "...distance to an unnamed emergent marsh complex...".
    """
    if verified or not name:
        return name
    s = re.sub(r"\s*\(([^)]+)\)\s*$", r" in \1", name)
    if s and s[0].isupper() and not s[1:2].isupper():
        s = s[0].lower() + s[1:]
    if article:
        s = f"{indefinite(s)} {s}"
    return s


def indefinite(phrase: str) -> str:
    """Choose 'a' or 'an' for the leading word of a phrase."""
    return "an" if phrase[:1].lower() in "aeiou" else "a"
