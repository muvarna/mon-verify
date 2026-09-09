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

Use these names for convenience:

```text
data/input/omega.csv
data/input/quartiles.csv
data/input/scival.csv
```

The SciVal CSV should start directly with the header row. The expected standard columns are:

```text
Title,Authors,Year,Scopus Source title,ISSN,Language,Citations,DOI,Publication type,EID,Number of Institutions
```

Do not include the SciVal metadata preamble or final copyright line.

## 4. Inspect all three inputs

```bash
monverify inspect-omega data/input/omega.csv
monverify inspect-quartiles data/input/quartiles.csv
monverify inspect-scival data/input/scival.csv
monverify inspect-ministry
```

The last command reads the versioned 2025 MON comparison claim from `config/rules_2025.yaml`; the Ministry workbook is optional.

## 5. Fetch independent WoS discovery — compact output only

```bash
monverify fetch-wos \
  --year 2025 \
  --no-cache \
  --output data/raw/wos_2025_discovery.json
```

`--no-cache` is important on a home computer: the full Expanded API pages are not written to the raw page cache. They are normalized in memory and the saved JSON contains only MON Verify evidence fields.

Research Commons records whose UID begins with `RC` are excluded.

## 6. Verify WoS IDs already present in OMEGA

```bash
monverify fetch-wos \
  --omega data/input/omega.csv \
  --no-cache \
  --output data/raw/wos_2025_omega_ids.json
```

This direct-ID pass is useful because a record in OMEGA may need checking even if it was not returned by the institutional discovery query.

## 7. Run the verification

```bash
monverify verify \
  --omega data/input/omega.csv \
  --quartiles data/input/quartiles.csv \
  --scival-csv data/input/scival.csv \
  --wos-json data/raw/wos_2025_discovery.json \
  --wos-json data/raw/wos_2025_omega_ids.json \
  --output-dir data/output
```

Expected outputs:

```text
data/output/canonical_publications.csv
data/output/united_verification_table.csv
data/output/ministry_comparison.csv
data/output/ministry_corrections.csv
data/output/unresolved_records.csv
data/output/over_10_institutions.csv
data/output/verification_summary.json
```

## 8. Check the summary

```bash
cat data/output/verification_summary.json
```

The `calculated.raw.a1` through `a4`, `publication_count`, weighted buckets, and `a_score` are always numeric confirmed subtotals. Unresolved records are reported separately through:

```text
unresolved_eligibility_count
unresolved_eligibility_by_bucket
unresolved_weight_count
calculation_complete
calculation_note
```

Thus an unresolved Q1 publication no longer turns the entire Q1 result into JSON `null`.

## 9. Run tests

```bash
pytest
```

## 10. Run Streamlit after the CLI fetch

The most disk-efficient approach is to fetch WoS from the CLI with `--no-cache` first, then use the compact JSON in Streamlit.

```bash
monverify ui
```

In the app choose **Uploaded/cached JSON** and upload:

- `omega.csv`
- `quartiles.csv`
- `scival.csv`
- `wos_2025_discovery.json`
- `wos_2025_omega_ids.json`

This avoids a second WoS retrieval and avoids persisting the large raw Expanded API responses.
