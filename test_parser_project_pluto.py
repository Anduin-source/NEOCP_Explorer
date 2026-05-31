"""Regression tests for the Project Pluto parser.

These tests do not call the internet. They read saved HTML responses from
Project Pluto and verify that NEO_Tracker.py can still parse them.

Run from the repository root:
    python test_parser_project_pluto.py
"""
from pathlib import Path

from NEO_Tracker import split_project_pluto_output, parse_ephemeris_table_for_ui


DATA_DIR = Path("test_data")


def _load_fixture(filename: str) -> str:
    path = DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Missing fixture: {path}\n"
            "Run: python fetch_project_pluto_test_data.py"
        )
    return path.read_text(encoding="utf-8")


def _assert_common_parse_ok(html: str, expected_name_hint: str) -> None:
    elements, eph, obs, advanced = split_project_pluto_output(html, obs_code="X93")
    rows = parse_ephemeris_table_for_ui(eph)

    assert rows, "No ephemeris rows were parsed."

    first = rows[0]
    assert first.get("utc"), "UTC was not parsed."
    assert first.get("ra"), "RA was not parsed."
    assert first.get("dec"), "Dec was not parsed."
    assert first.get("mag"), "Magnitude was not parsed."
    assert first.get("elong"), "Elongation was not parsed."

    # These columns were added after the Find_Orb-local migration.
    assert "rate" in first, "Apparent motion rate column is missing."
    assert "motion_pa" in first, "Motion PA column is missing."

    combined_text = "\n".join([elements, eph, obs, advanced])
    assert expected_name_hint in combined_text, f"Object name hint {expected_name_hint!r} not found."

    # Basic sanity checks: values should be displayable and not blank.
    for i, row in enumerate(rows[:3], start=1):
        assert row.get("ra"), f"Row {i}: missing RA"
        assert row.get("dec"), f"Row {i}: missing Dec"
        assert row.get("mag"), f"Row {i}: missing mag"


def test_parse_neocp_fixture() -> None:
    html = _load_fixture("project_pluto_A11D0Xd.html")
    _assert_common_parse_ok(html, "A11D0Xd")


def test_parse_known_object_fixture() -> None:
    html = _load_fixture("project_pluto_99942.html")
    _assert_common_parse_ok(html, "99942")


def main() -> None:
    test_parse_neocp_fixture()
    print("OK: NEOCP fixture parsed")
    test_parse_known_object_fixture()
    print("OK: known-object fixture parsed")
    print("All parser regression tests passed.")


if __name__ == "__main__":
    main()
