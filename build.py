#!/usr/bin/env python3
"""csv-flashcards-site: turn CSV files of terms into a static flashcard study site.

Reads every ``*.csv`` in a data directory, treats the first row as headers
(side labels for each deck), the first column as the card front and the
second column as the card back, then writes a self-contained static site:

  index.html   flip cards with shuffle, reverse and know / don't-know sorting
  print.html   a no-frills printable sheet of every card

Everything is embedded in the HTML, so the site runs offline directly from
``file://`` and works on GitHub Pages without any JavaScript editing.

Uses only the Python standard library. Python 3.8+.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from pathlib import Path

REQUIRED_COLUMNS = 2
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


class BuildError(Exception):
    """A user-facing problem with the input CSVs or arguments."""


def parse_csv(path: Path) -> dict:
    """Parse one CSV file into a deck dict.

    Row 1 is the header row: column 1 names the card front, column 2 names
    the card back. Extra columns are ignored. The deck name is the filename
    stem, title-cased.
    """
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = [row for row in csv.reader(handle) if any(cell.strip() for cell in row)]

    if not rows:
        raise BuildError(f"{path.name}: file contains no rows")

    header = [cell.strip() for cell in rows[0]]
    if len(header) < REQUIRED_COLUMNS:
        raise BuildError(
            f"{path.name}: header row needs at least {REQUIRED_COLUMNS} columns "
            f"(card front and card back), found {len(header)}"
        )

    front_label, back_label = header[0], header[1]
    if not front_label or not back_label:
        raise BuildError(f"{path.name}: header row has an empty column name")

    cards = []
    for line_no, row in enumerate(rows[1:], start=2):
        front = row[0].strip() if len(row) > 0 else ""
        back = row[1].strip() if len(row) > 1 else ""
        if not front or not back:
            print(
                f"warning: {path.name} line {line_no}: skipping row with an "
                f"empty front or back",
                file=sys.stderr,
            )
            continue
        cards.append({"id": line_no, "front": front, "back": back})

    if not cards:
        raise BuildError(f"{path.name}: no complete cards found under the header row")

    return {
        "name": path.stem.replace("-", " ").replace("_", " ").title(),
        "slug": path.stem,
        "front_label": front_label,
        "back_label": back_label,
        "cards": cards,
    }


def load_decks(data_dir: Path) -> list[dict]:
    """Load every CSV in data_dir as a deck, sorted by filename."""
    csv_paths = sorted(data_dir.glob("*.csv"))
    if not csv_paths:
        raise BuildError(f"no CSV files found in {data_dir}")
    return [parse_csv(path) for path in csv_paths]


def render(template_name: str, replacements: dict) -> str:
    """Read a template file and substitute {{PLACEHOLDER}} tokens."""
    template_path = TEMPLATE_DIR / template_name
    text = template_path.read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def decks_json_string(decks: list[dict]) -> str:
    """Serialize decks for embedding inside a <script> tag.

    ``</`` is escaped so a card can never close the script element, which
    keeps the embedded data safe even for adversarial CSV content.
    """
    return json.dumps(decks, ensure_ascii=False, indent=1).replace("</", "<\\/")


def total_cards(decks: list[dict]) -> int:
    return sum(len(deck["cards"]) for deck in decks)


def build_site(data_dir: Path, out_dir: Path, title: str = "Flashcards") -> dict:
    """Build the static site from data_dir into out_dir. Returns a summary."""
    if not data_dir.is_dir():
        raise BuildError(f"data directory not found: {data_dir}")

    decks = load_decks(data_dir)
    if total_cards(decks) == 0:
        raise BuildError("every deck is empty; nothing to build")

    index_html = render(
        "index.html",
        {
            "TITLE": html.escape(title),
            "GENERATED_NOTE": html.escape(
                f"Generated from {total_cards(decks)} cards in "
                f"{len(decks)} deck(s)."
            ),
            "DECKS_JSON": decks_json_string(decks),
            "DECK_OPTIONS": "\n".join(
                f'<option value="{i}">{html.escape(deck["name"])} '
                f'({len(deck["cards"])} cards)</option>'
                for i, deck in enumerate(decks)
            ),
        },
    )
    print_html = render(
        "print.html",
        {
            "TITLE": html.escape(title) + " — Print Sheet",
            "DECK_SECTIONS": "\n".join(print_deck_section(deck) for deck in decks),
        },
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(index_html, encoding="utf-8")
    (out_dir / "print.html").write_text(print_html, encoding="utf-8")

    return {"decks": len(decks), "cards": total_cards(decks), "out_dir": out_dir}


def print_deck_section(deck: dict) -> str:
    """Render one deck as a plain printable table."""
    rows = []
    for n, card in enumerate(deck["cards"], start=1):
        rows.append(
            "<tr>"
            f'<td class="num">{n}</td>'
            f'<td class="front">{html.escape(card["front"])}</td>'
            f'<td class="back">{html.escape(card["back"])}</td>'
            "<td class=\"mark\">☐</td>"
            "</tr>"
        )
    heading = (
        f"<h2>{html.escape(deck['name'])}"
        f'<span class="labels"> {html.escape(deck["front_label"])} → '
        f'{html.escape(deck["back_label"])}</span></h2>'
    )
    table = (
        "<table>"
        "<thead><tr>"
        f"<th>#</th><th>{html.escape(deck['front_label'])}</th>"
        f"<th>{html.escape(deck['back_label'])}</th><th>Known?</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )
    return f'<section class="deck">{heading}{table}</section>'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="csv-flashcards-site",
        description="Build a static flashcard study site from CSV files.",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="directory containing CSV decks (default: data)",
    )
    parser.add_argument(
        "--out-dir",
        default="site",
        help="directory to write the generated site (default: site)",
    )
    parser.add_argument(
        "--title",
        default="Flashcards",
        help="site title shown in the header and print sheet",
    )
    args = parser.parse_args(argv)

    try:
        summary = build_site(Path(args.data_dir), Path(args.out_dir), args.title)
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"built {summary['decks']} deck(s), {summary['cards']} card(s) "
        f"into {summary['out_dir']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
