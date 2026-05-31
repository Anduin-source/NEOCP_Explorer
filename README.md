# NEO Tracker — Ephemeris Calculator

NEO Tracker is a desktop application for calculating ephemerides and orbital information for known near-Earth objects and current NEOCP candidates.

Version 3.0 removes the requirement for a local Find_Orb installation. Ephemerides and preliminary orbital solutions are obtained from the Project Pluto online Find_Orb service. The application uses MPC NEOCP data for the candidate list and Astropy for local topocentric Alt/Az and airmass calculations.

## Main features

- Loads the current MPC NEOCP candidate list automatically.
- Calculates ephemerides for both known objects and NEOCP candidates using a single workflow.
- No local `fo64.exe`, `find_orb.cfg`, `MPCORB`, or `config.ini` required.
- Supports MPC observatory codes, with `X93` as the default GUI value.
- Displays RA/Dec, magnitude, elongation, apparent motion, uncertainty, altitude, azimuth, and airmass.
- Computes apparent motion rate in arcsec/min and motion position angle.
- Shows compact orbital elements, astrometry, residuals, and advanced Project Pluto metadata.
- Includes NEOFIXER target lookup by observatory code.

## Requirements

Python 3.10 or newer is recommended.

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Required packages:

```text
requests
pandas
astropy
```

## Running from source

```bash
python NEO_Tracker.py
```

The app requires an internet connection because it queries:

- MPC NEOCP JSON list
- Project Pluto online Find_Orb server
- NEOFIXER API, only when the NEOFIXER menu is used

## Using the application

1. Wait for the NEOCP panel on the left to load.
2. Double-click a NEOCP candidate, or manually type an object designation.
3. Enter the MPC observatory code. The default is `X93`.
4. Enter the number of ephemeris steps.
5. Click **Submit**.

Example object designations:

```text
99942
Apophis
2024 MK
A11D0Xd
NAOCYLA
```

The same input field supports both known objects and current NEOCP tracklets. The app automatically infers whether the object is a current NEOCP candidate when possible.

## Ephemeris columns

| Column | Meaning |
|---|---|
| UTC | Date and time in UTC |
| RA | Right ascension, J2000/ICRF style output from Project Pluto |
| Dec | Declination |
| Mag | Approximate visual magnitude |
| Rate \"/min | Apparent sky motion in arcsec per minute |
| Mot PA | Position angle of the apparent motion |
| Elong | Solar elongation in degrees |
| Unc. ° | Ephemeris uncertainty converted to degrees |
| Alt | Topocentric altitude in degrees, computed locally with Astropy |
| Az | Topocentric azimuth in degrees, computed locally with Astropy |
| Air | Approximate airmass, shown only for useful altitudes |

Distance information such as geocentric/topocentric distance and heliocentric distance is summarized in the **Summary** tab instead of the ephemeris table.

## Building an executable

Install PyInstaller separately if needed:

```bash
python -m pip install pyinstaller
```

Build:

```bash
python -m PyInstaller --onefile --windowed --icon=neo_tracker.ico --name="NEO_Tracker" NEO_Tracker.py
```

The resulting executable is created under `dist/`.

Unlike earlier versions, no local Find_Orb folder or `config.ini` needs to be distributed with the executable.

## Troubleshooting

### Project Pluto query failed

Possible causes:

- Object designation was not found.
- The NEOCP object is too new and has not yet propagated to Project Pluto/MPC data.
- Project Pluto could not retrieve valid observations.
- The observatory code is invalid.
- The Project Pluto or MPC service is temporarily unavailable.
- Internet connection is unavailable.

### NEOCP panel failed to load

Check the internet connection and try **Refresh**.

### Alt/Az unavailable

Install Astropy:

```bash
python -m pip install astropy
```

If the observatory code is not in the local coordinate table, Alt/Az may be unavailable until coordinates are added to the code.

## Data sources and acknowledgements

- Minor Planet Center — NEOCP candidate list and small-body data.
- Project Pluto — online Find_Orb ephemeris and orbit service.
- Astropy — local coordinate transformations.
- NEOFIXER — optional target-priority information via menu.

## Version 3.0 highlights

- Removed local Find_Orb dependency.
- Removed `config.ini`.
- Unified known-object and NEOCP workflows.
- Added local Alt/Az/Airmass computation with Astropy.
- Added apparent motion rate and motion PA.
- Improved Project Pluto error handling.
- Simplified distribution for Windows, macOS, and Linux.
