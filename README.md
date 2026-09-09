# MON Verify — MU-Varna 2025

Auditable verification tooling for the 2025 MU-Varna publication indicator supplied by the Bulgarian Ministry of Education and Science (MON).

This branch/workflow is intentionally designed for use **outside the MU-Varna network**:

- Web of Science Expanded API is the only live bibliographic API;
- Scopus API is not used;
- SciVal CSV provides institution counts when WoS does not;
- OMEGA is the local seed/reconciliation source;
- the supplied 2025 JCR/InCites CSV supplies the best JIF quartile per journal;
- the Ministry workbook is optional because the known 2025 claim is versioned in `config/rules_2025.yaml`.

## 2025 rule

```text
a = 5*a1 + 3*a2 + 2*a3 + a4
```

If a publication has co-authors from **more than 10 institutions**, contribution is `0.1`; otherwise `1.0`. Institution-count priority is:

1. Web of Science Organization-Enhanced institutions;
2. SciVal `Number of Institutions`.

WoS Research Commons records whose UID starts with `RC` are excluded.

## Versioned Ministry claim

`config/rules_2025.yaml` contains the comparison claim:

- publications: 334
- Q1 raw: 116
- Q1 adjusted: 103.4
- Q2 raw: 93
- Q2 adjusted: 92.1
- Q3: 50
- a4: 75
- final score: 968.3

The claim is never used to force the calculated result.

## Input CSV formats

### OMEGA

Expected headers include:

```text
Reference,Journal,publicationType,Issue year,DOI,WoSId,ScopusId,JIFQuartile,Authors MU-Varna,Link WOS,Link Scopus
```

Leading/trailing whitespace in OMEGA header names is stripped automatically.

### JCR/InCites quartiles

Expected headers:

```text
Name,ISSN,eISSN,Journal Impact Factor,JIF Quartile
```

Matching priority is ISSN, eISSN, normalized journal title. Fuzzy title matches are flagged for review.

### SciVal

For the home workflow, export/prepare the CSV so it starts directly with this header row; remove the first metadata rows and final copyright line before running:

```text
Title,Authors,Year,Scopus Source title,ISSN,Language,Citations,DOI,Publication type,EID,Number of Institutions
```

Required for institution matching are `Number of Institutions` plus one or more of `EID`, `DOI`, or `Title` + `Year`.

## Ubuntu installation

```bash
git clone https://github.com/muvarna/mon-verify.git
cd mon-verify

python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

Python 3.11 or newer is required.

Create `.env`:

```bash
cp .env.example .env
nano .env
```

Set:

```text
WOS_API_KEY=YOUR_WOS_EXPANDED_API_KEY
```

Never commit `.env`.

## Recommended local file layout

```text
data/input/
├── omega.csv
├── quartiles.csv
└── scival.csv
```

Create it with:

```bash
mkdir -p data/input data/raw data/output
```

Copy your files into `data/input/`.

## Step 1 — inspect inputs

```bash
monverify inspect-omega data/input/omega.csv
monverify inspect-quartiles data/input/quartiles.csv
monverify inspect-scival data/input/scival.csv
monverify inspect-ministry
```

`inspect-ministry` without a workbook shows the versioned 2025 claim from `config/rules_2025.yaml`.

## Step 2 — independent WoS discovery

This searches Organization-Enhanced `Medical University Varna` for 2025 and writes a compact JSON file:

```bash
monverify fetch-wos \
  --year 2025 \
  --output data/raw/wos_2025_discovery.json
```

The saved JSON does **not** contain the large complete Expanded API records. Each record is normalized immediately to the fields required by MON Verify:

- WoS UT;
- DOI;
- title;
- year;
- document type;
- journal;
- ISSN/eISSN;
- MU-Varna affiliation evidence;
- MU-Varna authors linked through WoS addresses;
- enhanced institution names and institution count;
- WoS evidence URL.

The HTTP page cache under `data/raw/wos/` may still contain raw API pages for retry/reproducibility. Delete that cache after successful compact export if disk space is a concern:

```bash
rm -rf data/raw/wos
```

## Step 3 — verify the WoS IDs already present in OMEGA

Run a second retrieval so OMEGA records that may not appear in the discovery result are checked directly by UT:

```bash
monverify fetch-wos \
  --omega data/input/omega.csv \
  --output data/raw/wos_2025_omega_ids.json
```

`RC...` Research Commons identifiers are skipped automatically.

## Step 4 — run verification

```bash
monverify verify \
  --omega data/input/omega.csv \
  --quartiles data/input/quartiles.csv \
  --scival-csv data/input/scival.csv \
  --wos-json data/raw/wos_2025_discovery.json \
  --wos-json data/raw/wos_2025_omega_ids.json \
  --output-dir data/output
```

If you also have the Ministry XLSX and want to parse it rather than use the versioned claim:

```bash
monverify verify \
  --ministry /path/to/assess-MUV-2025.xlsx \
  --omega data/input/omega.csv \
  --quartiles data/input/quartiles.csv \
  --scival-csv data/input/scival.csv \
  --wos-json data/raw/wos_2025_discovery.json \
  --wos-json data/raw/wos_2025_omega_ids.json \
  --output-dir data/output
```

## Outputs

`data/output/` contains:

```text
canonical_publications.csv
united_verification_table.csv
ministry_comparison.csv
ministry_corrections.csv
unresolved_records.csv
over_10_institutions.csv
verification_summary.json
```

The united table is OMEGA-shaped and ordered:

```text
Confirmed → Unresolved → Excluded
```

It preserves `Authors MU-Varna` and adds `MUV authors WOS`.

## Summary calculation behavior

The summary always reports numeric totals for **confirmed eligible publications**, even when other records are unresolved.

Example structure:

```json
{
  "calculated": {
    "publication_count": 436,
    "raw": {
      "a1": 100,
      "a2": 90,
      "a3": 34,
      "a4": 50
    },
    "unresolved_eligibility_count": 38,
    "calculation_complete": false,
    "calculation_note": "Confirmed subtotal only; unresolved records are reported separately"
  }
}
```

The older behavior that changed an entire bucket to JSON `null` when one unresolved publication existed in that bucket has been removed.

## Streamlit

Start locally:

```bash
source .venv/bin/activate
monverify ui
```

or:

```bash
streamlit run streamlit_app.py
```

In the browser:

1. upload OMEGA CSV;
2. upload the 2025 quartiles CSV;
3. upload the header-first SciVal CSV;
4. optionally upload the Ministry XLSX;
5. choose either uploaded/cached WoS JSON or Live WoS API;
6. run verification;
7. inspect/download the united table, discrepancy tables, >10-institution records, and summary.

No Scopus API key is requested or used.

## Tests

```bash
pytest
```

CI uses mocked APIs and requires no real API key.

Key regression coverage includes:

- Q1/Q2 Ministry fixture (`103.4`, `92.1`, final `968.3`);
- 10-vs-11 institution threshold;
- WoS pagination;
- RC Research Commons exclusion;
- compact WoS round-trip;
- WoS institution-count priority over SciVal;
- SciVal fallback when WoS count is missing;
- numeric summary subtotals when unresolved publications remain;
- normalization, deduplication and quartile matching.
