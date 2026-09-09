# MON Verify — MU-Varna 2025

Auditable Python tooling for independently verifying the 2025 publication indicator supplied by the Bulgarian Ministry of Education and Science (MON) for Medical University – Varna.

The Ministry workbook is treated as a **claim**, not as source truth. The verification corpus is built from OMEGA PSIR, Web of Science Expanded, Scopus, and the supplied 2025 JCR/InCites journal-quartile export.

## 2025 Ministry claim

The supplied assessment workbook reports:

- publications: 334
- Q1 raw: 116; adjusted: 103.4
- Q2 raw: 93; adjusted: 92.1
- Q3: 50
- a4: 75
- final publication score: 968.3

Rule implemented in `config/rules_2025.yaml`:

```text
a = 5*a1 + 3*a2 + 2*a3 + a4
```

A publication with co-authors from **more than 10 institutions** contributes `0.1`; otherwise it contributes `1.0`. The rule counts institutions, not authors.

Institution configuration:

- Web of Science Organization-Enhanced: `Medical University Varna`
- Scopus Affiliation ID: `60005828`

All document/publication types are included unless later Ministry evidence establishes an exclusion.

## Evidence priority

### Quartiles

Use the supplied 2025 JCR/InCites export. It already contains the best quartile per journal.

Journal matching priority:

1. ISSN
2. eISSN
3. exact normalized journal title
4. fuzzy title only as a manual-review suggestion

The OMEGA `JIFQuartile` field is preserved for comparison but does not override the supplied JCR/InCites file.

### Institution count

Priority:

1. WoS Expanded enhanced organizations
2. Scopus affiliation metadata when WoS count is missing
3. optional SciVal CSV supplied by the user

If WoS and Scopus counts disagree, both are retained and `INSTITUTION_COUNT_MISMATCH` is reported. WoS remains the selected source because it has priority.

## Repository layout

```text
mon-verify/
├── config/rules_2025.yaml
├── src/monverify/
│   ├── cli.py
│   ├── config.py
│   ├── models.py
│   ├── normalization.py
│   ├── ministry.py
│   ├── omega.py
│   ├── incites.py
│   ├── dedup.py
│   ├── scival.py
│   ├── rules.py
│   ├── verification.py
│   ├── reporting.py
│   └── clients/
│       ├── common.py
│       ├── wos.py
│       └── scopus.py
├── streamlit_app.py
├── tests/
└── .github/workflows/tests.yml
```

## Installation

Python 3.11+ is recommended.

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Linux/macOS:

```bash
source .venv/bin/activate
pip install -e ".[dev]"
```

## API configuration

Copy `.env.example` to `.env`:

```text
WOS_API_KEY=...
SCOPUS_API_KEY=...
SCOPUS_INSTTOKEN=
```

Never commit `.env` or `.streamlit/secrets.toml`.

The WoS client sends the API key in `X-ApiKey` and paginates with `firstRecord`/`count`. The 2025 rules default to `databaseId=WOK` because the Ministry workbook explicitly says Web of Science **all databases**; `--database-id` can override this for controlled tests.

The Scopus client sends `X-ELS-APIKey`, optionally `X-ELS-Insttoken`, and uses cursor pagination when the API provides a cursor.

Both clients implement JSON page caching, retries for HTTP 429/5xx responses, and exponential backoff.

## Inspect the source files

```bash
monverify inspect-ministry "assess-MUV-2025(1).xlsx"
monverify inspect-omega "OMEGA_2025.xlsm - Worksheet (1).csv"
monverify inspect-quartiles journals_Q_wos_2025.csv
```

OMEGA IDs are read as strings so long Scopus identifiers are not converted to floating-point/scientific notation.

## API retrieval workflows

The CLI supports both required workflows. Keep the outputs separate and pass both to `verify`; the canonicalizer merges them with OMEGA.

### 1. Independent discovery — WoS Expanded

```bash
monverify fetch-wos --year 2025 --organization "Medical University Varna" --database-id WOK \
  --output data/raw/wos_2025.json
```

Default query:

```text
OG=("Medical University Varna") AND PY=2025
```

### 2. OMEGA-ID verification — WoS Expanded

```bash
monverify fetch-wos --omega "OMEGA_2025.xlsm - Worksheet (1).csv" --database-id WOK \
  --output data/raw/wos_omega_ids_2025.json
```

This retrieves the WoS/BCI/etc. identifiers already present in OMEGA and validates their record metadata independently of the institution-discovery result set.

### 3. Independent discovery — Scopus

```bash
monverify fetch-scopus --year 2025 --affiliation-id 60005828 \
  --output data/raw/scopus_2025.json
```

Default query:

```text
AF-ID(60005828) AND PUBYEAR = 2025
```

### 4. OMEGA-ID verification — Scopus

```bash
monverify fetch-scopus --omega "OMEGA_2025.xlsm - Worksheet (1).csv" \
  --output data/raw/scopus_omega_ids_2025.json
```

