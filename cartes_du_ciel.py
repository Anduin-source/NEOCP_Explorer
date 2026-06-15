"""Small Cartes du Ciel / SkyChart TCP client for NEOCP Explorer.

This module communicates with the Cartes du Ciel/SkyChart TCP/IP server.
It intentionally keeps only the workflows used by NEOCP Explorer:

    1. Load a generated CdC Observing List file.
    2. Ask CdC to slew the telescope to selected RA/Dec coordinates.

CdC/SkyChart TCP server must be enabled, usually on 127.0.0.1:3292.
"""

from __future__ import annotations

import os
import socket
import time


class CartesDuCielError(Exception):
    """Raised when Cartes du Ciel cannot be reached or rejects a command."""


def ra_to_decimal_hours(ra_text: str) -> float:
    """Convert 'HH MM SS.s' or 'HH:MM:SS.s' to decimal hours."""
    parts = str(ra_text).strip().replace(":", " ").split()
    if len(parts) != 3:
        raise ValueError(f"Invalid RA format: {ra_text!r}")
    h, m, s = (float(x) for x in parts)
    return h + m / 60.0 + s / 3600.0


def dec_to_decimal_degrees(dec_text: str) -> float:
    """Convert '+DD MM SS.s' or '-DD:MM:SS.s' to decimal degrees."""
    parts = str(dec_text).strip().replace(":", " ").split()
    if len(parts) != 3:
        raise ValueError(f"Invalid Dec format: {dec_text!r}")
    d_text, m_text, s_text = parts
    sign = -1.0 if d_text.startswith("-") else 1.0
    d = abs(float(d_text))
    m = float(m_text)
    sec = float(s_text)
    return sign * (d + m / 60.0 + sec / 3600.0)


def _send_command(sock: socket.socket, command: str, pause_s: float = 0.15) -> str:
    """Send one command to CdC and return its response text, if any."""
    sock.sendall((command + "\r\n").encode("ascii"))
    time.sleep(pause_s)
    try:
        response = sock.recv(2048).decode(errors="ignore").strip()
    except socket.timeout:
        response = ""
    return response


def slew_telescope_via_cdc(
    ra_text: str,
    dec_text: str,
    host: str = "127.0.0.1",
    port: int = 3292,
    timeout: float = 5.0,
) -> list[tuple[str, str]]:
    """Ask Cartes du Ciel to slew its configured telescope to RA/Dec.

    This sends CdC server commands:

        CONNECTTELESCOPE
        SLEW <RA_decimal_hours> <Dec_decimal_degrees>

    CdC may not return an immediate response to SLEW while the mount is
    moving.  A timeout after the SLEW command is therefore recorded as an
    empty response, not treated as failure.
    """
    try:
        ra_hours = ra_to_decimal_hours(ra_text)
        dec_deg = dec_to_decimal_degrees(dec_text)
    except ValueError as exc:
        raise CartesDuCielError(str(exc)) from exc

    commands = [
        "CONNECTTELESCOPE",
        f"SLEW {ra_hours:.8f} {dec_deg:.8f}",
    ]

    replies: list[tuple[str, str]] = []
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as sock:
            sock.settimeout(timeout)
            for command in commands:
                response = _send_command(sock, command, pause_s=0.30)
                replies.append((command, response))

                if command == "CONNECTTELESCOPE":
                    if response and "OK" not in response.upper():
                        raise CartesDuCielError(
                            f"Cartes du Ciel returned unexpected response for {command!r}: {response}"
                        )
                elif response and "OK" not in response.upper():
                    raise CartesDuCielError(
                        f"Cartes du Ciel returned unexpected response for {command!r}: {response}"
                    )
    except OSError as exc:
        raise CartesDuCielError(
            f"Could not connect to Cartes du Ciel at {host}:{port}.\n"
            "Check that CdC is open and TCP/IP server is enabled."
        ) from exc

    return replies


def load_observing_list_in_cdc(
    file_path: str,
    host: str = "127.0.0.1",
    port: int = 3292,
    timeout: float = 5.0,
) -> list[tuple[str, str]]:
    """Load a Cartes du Ciel/SkyChart Observing List file.

    This sends the CdC server command:

        OBSLISTLOAD <list_file_name>

    The path is quoted first to support folders containing spaces.  If CdC
    returns a non-OK response, the unquoted form is tried once as a fallback.
    """
    path = os.path.abspath(str(file_path))
    command = f'OBSLISTLOAD "{path}"'

    replies: list[tuple[str, str]] = []
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as sock:
            sock.settimeout(timeout)
            response = _send_command(sock, command, pause_s=0.30)
            replies.append((command, response))

            if response and "OK" not in response.upper():
                # Some CdC builds may expect an unquoted path. Try once.
                command2 = f"OBSLISTLOAD {path}"
                response2 = _send_command(sock, command2, pause_s=0.30)
                replies.append((command2, response2))
                if response2 and "OK" not in response2.upper():
                    raise CartesDuCielError(
                        f"Cartes du Ciel returned unexpected response for OBSLISTLOAD: {response2}"
                    )
    except OSError as exc:
        raise CartesDuCielError(
            f"Could not connect to Cartes du Ciel at {host}:{port}.\n"
            "Check that CdC is open and TCP/IP server is enabled."
        ) from exc

    return replies
