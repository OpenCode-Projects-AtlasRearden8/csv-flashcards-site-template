"""Tests for csv-flashcards-site's build script.

Each test builds a site into a temporary directory from temporary CSV data
and makes assertions about the generated files and their structure.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = PROJECT_ROOT / "build.py"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def write_csv(data_dir: Path, name: str, text: str) -> None:
    path = data_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run_build(tmp_path: Path, data_dir_name: str = "data") -> list[Path]:
    """Run build.py as a subprocess and return list of generated files."""
    out_dir = tmp_path / "site"
    result = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--data-dir", str(tmp_path / data_dir_name), "--out-dir", str(out_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return sorted(p.name for p in out_dir.iterdir())


def extract_decks(index_html: str) -> list[dict]:
    """Pull the embedded DECKS JSON back out of a generated index.html."""
    match = re.search(r"var DECKS = (\[.*?\]);\n", index_html, re.S)
    assert match, "generated index.html must embed the decks JSON"
    payload = match.group(1)
    # the build escapes "</" so the payload cannot close its <script> tag
    return json.loads(payload.replace("<\\/", "</"))


# ---------------------------------------------------------------------------
# structure and content
# ---------------------------------------------------------------------------


def test_build_writes_expected_files(tmp_path: Path) -> None:
    write_csv(
        tmp_path,
        "data/colors.csv",
        "Color,Example\nRed,stop sign\nGreen,grass\n",
    )
    assert run_build(tmp_path) == ["index.html", "print.html"]


def test_deck_name_and_labels_come_from_file_and_headers(tmp_path: Path) -> None:
    write_csv(
        tmp_path,
        "data/myDeck_1-english.csv",
        "Word,Meaning\nhola,hello\n",
    )
    run_build(tmp_path)
    decks = extract_decks((tmp_path / "site" / "index.html").read_text(encoding="utf-8"))
    assert len(decks) == 1
    deck = decks[0]
    assert deck["name"] == "Mydeck 1 English"
    assert deck["front_label"] == "Word"
    assert deck["back_label"] == "Meaning"
    assert deck["cards"] == [{"id": 2, "front": "hola", "back": "hello"}]


def test_multi_csv_data_dir_produces_one_deck_per_file(tmp_path: Path) -> None:
    write_csv(tmp_path, "data/aa-first.csv", "A,B\none,1\n")
    write_csv(tmp_path, "data/bb-second.csv", "A,B\nthree,3\ntwo,2\n")
    run_build(tmp_path)
    decks = extract_decks((tmp_path / "site" / "index.html").read_text(encoding="utf-8"))
    # decks are sorted by filename
    assert [d["name"] for d in decks] == ["Aa First", "Bb Second"]
    assert len(decks[0]["cards"]) == 1
    assert len(decks[1]["cards"]) == 2


def test_generated_index_contains_ui_contracts(tmp_path: Path) -> None:
    write_csv(tmp_path, "data/deck.csv", "Term,Definition\nalpha,first\n")
    run_build(tmp_path)
    html_text = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")

    # every feature the site promises is present in the page markup
    for anchor in (
        "id=\"shuffle-btn\"",
        "id=\"order-btn\"",
        "id=\"reverse-toggle\"",
        "class=\"judge\"",
        "id=\"know-btn\"",
        "id=\"dunno-btn\"",
        "id=\"review-unknown-btn\"",
        "id=\"deck-select\"",
        "href=\"print.html\"",
        "class=\"face front\"",
        "class=\"face back\"",
    ):
        assert anchor in html_text, f"missing UI element: {anchor}"

    # keyboard + flip behaviour is wired up
    for snippet in ("flip", "keydown", "ArrowLeft", "ArrowRight", "shuffled"):
        assert snippet in html_text

    # no unfinished template slots end up in the output
    assert "{{" not in html_text
    assert "}}" not in html_text


def test_print_sheet_lists_every_card_as_a_row(tmp_path: Path) -> None:
    write_csv(
        tmp_path,
        "data/animals.csv",
        "Animal,Sound\ncat,meow\ndog,woof\n",
    )
    run_build(tmp_path)
    print_html = (tmp_path / "site" / "print.html").read_text(encoding="utf-8")

    for fragment in ("cat", "meow", "dog", "woof"):
        assert fragment in print_html

    assert print_html.count("<tr>") == 3  # one header row + two card rows
    assert print_html.count("<h2>") == 1
    assert "Animal" in print_html and "Sound" in print_html
    assert "href=\"index.html\"" in print_html


def test_custom_title_appears_in_both_pages(tmp_path: Path) -> None:
    write_csv(tmp_path, "data/deck.csv", "A,B\nx,y\n")
    out_dir = tmp_path / "site"
    result = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--data-dir", str(tmp_path / "data"), "--out-dir", str(out_dir), "--title", "Study Time"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Study Time" in (out_dir / "index.html").read_text(encoding="utf-8")
    assert "Study Time" in (out_dir / "print.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# safety and robustness
# ---------------------------------------------------------------------------


def test_html_escapes_js_breaking_content(tmp_path: Path) -> None:
    write_csv(
        tmp_path,
        "data/evil.csv",
        "Term,Definition\n<script>alert(1)</script>,quote</script>test\n",
    )
    run_build(tmp_path)
    index_html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")

    # a raw "</script>" from the CSV must never appear in the JSON payload,
    # or it would terminate the script element and inject markup
    assert "</script>alert" not in index_html
    decks = extract_decks(index_html)
    assert decks[0]["cards"][0]["front"] == "<script>alert(1)</script>"
    assert decks[0]["cards"][0]["back"] == "quote</script>test"

    # the print sheet escapes the same content for HTML display
    print_html = (tmp_path / "site" / "print.html").read_text(encoding="utf-8")
    assert "<script>" not in print_html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in print_html


def test_blank_rows_and_lines_are_tolerated(tmp_path: Path) -> None:
    write_csv(
        tmp_path,
        "data/gaps.csv",
        "Front,Back\n\none,uno\n,,\ntwo,dos\n",
    )
    run_build(tmp_path)
    decks = extract_decks((tmp_path / "site" / "index.html").read_text(encoding="utf-8"))
    fronts = [c["front"] for c in decks[0]["cards"]]
    assert fronts == ["one", "two"]


def test_unicode_content_survives_the_round_trip(tmp_path: Path) -> None:
    write_csv(tmp_path, "data/spanish.csv", "Español,English\npiñata,pinata — ¡olé!\n")
    run_build(tmp_path)
    decks = extract_decks((tmp_path / "site" / "index.html").read_text(encoding="utf-8"))
    assert decks[0]["cards"][0]["back"] == "pinata — ¡olé!"


def test_build_is_deterministic(tmp_path: Path) -> None:
    write_csv(tmp_path, "data/deck.csv", "A,B\none,1\ntwo,2\nthree,3\n")
    run_build(tmp_path)
    first = (tmp_path / "site" / "index.html").read_bytes()
    (tmp_path / "site" / "print.html").read_bytes()

    out2 = tmp_path / "site2"
    subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--data-dir", str(tmp_path / "data"), "--out-dir", str(out2)],
        capture_output=True,
        text=True,
    )
    assert (out2 / "index.html").read_bytes() == first


# ---------------------------------------------------------------------------
# failure modes
# ---------------------------------------------------------------------------


def build_fails(tmp_path: Path) -> str:
    result = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--data-dir", str(tmp_path / "data"), "--out-dir", str(tmp_path / "site")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    return result.stderr


def test_missing_data_dir_is_a_clean_error(tmp_path: Path) -> None:
    assert "not found" in build_fails(tmp_path)


def test_directory_without_csvs_is_a_clean_error(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    text_path = tmp_path / "data" / "notes.txt"
    text_path.write_text("not a csv", encoding="utf-8")
    assert "no CSV files" in build_fails(tmp_path)


def test_csv_with_single_header_column_is_rejected(tmp_path: Path) -> None:
    write_csv(tmp_path, "data/one-col.csv", "Term\napple\n")
    assert "at least 2 columns" in build_fails(tmp_path)


def test_empty_csv_file_is_rejected(tmp_path: Path) -> None:
    write_csv(tmp_path, "data/empty.csv", "")
    assert "no rows" in build_fails(tmp_path)


def test_header_only_csv_is_rejected(tmp_path: Path) -> None:
    write_csv(tmp_path, "data/header-only.csv", "Front,Back\n")
    assert "no complete cards" in build_fails(tmp_path)


def test_rows_missing_a_side_are_skipped_with_a_warning(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    csv_text = "Front,Back\none,uno\nonly-front\n"
    (tmp_path / "data" / "partial.csv").write_text(csv_text, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--data-dir", str(tmp_path / "data"), "--out-dir", str(tmp_path / "site")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "line 3" in result.stderr
    decks = extract_decks((tmp_path / "site" / "index.html").read_text(encoding="utf-8"))
    assert len(decks[0]["cards"]) == 1


# ---------------------------------------------------------------------------
# project sanity
# ---------------------------------------------------------------------------


def test_license_file_has_expected_copyright() -> None:
    license_text = (PROJECT_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Copyright (c) 2026 Asdale Dynamics, LLC" in license_text


def test_readme_credits_the_llc() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    assert "Asdale Dynamics, LLC" in readme


def test_sample_data_dir_builds(tmp_path: Path) -> None:
    out_dir = tmp_path / "site"
    result = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--data-dir", str(PROJECT_ROOT / "data"), "--out-dir", str(out_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    decks = extract_decks((out_dir / "index.html").read_text(encoding="utf-8"))
    assert len(decks) >= 2
    assert all(d["cards"] for d in decks)
