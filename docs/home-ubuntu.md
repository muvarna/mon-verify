# Ubuntu home runbook — MU-Varna 2025

This workflow uses **WoS Expanded + OMEGA + 2025 JCR/InCites quartiles + SciVal**. It does **not** call the Scopus API.

## 1. Install

```bash
git clone https://github.com/muvarna/mon-verify.git
cd mon-verify
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

## 2. Configure WoS

```bash
cp .env.example .env
nano .env
```

Add:

```text
WOS_API_KEY=YOUR_WOS_EXPANDED_API_KEY
```

## 3. Put the input files in place

```bash
mkdir -p data/input data/raw data/output
```

Use:

```text
data/input/omega.csv
data/input/quartiles.csv
data/input/scival.csv
```

The SciVal CSV may start directly with its header row. Required standard fields include:

```text
Title,Year,DOI,EID,Number of Institutions
```

SciVal EID is used to reconcile OMEGA `ScopusId`. Matching priority is:

1. normalized DOI exact match;
2. existing Scopus ID/EID exact match;
3. exact normalized title + year when unambiguous.

For a matched record the canonical values become:

```text
ScopusId = numeric Scopus ID, e.g. 85219548783
Scopus EID = full EID, e.g. 2-s2.0-85219548783
```

The original OMEGA value is preserved separately as `Original OMEGA ScopusId`.

SciVal institution count `0` is treated as missing and therefore requires manual review unless WoS supplies a positive count.

## 4. Inspect inputs

```bash
monverify inspect-omega data/input/omega.csv
monverify inspect-quartiles data/input/quartiles.csv
monverify inspect-scival data/input/scival.csv
monverify inspect-ministry
```

## 5. Fetch independent WoS discovery — compact output only

```bash
monverify fetch-wos \
  --year 2025 \
  --no-cache \
  --output data/raw/wos_2025_discovery.json
```

## 6. Verify WoS IDs already present in OMEGA

```bash
monverify fetch-wos \
  --omega data/input/omega.csv \
  --no-cache \
  --output data/raw/wos_2025_omega_ids.json
```

## 7. First verification run

```bash
monverify verify \
  --omega data/input/omega.csv \
  --quartiles data/input/quartiles.csv \
  --scival-csv data/input/scival.csv \
  --wos-json data/raw/wos_2025_discovery.json \
  --wos-json data/raw/wos_2025_omega_ids.json \
  --output-dir data/output
```

A record is resolved when it has a usable institution count. WoS and/or Scopus identifiers are retained as evidence. Other discrepancies can still be flagged without forcing the record into the unresolved section.

`unresolved_records.csv` contains only active publications whose selected institution count is still missing, including SciVal rows with institution count `0` when WoS did not supply a count.

## 8. Resolve missing institution counts manually

Create an overrides file:

```bash
monverify make-overrides \
  --omega data/input/omega.csv \
  --quartiles data/input/quartiles.csv \
  --scival-csv data/input/scival.csv \
  --wos-json data/raw/wos_2025_discovery.json \
  --wos-json data/raw/wos_2025_omega_ids.json \
  --output data/input/manual_overrides.csv
```

Open `data/input/manual_overrides.csv` in LibreOffice/Excel and fill:

```text
manual_institution_count
```

with the positive number of institutions found manually in WoS/Scopus/SciVal.

To remove a publication from the active calculation, set:

```text
remove = true
```

Optionally add a reason in:

```text
note
```

Then rerun:

```bash
monverify verify \
  --omega data/input/omega.csv \
  --quartiles data/input/quartiles.csv \
  --scival-csv data/input/scival.csv \
  --wos-json data/raw/wos_2025_discovery.json \
  --wos-json data/raw/wos_2025_omega_ids.json \
  --manual-overrides data/input/manual_overrides.csv \
  --output-dir data/output
```

Removed records are excluded from the active united table/calculation but preserved in:

```text
data/output/removed_records.csv
```

## 9. Output files

```text
data/output/canonical_publications.csv
data/output/united_verification_table.csv
data/output/ministry_comparison.csv
data/output/ministry_corrections.csv
data/output/unresolved_records.csv
data/output/removed_records.csv
data/output/over_10_institutions.csv
data/output/verification_summary.json
```

The united table is ordered:

```text
Resolved records — source title alphabetically
Unresolved records — source title alphabetically
```

## 10. Streamlit

```bash
monverify ui
```

The **Manual review** tab lets you:

- enter a positive institution count;
- mark any record for removal;
- add a manual note;
- apply the changes immediately;
- download `manual_overrides.csv` for reuse in later runs.

## 11. Run tests

```bash
pytest
```
