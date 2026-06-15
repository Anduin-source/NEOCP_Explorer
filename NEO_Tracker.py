import html
import os
import sys
import requests
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import scrolledtext, messagebox, font, filedialog
import re
import logging
import threading
import math
from datetime import datetime
import pandas as pd

try:
    from cartes_du_ciel import slew_telescope_via_cdc, load_observing_list_in_cdc, CartesDuCielError
    CDC_AVAILABLE = True
except Exception:
    slew_telescope_via_cdc = None
    load_observing_list_in_cdc = None
    CartesDuCielError = Exception
    CDC_AVAILABLE = False

# Optional: used only to compute topocentric Alt/Az from Project Pluto RA/Dec.
# The application still runs without astropy; Alt/Az will simply be unavailable.
try:
    from astropy.coordinates import SkyCoord, EarthLocation, AltAz
    from astropy.time import Time
    import astropy.units as u
    ASTROPY_AVAILABLE = True
except Exception:
    ASTROPY_AVAILABLE = False


# Configure logging to log to both file and console
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Avoid duplicate log entries if this module is reloaded in an IDE/session.
if not logger.handlers:
    file_handler = logging.FileHandler('app.log')
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


# ---------------------------------------------------------------------------
# Colour palette — neutral professional dark
# ---------------------------------------------------------------------------
C = {
    'bg':          '#1e1e1e',
    'panel':       '#252526',
    'panel_alt':   '#2d2d2d',
    'border':      '#3c3c3c',
    'accent':      '#0078d4',
    'accent_dark': '#005a9e',
    'fg':          '#d4d4d4',
    'fg_dim':      '#8a8a8a',
    'fg_header':   '#ffffff',
    'entry_bg':    '#3c3c3c',
    'entry_fg':    '#d4d4d4',
    'row_even':    '#2a2a2a',
    'row_odd':     '#252526',
    'row_sel':     '#094771',
    'status_bg':   '#007acc',
    'status_fg':   '#ffffff',
    'error':       '#5a1a1a',
    'success':     '#4ec9b0',
    'warning':     '#dcdcaa',
}


