# Data directories

- `raw/`: API caches and retrieved raw JSON.
- `interim/`: canonical/intermediate datasets.
- `output/`: verification CSV/JSON reports.

The contents of these directories are ignored by Git by default because WoS/Scopus exports and API responses may contain licensed bibliographic data. Only `.gitkeep` placeholders are committed.
