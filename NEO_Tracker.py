import subprocess
import os
import requests
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import scrolledtext, messagebox, font
import re
import logging
import threading
import argparse
import configparser
import sys
import pandas as pd

# Configure logging to log to both file and console
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

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
        x, y, _, cy = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += cy + self.widget.winfo_rooty() + 20
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


def get_observations(object_type_value, target_object):
    """Retrieves observations from the Minor Planet Center API."""
    if object_type_value == "NEO":
        url = "https://data.minorplanetcenter.net/api/get-obs"
        payload = {"desigs": [target_object], "output_format": ["OBS80"]}
    elif object_type_value == "NEOCP":
        url = "https://data.minorplanetcenter.net/api/get-obs-neocp"
        payload = {"trksubs": [target_object], "output_format": ["OBS80"]}
    else:
        raise ValueError("Invalid option for object type.")

    try:
        response = requests.get(url, json=payload)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {e}")
        raise requests.exceptions.RequestException(f"Request error: {e}")

    try:
        data = response.json()
    except ValueError:
        logger.error("Error decoding JSON response.")
        raise ValueError("Error decoding JSON response.")

    try:
        obs80_string = data[0]['OBS80']
        return obs80_string
    except (KeyError, IndexError):
        logger.error("Error processing response data.")
        raise KeyError("Error processing response data. Check if the object name is correct.")


def run_find_orb(obs_file, obs_code, find_orb_path, eph_steps):
    """Executes the find_orb program with the specified parameters."""
    ephemeris_output_path = os.path.join(find_orb_path, 'efemerides.txt')
    elements_output_path = os.path.join(find_orb_path, 'elements.txt')

    executable = os.path.join(find_orb_path, 'fo64.exe')
    if not os.path.exists(executable):
        raise FileNotFoundError(f"fo64.exe not found at: {executable}")

    command = [
        executable, obs_file,
        '-e', ephemeris_output_path,
        '-E', '3,5,24',
        '-C', obs_code,
        f'EPHEM_STEPS={eph_steps}',
        'EPHEM_STEP_SIZE=1h'
    ]

    try:
        subprocess.run(command, cwd=find_orb_path, check=True)

        if os.path.exists(ephemeris_output_path):
            with open(ephemeris_output_path, 'r') as f:
                eph_content = f.read()
        else:
            raise FileNotFoundError("efemerides.txt was not found.")

        if os.path.exists(elements_output_path):
            with open(elements_output_path, 'r') as f:
                elements_content = f.read()
        else:
            raise FileNotFoundError("elements.txt was not found.")

        return elements_content, eph_content

    except subprocess.CalledProcessError as e:
        raise Exception(f"Error executing find_orb: {e}")


def delete_temporary_files(files):
    """Deletes temporary files."""
    for file in files:
        try:
            if os.path.exists(file):
                os.remove(file)
        except Exception as e:
            logger.error(f"Could not delete file {file}: {e}")


