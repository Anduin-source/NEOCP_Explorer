"""Download small Project Pluto HTML fixtures for parser regression tests.

Run from the repository root:
    python fetch_project_pluto_test_data.py

If a NEOCP designation is no longer available, replace A11D0Xd below with a
current NEOCP candidate from the left panel of the app.
"""
from pathlib import Path
import requests

PROJECT_PLUTO_URL = "https://www.projectpluto.com/cgi-bin/fo/fo_serve.cgi"

# Keep one known object and one NEOCP-style object.
# If A11D0Xd disappears from NEOCP, replace it with a current candidate.
OBJECTS = {
    "project_pluto_A11D0Xd.html": "A11D0Xd",
    "project_pluto_99942.html": "99942",
}

BASE_PARAMS = {
    "year": "now",
    "n_steps": 10,
    "stepsize": "1h",
    "mpc_code": "X93",
    "faint_limit": 99,
    "ephem_type": 0,
    "sigmas": "on",
    "element_center": -2,
    "epoch": "default",
    "resids": 0,
    "language": "e",
    "file_no": 0,
}

HEADERS = {
    "User-Agent": "NEOCP Explorer parser fixture downloader (https://github.com/Anduin-source/NEOCP_Explorer)"
}


def download_fixture(filename: str, object_name: str) -> None:
    params = dict(BASE_PARAMS)
    params["obj_name"] = object_name

    print(f"Downloading {object_name} ...")
    response = requests.get(PROJECT_PLUTO_URL, params=params, headers=HEADERS, timeout=30)
    response.raise_for_status()

    text = response.text
    if "Ephemerides for" not in text:
        raise RuntimeError(
            f"Project Pluto did not return an ephemeris table for {object_name}.\n"
            "If this is the NEOCP object, replace it with a current candidate."
        )

    out_dir = Path("test_data")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / filename
    out_path.write_text(text, encoding="utf-8")
    print(f"Saved {out_path}")


def main() -> None:
    for filename, object_name in OBJECTS.items():
        download_fixture(filename, object_name)
    print("Done.")


if __name__ == "__main__":
    main()
