"""Small Cartes du Ciel / SkyChart TCP client for NEO Tracker.

This module only sends chart-centering coordinates to CdC.  It does not
control the telescope or ASCOM.  The intended workflow is:

    NEO Tracker -> Cartes du Ciel -> NINA Planetarium Sync

CdC/SkyChart TCP server must be enabled, usually on 127.0.0.1:3292.
"""

from __future__ import annotations

import socket
import time


class CartesDuCielError(Exception):
    """Raised when Cartes du Ciel cannot be reached or rejects a command."""


def ra_to_cdc(ra_text: str) -> str:
    """Convert 'HH MM SS.s' or 'HH:MM:SS.s' to CdC RA format.

    Example:
        '18 46 59.060' -> '18h46m59.060s'
    """
    parts = str(ra_text).strip().replace(":", " ").split()
    if len(parts) != 3:
        raise ValueError(f"Invalid RA format: {ra_text!r}")
    h, m, s = parts
    return f"{h}h{m}m{s}s"


def dec_to_cdc(dec_text: str) -> str:
    """Convert '+DD MM SS.s' or '-DD:MM:SS.s' to CdC Dec format.

    Example:
        '-38 46 41.01' -> '-38d46m41.01s'
    """
    parts = str(dec_text).strip().replace(":", " ").split()
    if len(parts) != 3:
        raise ValueError(f"Invalid Dec format: {dec_text!r}")
    d, m, s = parts
    return f"{d}d{m}m{s}s"


def _send_command(sock: socket.socket, command: str, pause_s: float = 0.15) -> str:
    """Send one command to CdC and return its response text."""
    sock.sendall((command + "\r\n").encode("ascii"))
    time.sleep(pause_s)
    try:
        response = sock.recv(2048).decode(errors="ignore").strip()
    except socket.timeout:
        response = ""
    return response


def send_coordinates_to_cdc(
    ra_text: str,
    dec_text: str,
    host: str = "127.0.0.1",
    port: int = 3292,
    timeout: float = 5.0,
) -> list[tuple[str, str]]:
    """Center Cartes du Ciel on the supplied RA/Dec.

    Parameters
    ----------
    ra_text:
        RA as displayed in NEO Tracker, usually 'HH MM SS.s'.
    dec_text:
        Dec as displayed in NEO Tracker, usually '+DD MM SS.s'.
    host, port:
        CdC TCP/IP server settings.  Defaults match the usual local setup.
    timeout:
        Socket connection/read timeout in seconds.

    Returns
    -------
    list of (command, response) tuples.
    """
    try:
        ra = ra_to_cdc(ra_text)
        dec = dec_to_cdc(dec_text)
    except ValueError as exc:
        raise CartesDuCielError(str(exc)) from exc

    commands = [
        f"SETRA RA:{ra}",
        f"SETDEC DEC:{dec}",
        "REDRAW",
    ]

    replies: list[tuple[str, str]] = []
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as sock:
            sock.settimeout(timeout)
            for command in commands:
                response = _send_command(sock, command)
                replies.append((command, response))
                if response and "OK" not in response.upper():
                    raise CartesDuCielError(
                        f"Cartes du Ciel returned unexpected response for {command!r}: {response}"
                    )
    except OSError as exc:
        raise CartesDuCielError(
            f"Could not connect to Cartes du Ciel at {host}:{port}.\n"
            "Check that CdC is open and TCP/IP server is enabled."
        ) from exc

    return replies
