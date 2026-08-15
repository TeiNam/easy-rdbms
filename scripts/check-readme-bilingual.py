#!/usr/bin/env python3
"""Fail when a factual number went stale in one README language section.

The English and Korean sections are not translations — they are written in their own voice, so
their prose will never line up and comparing it would only produce noise. Two specific numbers
*have* gone stale in one language while being corrected in the other, and those are what this
checks:

  1. Day counts (an integer-exhaustion runway). Corrected to ~2.5 days in English, left at
     ~5 days in Korean.
  2. The review finding total. Stated as 267 in both, when the listed rounds sum to 272.

Deliberately narrow: the smallest check that fails if either recurs. Note that the two sections
use different numbering systems for large values (Korean 억 = 10^8, English billion = 10^9), so
those are not comparable token-for-token and are not compared.

Usage: python3 scripts/check-readme-bilingual.py [README.md]
"""
import re
import sys

KOREAN_MARKER = "## 한국어"
DAYS = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?:days?|일)(?![\w])")
# "**272 issues**" / "**272건**"
TOTAL = re.compile(r"(\d[\d,]*)\s*(?:issues|건)")
# The per-round sequence, e.g. "33 → 18 → … → 116"
SEQUENCE = re.compile(r"(\d+(?:\s*→\s*\d+){3,})")


def fail(msg: str) -> None:
    print(f"  {msg}")


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "README.md"
    text = open(path, encoding="utf-8").read()
    if KOREAN_MARKER not in text:
        print(f"FAIL {path}: no '{KOREAN_MARKER}' section — cannot compare")
        return 1
    split = text.index(KOREAN_MARKER)
    english, korean = text[:split], text[split:]

    problems = []

    en_days, ko_days = set(DAYS.findall(english)), set(DAYS.findall(korean))
    for value in sorted(en_days - ko_days):
        problems.append(f"{value} days: English only — was the Korean section left stale?")
    for value in sorted(ko_days - en_days):
        problems.append(f"{value} days: Korean only — was the English section left stale?")

    # Every stated total must equal the sum of the round sequence it accompanies.
    sequences = SEQUENCE.findall(text)
    expected = None
    if sequences:
        rounds = [int(n) for n in re.findall(r"\d+", sequences[0])]
        expected = sum(rounds)
        for other in sequences[1:]:
            if [int(n) for n in re.findall(r"\d+", other)] != rounds:
                problems.append("the per-round sequences disagree between sections")
    for section_name, section in (("English", english), ("Korean", korean)):
        for value in TOTAL.findall(section):
            stated = int(value.replace(",", ""))
            if expected is not None and stated != expected and stated > 100:
                problems.append(
                    f"{section_name} states {stated} findings but the listed rounds sum to {expected}"
                )

    if problems:
        print(f"FAIL {path}:")
        for p in problems:
            fail(p)
        return 1

    detail = f"days paired: {sorted(en_days) or 'none'}"
    if expected is not None:
        detail += f"; round total {expected} consistent"
    print(f"ok {path}: {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
