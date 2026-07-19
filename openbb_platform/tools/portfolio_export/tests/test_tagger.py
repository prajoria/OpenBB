"""Tests for tagger.py — uses synthetic CSV data only.

Never reads or produces content that resembles a real portfolio export.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from portfolio_export.tagger import USER_ID_COL, TaggerError, tag_csv


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        for row in rows:
            w.writerow(row)


def _read_csv(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


def test_tag_csv_adds_column_and_renames(tmp_path: Path) -> None:
    src = tmp_path / "sample.csv"
    _write_csv(
        src,
        [
            ["col_a", "col_b", "col_c"],
            ["x1", "y1", "z1"],
            ["x2", "y2", "z2"],
        ],
    )

    out, n = tag_csv(src, "alice")

    assert out == tmp_path / "sample_alice.csv"
    assert n == 2
    assert src.exists(), "original must be preserved unless --replace"
    got = _read_csv(out)
    assert got[0] == ["col_a", "col_b", "col_c", USER_ID_COL]
    assert got[1] == ["x1", "y1", "z1", "alice"]
    assert got[2] == ["x2", "y2", "z2", "alice"]


def test_tag_csv_delete_original(tmp_path: Path) -> None:
    src = tmp_path / "sample.csv"
    _write_csv(src, [["h1", "h2"], ["a", "b"]])

    out, n = tag_csv(src, "bob", delete_original=True)

    assert out.exists()
    assert not src.exists()
    assert n == 1


def test_tag_csv_passes_through_footer_rows(tmp_path: Path) -> None:
    """Broker CSVs often append disclaimer/blank rows; those pass through unchanged."""
    src = tmp_path / "with_footer.csv"
    _write_csv(
        src,
        [
            ["h1", "h2", "h3"],
            ["a", "b", "c"],
            [],  # blank
            ["some footer disclaimer text"],  # short row
        ],
    )

    out, n = tag_csv(src, "carol")

    assert n == 1  # only the one true data row got tagged
    got = _read_csv(out)
    assert got[0] == ["h1", "h2", "h3", USER_ID_COL]
    assert got[1] == ["a", "b", "c", "carol"]
    # footer rows written through unmodified
    assert got[2] == []
    assert got[3] == ["some footer disclaimer text"]


def test_tag_csv_tolerates_trailing_comma_on_data_rows(tmp_path: Path) -> None:
    """Fidelity (and others) emit `a,b,c,` with a stray trailing comma on data rows.

    Header has 3 cols, data rows have 4 cells (last empty). We drop the
    empty and tag as usual — otherwise every real broker export would
    be misread as an all-footer file.
    """
    src = tmp_path / "trailing.csv"
    # csv.writer will faithfully emit an extra comma when a row has
    # an extra empty cell — that's exactly the shape we want to test.
    _write_csv(
        src,
        [
            ["h1", "h2", "h3"],
            ["a", "b", "c", ""],
            ["d", "e", "f", ""],
            ["some short footer"],
        ],
    )

    out, n = tag_csv(src, "ivy")

    assert n == 2
    got = _read_csv(out)
    assert got[0] == ["h1", "h2", "h3", USER_ID_COL]
    assert got[1] == ["a", "b", "c", "ivy"]
    assert got[2] == ["d", "e", "f", "ivy"]
    assert got[3] == ["some short footer"]  # untouched


def test_tag_csv_refuses_double_tag(tmp_path: Path) -> None:
    src = tmp_path / "already.csv"
    _write_csv(src, [["h1", USER_ID_COL], ["v", "prev"]])

    with pytest.raises(TaggerError, match="already present"):
        tag_csv(src, "dave")


def test_tag_csv_rejects_bad_user_id(tmp_path: Path) -> None:
    src = tmp_path / "s.csv"
    _write_csv(src, [["h"], ["v"]])

    for bad in ["", "has space", "semi;colon", "unicode\u00e9", "a" * 65]:
        with pytest.raises(TaggerError, match="user_id must match"):
            tag_csv(src, bad)


def test_tag_csv_rejects_missing_input(tmp_path: Path) -> None:
    with pytest.raises(TaggerError, match="input not found"):
        tag_csv(tmp_path / "nope.csv", "eve")


def test_tag_csv_rejects_output_equal_input(tmp_path: Path) -> None:
    src = tmp_path / "s.csv"
    _write_csv(src, [["h"], ["v"]])

    with pytest.raises(TaggerError, match="differ from input_path"):
        tag_csv(src, "frank", output_path=src)


def test_tag_csv_rejects_empty_file(tmp_path: Path) -> None:
    src = tmp_path / "empty.csv"
    src.write_text("", encoding="utf-8")

    with pytest.raises(TaggerError, match="CSV is empty"):
        tag_csv(src, "gina")


def test_tag_csv_explicit_output_path(tmp_path: Path) -> None:
    src = tmp_path / "s.csv"
    _write_csv(src, [["h"], ["v"]])
    dest = tmp_path / "sub" / "custom_name.csv"
    dest.parent.mkdir()

    out, n = tag_csv(src, "helen", output_path=dest)

    assert out == dest
    assert n == 1
    assert dest.exists()