def parse_summary(elements_content, eph_content, target_object):
    """
    Parses Find_Orb elements and ephemeris output to produce a human-readable
    summary of the key physical and observational properties of the object.

    Sources:
      - elements_content : raw text from elements.txt (Find_Orb output)
      - eph_content      : raw text from efemerides.txt (Find_Orb output)
      - target_object    : designation string (for display)

    Returns a list of (text, tag) tuples where tag is one of:
      'summary'         — normal green text
      'summary_warning' — orange/red for PHA and hyperbolic flags
    """

    def _get(pattern, text, group=1, default='N/A'):
        m = re.search(pattern, text)
        return m.group(group).strip() if m else default

    # ------------------------------------------------------------------ #
    # 1. Parse elements_content
    # ------------------------------------------------------------------ #

    diameter  = _get(r'Diameter\s+([\d.]+)\s+meters', elements_content)
    enc_vel   = _get(r'Earth encounter velocity\s+([\d.]+)\s+km/s', elements_content)
    moid      = _get(r'Earth MOID[:\s]+([\d.]+)', elements_content)
    score     = _get(r'Score:\s+([\d.]+)', elements_content)
    obs_used  = _get(r'(\d+)\s+of\s+\d+\s+observations', elements_content)
    obs_total = _get(r'\d+\s+of\s+(\d+)\s+observations', elements_content)
    obs_arc   = _get(r'\d+\s+of\s+\d+\s+observations\s+[\d\w. ]+\(([\d.]+\s+hr)\)',
                     elements_content)
    perihelion = _get(r'Perihelion\s+(\d{4}\s+\w+\s+[\d.]+)', elements_content)
    ecc        = _get(r'\be\s+([\d.]+)', elements_content)
    incl       = _get(r'Incl\.\s+([\d.]+)', elements_content)
    a_au       = _get(r'\ba\s+([\d.]+)', elements_content)
    tisserand  = _get(r'Tisserand relative to Earth:\s+([\d.]+)', elements_content)
    h_mag      = _get(r'\bH\s+([\d.]+)', elements_content)

    # ------------------------------------------------------------------ #
    # 2. Find closest approach in ephemeris table
    # ------------------------------------------------------------------ #
    closest_date  = 'N/A'
    closest_delta = None
    closest_mag   = 'N/A'
    closest_alt   = 'N/A'

    # The ephemeris produced by the fixed '-E 3,5,24' options ends with a
    # known 7-column numeric tail:
    #   [delta, r, mag, "/min, PA, alt, az]
    # The leading part (date + RA h m s + Dec d m s) has a variable token
    # count, so we anchor on the END of the line instead of fixed front
    # indices. The previous code read parts[14] as 'alt', but that column is
    # actually PA — yielding impossible altitudes like 104.7 deg (the real
    # altitude is the 2nd-from-last token).
    for line in eph_content.splitlines():
        if not re.match(r'^\d{4}\s+\d{2}\s+\d{2}\s+\d{2}', line):
            continue
        parts = line.split()
        if len(parts) < 17:          # date(4)+RA(3)+Dec(3)+7-col tail = 17
            continue
        try:
            tail  = parts[-7:]       # [delta, r, mag, "/min, PA, alt, az]
            delta = float(tail[0])
            mag   = tail[2]
            alt   = tail[5]          # real altitude (NOT tail[4]=PA)
            date_str = f"{parts[0]}-{parts[1]}-{parts[2]} {parts[3]}h UTC"
            if closest_delta is None or delta < closest_delta:
                closest_delta = delta
                closest_date  = date_str
                closest_mag   = mag
                closest_alt   = alt
        except (ValueError, IndexError):
            continue

    closest_delta_str = 'N/A'
    if closest_delta is not None:
        ld = closest_delta * 389.17
        closest_delta_str = f"{closest_delta:.5f} AU  ({ld:.1f} LD)"

    # ------------------------------------------------------------------ #
    # 3. Classification
    #     (a) NEO sub-class (Atira/Aten/Apollo/Amor) from orbital elements.
    #     (b) Dynamical class from the Tisserand parameter RELATIVE TO
    #         JUPITER (T_J).
    #
    # NOTE: the comet/asteroid distinction uses the Tisserand parameter
    # relative to JUPITER, not Earth. A previous version read 'Tisserand
    # relative to Earth' and applied Jupiter-family thresholds to it — the
    # wrong basis, producing misleading labels. Find_Orb does not always
    # print T_J, so there is an explicit fallback when the line is absent.
    # ------------------------------------------------------------------ #

    tisserand_jup = _get(r'Tisserand relative to Jupiter:\s+([\d.]+)',
                         elements_content)

    # q and Q derived from a and e (more robust than parsing their own
    # lines):  q = a(1 - e) (perihelion)   Q = a(1 + e) (aphelion)
    EARTH_Q = 1.017   # Earth aphelion (AU)
    EARTH_q = 0.983   # Earth perihelion (AU)
    neo_subclass = "Unknown"
    try:
        a_val = float(a_au)
        e_val = float(ecc)
        q = a_val * (1.0 - e_val)
        Q = a_val * (1.0 + e_val)
        if a_val < 1.0 and Q < EARTH_q:
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

    # Dynamical class from Jupiter Tisserand (T_J)
    try:
        tj = float(tisserand_jup)
        if tj < 2:
            dyn_class = "Halley-type / long-period comet (T_J < 2)"
        elif tj < 3:
            dyn_class = "Jupiter-family comet (2 <= T_J < 3)"
        else:
            dyn_class = "Asteroid (T_J >= 3)"
    except ValueError:
        dyn_class = "Unavailable (Find_Orb did not report T_J)"

    # ------------------------------------------------------------------ #
    # 4. Flags
    # ------------------------------------------------------------------ #
    # PHA: MOID < 0.05 AU and H < 22
    try:
        pha = float(moid) < 0.05 and float(h_mag) < 22
    except ValueError:
        pha = False

    # Hyperbolic / interstellar: e >= 1
    try:
        hyperbolic = float(ecc) >= 1.0
    except ValueError:
        hyperbolic = False

    # Earth-crossing: MOID < 0.05 AU (regardless of size)
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

    # Warning flags at the top — most prominent
    if hyperbolic:
        blocks.append(("⚠  HYPERBOLIC ORBIT (e ≥ 1) — POSSIBLE INTERSTELLAR OBJECT\n", W))
    if pha:
        blocks.append(("⚠  POTENTIALLY HAZARDOUS ASTEROID (PHA) — MOID < 0.05 AU  &  H < 22\n", W))
    elif earth_crossing:
        blocks.append(("⚠  EARTH-CROSSING ORBIT — MOID < 0.05 AU\n", W))

    if blocks:
        blocks.append(("\n", S))

    blocks += [
        (f"Object          : {target_object}\n", S),
        (f"NEO sub-class   : {neo_subclass}\n", S),
        (f"Dynamical class : {dyn_class}\n", S),
        (f"\n", S),
        (f"── Physical ──────────────────────────────\n", S),
        (f"Est. diameter   : {diameter} m  (10% albedo assumed)\n", S),
        (f"Abs. magnitude  : H = {h_mag}\n", S),
        (f"\n", S),
        (f"── Orbit ─────────────────────────────────\n", S),
        (f"Semi-major axis : {a_au} AU\n", S),
        (f"Eccentricity    : {ecc}", S),
    ]

    # Inline hyperbolic flag next to eccentricity
    if hyperbolic:
        blocks.append(("  ← hyperbolic\n", W))
    else:
        blocks.append(("\n", S))

    blocks += [
        (f"Inclination     : {incl}°\n", S),
        (f"Perihelion      : {perihelion}\n", S),
        (f"Earth MOID      : {moid} AU", S),
    ]

    if earth_crossing:
        blocks.append(("  ← Earth-crossing\n", W))
    else:
        blocks.append(("\n", S))

    blocks += [
        (f"PHA             : {'YES' if pha else 'No'}", S),
    ]
    if pha:
        blocks.append(("  ⚠\n", W))
    else:
        blocks.append(("\n", S))

    blocks += [
        (f"Tisserand (T_E) : {tisserand}\n", S),
        (f"Tisserand (T_J) : {tisserand_jup}\n", S),
        (f"\n", S),
        (f"── Min. Distance in Ephemeris Window ─────\n", S),
        (f"Time (min dist) : {closest_date}\n", S),
        (f"Min. distance   : {closest_delta_str}\n", S),
        (f"Magnitude       : {closest_mag}\n", S),
        (f"Altitude        : {closest_alt}°  (observatory)\n", S),
        (f"Enc. velocity   : {enc_vel} km/s\n", S),
        (f"\n", S),
        (f"── Observations ──────────────────────────\n", S),
        (f"Used / total    : {obs_used} / {obs_total}\n", S),
        (f"Observed arc    : {obs_arc}\n", S),
        (f"NEO score       : {score}\n", S),
    ]

    return blocks


