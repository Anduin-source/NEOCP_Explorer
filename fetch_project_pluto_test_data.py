"""Download Project Pluto responses for local parser diagnostics.

Downloaded responses are third-party material. They are stored only under the
Git-ignored .local_test_data directory and must not be committed or
redistributed. The repository's automated tests use synthetic fixtures instead.

Run from the repository root:
    python fetch_project_pluto_test_data.py
"""
from pathlib import Path
import requests

PROJECT_PLUTO_URL = "https://www.projectpluto.com/cgi-bin/fo/fo_serve.cgi"

OBJECTS = {
    "project_pluto_current_neocp.html": "A11D0Xd",
    "project_pluto_known_object.html": "99942",
}

BASE_PARAMS = {
    "year": "now",
    "n_steps": 10,
    "stepsize": "1h",
    "mpc_code": "X93",
    "faint_limit": 99,
    "ephem_type": 0,
    "sigmas": "on",
    "element_center": 0,
    "epoch": "default",
    "resids": 0,
    "language": "e",
    "file_no": 0,
}

HEADERS = {
    "User-Agent": (
        "NEOCP Explorer local parser diagnostics "
        "(https://github.com/Anduin-source/NEOCP_Explorer)"
    )
}

LOCAL_DATA_DIR = Path(".local_test_data")


def download_fixture(filename: str, object_name: str) -> None:
    params = dict(BASE_PARAMS)
    params["obj_name"] = object_name

    print(f"Downloading {object_name} for local diagnostics ...")
    response = requests.get(
        PROJECT_PLUTO_URL,
        params=params,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    text = response.text
    if "Ephemerides for" not in text:
        raise RuntimeError(
            f"Project Pluto did not return an ephemeris table for {object_name}."
        )

    LOCAL_DATA_DIR.mkdir(exist_ok=True)
    out_path = LOCAL_DATA_DIR / filename
    out_path.write_text(text, encoding="utf-8")
    print(f"Saved local-only response to {out_path}")


def main() -> None:
    print(
        "NOTICE: downloaded responses are for local diagnostics only; "
        "do not commit or redistribute them."
    )
    for filename, object_name in OBJECTS.items():
        download_fixture(filename, object_name)
    print("Done.")


if __name__ == "__main__":
    main()