class Tooltip:
    """Creates tooltips for Tkinter widgets."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        widget.bind("<Enter>", self.show_tooltip)
        widget.bind("<Leave>", self.hide_tooltip)

    def show_tooltip(self, event=None):
        if self.tooltip_window or not self.text:
            return
        x = self.widget.winfo_rootx() + (event.x if event else 10)
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tooltip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, background='#3c3c3c',
                         foreground=C['fg'], relief='solid', borderwidth=1,
                         font=('Segoe UI', 9))
        label.pack(ipadx=4, ipady=2)

    def hide_tooltip(self, event=None):
        tw = self.tooltip_window
        if tw:
            tw.destroy()
        self.tooltip_window = None




# ---------------------------------------------------------------------------
# Project Pluto remote ephemeris provider
# ---------------------------------------------------------------------------

PROJECT_PLUTO_URL = "https://www.projectpluto.com/cgi-bin/fo/fo_serve.cgi"
LD_PER_AU = 389.17  # mean lunar distances per astronomical unit


def resource_path(relative_path):
    """Return absolute path to a bundled resource.

    Works both in normal Python execution and in PyInstaller --onefile builds.
    """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def project_pluto_uncertainty_to_degrees(value):
    """Convert Project Pluto/Find_Orb ephemeris uncertainty to degrees.

    Project Pluto may report the ephemeris uncertainty with different suffixes:
      - d  : degrees, for very large uncertainties, e.g. 40d
      - m  : arcminutes, e.g. 3.6m
      - "  : arcseconds, e.g. 2728"
      - no suffix: treated as arcseconds, which is how some pseudo-MPEC
        text appears after HTML conversion/parsing.

    The UI displays a single normalized unit, degrees, to avoid mixing
    values like 40d and 2728" in the same column.
    """
    if value is None:
        return None

    s = str(value).strip()
    if not s or s.upper() == 'N/A':
        return None

    # Normalize typographic prime characters that may appear in copied HTML.
    s = s.replace('″', '"').replace('”', '"').replace('′', "'").replace('’', "'")

    try:
        lower = s.lower()
        if lower.endswith('d'):
            return float(lower[:-1])
        if lower.endswith('m') or lower.endswith("'"):
            return float(lower[:-1]) / 60.0
        if lower.endswith('s') or lower.endswith('"'):
            return float(lower[:-1]) / 3600.0

        # Project Pluto often emits bare numeric values for arcseconds.
        return float(lower) / 3600.0
    except ValueError:
        return None


def format_uncertainty_degrees(value):
    """Return uncertainty normalized to degrees for table display."""
    deg = project_pluto_uncertainty_to_degrees(value)
    if deg is None:
        return str(value).strip() if value is not None else ''
    if deg >= 10:
        return f"{deg:.1f}"
    if deg >= 1:
        return f"{deg:.2f}"
    return f"{deg:.3f}"


class ProjectPlutoError(Exception):
    """Raised when Project Pluto returns a page that cannot be used as an ephemeris."""


def fetch_project_pluto_ephemeris(target_object, obs_code="X93", eph_steps=10, step_size="1h"):
    """
    Fetches ephemerides from Project Pluto's online Find_Orb server.

    Works for both NEOCP tracklets and known minor-planet designations.
    This is the only calculation engine used by this no-local-Find_Orb build.
    """
    params = {
        "obj_name": target_object,
        "year": "now",
        "n_steps": int(eph_steps),
        "stepsize": step_size,
        "mpc_code": obs_code,
        "faint_limit": 99,
        "ephem_type": 0,
        "sigmas": "on",
        # Force heliocentric (Sun-centered) elements. With the "automatic"
        # setting (-2) Find_Orb returns GEOCENTRIC elements for short-arc
        # near-Earth objects ("Perigee"/"(J2000 equator)"), whose eccentricity
        # is relative to Earth (e >> 1 for any flyby) and has no semi-major
        # axis. That produced spurious "hyperbolic/interstellar" flags and made
        # the orbit incomparable to the MPC. 0 = Sun keeps every object
        # heliocentric, matching the MPC.
        "element_center": 0,
        "epoch": "default",
        "resids": 0,
        "language": "e",
        "file_no": 0,
    }

    headers = {
        "User-Agent": (
            "NEO Tracker/3.0 "
            "(https://github.com/Anduin-source/NEOS_Tracker)"
        )
    }

    try:
        response = requests.get(
            PROJECT_PLUTO_URL,
            params=params,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Project Pluto request error: {e}")
        raise requests.exceptions.RequestException(
            f"Project Pluto request error: {e}"
        )

    return response.text


def _extract_html_comments(html_text):
    """Extracts hidden Project Pluto metadata comments from the HTML."""
    return "\n".join(
        c.strip() for c in re.findall(r"<!--(.*?)-->", html_text, flags=re.S)
        if c.strip()
    )


# Observatory coordinates used for local Alt/Az after Project Pluto returns RA/Dec.
# Longitude is degrees East. 313.6047 E = 46.3953 W.
# Add more observatories here later if needed.
OBSERVATORY_COORDS = {
    "X93": {
        "name": "Munhoz Observatory",
        "lat_deg": -22.628914,
        "lon_deg": 313.6047,
        "height_m": 1078.766,
    },
}


def _html_to_readable_text(html_text):
    """Converts Project Pluto's simple HTML pseudo-MPEC into readable visible text."""
    # Remove hidden comments from visible text. They are kept separately as
    # advanced metadata, not mixed into the main orbital-elements display.
    text = re.sub(r"<!--.*?-->", "", html_text, flags=re.S)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = re.sub(r"(?i)</pre\s*>", "\n", text)
    text = re.sub(r"(?i)<li\s*>", "\n- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return text

def _clean_project_pluto_error_excerpt(readable_text):
    """Returns a compact, user-facing excerpt from a failed Project Pluto page.

    Project Pluto/Find_Orb may return HTTP 200 with an HTML page describing
    the problem instead of a machine-readable error.  The visible text can also
    include CSS/style artifacts.  This helper removes those artifacts and keeps
    the operational message, usually beginning with 'Problem reading
    observations'.
    """
    lines = []
    skip_css = False

    for raw in readable_text.splitlines():
        line = raw.strip()
        if not line:
            continue

        lower = line.lower()

        # Drop common CSS/style artifacts that can appear after stripping tags.
        if lower.startswith(('.neocp', '.whtext')) or '{' in line or '}' in line:
            skip_css = True
            if '}' in line:
                skip_css = False
            continue
        if skip_css:
            if '}' in line:
                skip_css = False
            continue

        # Drop generic headings/navigation that are not useful in an error box.
        if lower in {'ephemeris generator', 'pseudo-mpec'}:
            continue
        if lower.startswith('click here') or lower.startswith('orbit simulator'):
            continue

        lines.append(line)

    # Prefer the actual Find_Orb/Project Pluto error paragraph when present.
    start_idx = 0
    for i, line in enumerate(lines):
        if 'problem reading observations' in line.lower():
            start_idx = i
            break
        if 'no objects found' in line.lower():
            start_idx = i
            break

    useful = lines[start_idx:start_idx + 12]
    cleaned = []
    for line in useful:
        if len(line) > 180:
            line = line[:177] + '...'
        cleaned.append(line)

    return "\n".join(cleaned) or "No readable server message returned."


def _section_between(text, start_marker, end_marker=None):
    """Returns a text section from start_marker up to end_marker."""
    start = text.find(start_marker)
    if start == -1:
        return ""
    if end_marker:
        end = text.find(end_marker, start + len(start_marker))
        if end != -1:
            return text[start:end].strip()
    return text[start:].strip()


def _parse_project_pluto_ephemeris_rows(eph_text):
    """Parse Project Pluto ephemeris rows into dictionaries.

    Project Pluto can return two slightly different visible formats:

    Daily step:
      YYYY MM DD  RA_h RA_m RA_s  Dec_d Dec_m Dec_s  delta r elong mag sig PA

    Hourly/sub-day step:
      YYYY MM DD HH  RA_h RA_m RA_s  Dec_d Dec_m Dec_s  delta r elong mag sig PA

    The previous v3 parser only handled the daily form and a HH:MM token. With
    stepsize=1h, Project Pluto emits a standalone HH column, so RA/Dec were
    shifted and Alt/Az could not be computed. This parser detects that form.
    """
    rows = []

    for line in eph_text.splitlines():
        stripped = line.strip()
        if not re.match(r"^\d{4}\s+\d{2}\s+\d{2}\s+", stripped):
            continue

        parts = stripped.split()
        if len(parts) < 15:
            continue

        try:
            year, month, day = parts[0], parts[1], parts[2]
            idx = 3
            time_utc = "00:00"

            # Case A: explicit HH:MM or HH:MM:SS token.
            if idx < len(parts) and re.match(r"^\d{1,2}:\d{2}(:\d{2})?$", parts[idx]):
                time_utc = parts[idx][:5]
                idx += 1

            # Case B: Project Pluto hourly output has a standalone HH column.
            # Example:
            # 2026 05 31 18  19 01 52.377  -40 12 50.42 ...
            # If parts[7] starts with +/-, then parts[4:7] are RA and parts[7]
            # is Dec degrees; therefore parts[3] is the hour.
            elif (
                len(parts) >= 16
                and re.match(r"^\d{1,2}$", parts[3])
                and parts[7][0] in "+-"
            ):
                hour = int(parts[3])
                if 0 <= hour <= 23:
                    time_utc = f"{hour:02d}:00"
                    idx = 4

            ra = f"{parts[idx]} {parts[idx+1]} {parts[idx+2]}"
            dec = f"{parts[idx+3]} {parts[idx+4]} {parts[idx+5]}"
            delta = float(parts[idx+6])
            r = float(parts[idx+7])
            elong = float(parts[idx+8])
            mag = float(parts[idx+9])
            sig = parts[idx+10]
            pa = int(float(parts[idx+11]))

            rows.append({
                "date": f"{year}-{month}-{day}",
                "time": time_utc,
                "ra": ra,
                "dec": dec,
                "delta": delta,
                "r": r,
                "elong": elong,
                "mag": mag,
                "sig": sig,
                "pa": pa,
                "alt": None,
                "az": None,
                "airmass": None,
                "rate": None,
                "motion_pa": None,
            })
        except Exception as e:
            logger.debug(f"Could not parse Project Pluto ephemeris line: {line!r}; {e}")
            continue

    return rows

def _compute_altaz_for_rows(rows, obs_code):
    """Adds Alt/Az/Airmass to Project Pluto rows when astropy and coordinates exist."""
    if not ASTROPY_AVAILABLE:
        return "Alt/Az not computed: astropy is not installed."

    code = (obs_code or "").strip().upper()
    info = OBSERVATORY_COORDS.get(code)
    if not info:
        return f"Alt/Az not computed: coordinates for observatory {code} are not in the local table."

    location = EarthLocation(
        lat=info["lat_deg"] * u.deg,
        lon=info["lon_deg"] * u.deg,
        height=info["height_m"] * u.m,
    )

    for row in rows:
        try:
            # Convert RA/Dec strings to astropy coordinates.
            rah, ram, ras = row["ra"].split()
            decd, decm, decs = row["dec"].split()
            coord = SkyCoord(
                f"{rah}h{ram}m{ras}s {decd}d{decm}m{decs}s",
                frame="icrs",
            )

            t = Time(f"{row['date']}T{row['time']}", scale="utc")
            altaz = coord.transform_to(AltAz(obstime=t, location=location))
            row["alt"] = float(altaz.alt.deg)
            row["az"] = float(altaz.az.deg)

            # sec(z) approximation is acceptable for display; avoid values
            # below/near the horizon.
            if row["alt"] > 5:
                z_rad = math.radians(90.0 - row["alt"])
                row["airmass"] = 1.0 / math.cos(z_rad)
        except Exception as e:
            logger.debug(f"Could not compute Alt/Az for row {row}: {e}")
    return None




def _ra_to_degrees(ra_text):
    """Convert RA string 'HH MM SS.s' to decimal degrees."""
    h, m, s = [float(x) for x in str(ra_text).split()]
    return 15.0 * (h + m / 60.0 + s / 3600.0)


def _dec_to_degrees(dec_text):
    """Convert Dec string '+DD MM SS.s' or '-DD MM SS.s' to decimal degrees."""
    d_s, m_s, s_s = str(dec_text).split()
    sign = -1.0 if d_s.startswith('-') else 1.0
    d = abs(float(d_s))
    m = float(m_s)
    s = float(s_s)
    return sign * (d + m / 60.0 + s / 3600.0)


def _row_datetime_utc(row):
    """Return a naive UTC datetime for an ephemeris row."""
    return datetime.strptime(f"{row['date']} {row['time']}", "%Y-%m-%d %H:%M")


def _angular_sep_and_pa(ra1_deg, dec1_deg, ra2_deg, dec2_deg):
    """Return angular separation in arcsec and position angle in degrees.

    PA is measured east of north, matching the usual astronomical convention
    used for apparent motion PA in ephemerides.
    """
    ra1 = math.radians(ra1_deg)
    dec1 = math.radians(dec1_deg)
    ra2 = math.radians(ra2_deg)
    dec2 = math.radians(dec2_deg)
    dra = ra2 - ra1

    # Great-circle separation.
    cos_sep = (
        math.sin(dec1) * math.sin(dec2)
        + math.cos(dec1) * math.cos(dec2) * math.cos(dra)
    )
    cos_sep = max(-1.0, min(1.0, cos_sep))
    sep_rad = math.acos(cos_sep)

    # Position angle from point 1 to point 2, east of north.
    y = math.sin(dra) * math.cos(dec2)
    x = (
        math.cos(dec1) * math.sin(dec2)
        - math.sin(dec1) * math.cos(dec2) * math.cos(dra)
    )
    pa_deg = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
    return math.degrees(sep_rad) * 3600.0, pa_deg


def _compute_apparent_motion_for_rows(rows):
    """Add apparent sky motion to ephemeris rows.

    Project Pluto's pseudo-MPEC table used here provides the ephemeris
    uncertainty and its PA, but not the apparent motion rate.  We compute the
    apparent motion from successive RA/Dec positions.  Interior rows use a
    centered difference; the first and last rows use forward/backward
    differences.  Units are arcsec/min.
    """
    if len(rows) < 2:
        return

    try:
        coords = [(_ra_to_degrees(r['ra']), _dec_to_degrees(r['dec'])) for r in rows]
        times = [_row_datetime_utc(r) for r in rows]
    except Exception as e:
        logger.debug(f"Could not prepare apparent-motion calculation: {e}")
        return

    for i, row in enumerate(rows):
        try:
            if i == 0:
                j1, j2 = 0, 1
            elif i == len(rows) - 1:
                j1, j2 = len(rows) - 2, len(rows) - 1
            else:
                j1, j2 = i - 1, i + 1

            dt_min = abs((times[j2] - times[j1]).total_seconds()) / 60.0
            if dt_min <= 0:
                continue

            sep_arcsec, pa_deg = _angular_sep_and_pa(
                coords[j1][0], coords[j1][1], coords[j2][0], coords[j2][1]
            )
            rate = sep_arcsec / dt_min
            row['rate'] = rate
            row['motion_pa'] = pa_deg
        except Exception as e:
            logger.debug(f"Could not compute apparent motion for row {row}: {e}")
            continue

def _format_project_pluto_ephemeris(eph_raw, obs_code):
    """Builds a clean ephemeris table enhanced with Alt/Az and apparent motion."""
    rows = _parse_project_pluto_ephemeris_rows(eph_raw)
    if not rows:
        return eph_raw

    altaz_note = _compute_altaz_for_rows(rows, obs_code)
    _compute_apparent_motion_for_rows(rows)

    title = "Project Pluto ephemerides"
    m = re.search(r"Ephemerides for.*", eph_raw)
    if m:
        title = m.group(0).strip()

    lines = []
    lines.append(title)
    if altaz_note:
        lines.append(altaz_note)
    else:
        lines.append(f"Alt/Az computed locally for observatory {obs_code.upper()}.")
    lines.append("Apparent motion computed locally from successive RA/Dec positions.")
    lines.append("")
    lines.append(
        "Date UTC   Time   RA             Dec            delta    r       elong   mag   rate   motPA unc_deg uncPA Alt    Az    Air"
    )
    lines.append(
        "---------  -----  ------------   ------------   -------  ------  ------  ----  ------  ----- ------- ----- -----  -----  ----"
    )

    for row in rows:
        alt = f"{row['alt']:5.1f}" if row["alt"] is not None else "  N/A"
        az = f"{row['az']:5.1f}" if row["az"] is not None else "  N/A"
        air = f"{row['airmass']:4.2f}" if row["airmass"] is not None else " N/A"
        unc_deg = format_uncertainty_degrees(row['sig'])
        rate = f"{row['rate']:6.2f}" if row.get('rate') is not None else "   N/A"
        mot_pa = f"{row['motion_pa']:5.1f}" if row.get('motion_pa') is not None else "  N/A"
        lines.append(
            f"{row['date']}  {row['time']:<5}  "
            f"{row['ra']:<12}   {row['dec']:<12}   "
            f"{row['delta']:7.5f}  {row['r']:6.4f}  {row['elong']:6.1f}  "
            f"{row['mag']:4.1f}  {rate}  {mot_pa}  "
            f"{unc_deg:>7} {row['pa']:5d}  {alt}  {az}  {air}"
        )

    return "\n".join(lines)

def _parse_project_pluto_station_names(station_text):
    """Builds {MPC_code: station_name} from Project Pluto Station data."""
    names = {}
    for line in station_text.splitlines():
        line = line.strip()
        m = re.match(r"^\(([A-Za-z0-9]{3})\)\s+(.+?)(?:\s+\([NS][\d.]+\s+[EW][\d.]+\)|\s{2,}|$)", line)
        if m:
            code = m.group(1).upper()
            name = " ".join(m.group(2).split())
            names[code] = name
    return names


def _format_project_pluto_observations(obs_raw, station_text):
    """Appends the observatory name beside each OBS80 astrometry line."""
    station_names = _parse_project_pluto_station_names(station_text)
    if not obs_raw.strip():
        return obs_raw

    out = []
    for line in obs_raw.splitlines():
        raw = line.rstrip()
        stripped = raw.strip()
        if not stripped or stripped.lower().startswith("astrometry"):
            out.append(raw)
            continue

        # In the readable Project Pluto pseudo-MPEC, the reporting MPC code is
        # normally the final 3 alphanumeric characters of each astrometry line.
        m = re.search(r"([A-Za-z0-9]{3})\s*$", stripped)
        if m:
            code = m.group(1).upper()
            station = station_names.get(code)
            if station:
                out.append(f"{raw}    [{code} — {station}]")
                continue
        out.append(raw)

    if station_names:
        out.append("")
        out.append("Observatory codes:")
        for code in sorted(station_names):
            out.append(f"  {code} — {station_names[code]}")

    return "\n".join(out)

def split_project_pluto_output(html_text, obs_code="X93"):
    """Splits Project Pluto pseudo-MPEC into UI blocks.

    Returns:
      elements_content  - clean orbital elements + residuals, without hidden dump
      eph_content       - clean/enhanced ephemeris table
      obs_content       - astrometry only
      advanced_content  - hidden Project Pluto metadata for optional display
    """
    readable = _html_to_readable_text(html_text)
    hidden_metadata = _extract_html_comments(html_text)

    if "Ephemerides for" not in readable:
        logger.error("Project Pluto response did not contain an ephemeris table.")
        logger.debug("Project Pluto response snippet:\n%s", readable[:2000])

        # Project Pluto/Find_Orb usually returns HTTP 200 even for search
        # failures; the failure is described in the HTML/text itself.  Keep a
        # compact, readable snippet for the user and the full text in app.log.
        server_msg = _clean_project_pluto_error_excerpt(readable)

        raise ProjectPlutoError(
            "Project Pluto did not return an ephemeris table.\n\n"
            "Possible causes:\n"
            "• object designation was not found in MPC/NEOCP data;\n"
            "• object exists, but Project Pluto could not retrieve valid observations;\n"
            "• observatory code is invalid;\n"
            "• Project Pluto/MPC service is temporarily unavailable.\n\n"
            f"Server message excerpt:\n{server_msg}"
        )

    obs_raw = _section_between(readable, "Astrometry:", "Station data:")
    station_content = _section_between(readable, "Station data:", "Orbital elements:")
    obs_content = _format_project_pluto_observations(obs_raw, station_content)
    elements_content = _section_between(
        readable,
        "Orbital elements:",
        "Residuals in arcseconds:"
    )
    residuals_content = _section_between(
        readable,
        "Residuals in arcseconds:",
        "Ephemerides for"
    )
    eph_raw = _section_between(readable, "Ephemerides for")

    if residuals_content:
        elements_content = (elements_content + "\n\n" + residuals_content).strip()

    eph_content = _format_project_pluto_ephemeris(eph_raw, obs_code)

    advanced_content = ""
    if hidden_metadata:
        advanced_content = "Hidden Project Pluto metadata:\n" + hidden_metadata

    return elements_content, eph_content, obs_content, advanced_content


def infer_object_category(target_object, obs_content="", advanced_content="", neocp_designations=None):
    """Infer whether the submitted object is a current NEOCP candidate or a known object."""
    target = (target_object or "").strip().upper()
    neocp_set = {str(x).strip().upper() for x in (neocp_designations or set())}

    if target and target in neocp_set:
        return "NEOCP candidate (current MPC NEOCP list)"

    combined = f"{obs_content}\n{advanced_content}"
    if "NEOCP" in combined:
        return "NEOCP candidate"

    return "Known object / MPC designation"

def parse_summary(elements_content, eph_content, target_object, object_category="Unknown"):
    """
    Parses Find_Orb / Project Pluto elements and ephemeris output to produce
    a human-readable summary.

    This version supports both:
      - local Find_Orb output, with altitude/azimuth columns;
      - Project Pluto pseudo-MPEC output, without altitude/azimuth but with
        useful hidden metadata in HTML comments.
    """

    def _get(pattern, text, group=1, default='N/A', flags=0):
        m = re.search(pattern, text, flags)
        return m.group(group).strip() if m else default

    metadata_text = elements_content + "\n" + eph_content

    # Detect a geocentric (Earth-centered) elements block. Find_Orb falls back
    # to this for some short-arc near-Earth objects: it prints "Perigee" and
    # "(J2000 equator)" instead of "Perihelion"/"(J2000 ecliptic)", and the
    # eccentricity is then relative to Earth (e >> 1 for any flyby), with no
    # semi-major axis. We request heliocentric elements (element_center=0), so
    # this should not happen, but guard against it to avoid false interstellar
    # flags if the server ever returns a geocentric solution.
    geocentric = bool(
        re.search(r'J2000\s+equator', elements_content)
        or re.search(r'^\s*Perigee\b', elements_content, re.MULTILINE)
    )

    # ------------------------------------------------------------------ #
    # 1. Parse orbital / physical metadata
    # ------------------------------------------------------------------ #
    diameter  = _get(r'Diameter\s+([\d.]+)\s+meters', metadata_text)
    enc_vel   = _get(r'Earth encounter velocity\s+([\d.]+)\s+km/s', metadata_text)
    moid      = _get(r'Earth MOID[:\s]+([\d.]+)', metadata_text)
    score     = _get(r'Score:\s+([\d.]+)', metadata_text)

    perihelion = _get(r'Perihelion\s+(\d{4}\s+\w+\s+[\d.]+)', elements_content)
    ecc        = _get(r'\be\s+([\d.]+)', elements_content)
    # Eccentricity 1-sigma uncertainty (may be in scientific notation, e.g.
    # "1.26e-8"). A short observation arc leaves e essentially unconstrained,
    # which Find_Orb reports as a large sigma here.
    ecc_sigma  = _get(r'\be\s+[\d.]+\s+\+/-\s+([0-9.eE+-]+)', elements_content)
    incl       = _get(r'Incl\.\s+([\d.]+)', elements_content)
    a_au       = _get(r'\ba\s+(-?[\d.]+)', elements_content)
    tisserand  = _get(r'Tisserand relative to Earth:\s+([\d.]+)', metadata_text)
    tisserand_jup = _get(r'Tisserand relative to Jupiter:\s+([\d.]+)', metadata_text)
    h_mag      = _get(r'\bH\s+([\d.]+)', elements_content)

    # Observations: local Find_Orb and Project Pluto use different wording.
    obs_used  = _get(r'(\d+)\s+of\s+\d+\s+observations', elements_content)
    obs_total = _get(r'\d+\s+of\s+(\d+)\s+observations', elements_content)
    obs_arc   = _get(r'\d+\s+of\s+\d+\s+observations\s+[\d\w. ]+\(([\d.]+\s+hr)\)',
                     elements_content)

    if obs_used == 'N/A':
        obs_used = _get(r'From\s+(\d+)\s+observations', elements_content)
        obs_total = obs_used
        obs_arc = _get(r'From\s+\d+\s+observations\s+.*?\(([\d.]+\s+min)\)',
                       elements_content)

    # ------------------------------------------------------------------ #
    # 2. Find closest approach in ephemeris table
    # ------------------------------------------------------------------ #
    closest_date  = 'N/A'
    closest_delta = None
    closest_mag   = 'N/A'
    closest_alt   = 'N/A'
    closest_rate  = 'N/A'
    closest_mot_pa = 'N/A'

    first_date = 'N/A'
    first_delta = None
    first_r = 'N/A'
    first_elong = 'N/A'

    # Project Pluto enhanced table generated by _format_project_pluto_ephemeris:
    #   YYYY-MM-DD HH:MM RA_h RA_m RA_s Dec_d Dec_m Dec_s delta r elong mag sig PA alt az air
    # Local Find_Orb table:
    #   YYYY MM DD HH RA_h RA_m RA_s Dec_d Dec_m Dec_s delta r mag motion PA alt az
    for line in eph_content.splitlines():
        sline = line.strip()
        if not sline:
            continue

        try:
            if re.match(r'^\d{4}-\d{2}-\d{2}\s+', sline):
                # Enhanced Project Pluto table.
                parts = sline.split()
                if len(parts) >= 19:
                    date_str = f"{parts[0]} {parts[1]} UTC"
                    # Enhanced v15 columns:
                    # date time RA(3) Dec(3) delta r elong mag rate motPA unc PA alt az air
                    delta = float(parts[8])
                    r_val = parts[9]
                    elong_val = parts[10]
                    mag = parts[11]
                    apparent_rate = parts[12]
                    motion_pa = parts[13]
                    alt = parts[16]
                elif len(parts) >= 17:
                    date_str = f"{parts[0]} {parts[1]} UTC"
                    # Enhanced v14 columns:
                    # date time RA(3) Dec(3) delta r elong mag unc PA alt az air
                    delta = float(parts[8])
                    r_val = parts[9]
                    elong_val = parts[10]
                    mag = parts[11]
                    apparent_rate = 'N/A'
                    motion_pa = 'N/A'
                    alt = parts[14]
                else:
                    continue
            elif re.match(r'^\d{4}\s+\d{2}\s+\d{2}\s+\d{2}', sline):
                # Local Find_Orb table from '-E 3,5,24'.
                parts = sline.split()
                if len(parts) < 17:
                    continue
                tail = parts[-7:]       # [delta, r, mag, motion, PA, alt, az]
                delta = float(tail[0])
                r_val = tail[1]
                elong_val = 'N/A'
                mag = tail[2]
                apparent_rate = tail[3]
                motion_pa = tail[4]
                alt = tail[5]
                date_str = f"{parts[0]}-{parts[1]}-{parts[2]} {parts[3]}h UTC"
            elif re.match(r'^\d{4}\s+\d{2}\s+\d{2}\s+', sline):
                # Raw Project Pluto pseudo-MPEC table, kept as fallback.
                parts = sline.split()
                if len(parts) < 15:
                    continue
                delta = float(parts[9])
                r_val = parts[10]
                elong_val = parts[11]
                mag = parts[12]
                apparent_rate = 'N/A'
                motion_pa = 'N/A'
                alt = 'N/A'
                date_str = f"{parts[0]}-{parts[1]}-{parts[2]} UTC"
            else:
                continue

            if first_delta is None:
                first_date = date_str
                first_delta = delta
                first_r = r_val
                first_elong = elong_val

            if closest_delta is None or delta < closest_delta:
                closest_delta = delta
                closest_date  = date_str
                closest_mag   = mag
                closest_alt   = alt
                closest_rate  = apparent_rate
                closest_mot_pa = motion_pa
        except (ValueError, IndexError):
            continue

    closest_delta_str = 'N/A'
    if closest_delta is not None:
        ld = closest_delta * LD_PER_AU
        closest_delta_str = f"{closest_delta:.5f} AU  ({ld:.1f} LD)"

    first_delta_str = 'N/A'
    if first_delta is not None:
        first_delta_str = f"{first_delta:.5f} AU  ({first_delta * LD_PER_AU:.1f} LD)"

    try:
        first_r_str = f"{float(first_r):.4f} AU"
    except (TypeError, ValueError):
        first_r_str = 'N/A'

    try:
        first_elong_str = f"{float(first_elong):.1f}°"
    except (TypeError, ValueError):
        first_elong_str = 'N/A'

    # ------------------------------------------------------------------ #
    # 3. Classification
    # ------------------------------------------------------------------ #
    EARTH_Q = 1.017   # Earth aphelion (AU)
    EARTH_q = 0.983   # Earth perihelion (AU)
    neo_subclass = "Unknown"
    try:
        a_val = float(a_au)
        e_val = float(ecc)
        q = a_val * (1.0 - e_val)
        Q = a_val * (1.0 + e_val)
        if not geocentric and e_val >= 1.0:
            # Hyperbolic heliocentric orbit: a is negative and Q is meaningless,
            # so the Aten/Atira (a < 1) branches below must not be reached.
            neo_subclass = "Hyperbolic / unbound orbit (e ≥ 1)"
        elif a_val < 1.0 and Q < EARTH_q:
            neo_subclass = "Atira (orbit interior to Earth's)"
        elif a_val < 1.0:
            neo_subclass = "Aten (a < 1 AU, crosses Earth's orbit)"
        elif q < EARTH_Q:
            neo_subclass = "Apollo (a > 1 AU, crosses Earth's orbit)"
        elif q < 1.3:
            neo_subclass = "Amor (a > 1 AU, approaches but does not cross)"
        else:
            neo_subclass = "Outside NEO criterion (q > 1.3 AU)"
    except ValueError:
        neo_subclass = "Unknown"

    try:
        tj = float(tisserand_jup)
        if tj < 2:
            dyn_class = "Halley-type / long-period comet (T_J < 2)"
        elif tj < 3:
            dyn_class = "Jupiter-family comet (2 <= T_J < 3)"
        else:
            dyn_class = "Asteroid (T_J >= 3)"
    except ValueError:
        dyn_class = "Unavailable (T_J not reported)"

    # ------------------------------------------------------------------ #
    # 4. Flags
    # ------------------------------------------------------------------ #
    try:
        pha = float(moid) < 0.05 and float(h_mag) < 22
    except ValueError:
        pha = False

    # A large sigma on e means the orbit is poorly constrained (typically a
    # very short observation arc), so the eccentricity value is not meaningful.
    try:
        sig_e = float(ecc_sigma)
        poorly_constrained = sig_e >= 0.1
    except ValueError:
        sig_e = None
        poorly_constrained = False

    # Only a heliocentric eccentricity >= 1 indicates a (possibly interstellar)
    # hyperbolic orbit. A geocentric solution always has e >> 1 and says nothing
    # about heliocentric dynamics, so never flag it as hyperbolic. A short-arc
    # fit with a huge sigma can land at e >= 1 by chance, so only call it a
    # *significant* (possible interstellar) hyperbolic orbit when e exceeds 1 by
    # more than 3 sigma.
    try:
        e_val_flag = (not geocentric) and float(ecc)
        hyperbolic = bool(e_val_flag) and e_val_flag >= 1.0
        if hyperbolic and sig_e is not None:
            hyperbolic_significant = (e_val_flag - 3.0 * sig_e) > 1.0
        else:
            hyperbolic_significant = hyperbolic
    except ValueError:
        hyperbolic = False
        hyperbolic_significant = False

    try:
        earth_crossing = float(moid) < 0.05
    except ValueError:
        earth_crossing = False

    # ------------------------------------------------------------------ #
    # 5. Assemble list of (text, tag) tuples
    # ------------------------------------------------------------------ #
    S = 'summary'
    W = 'summary_warning'
    blocks = []

    if hyperbolic_significant:
        blocks.append(("⚠  HYPERBOLIC ORBIT (e ≥ 1) — POSSIBLE INTERSTELLAR OBJECT\n", W))
    elif hyperbolic:
        blocks.append(("⚠  Hyperbolic best-fit (e ≥ 1) but poorly constrained — "
                       "likely short-arc artifact, not interstellar\n", W))
    if pha:
        blocks.append(("⚠  POTENTIALLY HAZARDOUS ASTEROID (PHA) — MOID < 0.05 AU  &  H < 22\n", W))
    elif earth_crossing:
        blocks.append(("⚠  EARTH-CROSSING ORBIT — MOID < 0.05 AU\n", W))

    if blocks:
        blocks.append(("\n", S))

    ecc_display = ecc if ecc_sigma == 'N/A' else f"{ecc} ± {ecc_sigma}"

    blocks += [
        (f"Object          : {target_object}\n", S),
        (f"Object category : {object_category}\n", S),
        (f"NEO sub-class   : {neo_subclass}\n", S),
        (f"\n", S),
        (f"── Physical ──────────────────────────────\n", S),
        (f"Est. diameter   : {diameter} m  (10% albedo assumed)\n", S),
        (f"Abs. magnitude  : H = {h_mag}\n", S),
        (f"\n", S),
        (f"── Orbit ─────────────────────────────────\n", S),
        (f"Semi-major axis : {a_au} AU\n", S),
        (f"Eccentricity    : {ecc_display}", S),
    ]

    if hyperbolic:
        blocks.append(("  ← hyperbolic\n", W))
    else:
        blocks.append(("\n", S))
    if poorly_constrained:
        blocks.append(("                  ↳ poorly constrained (short arc) — "
                       "eccentricity uncertain\n", W))

    blocks += [
        (f"Inclination     : {incl}°\n", S),
        (f"Perihelion      : {perihelion}\n", S),
        (f"Earth MOID      : {moid} AU", S),
    ]

    if earth_crossing:
        blocks.append(("  ← Earth-crossing\n", W))
    else:
        blocks.append(("\n", S))

    blocks += [(f"PHA             : {'YES' if pha else 'No'}", S)]
    if pha:
        blocks.append(("  ⚠\n", W))
    else:
        blocks.append(("\n", S))

    blocks.append((f"Tisserand (T_E) : {tisserand}\n", S))
    if tisserand_jup != 'N/A':
        blocks.append((f"Tisserand (T_J) : {tisserand_jup}\n", S))

    blocks += [
        (f"\n", S),
        (f"── Geometry at First Ephemeris Line ──────\n", S),
        (f"Time            : {first_date}\n", S),
        (f"Distance Δ      : {first_delta_str}\n", S),
        (f"Solar distance r: {first_r_str}\n", S),
        (f"Elongation      : {first_elong_str}\n", S),
        (f"\n", S),
        (f"── Min. Distance in Ephemeris Window ─────\n", S),
        (f"Time (min dist) : {closest_date}\n", S),
        (f"Min. distance   : {closest_delta_str}\n", S),
        (f"Magnitude       : {closest_mag}\n", S),
        (f"Altitude        : {closest_alt}\n", S),
        (f"App. motion     : {closest_rate} arcsec/min\n", S),
        (f"Motion PA       : {closest_mot_pa}°\n", S),
        (f"Enc. velocity   : {enc_vel} km/s\n", S),
        (f"\n", S),
        (f"── Observations ──────────────────────────\n", S),
        (f"Used / total    : {obs_used} / {obs_total}\n", S),
        (f"Observed arc    : {obs_arc}\n", S),
        (f"Project Pluto score : {score}\n", S),
    ]

    return blocks


def parse_ephemeris_table_for_ui(eph_content):
    """Extract ephemeris rows for the Treeview.

    Delta is stored internally in AU for summary calculations.
    Project Pluto uncertainty is normalized to degrees. Apparent motion is
    computed locally in the formatted table and displayed as arcsec/min plus
    motion PA.
    """

    def delta_au_to_ld(value):
        try:
            return f"{float(value) * LD_PER_AU:.1f}"
        except (TypeError, ValueError):
            return ""

    rows = []
    for line in eph_content.splitlines():
        sline = line.strip()
        if not sline:
            continue
        try:
            if re.match(r'^\d{4}-\d{2}-\d{2}\s+', sline):
                parts = sline.split()
                if len(parts) >= 19:
                    # v15 enhanced Project Pluto table:
                    # date time RA(3) Dec(3) delta r elong mag rate motPA unc uncPA alt az air
                    delta_au = parts[8]
                    rows.append({
                        'utc': f"{parts[0]} {parts[1]}",
                        'ra': f"{parts[2]} {parts[3]} {parts[4]}",
                        'dec': f"{parts[5]} {parts[6]} {parts[7]}",
                        'delta_ld': delta_au_to_ld(delta_au),
                        'delta_au': delta_au,
                        'r': parts[9],
                        'elong': parts[10],
                        'mag': parts[11],
                        'rate': parts[12],
                        'motion_pa': parts[13],
                        'unc': parts[14],
                        'unc_pa': parts[15],
                        'alt': parts[16],
                        'az': parts[17],
                        'air': parts[18],
                    })
                elif len(parts) >= 17:
                    # v14 enhanced Project Pluto table:
                    # date time RA(3) Dec(3) delta r elong mag unc PA alt az air
                    delta_au = parts[8]
                    rows.append({
                        'utc': f"{parts[0]} {parts[1]}",
                        'ra': f"{parts[2]} {parts[3]} {parts[4]}",
                        'dec': f"{parts[5]} {parts[6]} {parts[7]}",
                        'delta_ld': delta_au_to_ld(delta_au),
                        'delta_au': delta_au,
                        'r': parts[9],
                        'elong': parts[10],
                        'mag': parts[11],
                        'rate': '',
                        'motion_pa': '',
                        'unc': parts[12],
                        'unc_pa': parts[13],
                        'alt': parts[14],
                        'az': parts[15],
                        'air': parts[16],
                    })
            elif re.match(r'^\d{4}\s+\d{2}\s+\d{2}\s+\d{2}', sline):
                # Legacy/local Find_Orb style. Tail = [delta, r, mag, motion, PA, alt, az]
                parts = sline.split()
                if len(parts) < 17:
                    continue
                tail = parts[-7:]
                delta_au = tail[0]
                rows.append({
                    'utc': f"{parts[0]}-{parts[1]}-{parts[2]} {parts[3]}:00",
                    'ra': " ".join(parts[4:7]),
                    'dec': " ".join(parts[7:10]),
                    'delta_ld': delta_au_to_ld(delta_au),
                    'delta_au': delta_au,
                    'r': tail[1],
                    'elong': '',
                    'mag': tail[2],
                    'rate': tail[3],
                    'motion_pa': tail[4],
                    'unc': '',
                    'unc_pa': '',
                    'alt': tail[5],
                    'az': tail[6],
                    'air': '',
                })
        except Exception as e:
            logger.debug(f"Could not parse ephemeris UI row: {line!r}; {e}")
            continue
    return rows

def extract_compact_orbital_elements(elements_content):
    """Builds a compact orbital-elements block for the Results tab."""
    def _get(pattern, text, group=1, default='N/A'):
        m = re.search(pattern, text)
        return m.group(group).strip() if m else default

    a = _get(r'\ba\s+([\d.]+)', elements_content)
    e = _get(r'\be\s+([\d.]+)', elements_content)
    inc = _get(r'Incl\.\s+([\d.]+)', elements_content)
    q = _get(r'\bq\s+([\d.]+)', elements_content)
    Q = _get(r'\bQ\s+([\d.]+)', elements_content)
    h = _get(r'\bH\s+([\d.]+)', elements_content)
    moid = _get(r'Earth MOID[:\s]+([\d.]+)', elements_content)
    peri = _get(r'Perihelion\s+(\d{4}\s+\w+\s+[\d.]+)', elements_content)
    node = _get(r'Node\s+([\d.]+)', elements_content)
    argp = _get(r'Peri\.\s+([\d.]+)', elements_content)
    n = _get(r'\bn\s+([\d.]+)', elements_content)

    return (
        f"a        : {a} AU\n"
        f"e        : {e}\n"
        f"i        : {inc}°\n"
        f"q        : {q} AU\n"
        f"Q        : {Q} AU\n"
        f"H        : {h}\n"
        f"MOID Ea  : {moid} AU\n"
        f"Perihel. : {peri}\n"
        f"Node     : {node}°\n"
        f"Arg peri : {argp}°\n"
        f"n        : {n} deg/day\n"
    )


class NEOTrackerApp:
    """Main application — split-pane layout with integrated NEOCP panel."""

    def __init__(self, root):
        self.root = root
        self.root.title("NEOCP Explorer v3.1")
        self.root.geometry("1400x800")
        self.root.configure(bg=C['bg'])
        self.root.minsize(900, 600)
        try:
            self.root.iconbitmap(resource_path("neo_tracker.ico"))
        except Exception:
            # Keep the app usable even if the icon resource is missing.
            pass

        self._processing = False
        self.neocp_designations = set()

        self._apply_theme()
        self.create_layout()
        self.create_menu()
        self.create_status_bar()
        self._set_default_obs_code()

        # Load NEOCP panel automatically on startup
        self.root.after(300, self._start_neocp_load)

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _apply_theme(self):
        s = ttk.Style()
        s.theme_use('clam')

        s.configure('.', background=C['bg'], foreground=C['fg'],
                    fieldbackground=C['entry_bg'], troughcolor=C['border'],
                    bordercolor=C['border'], darkcolor=C['bg'],
                    lightcolor=C['border'], font=('Segoe UI', 10))

        s.configure('TFrame', background=C['bg'])
        s.configure('Panel.TFrame', background=C['panel'])

        s.configure('TLabel', background=C['bg'], foreground=C['fg'],
                    font=('Segoe UI', 10))
        s.configure('Header.TLabel', background=C['panel'],
                    foreground=C['fg_header'], font=('Segoe UI', 10, 'bold'))
        s.configure('PanelTitle.TLabel', background=C['panel'],
                    foreground=C['fg_header'], font=('Segoe UI', 11, 'bold'))
        s.configure('Counter.TLabel', background=C['panel'],
                    foreground=C['success'], font=('Segoe UI', 10, 'bold'))
        s.configure('Dim.TLabel', background=C['panel'],
                    foreground=C['fg_dim'], font=('Segoe UI', 9))

        s.configure('TEntry', fieldbackground=C['entry_bg'],
                    foreground=C['entry_fg'], insertcolor=C['fg'],
                    bordercolor=C['border'], font=('Segoe UI', 10))
        s.map('TEntry', fieldbackground=[('focus', '#4a4a4a')])

        # Validation-error style. In ttk.Entry the visible fill comes from
        # the style (fieldbackground), not the widget's 'background' option —
        # which is why the old direct .configure(background=...) had no
        # visible effect. We use a dedicated style instead.
        s.configure('Error.TEntry', fieldbackground=C['error'],
                    foreground=C['entry_fg'], insertcolor=C['fg'],
                    bordercolor=C['border'], font=('Segoe UI', 10))

        s.configure('TCombobox', fieldbackground=C['entry_bg'],
                    background=C['entry_bg'], foreground=C['entry_fg'],
                    arrowcolor=C['fg_dim'], bordercolor=C['border'],
                    font=('Segoe UI', 10))
        s.map('TCombobox',
              fieldbackground=[('readonly', C['entry_bg']), ('focus', '#4a4a4a')],
              foreground=[('readonly', C['entry_fg'])])

        s.configure('TButton', background=C['accent'], foreground='#ffffff',
                    bordercolor=C['accent'], font=('Segoe UI', 10),
                    padding=(10, 5))
        s.map('TButton',
              background=[('active', C['accent_dark']), ('pressed', C['accent_dark'])],
              foreground=[('active', '#ffffff')])

        s.configure('Secondary.TButton', background=C['panel_alt'],
                    foreground=C['fg'], bordercolor=C['border'],
                    font=('Segoe UI', 10), padding=(8, 4))
        s.map('Secondary.TButton',
              background=[('active', C['border']), ('pressed', C['border'])])

        s.configure('TRadiobutton', background=C['panel'], foreground=C['fg'],
                    font=('Segoe UI', 10))
        s.map('TRadiobutton', background=[('active', C['panel'])])

        s.configure('TProgressbar', troughcolor=C['border'],
                    background=C['accent'], bordercolor=C['border'])

        s.configure('Treeview', background=C['row_odd'], foreground=C['fg'],
                    fieldbackground=C['row_odd'], bordercolor=C['border'],
                    font=('Segoe UI', 9), rowheight=24)
        s.configure('Treeview.Heading', background=C['panel_alt'],
                    foreground=C['fg_header'], font=('Segoe UI', 9, 'bold'),
                    bordercolor=C['border'])
        s.map('Treeview',
              background=[('selected', C['row_sel'])],
              foreground=[('selected', '#ffffff')])
        s.map('Treeview.Heading',
              background=[('active', C['border'])])

        s.configure('TScrollbar', background=C['panel_alt'],
                    troughcolor=C['panel'], bordercolor=C['border'],
                    arrowcolor=C['fg_dim'])

        s.configure('TSeparator', background=C['border'])


        # Notebook/results tabs — styled to match the dark application theme.
        s.configure('TNotebook', background=C['panel'], borderwidth=0, tabmargins=(0, 4, 0, 0))
        s.configure('TNotebook.Tab', background=C['panel_alt'], foreground=C['fg_dim'],
                    bordercolor=C['border'], lightcolor=C['panel_alt'], darkcolor=C['panel_alt'],
                    padding=(14, 7), font=('Segoe UI', 9, 'bold'))
        s.map('TNotebook.Tab',
              background=[('selected', C['accent']), ('active', C['border'])],
              foreground=[('selected', '#ffffff'), ('active', C['fg_header'])],
              bordercolor=[('selected', C['accent']), ('active', C['border'])])

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def create_layout(self):
        self.paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.paned.pack(expand=True, fill='both')

        self.left_frame = ttk.Frame(self.paned, style='Panel.TFrame', width=420)
        self.paned.add(self.left_frame, weight=1)

        self.right_frame = ttk.Frame(self.paned, style='Panel.TFrame')
        self.paned.add(self.right_frame, weight=2)

        self._build_left_panel()
        self._build_right_panel()

    def _build_left_panel(self):
        # Header
        header_frame = ttk.Frame(self.left_frame, style='Panel.TFrame')
        header_frame.pack(fill='x', padx=10, pady=(10, 4))

        ttk.Label(header_frame, text="NEOCP Candidates",
                  style='PanelTitle.TLabel').pack(side='left')

        self.neocp_counter_label = ttk.Label(header_frame, text="",
                                             style='Counter.TLabel')
        self.neocp_counter_label.pack(side='left', padx=(8, 0))

        refresh_btn = ttk.Button(header_frame, text="↻  Refresh",
                                 style='Secondary.TButton',
                                 command=self._start_neocp_load)
        refresh_btn.pack(side='right')
        Tooltip(refresh_btn, "Reload NEOCP candidates from MPC")

        ttk.Label(header_frame, text="double-click to select",
                  style='Dim.TLabel').pack(side='right', padx=(0, 8))

        # Loading indicator
        self.neocp_loading_label = ttk.Label(self.left_frame,
                                             text="", style='Dim.TLabel')
        self.neocp_loading_label.pack(pady=(2, 0))

        self.neocp_progress = ttk.Progressbar(self.left_frame,
                                              mode='indeterminate', length=200)

        # Treeview
        tree_frame = ttk.Frame(self.left_frame, style='Panel.TFrame')
        tree_frame.pack(expand=True, fill='both', padx=6, pady=(4, 6))

        self.neocp_tree = ttk.Treeview(tree_frame)
        self.neocp_tree.pack(side='left', expand=True, fill='both')

        neocp_scroll = ttk.Scrollbar(tree_frame, orient='vertical',
                                     command=self.neocp_tree.yview)
        neocp_scroll.pack(side='right', fill='y')
        self.neocp_tree.configure(yscrollcommand=neocp_scroll.set)
        self.neocp_tree.bind("<Double-1>", self._select_neocp_from_panel)

    def _build_right_panel(self):
        # Form
        form_frame = ttk.Frame(self.right_frame, style='Panel.TFrame')
        form_frame.pack(fill='x', padx=14, pady=(12, 6))
        form_frame.columnconfigure(1, weight=1)

        # Object designation — one Project Pluto workflow for known objects and NEOCP tracklets
        ttk.Label(form_frame, text="Object designation:",
                  style='Header.TLabel').grid(row=0, column=0, sticky='w', pady=5)
        self.target_object_entry = ttk.Entry(form_frame, font=('Segoe UI', 10))
        self.target_object_entry.grid(row=0, column=1, sticky='ew', padx=(6, 0))
        self.target_object_placeholder = "e.g. 99942, Apophis, 2024 MK, A11D0Xd"
        self.target_object_entry.insert(0, self.target_object_placeholder)
        self.target_object_entry.configure(foreground=C['fg_dim'])
        self.target_object_entry.bind("<FocusIn>",
            lambda e: self.clear_placeholder(e, self.target_object_entry,
                                             self.target_object_placeholder))
        self.target_object_entry.bind("<FocusOut>",
            lambda e: self.add_placeholder(e, self.target_object_entry,
                                           self.target_object_placeholder))
        Tooltip(self.target_object_entry,
                "Enter a known object name/number or a current NEOCP designation")

        # Observatory code
        ttk.Label(form_frame, text="Observatory code:",
                  style='Header.TLabel').grid(row=1, column=0, sticky='w', pady=5)
        self.obs_code_entry = ttk.Entry(form_frame, font=('Segoe UI', 10), width=12)
        self.obs_code_entry.grid(row=1, column=1, sticky='w', padx=(6, 0))
        self.obs_code_placeholder = "e.g. X93"
        self.obs_code_entry.insert(0, self.obs_code_placeholder)
        self.obs_code_entry.configure(foreground=C['fg_dim'])
        self.obs_code_entry.bind("<FocusIn>",
            lambda e: self.clear_placeholder(e, self.obs_code_entry,
                                             self.obs_code_placeholder))
        self.obs_code_entry.bind("<FocusOut>",
            lambda e: self.add_placeholder(e, self.obs_code_entry,
                                           self.obs_code_placeholder))
        Tooltip(self.obs_code_entry,
                "3-char MPC code. Default: X93. "
                "See minorplanetcenter.net/iau/lists/ObsCodes.html")

        # Ephemeris steps
        ttk.Label(form_frame, text="Ephemeris steps:",
                  style='Header.TLabel').grid(row=2, column=0, sticky='w', pady=5)
        self.eph_steps_entry = ttk.Entry(form_frame, font=('Segoe UI', 10), width=8)
        self.eph_steps_entry.grid(row=2, column=1, sticky='w', padx=(6, 0))
        self.eph_steps_entry.insert(0, "10")
        Tooltip(self.eph_steps_entry, "Number of ephemeris data points to calculate")

        # Ephemeris step size
        ttk.Label(form_frame, text="Step size:",
                  style='Header.TLabel').grid(row=3, column=0, sticky='w', pady=5)
        self.step_size_var = tk.StringVar(value="1h")
        self.step_size_combo = ttk.Combobox(
            form_frame,
            textvariable=self.step_size_var,
            values=("10m", "30m", "1h", "1d"),
            state="readonly",
            width=8,
            font=('Segoe UI', 10),
        )
        self.step_size_combo.grid(row=3, column=1, sticky='w', padx=(6, 0))
        Tooltip(
            self.step_size_combo,
            "Ephemeris interval. Default: 1h. Use 10m for fast NEOCP objects, "
            "30m for moderate objects, and 1d for multi-day planning."
        )

        # Buttons
        btn_frame = ttk.Frame(form_frame, style='Panel.TFrame')
        btn_frame.grid(row=4, column=0, columnspan=2, pady=(12, 4), sticky='w')

        self.submit_button = ttk.Button(btn_frame, text="▶  Calculate", command=self.submit)
        self.submit_button.pack(side='left', padx=(0, 8))
        self.root.bind('<Control-s>', lambda e: self.submit(), add='')
        Tooltip(self.submit_button, "Calculate ephemerides  (Ctrl+S)")

        reset_btn = ttk.Button(btn_frame, text="⟳  Clear",
                               style='Secondary.TButton', command=self.refresh)
        reset_btn.pack(side='left')
        self.root.bind('<Control-n>', lambda e: self.refresh(), add='')
        Tooltip(reset_btn, "Clear fields and results  (Ctrl+N)")

        # Progress bar
        self.progress = ttk.Progressbar(self.right_frame, mode='indeterminate')

        # Results notebook: tabs act as the section header, keeping the UI cleaner.
        mono = ('Cascadia Code', 9) if self._font_exists('Cascadia Code') \
            else ('Courier New', 9)

        self.results_notebook = ttk.Notebook(self.right_frame, style='TNotebook')
        self.results_notebook.pack(expand=True, fill='both', padx=10, pady=(10, 6))

        self.summary_tab = ttk.Frame(self.results_notebook, style='Panel.TFrame')
        self.eph_tab = ttk.Frame(self.results_notebook, style='Panel.TFrame')
        self.elements_tab = ttk.Frame(self.results_notebook, style='Panel.TFrame')
        self.obs_tab = ttk.Frame(self.results_notebook, style='Panel.TFrame')
        self.advanced_tab = ttk.Frame(self.results_notebook, style='Panel.TFrame')

        self.results_notebook.add(self.summary_tab, text='Summary')
        self.results_notebook.add(self.eph_tab, text='Ephemerides')
        self.results_notebook.add(self.elements_tab, text='Orbit')
        self.results_notebook.add(self.obs_tab, text='Observations')
        self.results_notebook.add(self.advanced_tab, text='Details')

        self.summary_text = scrolledtext.ScrolledText(
            self.summary_tab, wrap=tk.WORD, font=('Segoe UI', 10),
            background=C['bg'], foreground=C['fg'], insertbackground=C['fg'],
            selectbackground=C['row_sel'], borderwidth=0, relief='flat'
        )
        self.summary_text.pack(expand=True, fill='both')
        self.summary_text.configure(state='disabled')

        eph_tree_frame = ttk.Frame(self.eph_tab, style='Panel.TFrame')
        eph_tree_frame.pack(expand=True, fill='both')
        self.ephem_tree = ttk.Treeview(eph_tree_frame)
        self.ephem_tree.pack(side='left', expand=True, fill='both')
        self.ephem_scroll = ttk.Scrollbar(eph_tree_frame, orient='vertical', command=self.ephem_tree.yview)
        self.ephem_scroll.pack(side='right', fill='y')
        self.ephem_tree.configure(yscrollcommand=self.ephem_scroll.set)

        # Right-click context menu for fast CdC/SkyChart hand-off.
        self.ephem_context_menu = tk.Menu(
            self.ephem_tree, tearoff=0, background=C['panel'],
            foreground=C['fg'], activebackground=C['accent'],
            activeforeground='#ffffff'
        )
        self.ephem_context_menu.add_command(
            label="Slew telescope via SkyChart...",
            command=self.slew_selected_ephemeris_via_cdc
        )
        self.ephem_context_menu.add_separator()
        self.ephem_context_menu.add_command(
            label="Load ephemeris trail in CdC Observing List",
            command=self.export_all_ephemerides_to_cdc_obslist
        )
        self.ephem_tree.bind("<Button-3>", self._show_ephemeris_context_menu)

        self.elements_text = scrolledtext.ScrolledText(
            self.elements_tab, wrap=tk.WORD, font=mono,
            background=C['bg'], foreground=C['fg'], insertbackground=C['fg'],
            selectbackground=C['row_sel'], borderwidth=0, relief='flat'
        )
        self.elements_text.pack(expand=True, fill='both')
        self.elements_text.configure(state='disabled')

        self.obs_text = scrolledtext.ScrolledText(
            self.obs_tab, wrap=tk.WORD, font=mono,
            background=C['bg'], foreground=C['fg'], insertbackground=C['fg'],
            selectbackground=C['row_sel'], borderwidth=0, relief='flat'
        )
        self.obs_text.pack(expand=True, fill='both')
        self.obs_text.configure(state='disabled')

        self.advanced_text = scrolledtext.ScrolledText(
            self.advanced_tab, wrap=tk.WORD, font=mono,
            background=C['bg'], foreground=C['fg'], insertbackground=C['fg'],
            selectbackground=C['row_sel'], borderwidth=0, relief='flat'
        )
        self.advanced_text.pack(expand=True, fill='both')
        self.advanced_text.configure(state='disabled')

    @staticmethod
    def _font_exists(name):
        try:
            return name in font.families()
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    def create_menu(self):
        menubar = tk.Menu(self.root, background=C['panel'], foreground=C['fg'],
                          activebackground=C['accent'], activeforeground='#ffffff',
                          borderwidth=0)
        self.root.config(menu=menubar)

        tools_menu = tk.Menu(menubar, tearoff=0, background=C['panel'],
                             foreground=C['fg'], activebackground=C['accent'],
                             activeforeground='#ffffff')
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="NEOFIXER Targets", command=self.run_neofixer)
        tools_menu.add_separator()
        tools_menu.add_command(label="Slew Telescope via Cartes du Ciel...",
                               command=self.slew_selected_ephemeris_via_cdc)
        tools_menu.add_command(label="Load Ephemeris Trail in CdC Observing List",
                               command=self.export_all_ephemerides_to_cdc_obslist)
        tools_menu.add_separator()
        tools_menu.add_command(label="Refresh NEOCP List", command=self._start_neocp_load)

        help_menu = tk.Menu(menubar, tearoff=0, background=C['panel'],
                            foreground=C['fg'], activebackground=C['accent'],
                            activeforeground='#ffffff')
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="User Manual", command=self.show_help)
        help_menu.add_separator()
        help_menu.add_command(label="About", command=self.show_about)
        help_menu.add_separator()
        help_menu.add_command(label="Exit", command=self.quit_application)

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------

    def create_status_bar(self):
        self.status_bar = tk.Label(self.root, text="Ready",
                                   background=C['panel_alt'],
                                   foreground=C['fg_dim'],
                                   anchor='w', padx=10,
                                   font=('Segoe UI', 9))
        self.status_bar.pack(side='bottom', fill='x')

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def clear_placeholder(self, event, entry, placeholder):
        if entry.get() == placeholder:
            entry.delete(0, tk.END)
            entry.configure(foreground=C['entry_fg'])

    def add_placeholder(self, event, entry, placeholder):
        if entry.get() == '':
            entry.insert(0, placeholder)
            entry.configure(foreground=C['fg_dim'])

    def validate_entries(self):
        valid = True
        obj_name = self.target_object_entry.get()
        obs_code = self.obs_code_entry.get()

        # --- Object name ---
        if obj_name == '' or obj_name == self.target_object_placeholder:
            self.target_object_entry.configure(style='Error.TEntry')
            valid = False
        elif not re.match(r'^[A-Za-z0-9\s\-/()._]+$', obj_name):
            self.target_object_entry.configure(style='Error.TEntry')
            messagebox.showerror("Error",
                                 "Invalid object name. Enter a valid designation.\nAllowed: letters, numbers, spaces, hyphen, slash, parentheses, dot and underscore.")
            valid = False
        else:
            self.target_object_entry.configure(style='TEntry')

        # --- Observatory code ---
        if obs_code == '' or obs_code == self.obs_code_placeholder:
            self.obs_code_entry.configure(style='Error.TEntry')
            valid = False
        elif not re.match(r'^[A-Za-z0-9]{3}$', obs_code):
            self.obs_code_entry.configure(style='Error.TEntry')
            messagebox.showerror("Error",
                                 "Observatory code must be 3 alphanumeric characters.")
            valid = False
        else:
            self.obs_code_entry.configure(style='TEntry')

        # --- Ephemeris steps ---
        # BUG FIX: validate HERE, before submit() sets _processing=True.
        # Previously a non-integer value was caught late (inside the worker
        # thread) via an early 'return' that skipped the finally block,
        # leaving _processing stuck at True — silently locking the Submit
        # button for the rest of the session.
        eph = self.eph_steps_entry.get().strip()
        if not eph.isdigit() or int(eph) <= 0:
            self.eph_steps_entry.configure(style='Error.TEntry')
            messagebox.showerror("Error",
                                 "Ephemeris steps must be a positive integer.")
            valid = False
        else:
            self.eph_steps_entry.configure(style='TEntry')

        # --- Step size ---
        if hasattr(self, 'step_size_var') and self.step_size_var.get() not in {'10m', '30m', '1h', '1d'}:
            messagebox.showerror("Error", "Step size must be one of: 10m, 30m, 1h, 1d.")
            valid = False

        return valid

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    def submit(self, event=None):
        if self._processing:
            return
        if not self.validate_entries():
            return
        self._processing = True
        thread = threading.Thread(target=self.process_submission, daemon=True)
        thread.start()

    def process_submission(self):
        target_object = self.target_object_entry.get().strip()
        obs_code = self.obs_code_entry.get().strip()

        self.root.after(0, lambda: self.submit_button.configure(state='disabled'))
        self.root.after(0, lambda: self.progress.pack(pady=4))
        self.root.after(0, self.progress.start)
        step_size_for_status = self.step_size_var.get().strip() if hasattr(self, 'step_size_var') else "1h"
        self.root.after(0, lambda: self.status_bar.config(
            text=f"Querying Project Pluto online Find_Orb… step={step_size_for_status}"))

        try:
            # One remote workflow for both known NEOs and NEOCP tracklets.
            # No local executable, no OBS80 temporary files, no path configuration.
            eph_steps_int = int(self.eph_steps_entry.get())

            step_size = self.step_size_var.get().strip() or "1h"

            pp_html = fetch_project_pluto_ephemeris(
                target_object=target_object,
                obs_code=obs_code,
                eph_steps=eph_steps_int,
                step_size=step_size,
            )

            self.root.after(0, lambda: self.status_bar.config(
                text="Processing Project Pluto results…"))

            elements_content, eph_content, obs_content, advanced_content = split_project_pluto_output(
                pp_html,
                obs_code=obs_code,
            )

            self.root.after(0, self.show_text, elements_content,
                            eph_content, obs_content, target_object,
                            advanced_content)

        except Exception as e:
            logger.error(str(e))
            msg = str(e)
            if "Invalid observatory code" in msg:
                self.root.after(0, lambda: messagebox.showerror("Error",
                    "Invalid observatory code.\n"
                    "See: https://minorplanetcenter.net/iau/lists/ObsCodes.html"))
            elif isinstance(e, ProjectPlutoError) or "Project Pluto" in msg or "ephemeris table" in msg:
                self.root.after(0, lambda: messagebox.showerror("Project Pluto query failed", msg))
            elif "Error processing response data" in msg:
                self.root.after(0, lambda: messagebox.showerror("Error",
                    "Object not found. Check the designation and try again."))
                self.root.after(0, self.refresh)
            else:
                self.root.after(0, lambda: messagebox.showerror("Error",
                    f"Unexpected error: {msg}\nSee app.log for details."))
            self.root.after(0, lambda: self.status_bar.config(text="Error."))
        finally:
            self._processing = False
            self.root.after(0, self.progress.stop)
            self.root.after(0, self.progress.pack_forget)
            self.root.after(0, lambda: self.submit_button.configure(state='normal'))

    def _set_default_obs_code(self):
        """Pre-fills the observatory code field with the default MPC code.

        This build does not read or write any settings file; users can
        change the code directly in the GUI for each session.
        """
        self.obs_code_entry.configure(foreground=C['entry_fg'])
        self.obs_code_entry.delete(0, tk.END)
        self.obs_code_entry.insert(0, 'X93')

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def refresh(self, event=None):
        if messagebox.askyesno("Confirmation", "Reset all fields?"):
            self.target_object_entry.delete(0, tk.END)
            self.target_object_entry.insert(0, self.target_object_placeholder)
            self.target_object_entry.configure(foreground=C['fg_dim'], style='TEntry')

            self.obs_code_entry.configure(style='TEntry')
            self.obs_code_entry.delete(0, tk.END)
            self._set_default_obs_code()

            self.eph_steps_entry.configure(style='TEntry')
            self.eph_steps_entry.delete(0, tk.END)
            self.eph_steps_entry.insert(0, "10")
            if hasattr(self, 'step_size_var'):
                self.step_size_var.set("1h")

            self._clear_results()
            self.status_bar.config(text="Ready")

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------

    def _write_text_widget(self, widget, text):
        widget.configure(state='normal')
        widget.delete(1.0, tk.END)
        widget.insert(tk.INSERT, text)
        widget.configure(state='disabled')

    def _clear_results(self):
        for widget in ('summary_text', 'elements_text', 'obs_text', 'advanced_text'):
            if hasattr(self, widget):
                w = getattr(self, widget)
                w.configure(state='normal')
                w.delete(1.0, tk.END)
                w.configure(state='disabled')
        if hasattr(self, 'ephem_tree'):
            for row in self.ephem_tree.get_children():
                self.ephem_tree.delete(row)

    def _populate_ephemeris_tree(self, eph_content):
        rows = parse_ephemeris_table_for_ui(eph_content)
        for row in self.ephem_tree.get_children():
            self.ephem_tree.delete(row)

        columns = ('UTC', 'RA', 'Dec', 'Mag', 'Rate \"/min', 'Mot PA', 'Elong', 'Unc. °', 'Alt', 'Az', 'Air')
        self.ephem_tree['columns'] = columns
        self.ephem_tree['show'] = 'headings'
        widths = {
            'UTC': 130, 'RA': 115, 'Dec': 115, 'Mag': 55,
            'Rate \"/min': 80, 'Mot PA': 65,
            'Elong': 65, 'Unc. °': 70,
            'Alt': 55, 'Az': 55, 'Air': 55,
        }
        for col in columns:
            self.ephem_tree.heading(col, text=col)
            self.ephem_tree.column(col, anchor='center', width=widths.get(col, 70), minwidth=40)

        def fmt(value, decimals=0):
            """Format numeric values compactly for the UI table, preserving N/A/blank."""
            if value in (None, '', 'N/A'):
                return 'N/A' if value == 'N/A' else ''
            try:
                return f"{float(value):.{decimals}f}"
            except (TypeError, ValueError):
                return str(value)

        for i, row in enumerate(rows):
            tag = 'even' if i % 2 == 0 else 'odd'
            self.ephem_tree.insert('', 'end', tags=(tag,), values=(
                row.get('utc', ''), row.get('ra', ''), row.get('dec', ''),
                row.get('mag', ''),
                fmt(row.get('rate', ''), 0),
                fmt(row.get('motion_pa', ''), 0),
                fmt(row.get('elong', ''), 0),
                row.get('unc', ''),
                row.get('alt', ''),
                fmt(row.get('az', ''), 0),
                fmt(row.get('air', ''), 1),
            ))
        self.ephem_tree.tag_configure('even', background=C['row_even'])
        self.ephem_tree.tag_configure('odd', background=C['row_odd'])

        if not rows:
            self.ephem_tree.insert('', 'end', values=('No ephemeris rows parsed', '', '', '', '', '', '', '', '', '', ''))

    def show_text(self, elements_content, eph_content, obs_content, target_object, advanced_content=""):
        self._clear_results()

        # Summary tab
        self.summary_text.configure(state='normal')
        self.summary_text.delete(1.0, tk.END)
        self.summary_text.tag_configure('header', font=('Segoe UI', 10, 'bold'), foreground=C['warning'])
        self.summary_text.tag_configure('summary', font=('Segoe UI', 10), foreground=C['success'])
        self.summary_text.tag_configure('summary_warning', font=('Segoe UI', 10, 'bold'), foreground='#f44747')
        self.summary_text.insert(tk.INSERT, "── Summary ──\n", 'header')
        try:
            object_category = infer_object_category(
                target_object,
                obs_content=obs_content,
                advanced_content=advanced_content,
                neocp_designations=self.neocp_designations,
            )
            summary_blocks = parse_summary(
                elements_content + "\n" + advanced_content,
                eph_content,
                target_object,
                object_category=object_category,
            )
            for text, tag in summary_blocks:
                self.summary_text.insert(tk.INSERT, text, tag)
        except Exception as e:
            logger.warning(f"Could not generate summary: {e}")
            self.summary_text.insert(tk.INSERT, "(Summary unavailable)\n", 'summary')
        self.summary_text.configure(state='disabled')

        # Ephemerides tab
        self._populate_ephemeris_tree(eph_content)

        # Orbital Elements tab: compact first, raw below for traceability.
        elements_display = (
            "── Compact Orbital Elements ──\n"
            + extract_compact_orbital_elements(elements_content)
            + "\n── Raw Orbital Elements / Residuals ──\n"
            + elements_content
        )
        self._write_text_widget(self.elements_text, elements_display)
        self._write_text_widget(self.obs_text, obs_content)

        advanced_display = advanced_content.strip()
        if not advanced_display:
            advanced_display = "No advanced metadata available for this run."
        self._write_text_widget(self.advanced_text, advanced_display)

        self.results_notebook.select(self.summary_tab)
        self.status_bar.config(text="Done.")

    # ------------------------------------------------------------------
    # NEOCP — integrated left panel
    # ------------------------------------------------------------------

    def _start_neocp_load(self):
        self.neocp_loading_label.configure(text="Loading candidates…")
        self.neocp_progress.pack(pady=(0, 6))
        self.neocp_progress.start()
        self.neocp_counter_label.configure(text="")
        for row in self.neocp_tree.get_children():
            self.neocp_tree.delete(row)
        thread = threading.Thread(target=self._fetch_neocp_data, daemon=True)
        thread.start()

    def _fetch_neocp_data(self):
        url = "https://www.minorplanetcenter.net/Extended_Files/neocp.json"
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            data = response.json()
            self.root.after(0, lambda: self._populate_neocp_panel(data))
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching NEOCP: {e}")
            self.root.after(0, lambda: self._neocp_load_error(str(e)))

    def _populate_neocp_panel(self, data):
        try:
            df = pd.json_normalize(data)

            # Combine discovery date
            if all(c in df.columns for c in
                   ['Discovery_year', 'Discovery_month', 'Discovery_day']):
                df['Disc. Date'] = (
                    df['Discovery_year'].astype(str) + '-' +
                    df['Discovery_month'].astype(str).str.zfill(2) + '-' +
                    df['Discovery_day'].astype(str).str.zfill(2)
                )
                df.drop(['Discovery_year', 'Discovery_month', 'Discovery_day'],
                        axis=1, inplace=True)

            # Round floats
            for col in df.select_dtypes(include='float').columns:
                df[col] = df[col].round(2)

            # Drop columns with little observational value
            drop_cols = ['H', 'Updated', 'Note', 'R.A.', 'Decl.']
            df.drop(columns=[c for c in drop_cols if c in df.columns], inplace=True)

            # Sort by V (magnitude) ascending — brightest first
            if 'V' in df.columns:
                df['V'] = pd.to_numeric(df['V'], errors='coerce')
                df.sort_values('V', ascending=True, inplace=True, na_position='last')

            if 'Temp_Desig' in df.columns:
                self.neocp_designations = set(df['Temp_Desig'].astype(str).str.upper())

            # Preferred column order
            preferred = ['Temp_Desig', 'V', 'Score', 'NObs', 'Arc',
                         'Not_Seen_dys', 'Disc. Date']
            cols = [c for c in preferred if c in df.columns]
            cols += [c for c in df.columns if c not in cols]

            self.neocp_tree["columns"] = cols
            self.neocp_tree["show"] = "headings"

            col_widths = {
                'Temp_Desig': 105, 'V': 50, 'Score': 55, 'NObs': 50,
                'Arc': 50, 'Not_Seen_dys': 85, 'Disc. Date': 95,
            }
            for col in cols:
                w = col_widths.get(col, 70)
                anchor = 'w' if col == 'Temp_Desig' else 'center'
                self.neocp_tree.heading(
                    col, text=col,
                    command=lambda _c=col: self._sort_neocp(
                        self.neocp_tree, _c, False))
                self.neocp_tree.column(col, anchor=anchor, width=w, minwidth=30)

            for i, (_, row) in enumerate(df.iterrows()):
                values = [f"{row[c]:.1f}" if isinstance(row[c], float) and c == 'V'
                          else f"{row[c]:.2f}" if isinstance(row[c], float)
                          else row[c] for c in cols]
                tag = 'even' if i % 2 == 0 else 'odd'
                self.neocp_tree.insert("", "end", values=values, tags=(tag,))

            self.neocp_tree.tag_configure('even', background=C['row_even'])
            self.neocp_tree.tag_configure('odd', background=C['row_odd'])

            count = len(df)
            self.neocp_counter_label.configure(text=f"{count} objects")
            self.neocp_loading_label.configure(text="")
            self.status_bar.config(text=f"NEOCP: {count} candidates loaded.")

        except Exception as e:
            logger.error(f"Error populating NEOCP panel: {e}")
            self.neocp_loading_label.configure(text=f"Error: {e}")
        finally:
            self.neocp_progress.stop()
            self.neocp_progress.pack_forget()

    def _neocp_load_error(self, msg):
        self.neocp_progress.stop()
        self.neocp_progress.pack_forget()
        self.neocp_loading_label.configure(text="Failed to load — check connection")
        self.status_bar.config(text="NEOCP load failed.")

    def _select_neocp_from_panel(self, event):
        # Identify clicked region — ignore header and empty areas
        region = self.neocp_tree.identify_region(event.x, event.y)
        if region != 'cell':
            return
        selected = self.neocp_tree.focus()
        if not selected:
            return
        values = self.neocp_tree.item(selected, 'values')
        if not values:
            return
        cols = list(self.neocp_tree['columns'])
        desig_idx = cols.index('Temp_Desig') if 'Temp_Desig' in cols else 0
        designation = values[desig_idx]
        self.target_object_entry.configure(foreground=C['entry_fg'],
                                           style='TEntry')
        self.target_object_entry.delete(0, tk.END)
        self.target_object_entry.insert(0, designation)
        self.status_bar.config(
            text=f"Selected: {designation}  —  press Calculate to get ephemerides.")

    def _sort_neocp(self, tree, col, descending):
        data = [(tree.set(child, col), child) for child in tree.get_children('')]
        try:
            data.sort(key=lambda x: float(x[0]), reverse=descending)
        except ValueError:
            data.sort(reverse=descending)
        for ix, item in enumerate(data):
            tree.move(item[1], '', ix)
            tree.item(item[1], tags=('even' if ix % 2 == 0 else 'odd',))
        tree.heading(col,
                     command=lambda: self._sort_neocp(tree, col, not descending))

    # ------------------------------------------------------------------
    # Cartes du Ciel / SkyChart integration
    # ------------------------------------------------------------------

    def _show_ephemeris_context_menu(self, event):
        """Select the row under the mouse and show the ephemeris popup menu."""
        row_id = self.ephem_tree.identify_row(event.y)
        if not row_id:
            return
        self.ephem_tree.selection_set(row_id)
        self.ephem_tree.focus(row_id)
        try:
            self.ephem_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.ephem_context_menu.grab_release()

    def _selected_ephemeris_row(self):
        """Return the selected ephemeris row as a dict keyed by Treeview columns."""
        if not hasattr(self, 'ephem_tree'):
            return None

        selected = self.ephem_tree.selection()
        item_id = selected[0] if selected else self.ephem_tree.focus()
        if not item_id:
            return None

        values = self.ephem_tree.item(item_id, 'values')
        if not values:
            return None

        columns = list(self.ephem_tree['columns'])
        return {col: values[i] if i < len(values) else '' for i, col in enumerate(columns)}

    def _selected_ephemeris_altitude(self, row):
        """Return selected-row altitude as float, or None when unavailable."""
        raw_alt = str(row.get('Alt', '')).strip()
        if not raw_alt or raw_alt.upper() == 'N/A':
            return None
        try:
            return float(raw_alt)
        except ValueError:
            return None

    def slew_selected_ephemeris_via_cdc(self):
        """Slew the CdC-configured telescope to the selected ephemeris row.

        Safety policy:
        - requires a selected ephemeris row;
        - requires valid local altitude;
        - refuses targets below the horizon;
        - requires user confirmation before sending SLEW.
        """
        if not CDC_AVAILABLE or slew_telescope_via_cdc is None:
            messagebox.showerror(
                "Cartes du Ciel integration unavailable",
                "The Cartes du Ciel helper module was not found.\n"
                "Make sure cartes_du_ciel.py is in the same folder as NEO_Tracker.py."
            )
            return

        row = self._selected_ephemeris_row()
        if not row:
            messagebox.showinfo(
                "No ephemeris selected",
                "Select one row in the Ephemerides tab first."
            )
            return

        ra = row.get('RA', '').strip()
        dec = row.get('Dec', '').strip()
        utc = row.get('UTC', '').strip()
        alt = self._selected_ephemeris_altitude(row)

        if not ra or not dec:
            messagebox.showerror(
                "Invalid ephemeris row",
                "The selected row does not contain valid RA/Dec coordinates."
            )
            return

        if alt is None:
            messagebox.showerror(
                "Slew blocked",
                "The selected ephemeris row has no valid altitude.\n"
                "Slew is blocked because altitude cannot be checked."
            )
            return

        if alt < 0.0:
            messagebox.showerror(
                "Slew blocked",
                f"The selected target is below the horizon.\n\n"
                f"UTC: {utc}\n"
                f"Altitude: {alt:.1f}°\n\n"
                "Slew was not sent."
            )
            return

        target = self.target_object_entry.get().strip()
        if target == self.target_object_placeholder:
            target = "selected object"

        ok = messagebox.askyesno(
            "Confirm telescope slew",
            "Slew telescope via SkyChart / Cartes du Ciel?\n\n"
            f"Object: {target}\n"
            f"UTC: {utc}\n"
            f"RA: {ra}\n"
            f"Dec: {dec}\n"
            f"Altitude: {alt:.1f}°\n\n"
            "This will send a telescope SLEW command through Cartes du Ciel."
        )
        if not ok:
            return

        self.status_bar.config(text=f"Sending slew command via Cartes du Ciel: {target}  {utc}…")

        def worker():
            try:
                replies = slew_telescope_via_cdc(ra, dec)
                logger.info(
                    "Slew command sent via Cartes du Ciel: target=%s UTC=%s RA=%s Dec=%s Alt=%.1f replies=%s",
                    target, utc, ra, dec, alt, replies
                )
                self.root.after(0, lambda: self.status_bar.config(
                    text=f"Slew command sent via Cartes du Ciel: {target}  {utc}  Alt {alt:.1f}°"
                ))
            except Exception as exc:
                logger.error("Cartes du Ciel slew failed: %s", exc)
                self.root.after(0, lambda: self.status_bar.config(
                    text="Cartes du Ciel slew failed."
                ))
                self.root.after(0, lambda: messagebox.showerror(
                    "Cartes du Ciel slew failed",
                    str(exc)
                ))

        threading.Thread(target=worker, daemon=True).start()


    # ------------------------------------------------------------------
    # CdC Observing List export
    # ------------------------------------------------------------------

    def _ephemeris_tree_rows(self):
        """Return all ephemeris rows currently displayed in the Treeview."""
        if not hasattr(self, 'ephem_tree'):
            return []
        columns = list(self.ephem_tree['columns'])
        rows = []
        for item_id in self.ephem_tree.get_children():
            values = self.ephem_tree.item(item_id, 'values')
            if not values:
                continue
            row = {col: values[i] if i < len(values) else '' for i, col in enumerate(columns)}
            # Skip placeholder/error rows.
            if row.get('RA') and row.get('Dec'):
                rows.append(row)
        return rows

    def _sanitize_cdc_name(self, text, max_len=32):
        """Return a compact CdC-safe object/list label."""
        cleaned = re.sub(r'[^A-Za-z0-9_+\-.]', '_', str(text).strip())
        cleaned = re.sub(r'_+', '_', cleaned).strip('_')
        return (cleaned or 'NEO_Target')[:max_len]

    def _cdc_obslist_label_from_utc(self, utc):
        """Return a compact label for CdC map display.

        CdC tends to display the observing-list object name plus the label on
        the sky map.  To avoid long labels such as
        A11D5ma_202606050600 2026-06-05, keep the object name as the target
        designation and put only the ephemeris time/date in the label.
        """
        utc = (utc or '').strip()
        m = re.match(r'^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}:\d{2})$', utc)
        if m:
            _, month, day, hhmm = m.groups()
            return f"{month}-{day} {hhmm}"
        return utc[:32]

    def _cdc_obslist_line(self, name, row):
        """Build one fixed-width Cartes du Ciel Observing List line.

        CdC Observing List format:
          1-32   object name
          33-42  RA in decimal degrees, J2000
          43-52  Dec in decimal degrees, J2000
          53-84  label/name
          85+    free description
        """
        ra_text = row.get('RA', '').strip()
        dec_text = row.get('Dec', '').strip()
        if not ra_text or not dec_text:
            raise ValueError('Missing RA/Dec in ephemeris row.')

        ra_deg = _ra_to_degrees(ra_text)
        dec_deg = _dec_to_degrees(dec_text)

        utc = row.get('UTC', '').strip()
        label = self._cdc_obslist_label_from_utc(utc)[:32]
        desc = (
            f"UTC {utc}; "
            f"RA {ra_text}; Dec {dec_text}; "
            f"Mag {row.get('Mag', '')}; "
            f"Rate {row.get('Rate \"/min', '')} arcsec/min; "
            f"MotPA {row.get('Mot PA', '')}; "
            f"Unc {row.get('Unc. °', '')} deg; "
            f"Alt {row.get('Alt', '')}; Az {row.get('Az', '')}; Air {row.get('Air', '')}"
        )

        return f"{name:<32}{ra_deg:10.5f}{dec_deg:10.5f}{label:<32}{desc}"

    def _write_cdc_obslist_file(self, rows, default_name):
        """Ask for a file path and write selected/all rows as a CdC Observing List."""
        if not rows:
            messagebox.showinfo(
                "No ephemeris rows",
                "There are no valid ephemeris rows to export."
            )
            return

        target = self.target_object_entry.get().strip()
        if not target or target == self.target_object_placeholder:
            target = "NEO_Target"

        safe_target = self._sanitize_cdc_name(target)
        default_file = self._sanitize_cdc_name(default_name, max_len=80) + ".txt"

        path = filedialog.asksaveasfilename(
            title="Save Cartes du Ciel Observing List",
            defaultextension=".txt",
            initialfile=default_file,
            filetypes=[
                ("Cartes du Ciel observing list", "*.txt"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        lines = [f"NEOCP Explorer - {target} ephemeris"]
        # Keep the CdC object name short.  The UTC of each ephemeris point is
        # stored in the label and description, so the sky-map label remains
        # readable while every row is still uniquely documented.
        obj_name = self._sanitize_cdc_name(safe_target)
        for row in rows:
            lines.append(self._cdc_obslist_line(obj_name, row))

        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write("\n".join(lines) + "\n")
        except OSError as exc:
            messagebox.showerror("CdC Observing List export failed", str(exc))
            self.status_bar.config(text="CdC Observing List export failed.")
            return

        # Try to load the generated list directly into an already-running
        # Cartes du Ciel/SkyChart session.  If CdC is not available, keep the
        # file export as a successful operation and report only the load issue.
        if CDC_AVAILABLE and load_observing_list_in_cdc is not None:
            try:
                replies = load_observing_list_in_cdc(path)
                logger.info("Loaded CdC Observing List: path=%s replies=%s", path, replies)
                self.status_bar.config(
                    text=f"Saved and loaded CdC Observing List: {len(rows)} row(s)"
                )
                return
            except Exception as exc:
                logger.warning("Saved CdC Observing List, but auto-load failed: %s", exc)
                self.status_bar.config(
                    text=f"Saved CdC Observing List, but auto-load failed: {path}"
                )
                messagebox.showwarning(
                    "CdC Observing List saved",
                    "The observing-list file was saved, but NEO Tracker could not "
                    "load it automatically into Cartes du Ciel.\n\n"
                    f"File:\n{path}\n\n"
                    f"CdC message:\n{exc}"
                )
                return

        self.status_bar.config(
            text=f"Saved CdC Observing List: {len(rows)} row(s) → {path}"
        )

    def export_all_ephemerides_to_cdc_obslist(self):
        """Export every displayed ephemeris row as a CdC Observing List trail."""
        rows = self._ephemeris_tree_rows()
        target = self.target_object_entry.get().strip()
        if not target or target == self.target_object_placeholder:
            target = "NEO_Target"
        self._write_cdc_obslist_file(rows, f"cdc_obslist_{target}_trail")

    # ------------------------------------------------------------------
    # NEOFIXER
    # ------------------------------------------------------------------

    def run_neofixer(self):
        try:
            site_code = self.obs_code_entry.get()
            if not site_code or site_code == self.obs_code_placeholder:
                site_code = 'X93'
            response = requests.get(
                f'https://neofixerapi.arizona.edu/targets/?site={site_code}&num=40', timeout=20)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            messagebox.showerror("Error", f"Unable to fetch NEOFIXER targets:\n{e}")
            return

        targets = data.get('result', {}).get('objects', {})
        if not targets:
            messagebox.showinfo("NEOFIXER", "No targets found.")
            return

        win = tk.Toplevel(self.root)
        win.title("NEOFIXER Targets")
        win.geometry("820x440")
        win.configure(bg=C['bg'])

        tree_frame = ttk.Frame(win)
        tree_frame.pack(expand=True, fill='both', padx=10, pady=10)

        tree = ttk.Treeview(tree_frame)
        tree.pack(side='left', expand=True, fill='both')

        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical', command=tree.yview)
        scrollbar.pack(side='right', fill='y')
        tree.configure(yscrollcommand=scrollbar.set)

        columns = ('ID', 'Priority', 'Score', 'Cost', 'Magnitude', '1σ Uncertainty')
        tree["columns"] = columns
        tree["show"] = "headings"

        for col in columns:
            tree.heading(col, text=col,
                         command=lambda _c=col: self.sort_by(tree, _c, False))
            tree.column(col, anchor='center', width=120)

        for i, (sID, dObj) in enumerate(targets.items()):
            tag = 'even' if i % 2 == 0 else 'odd'
            tree.insert("", "end", tags=(tag,), values=(
                sID,
                dObj.get('priority', '-'),
                f"{dObj.get('score', 0):.2f}",
                f"{dObj.get('cost', 0):.1f}",
                f"{dObj.get('vmag', 0):.1f}",
                f"{dObj.get('uncert', 0):.4f}"
            ))

        tree.tag_configure('even', background=C['row_even'])
        tree.tag_configure('odd', background=C['row_odd'])

    def sort_by(self, tree, col, descending):
        data = [(tree.set(child, col), child) for child in tree.get_children('')]
        try:
            data.sort(key=lambda x: float(x[0]), reverse=descending)
        except ValueError:
            data.sort(reverse=descending)
        for ix, item in enumerate(data):
            tree.move(item[1], '', ix)
            tree.item(item[1], tags=('even' if ix % 2 == 0 else 'odd',))
        tree.heading(col, command=lambda: self.sort_by(tree, col, not descending))

    # ------------------------------------------------------------------
    # Help / About / Quit
    # ------------------------------------------------------------------

    def show_about(self):
        messagebox.showinfo(
            "About",
            "NEOCP Explorer v3.1\n"
            "Developed by Andre Brossel\n\n"
            "Ephemerides and orbital solutions:\n"
            "  Project Pluto / Find_Orb by Bill Gray\n"
            "  https://www.projectpluto.com/\n\n"
            "NEOCP candidate data:\n"
            "  Minor Planet Center\n\n"
            "Topocentric Alt/Az/Airmass calculations:\n"
            "  Astropy\n\n"
            "Optional target information:\n"
            "  NEOFIXER\n\n"
            "NEOCP Explorer is an independent project and is not affiliated "
            "with Project Pluto, the Minor Planet Center, JPL, NEOFIXER, "
            "Astropy, or Cartes du Ciel."
        )

    def show_help(self):
        help_text = (
            "User Manual\n\n"
            "NEOCP Explorer calculates ephemerides and orbital elements "
            "for NEOs and NEOCP candidates.\n\n"
            "Quick start:\n"
            "1. The NEOCP panel on the left loads candidates automatically.\n"
            "   Double-click any row to fill the form.\n"
            "2. Enter the object designation, observatory code, ephemeris steps, and step size.\n"
            "3. Click Calculate (or Ctrl+S).\n\n"
            "Observatory code:\n"
            "  3-character alphanumeric MPC code.\n"
            "  List: https://minorplanetcenter.net/iau/lists/ObsCodes.html\n"
            "  Default in the GUI: X93. Change it directly before submitting.\n\n"
            "Step size:\n"
            "  1h  = default; useful for general planning and slower known objects.\n"
            "  30m = useful for moderate NEOCP objects.\n"
            "  10m = use for fast NEOCP objects or precise hand-off to SkyChart/NINA.\n"
            "  1d  = useful for multi-day planning.\n\n"
            "Ephemeris columns:\n"
            "  Rate \"/min = apparent sky motion in arcsec/min.\n"
            "  Mot PA = apparent motion position angle, east of north.\n"
            "  Unc. ° = ephemeris uncertainty, converted to degrees.\n"
            "           Project Pluto may originally report uncertainty as degrees, arcminutes,\n"
            "           or arcseconds; the table converts all cases to degrees.\n"
            "  Distances Δ and r are shown in the Summary instead of the table.\n\n"
            "Cartes du Ciel / SkyChart:\n"
            "  Right-click an ephemeris row to send its coordinates to CdC.\n"
            "  You can also export the selected row or the full ephemeris trail\n"
            "  as a CdC Observing List file, so each ephemeris point appears\n"
            "  as a temporary labeled object in SkyChart.\n\n"
            "Configuration:\n"
            "  This version no longer uses config.ini or a local Find_Orb path.\n\n"
            "Logs: app.log\n"
            "Support: https://github.com/Anduin-source/NEOS_Tracker/issues"
        )
        win = tk.Toplevel(self.root)
        win.title("User Manual")
        win.geometry("640x460")
        win.configure(bg=C['bg'])
        txt = scrolledtext.ScrolledText(win, wrap=tk.WORD,
                                        background=C['bg'], foreground=C['fg'],
                                        font=('Segoe UI', 10),
                                        borderwidth=0, relief='flat')
        txt.insert(tk.INSERT, help_text)
        txt.configure(state='disabled')
        txt.pack(expand=True, fill='both', padx=12, pady=12)

    def quit_application(self):
        if messagebox.askyesno("Quit", "Are you sure you want to quit?"):
            self.root.quit()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    root = tk.Tk()
    root.withdraw()
    NEOTrackerApp(root)
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()