class FindOrbApp:
    """Main application — split-pane layout with integrated NEOCP panel."""

    def __init__(self, root, find_orb_path):
        self.root = root
        self.root.title("NEO Tracker  |  Ephemeris Calculator")
        self.root.geometry("1400x800")
        self.root.configure(bg=C['bg'])
        self.root.minsize(900, 600)

        self.find_orb_path = find_orb_path
        self.validate_find_orb_path()
        self._processing = False

        self._apply_theme()
        self.create_layout()
        self.create_menu()
        self.create_status_bar()
        self._load_saved_obs_code()

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

    def _build_right_panel(self):
        # Form
        form_frame = ttk.Frame(self.right_frame, style='Panel.TFrame')
        form_frame.pack(fill='x', padx=14, pady=(12, 6))
        form_frame.columnconfigure(1, weight=1)

        # Object type
        ttk.Label(form_frame, text="Object type:",
                  style='Header.TLabel').grid(row=0, column=0, sticky='w', pady=5)
        self.object_type = tk.StringVar(value="NEO")
        radio_frame = ttk.Frame(form_frame, style='Panel.TFrame')
        radio_frame.grid(row=0, column=1, sticky='w', padx=(6, 0))
        ttk.Radiobutton(radio_frame, text="NEO",
                        variable=self.object_type, value="NEO").pack(side='left', padx=(0, 14))
        ttk.Radiobutton(radio_frame, text="NEOCP",
                        variable=self.object_type, value="NEOCP").pack(side='left')

        # Object name
        ttk.Label(form_frame, text="Object name:",
                  style='Header.TLabel').grid(row=1, column=0, sticky='w', pady=5)
        self.target_object_entry = ttk.Entry(form_frame, font=('Segoe UI', 10))
        self.target_object_entry.grid(row=1, column=1, sticky='ew', padx=(6, 0))
        self.target_object_placeholder = "e.g. 2021 PDC"
        self.target_object_entry.insert(0, self.target_object_placeholder)
        self.target_object_entry.configure(foreground=C['fg_dim'])
        self.target_object_entry.bind("<FocusIn>",
            lambda e: self.clear_placeholder(e, self.target_object_entry,
                                             self.target_object_placeholder))
        self.target_object_entry.bind("<FocusOut>",
            lambda e: self.add_placeholder(e, self.target_object_entry,
                                           self.target_object_placeholder))
        Tooltip(self.target_object_entry, "Enter the object designation (e.g. 2021 PDC)")

        # Observatory code
        ttk.Label(form_frame, text="Observatory code:",
                  style='Header.TLabel').grid(row=2, column=0, sticky='w', pady=5)
        self.obs_code_entry = ttk.Entry(form_frame, font=('Segoe UI', 10), width=12)
        self.obs_code_entry.grid(row=2, column=1, sticky='w', padx=(6, 0))
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
                  style='Header.TLabel').grid(row=3, column=0, sticky='w', pady=5)
        self.eph_steps_entry = ttk.Entry(form_frame, font=('Segoe UI', 10), width=8)
        self.eph_steps_entry.grid(row=3, column=1, sticky='w', padx=(6, 0))
        self.eph_steps_entry.insert(0, "10")
        Tooltip(self.eph_steps_entry, "Number of ephemeris data points to calculate")

        # Buttons
        btn_frame = ttk.Frame(form_frame, style='Panel.TFrame')
        btn_frame.grid(row=4, column=0, columnspan=2, pady=(12, 4), sticky='w')

        self.submit_button = ttk.Button(btn_frame, text="▶  Submit", command=self.submit)
        self.submit_button.pack(side='left', padx=(0, 8))
        self.root.bind('<Control-s>', lambda e: self.submit(), add='')
        Tooltip(self.submit_button, "Calculate ephemerides  (Ctrl+S)")

        reset_btn = ttk.Button(btn_frame, text="⟳  Reset",
                               style='Secondary.TButton', command=self.refresh)
        reset_btn.pack(side='left')
        self.root.bind('<Control-n>', lambda e: self.refresh(), add='')
        Tooltip(reset_btn, "Clear all fields  (Ctrl+N)")

        # Progress bar
        self.progress = ttk.Progressbar(self.right_frame, mode='indeterminate')

        # Separator
        ttk.Separator(self.right_frame, orient='horizontal').pack(fill='x',
                                                                   padx=10, pady=4)

        # Results header
        res_hdr = ttk.Frame(self.right_frame, style='Panel.TFrame')
        res_hdr.pack(fill='x', padx=14, pady=(2, 2))
        ttk.Label(res_hdr, text="Results", style='PanelTitle.TLabel').pack(side='left')

        # Results text area
        mono = ('Cascadia Code', 9) if self._font_exists('Cascadia Code') \
            else ('Courier New', 9)
        self.text_area = scrolledtext.ScrolledText(
            self.right_frame, wrap=tk.WORD, font=mono,
            background=C['bg'], foreground=C['fg'],
            insertbackground=C['fg'], selectbackground=C['row_sel'],
            borderwidth=0, relief='flat'
        )
        self.text_area.configure(state='disabled')
        self.text_area.pack(expand=True, fill='both', padx=10, pady=(0, 6))

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

        neofixer_menu = tk.Menu(menubar, tearoff=0, background=C['panel'],
                                foreground=C['fg'], activebackground=C['accent'],
                                activeforeground='#ffffff')
        menubar.add_cascade(label="NEOFIXER", menu=neofixer_menu)
        neofixer_menu.add_command(label="Run NEOFIXER", command=self.run_neofixer)

        help_menu = tk.Menu(menubar, tearoff=0, background=C['panel'],
                            foreground=C['fg'], activebackground=C['accent'],
                            activeforeground='#ffffff')
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="User Manual", command=self.show_help)
        help_menu.add_separator()
        help_menu.add_command(label="About", command=self.show_about)

        quit_menu = tk.Menu(menubar, tearoff=0, background=C['panel'],
                            foreground=C['fg'], activebackground=C['accent'],
                            activeforeground='#ffffff')
        menubar.add_cascade(label="Quit", menu=quit_menu)
        quit_menu.add_command(label="Quit", command=self.quit_application)

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------

    def create_status_bar(self):
        self.status_bar = tk.Label(self.root, text="Ready",
                                   background=C['status_bg'],
                                   foreground=C['status_fg'],
                                   anchor='w', padx=10,
                                   font=('Segoe UI', 9))
        self.status_bar.pack(side='bottom', fill='x')

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_find_orb_path(self):
        executable = os.path.join(self.find_orb_path, 'fo64.exe')
        if not os.path.exists(executable):
            messagebox.showerror("Error", f"fo64.exe not found at: {executable}")
            sys.exit(1)

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
        elif not re.match(r'^[A-Za-z0-9\s\-]+$', obj_name):
            self.target_object_entry.configure(style='Error.TEntry')
            messagebox.showerror("Error",
                                 "Invalid object name. Enter a valid designation.")
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
        object_type_value = self.object_type.get()
        target_object = self.target_object_entry.get().strip()
        obs_code = self.obs_code_entry.get().strip()

        self.root.after(0, lambda: self.submit_button.configure(state='disabled'))
        self.root.after(0, lambda: self.progress.pack(pady=4))
        self.root.after(0, self.progress.start)
        self.root.after(0, lambda: self.status_bar.config(
            text="Fetching observations…"))

        try:
            # eph_steps was already validated as a positive integer in
            # validate_entries(). int() here is just a conversion — it lives
            # INSIDE the try/finally, so any unexpected failure still releases
            # _processing and re-enables the button.
            eph_steps_int = int(self.eph_steps_entry.get())

            obs80_string = get_observations(object_type_value, target_object)

            # --- Observation contamination filter ---
            # Applies ONLY to the get-obs-neocp endpoint: it occasionally
            # mixes lines from other objects into the payload (e.g. querying
            # C45YPL1 returned 2 lines for TF26C14). On that endpoint the
            # trksub appears as raw text in the designation columns, so a
            # literal comparison works.
            #
            # For NEO we do NOT filter: get-obs already returns only the
            # requested object, and OBS80 columns 1-12 hold the PACKED
            # designation, which never equals the human-readable form
            # (e.g. "2024 MK" -> "K24M00K"). Filtering by literal equality
            # here removed ALL of a NEO's observations, producing an empty
            # file and making fo64.exe return exit status 1.
            all_lines = obs80_string.splitlines()

            if object_type_value == "NEOCP":
                filtered_lines = [ln for ln in all_lines
                                  if ln[:12].strip() == target_object]
                non_blank = [ln for ln in all_lines if ln.strip()]
                removed = len(non_blank) - len(filtered_lines)
                if removed > 0:
                    foreign_ids = {ln[:12].strip() for ln in non_blank
                                   if ln[:12].strip() != target_object}
                    logger.warning(
                        f"NEOCP {target_object}: removed {removed} line(s) "
                        f"belonging to other objects: {foreign_ids}")
                obs80_string = '\n'.join(filtered_lines)
            else:
                obs80_string = '\n'.join(ln for ln in all_lines if ln.strip())

            if not obs80_string.strip():
                # No valid observations -> clear message instead of the cryptic
                # "find_orb exit 1". The substring below routes to the friendly
                # handler in the except block.
                raise KeyError("Error processing response data. "
                               "No valid observations returned.")

            logger.debug(f"OBS80 content for {target_object}:\n{obs80_string}")

            # Remove any leftover observation files before writing new one
            # Find_Orb processes ALL .txt files in its directory if multiple exist
            import glob
            for old_obs in glob.glob(os.path.join(self.find_orb_path, 'obs_*.txt')):
                try:
                    os.remove(old_obs)
                except Exception:
                    pass

            obs_file_path = os.path.join(self.find_orb_path,
                                         f"obs_{target_object}.txt")
            with open(obs_file_path, 'w') as obs_file:
                obs_file.write(obs80_string)

            self.root.after(0, lambda: self.status_bar.config(
                text="Running find_orb…"))

            elements_content, eph_content = run_find_orb(
                obs_file_path, obs_code, self.find_orb_path, eph_steps_int)

            self.root.after(0, lambda: self.status_bar.config(
                text="Processing results…"))

            with open(obs_file_path, 'r') as f:
                obs_content = f.read()

            self.root.after(0, self.show_text, elements_content,
                            eph_content, obs_content, target_object)
            self.root.after(0, lambda: self.save_obs_code(obs_code))

            self.delete_temp_files([
                obs_file_path,
                os.path.join(self.find_orb_path, 'efemerides.txt'),
                os.path.join(self.find_orb_path, 'elements.txt')
            ])

        except Exception as e:
            logger.error(str(e))
            msg = str(e)
            if "Invalid observatory code" in msg:
                self.root.after(0, lambda: messagebox.showerror("Error",
                    "Invalid observatory code.\n"
                    "See: https://minorplanetcenter.net/iau/lists/ObsCodes.html"))
            elif "Error processing response data" in msg:
                self.root.after(0, lambda: messagebox.showerror("Error",
                    "Object not found. Check the designation and try again."))
                self.root.after(0, self.refresh)
            elif "Error executing find_orb" in msg:
                self.root.after(0, lambda: messagebox.showerror("Error",
                    "find_orb execution failed. Check installation and config."))
            else:
                self.root.after(0, lambda: messagebox.showerror("Error",
                    f"Unexpected error: {msg}\nSee app.log for details."))
            self.root.after(0, lambda: self.status_bar.config(text="Error."))
        finally:
            self._processing = False
            self.root.after(0, self.progress.stop)
            self.root.after(0, self.progress.pack_forget)
            self.root.after(0, lambda: self.submit_button.configure(state='normal'))

    def delete_temp_files(self, files):
        for file in files:
            try:
                if os.path.exists(file):
                    os.remove(file)
            except Exception as e:
                logger.error(f"Could not delete file {file}: {e}")

    # ------------------------------------------------------------------
    # Observatory code persistence
    # ------------------------------------------------------------------

    def save_obs_code(self, obs_code):
        """Saves the observatory code to config.ini after a successful submission."""
        code_to_save = (obs_code
                        if obs_code and obs_code != self.obs_code_placeholder
                        else '500')
        config = configparser.ConfigParser()
        config.read('config.ini')
        if 'Paths' not in config:
            config['Paths'] = {}
        config['Paths']['obs_code'] = code_to_save
        with open('config.ini', 'w') as f:
            config.write(f)
        logger.debug(f"Observatory code saved: {code_to_save}")

    def _load_saved_obs_code(self):
        """Loads saved observatory code from config.ini and pre-fills the field."""
        config = configparser.ConfigParser()
        config.read('config.ini')
        saved_code = config.get('Paths', 'obs_code', fallback='X93')
        self.obs_code_entry.configure(foreground=C['entry_fg'])
        self.obs_code_entry.delete(0, tk.END)
        self.obs_code_entry.insert(0, saved_code)

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
            self._load_saved_obs_code()

            self.eph_steps_entry.configure(style='TEntry')
            self.eph_steps_entry.delete(0, tk.END)
            self.eph_steps_entry.insert(0, "10")

            self.text_area.configure(state='normal')
            self.text_area.delete(1.0, tk.END)
            self.text_area.configure(state='disabled')
            self.status_bar.config(text="Ready")

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------

    def show_text(self, elements_content, eph_content, obs_content, target_object):
        self.text_area.configure(state='normal')
        self.text_area.delete(1.0, tk.END)
        mono = ('Cascadia Code', 9) if self._font_exists('Cascadia Code') \
            else ('Courier New', 9)
        self.text_area.tag_configure('header',
                                     font=('Segoe UI', 10, 'bold'),
                                     foreground=C['warning'])
        self.text_area.tag_configure('content', font=mono, foreground=C['fg'])
        self.text_area.tag_configure('summary',
                                     font=('Segoe UI', 10),
                                     foreground=C['success'])
        self.text_area.tag_configure('summary_warning',
                                     font=('Segoe UI', 10, 'bold'),
                                     foreground='#f44747')  # bright red

        # Summary block
        self.text_area.insert(tk.INSERT, "── Summary ──\n", 'header')
        try:
            summary_blocks = parse_summary(elements_content, eph_content, target_object)
            for text, tag in summary_blocks:
                self.text_area.insert(tk.INSERT, text, tag)
        except Exception as e:
            logger.warning(f"Could not generate summary: {e}")
            self.text_area.insert(tk.INSERT, "(Summary unavailable)\n", 'summary')

        self.text_area.insert(tk.INSERT, "\n", 'content')
        self.text_area.insert(tk.INSERT, "── Orbital Elements ──\n", 'header')
        self.text_area.insert(tk.INSERT, elements_content + "\n", 'content')
        self.text_area.insert(tk.INSERT, "── Ephemerides ──\n", 'header')
        self.text_area.insert(tk.INSERT, eph_content + "\n", 'content')
        self.text_area.insert(tk.INSERT, "── Observations ──\n", 'header')
        self.text_area.insert(tk.INSERT, obs_content, 'content')
        self.text_area.configure(state='disabled')
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

            desig_idx = cols.index('Temp_Desig') if 'Temp_Desig' in cols else 0

            for i, (_, row) in enumerate(df.iterrows()):
                values = [f"{row[c]:.1f}" if isinstance(row[c], float) and c == 'V'
                          else f"{row[c]:.2f}" if isinstance(row[c], float)
                          else row[c] for c in cols]
                tag = 'even' if i % 2 == 0 else 'odd'
                self.neocp_tree.insert("", "end", values=values, tags=(tag,))

            self.neocp_tree.tag_configure('even', background=C['row_even'])
            self.neocp_tree.tag_configure('odd', background=C['row_odd'])

            self.neocp_tree.bind(
                "<Double-1>",
                lambda e: self._select_neocp_from_panel(e, desig_idx))

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

    def _select_neocp_from_panel(self, event, desig_idx):
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
        designation = values[desig_idx]
        self.target_object_entry.configure(foreground=C['entry_fg'],
                                           style='TEntry')
        self.target_object_entry.delete(0, tk.END)
        self.target_object_entry.insert(0, designation)
        self.object_type.set("NEOCP")
        self.status_bar.config(
            text=f"Selected: {designation}  —  press Submit to calculate ephemerides.")

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
    # NEOFIXER
    # ------------------------------------------------------------------

    def run_neofixer(self):
        try:
            site_code = self.obs_code_entry.get()
            if not site_code or site_code == self.obs_code_placeholder:
                site_code = 'X93'
            response = requests.get(
                f'https://neofixerapi.arizona.edu/targets/?site={site_code}&num=40')
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

        tree = ttk.Treeview(win)
        tree.pack(expand=True, fill='both', padx=10, pady=10)

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

        scrollbar = ttk.Scrollbar(win, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')

    def sort_by(self, tree, col, descending):
        data = [(tree.set(child, col), child) for child in tree.get_children('')]
        try:
            data.sort(key=lambda x: float(x[0]), reverse=descending)
        except ValueError:
            data.sort(reverse=descending)
        for ix, item in enumerate(data):
            tree.move(item[1], '', ix)
        tree.heading(col, command=lambda: self.sort_by(tree, col, not descending))

    # ------------------------------------------------------------------
    # Help / About / Quit
    # ------------------------------------------------------------------

    def show_about(self):
        messagebox.showinfo("About",
                            "NEO Tracker  |  Ephemeris Calculator\n"
                            "Developed by Andre\n\n"
                            "Data: Minor Planet Center · Find_Orb (Project Pluto)")

    def show_help(self):
        help_text = (
            "User Manual\n\n"
            "NEO Tracker calculates ephemerides and orbital elements "
            "for NEOs and NEOCP candidates.\n\n"
            "Quick start:\n"
            "1. The NEOCP panel on the left loads candidates automatically.\n"
            "   Double-click any row to fill the form.\n"
            "2. Select the object type (NEO or NEOCP).\n"
            "3. Enter the object designation, observatory code, and ephemeris steps.\n"
            "4. Click Submit (or Ctrl+S).\n\n"
            "Observatory code:\n"
            "  3-character alphanumeric MPC code.\n"
            "  List: https://minorplanetcenter.net/iau/lists/ObsCodes.html\n"
            "  Default: X93. Falls back to 500 (geocentric) if empty.\n\n"
            "Configuration (config.ini):\n"
            "  [Paths]\n"
            "  find_orb_path = C:\\Path\\To\\find_c64\n"
            "  obs_code = X93\n\n"
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
    parser = argparse.ArgumentParser(description='NEO Tracker — Ephemeris Calculator')
    parser.add_argument('--find_orb_path', type=str,
                        help='Path to the find_orb executable directory')
    args = parser.parse_args()

    config = configparser.ConfigParser()
    config.read('config.ini')
    find_orb_path = config.get('Paths', 'find_orb_path', fallback=None)

    if args.find_orb_path:
        find_orb_path = args.find_orb_path

    root = tk.Tk()
    root.withdraw()

    if not find_orb_path or not os.path.exists(find_orb_path):
        messagebox.showerror("Error",
                             "find_orb path not specified or not found.\n"
                             "Set find_orb_path in config.ini or use --find_orb_path.")
        sys.exit(1)

    executable = os.path.join(find_orb_path, 'fo64.exe')
    if not os.path.exists(executable):
        messagebox.showerror("Error", f"fo64.exe not found at: {executable}")
        sys.exit(1)

    root.deiconify()
    app = FindOrbApp(root, find_orb_path=find_orb_path)
    root.mainloop()


if __name__ == "__main__":
    main()