This uses Scopus Abstract Retrieval by the Scopus IDs already stored in OMEGA. Failed identifier lookups are preserved in the JSON rather than terminating the whole batch.

The JSON files contain raw API responses and retrieval metadata. Individual page responses are also cached under `data/raw/wos/` and `data/raw/scopus/`.

## Build and verify

OMEGA/JCR baseline only:

```bash
monverify verify \
  --ministry "assess-MUV-2025(1).xlsx" \
  --omega "OMEGA_2025.xlsm - Worksheet (1).csv" \
  --quartiles journals_Q_wos_2025.csv \
  --output-dir data/output
```

Full API reconciliation:

```bash
monverify verify \
  --ministry "assess-MUV-2025(1).xlsx" \
  --omega "OMEGA_2025.xlsm - Worksheet (1).csv" \
  --quartiles journals_Q_wos_2025.csv \
  --wos-json data/raw/wos_2025.json \
  --wos-json data/raw/wos_omega_ids_2025.json \
  --scopus-json data/raw/scopus_2025.json \
  --scopus-json data/raw/scopus_omega_ids_2025.json \
  --output-dir data/output
```

The OMEGA-only run is **not** a completed Ministry verification because it lacks independent API affiliation and institution-count evidence. Such records remain `eligible_for_calculation = unresolved`; the tool does not assume a 1.0 contribution when institution count is unknown.

## SciVal fallback

No SciVal column names are assumed. When a SciVal export is supplied, identify the actual columns explicitly.

Example:

```bash
monverify verify \
  ... \
  --scival-csv scival.csv \
  --scival-count-column "Number of institutions" \
  --scival-doi-column DOI
```

You can instead identify records using explicit WoS or Scopus identifier columns.

## Outputs

`data/output/` contains:

- `canonical_publications.csv`
- `ministry_comparison.csv`
- `ministry_corrections.csv`
- `unresolved_records.csv`
- `over_10_institutions.csv`
- `verification_summary.json`

Every canonical publication retains source provenance and available evidence URLs. `verification_summary.json` also records the run timestamp, rules version, source file names, SHA-256 hashes, API query/retrieval metadata when present, and the Git commit when run inside a Git checkout.

Important discrepancy codes include:

- `OMEGA_ONLY`
- `WOS_ONLY`
- `SCOPUS_ONLY`
- `YEAR_MISMATCH`
- `AFFILIATION_MISMATCH`
- `QUARTILE_MISMATCH`
- `QUARTILE_AMBIGUOUS`
- `JOURNAL_NOT_IN_JCR`
- `INSTITUTION_COUNT_MISMATCH`

## Deduplication

The union of WoS and Scopus is counted once per publication.

Automatic merge hierarchy:

1. normalized DOI exact match
2. exact WoS/Scopus identifiers
3. exact normalized title with compatible year (`±1` year to preserve online-first/issue-year conflicts)

Fuzzy title similarity is **not** used for automatic publication merging.

## Streamlit

Run locally:

```bash
streamlit run streamlit_app.py
```

or:

```bash
monverify ui
```

The app supports:

- uploaded/cached WoS and Scopus API data
- direct API calls from Streamlit
- Ministry vs calculated KPIs
- publication explorer
- discrepancy explorer
- `>10 institutions` records
- unresolved records
- CSV/JSON downloads

### Streamlit Community Cloud

For Streamlit Community Cloud, deploy `streamlit_app.py` from the repository root. `requirements.txt` installs the local package with `-e .`.

The app can read keys from Streamlit Secrets:

```toml
WOS_API_KEY = "..."
SCOPUS_API_KEY = "..."
SCOPUS_INSTTOKEN = "..."
```

Scopus institutional entitlements may depend on institutional IP or token configuration. For reproducibility, the hosted app also supports uploading JSON retrieved by the local CLI.

## Tests

```bash
pytest
```

CI uses mocked/synthetic data and does not require real API keys.

The rules fixture verifies:

```text
Q1 = 116 - 14 + 14*0.1 = 103.4
Q2 = 93 - 1 + 1*0.1 = 92.1
Q3 = 50
a4 = 75
a = 968.3
```

Tests also cover normalization, 10-vs-11 institution boundary, Ministry parsing, OMEGA ID preservation, quartile matching, deduplication, WoS organization counting, and WoS/Scopus pagination.

## Current verification limitations

- WoS enhanced-organization count is treated as the primary institution count. Any case where Enhanced Organization metadata is absent remains unresolved instead of guessing from suborganizations.
- Scopus Search API affiliation metadata is used only when present. If it does not provide a reliable complete institution set for a record, import a SciVal institution-count export.
- Online-first vs issue-year conflicts are preserved rather than silently corrected.
- Fuzzy journal-title matches never assign a quartile automatically.
- The Ministry result is never used to tune or force the independent calculation.
