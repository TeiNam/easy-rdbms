#!/usr/bin/env python3
"""Fail when a factual number in the README disagrees with reality or with the other language.

The English and Korean sections are not translations — they are written in their own voice, so
their prose will never line up and comparing it would only produce noise. Three specific numbers
*have* gone stale, and those are what this checks:

  1. Day counts (an integer-exhaustion runway). Corrected to ~2.5 days in English, left at
     ~5 days in Korean.
  2. The review finding total. Stated as 267 in both, when the listed rounds sum to 272.
  3. The reference-file count. Stated as eleven in both, when `rdbms-modeling` carries ten —
     the eleventh, `cost-evaluation.md`, belongs to `db-select`. Unlike 1 and 2 this one is
     checkable against the filesystem, so the count, the listed filenames, and the directory
     all have to agree.

Deliberately narrow: the smallest check that fails if any recurs. Note that the two sections
use different numbering systems for large values (Korean 억 = 10^8, English billion = 10^9), so
those are not comparable token-for-token and are not compared.

Usage: python3 scripts/check-readme-bilingual.py [README.md]
"""
import re
import sys
from pathlib import Path

KOREAN_MARKER = "## 한국어"
DAYS = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?:days?|일)(?![\w])")
# "**272 issues**" / "**272건**"
TOTAL = re.compile(r"(\d[\d,]*)\s*(?:issues|건)")
# The per-round sequence, e.g. "33 → 18 → … → 116"
SEQUENCE = re.compile(r"(\d+(?:\s*→\s*\d+){3,})")

# "**ten reference files**" / "three stages, ten reference files" / "Eleven reference files"
CLAIM_EN = re.compile(r"([A-Za-z]+|\d+)\s+reference files")
# "(참조파일 10개)" / "3단계와 참조파일 10개"
CLAIM_KO = re.compile(r"참조파일\s*(\d+)\s*개")
# A reference-file table row: "| `normalization.md` | … |"
TABLE_ROW = re.compile(r"^\|\s*`([^`]+\.md)`\s*\|")
# A claim is skill-scoped when the skill is named near it; otherwise it counts the whole plugin.
SCOPE_WINDOW = 140
OWNING_SKILL = "rdbms-modeling"
NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}


def as_count(token: str) -> int | None:
    """A claim's quantity, or None when the captured word is not a number ('The reference files')."""
    if token.isdigit():
        return int(token)
    return NUMBER_WORDS.get(token.lower())


def listed_reference_files(section: str) -> list[str] | None:
    """Filenames from the section's reference-file table, found by shape rather than by prose.

    Prose anchors get reworded; a table whose rows all start with a backticked `*.md` does not.
    """
    best = None
    rows: list[str] = []
    for line in section.split("\n"):
        match = TABLE_ROW.match(line.strip())
        if match:
            rows.append(match.group(1))
            continue
        if rows:
            if len(rows) > len(best or []):
                best = rows
            rows = []
    if len(rows) > len(best or []):
        best = rows
    # Two or three .md rows would be an ordinary mention, not the reference table.
    return best if best and len(best) >= 5 else None


def check_reference_files(english: str, korean: str, repo_root: Path) -> tuple[list[str], str | None]:
    """Reference-file counts and filenames, cross-checked against skills/ on disk."""
    skills = repo_root / "skills"
    owned = skills / OWNING_SKILL / "references"
    if not owned.is_dir():
        # Running against a README outside the repo — nothing to cross-check. Say so:
        # a check that quietly degrades to passing is worse than one that is absent,
        # because `ok` then means two different things.
        return [], f"reference-file check SKIPPED ({skills} not found)"

    on_disk = sorted(p.name for p in owned.glob("*.md"))
    plugin_wide = sum(1 for p in skills.glob("*/references/*.md"))
    problems = []

    for name, section, pattern in (
        ("English", english, CLAIM_EN),
        ("Korean", korean, CLAIM_KO),
    ):
        for match in pattern.finditer(section):
            stated = as_count(match.group(1))
            if stated is None:
                continue
            window = section[max(0, match.start() - SCOPE_WINDOW) : match.end() + SCOPE_WINDOW]
            if OWNING_SKILL in window:
                if stated != len(on_disk):
                    problems.append(
                        f"{name} claims {stated} reference files for `{OWNING_SKILL}`, "
                        f"but {owned.relative_to(repo_root)}/ holds {len(on_disk)}"
                    )
            elif stated != plugin_wide:
                problems.append(
                    f"{name} claims {stated} reference files plugin-wide, "
                    f"but skills/*/references/ holds {plugin_wide}"
                )

    for name, section in (("English", english), ("Korean", korean)):
        listed = listed_reference_files(section)
        if listed is None:
            problems.append(f"{name} has no reference-file table — did its shape change?")
            continue
        missing = sorted(set(on_disk) - set(listed))
        extra = sorted(set(listed) - set(on_disk))
        if missing:
            problems.append(f"{name} table omits {', '.join(missing)}")
        if extra:
            problems.append(
                f"{name} table lists {', '.join(extra)}, which `{OWNING_SKILL}` does not own — "
                f"a cross-reference row here is what made the count read as {len(listed)}"
            )

    return problems, f"{len(on_disk)} reference files match {OWNING_SKILL}/references/"


def fail(msg: str) -> None:
    print(f"  {msg}")


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "README.md")
    text = path.read_text(encoding="utf-8")
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

    reference_problems, reference_detail = check_reference_files(
        english, korean, path.resolve().parent
    )
    problems.extend(reference_problems)

    if problems:
        print(f"FAIL {path}:")
        # A count is usually claimed in more than one place per section, so the same sentence
        # would otherwise be printed once per claim site.
        for p in dict.fromkeys(problems):
            fail(p)
        return 1

    detail = f"days paired: {sorted(en_days) or 'none'}"
    if expected is not None:
        detail += f"; round total {expected} consistent"
    if reference_detail is not None:
        detail += f"; {reference_detail}"
    print(f"ok {path}: {detail}")
    if reference_detail and "SKIPPED" in reference_detail:
        print("  note: run this from the repo root for the reference-file cross-check to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
