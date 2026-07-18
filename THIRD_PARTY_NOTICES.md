# Third-party services and data

NEOCP Explorer source code is licensed under the MIT License. The MIT License applies only to the original NEOCP Explorer source code and does not grant rights over data, responses, trademarks, documentation, or software supplied by external providers.

## External services and software

- **Project Pluto / Find_Orb, by Bill Gray** — NEOCP Explorer uses the public online ephemeris interface. Project Pluto states that use of Find_Orb in or with commercial software requires written permission. Commercial deployments must verify the current terms and obtain any permission required by Project Pluto.
- **Minor Planet Center (MPC)** — supplies the public NEOCP candidate list and observational data. Queries must be made responsibly and remain subject to the MPC's current policies.
- **NEOfixer, University of Arizona** — supplies optional observatory-specific target-priority information through its documented public API.
- **Cartes du Ciel / SkyChart** — optional GPL-licensed desktop software. NEOCP Explorer does not bundle Cartes du Ciel; it communicates with a separately installed instance through the documented TCP server interface.
- **Astropy** — used locally for coordinate transformations and distributed under its own license.

NEOCP Explorer is an independent project and is not endorsed by or affiliated with Project Pluto, the Minor Planet Center, JPL, NEOfixer, Astropy, or Cartes du Ciel.

## Data status and operational caution

NEOCP candidates, astrometry, preliminary orbital solutions, and ephemerides can change rapidly as new observations become available. Results must be verified against the current original sources before critical observing or telescope-control operations.

## Test data

Files under `tests/fixtures/` are intentionally synthetic. Names, observations, coordinates, and orbital values in those files are fictional and exist only to exercise the parser. Responses downloaded by `fetch_project_pluto_test_data.py` are stored under the ignored `.local_test_data/` directory for local diagnostics only and must not be committed or redistributed.

## Official references

- Project Pluto tools and API interfaces: https://www.projectpluto.com/tools.htm
- Project Pluto / Find_Orb licensing: https://www.projectpluto.com/find_orb.htm
- MPC public documentation: https://docs.minorplanetcenter.net/
- NEOfixer API: https://neofixer.arizona.edu/api-info
- Cartes du Ciel server commands: https://www.ap-i.net/skychart/en/documentation/server_commands
- Cartes du Ciel software license: https://www.ap-i.net/skychart/en/documentation/software_license
- Astropy license: https://github.com/astropy/astropy/blob/main/LICENSE.rst
