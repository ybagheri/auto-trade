"""The two documentation sets must not drift apart.

An English page with no Persian counterpart is a translation debt that nobody
sees until someone needs it, so the pairs are listed here and the test fails when
one side is added, renamed, or deleted. This is the whole point: the failure is
cheap to fix at the moment a page is written, and expensive to discover later.

It also checks that each page links to its counterpart, so a reader who lands on
one language can find the other. That is a small courtesy, but a translation
nobody can find is not much use to the person who needs it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
FA = DOCS / "fa"

# Every page that exists in both languages. Adding a pair is a deliberate act:
# the new name goes here, and the test below then requires the link both ways.
PAIRS: tuple[str, ...] = (
    "DASHBOARD.md",
    "EXECUTION.md",
    "METRICS.md",
    "POSITION_READER.md",
    "RECOVERY.md",
    "SAFETY.md",
    "SIGNAL_PROTOCOL.md",
    "STRATEGY_INTEGRATION.md",
    "TRACEABILITY.md",
)

# Pages that are deliberately English-only. Each needs a reason, because the
# default answer to "why is this one missing?" should be a decision, not an
# oversight. These are developer- and operator-facing references rather than
# pages someone reads while a trade is refused, so they are tracked here and
# left untranslated deliberately.
ENGLISH_ONLY: dict[str, str] = {
    "ARCHITECTURE.md": "internal design record; the layer rules it states are enforced by mypy",
    "ARCHITECTURE_ASSESSMENT.md": "a point-in-time assessment of an early state of the code",
    "CONFIGURATION.md": "a variable reference read while configuring, alongside .env.example",
    "COMPLIANCE.md": "a legal and policy position that must not exist in a second wording",
    "TESTING.md": "an executed-results record; the numbers would drift between languages",
    "VERIFICATION.md": "developer-facing, describing the verification code paths",
    "STATUS.md": "the single page both languages link to first, kept in one wording",
    "PACKAGING.md": "build and installer instructions for the packaging scripts",
    "MT5_INTEGRATION.md": "machine-specific paths and process discovery details",
    "MT5_DEMO_VALIDATION.md": "a measured validation record whose rows must not be reworded",
}

LINK = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def links(path: Path) -> set[str]:
    return {target for _, target in LINK.findall(read(path))}


@pytest.mark.parametrize("name", PAIRS)
def test_a_persian_translation_exists_for_every_page(name: str) -> None:
    assert (DOCS / name).is_file(), f"missing English page: docs/{name}"
    assert (FA / name).is_file(), (
        f"docs/{name} has no Persian translation at docs/fa/{name}. Add the page to "
        f"PAIRS in this file only once the translation exists."
    )


@pytest.mark.parametrize("name", PAIRS)
def test_each_page_links_to_its_translation(name: str) -> None:
    """A translation nobody can find is not much use to the reader who needs it."""
    assert f"fa/{name}" in links(DOCS / name), f"docs/{name} does not link to docs/fa/{name}"
    assert name in links(FA / name), f"docs/fa/{name} does not link back to docs/{name}"


def test_every_file_in_the_persian_directory_is_a_known_page() -> None:
    """An orphan translation is a page no English reader is told about.

    Only the translated pairs belong here. A page listed in ``ENGLISH_ONLY`` has
    no file under ``docs/fa`` at all, which the next test checks.
    """
    present = {path.name for path in FA.glob("*.md")}

    assert present == set(PAIRS), (
        f"docs/fa holds {sorted(present - set(PAIRS))} which are not a translated "
        f"pair, and is missing {sorted(set(PAIRS) - present)}"
    )


def test_every_page_is_either_translated_or_exempted() -> None:
    """No page may fall through both lists, which is how the gap started."""
    every_page = {path.name for path in DOCS.glob("*.md")}

    assert set(PAIRS) | set(ENGLISH_ONLY) == every_page, (
        f"unaccounted for: {sorted(every_page - set(PAIRS) - set(ENGLISH_ONLY))}"
    )
    assert not (set(PAIRS) & set(ENGLISH_ONLY)), (
        f"listed as both translated and English-only: {sorted(set(PAIRS) & set(ENGLISH_ONLY))}"
    )


def relative_targets(path: Path) -> list[str]:
    """Every link in *path* that names a file on disk rather than a web address."""
    targets = []
    for _, target in LINK.findall(read(path)):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        cleaned = target.split("#")[0]
        if cleaned:
            targets.append(cleaned)
    return targets


def documentation_files() -> list[Path]:
    return sorted(DOCS.rglob("*.md")) + [
        ROOT / "README.md",
        ROOT / "README.fa.md",
        ROOT / "ROADMAP.md",
    ]


@pytest.mark.parametrize("path", documentation_files(), ids=lambda p: p.name)
def test_every_relative_link_resolves(path: Path) -> None:
    """A link to a page that is not there is worse than no link at all.

    The Persian pages under `docs/fa/` are the risk here: a link to a sibling
    needs no prefix, while a link to the English `docs/` root needs `../`. Both
    were written wrong on the first pass.
    """
    broken = [
        target for target in relative_targets(path) if not (path.parent / target).is_file()
    ]

    assert not broken, (
        f"{path.relative_to(ROOT)} links to {broken}, which do not exist. A page "
        f"under docs/fa/ needs no prefix for a sibling and ../ for docs/."
    )


def test_an_english_only_page_states_why() -> None:
    """The exemption is a decision with a reason, not a silent gap."""
    for name, reason in ENGLISH_ONLY.items():
        assert reason.strip(), f"docs/{name} is marked English-only with no reason given"
        assert (DOCS / name).is_file()
        assert not (FA / name).exists(), (
            f"docs/{name} is listed as English-only but a translation now exists"
        )


def test_the_readme_documents_both_languages_of_every_page() -> None:
    """The README is the index, so a page missing from it is a page nobody finds."""
    index = read(ROOT / "README.md")
    persian_index = read(ROOT / "README.fa.md")

    for name in PAIRS:
        assert f"docs/{name}" in index, f"README.md does not list docs/{name}"
        assert f"docs/fa/{name}" in persian_index, (
            f"README.fa.md does not list docs/fa/{name}"
        )


def test_a_translation_does_not_silently_drop_a_safety_section() -> None:
    """The refusal rules are the part that must not be lost in translation.

    Each of these pages states what the code refuses to do. A translation that
    keeps the prose but loses the refusals would be more dangerous than no
    translation at all, so the English source of each refusal is required to
    survive.
    """
    expected = {
        "EXECUTION.md": "refused by default",
        "RECOVERY.md": "No automatic recovery action is provided",
        "DASHBOARD.md": "Loopback only",
        "METRICS.md": "What these figures are not",
    }

    for name, marker in expected.items():
        assert marker in read(DOCS / name), f"docs/{name} no longer states: {marker}"

    # The Persian pages must each carry a section equivalent to it. These are
    # the headings, checked verbatim so a rename breaks the test rather than
    # quietly dropping the subject.
    for name, heading in {
        "EXECUTION.md": "## دروازه‌ها",
        "RECOVERY.md": "## قواعد",
        "DASHBOARD.md": "## ویژگی‌های ایمنی",
        "METRICS.md": "## این اعداد چه نیستند",
    }.items():
        assert heading in read(FA / name), f"docs/fa/{name} is missing the section {heading}"


def test_the_persian_pages_keep_the_codes_they_describe() -> None:
    """Refusal messages and identifiers are quoted verbatim and must not drift.

    A translated page is the easiest place for a copied identifier to pick up a
    typo, and these strings are what an operator compares against real output.
    """
    expected: dict[str, tuple[str, ...]] = {
        "EXECUTION.md": (
            "10408",
            "10409",
            "10325",
            "33033",
            "AUTO_TRADE_ENABLE_EXECUTION",
            "AUTO_TRADE_ENABLE_CLOSE",
            "duplicate signal id",
        ),
        "RECOVERY.md": (
            "REQUESTED",
            "UNKNOWN_EXECUTION",
            "idempotency.json",
            "operator-reconciled, not observed by this application",
        ),
        "DASHBOARD.md": ("127.0.0.1", "::1", "X-Auto-Trade-Token", "hmac.compare_digest"),
        "METRICS.md": (
            "unresolved_attempts",
            "click_to_outcome",
            "truncated",
            "SIGNAL_RECEIVED",
            "EXECUTION_DETECTED",
        ),
    }

    for name, values in expected.items():
        persian = read(FA / name)
        for value in values:
            assert value in persian, f"docs/fa/{name} is missing the literal {value!r}"


def test_the_persian_execution_page_lists_every_gate_the_english_one_does() -> None:
    """The gate table is the page's substance, so its rows must match in number."""
    english_rows = read(DOCS / "EXECUTION.md").count("| `")
    persian_rows = read(FA / "EXECUTION.md").count("| `")

    assert persian_rows == english_rows, (
        f"the Persian gate table has {persian_rows} rows and the English one has "
        f"{english_rows}; a gate may have been added on one side only"
    )
