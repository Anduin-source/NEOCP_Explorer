"""Small Cartes du Ciel / SkyChart TCP client for NEO Tracker.

This module sends coordinates to Cartes du Ciel/SkyChart through its
TCP/IP server.  It supports two separate workflows:

    1. Center the CdC chart on RA/Dec for NINA Planetarium Sync.
    2. Ask CdC to slew the telescope to RA/Dec using CdC's configured
       telescope connection.

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

                # CONNECTTELESCOPE should return OK.  SLEW often times out or
                # returns no text while CdC/mount is busy; don't reject an
                # empty SLEW response.
                if command == "CONNECTTELESCOPE":
                    if response and "OK" not in response.upper():
                        raise CartesDuCielError(
                            f"Cartes du Ciel returned unexpected response for {command!r}: {response}"
                        )
                elif response and "OK" not in response.upper():
                    # Non-empty non-OK SLEW response is useful to report.
                    raise CartesDuCielError(
                        f"Cartes du Ciel returned unexpected response for {command!r}: {response}"
                    )
    except OSError as exc:
        raise CartesDuCielError(
            f"Could not connect to Cartes du Ciel at {host}:{port}.\n"
            "Check that CdC is open and TCP/IP server is enabled."
        ) from exc

    return replies
