from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import typer

from .clients.wos import WOSClient, compact_wos_pages, is_research_commons_uid
from .config import AppConfig
from .incites import QuartileIndex
from .manual import overrides_template
from .ministry import parse_ministry_workbook
from .omega import load_omega, omega_records
from .reporting import write_reports
from .rules import RuleEngine
from .scival import inspect_scival
from .verification import build_canonical_publications

app = typer.Typer(no_args_is_help=True, help="Verify MU-Varna 2025 bibliometric indicators using WoS + SciVal.")


def _logging(verbose: bool) -> None:
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _claim(ministry: Path | None, rules: RuleEngine):
    return parse_ministry_workbook(ministry) if ministry else rules.ministry_claim()


@app.command("inspect-ministry")
def inspect_ministry(path: Path | None = typer.Argument(None, exists=True, readable=True), rules_path: Path = typer.Option(Path("config/rules_2025.yaml"), exists=True)) -> None:
    typer.echo(json.dumps(_claim(path, RuleEngine.from_yaml(rules_path)).model_dump(), ensure_ascii=False, indent=2))


@app.command("inspect-omega")
def inspect_omega(path: Path = typer.Argument(..., exists=True, readable=True)) -> None:
    frame = load_omega(path)
    summary = {
        "rows": len(frame),
        "columns": list(frame.columns),
        "publication_types": frame["publicationType"].value_counts(dropna=False).to_dict(),
        "issue_years": frame["Issue year"].value_counts(dropna=False).to_dict(),
        "wos_id_present": int(frame["WoSId"].replace({"n/a": "", "N/A": ""}).astype(str).str.strip().ne("").sum()),
        "scopus_id_present": int(frame["ScopusId"].replace({"n/a": "", "N/A": ""}).astype(str).str.strip().ne("").sum()),
    }
    typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))


@app.command("inspect-quartiles")
def inspect_quartiles(path: Path = typer.Argument(..., exists=True, readable=True)) -> None:
    frame = QuartileIndex.from_csv(path).frame
    typer.echo(json.dumps({"rows": len(frame), "columns": [c for c in frame.columns if not c.startswith("_")], "quartiles": frame["_quartile"].value_counts(dropna=False).to_dict()}, ensure_ascii=False, indent=2))


@app.command("inspect-scival")
def inspect_scival_command(path: Path = typer.Argument(..., exists=True, readable=True)) -> None:
    typer.echo(json.dumps(inspect_scival(path), ensure_ascii=False, indent=2))


@app.command("fetch-wos")
def fetch_wos(
    year: int = typer.Option(2025),
    organization: str = typer.Option("Medical University Varna"),
    database_id: str | None = typer.Option(None),
    omega: Path | None = typer.Option(None, exists=True),
    rules_path: Path = typer.Option(Path("config/rules_2025.yaml"), exists=True),
    output: Path = typer.Option(Path("data/raw/wos_2025_compact.json")),
    no_cache: bool = typer.Option(False),
    verbose: bool = typer.Option(False),
) -> None:
    _logging(verbose)
    config = AppConfig.from_env(rules_path)
    if not config.wos_api_key:
        raise typer.BadParameter("WOS_API_KEY is not set")
    rules = RuleEngine.from_yaml(rules_path)
    db = database_id or str(rules.rules.get("wos", {}).get("database_id", "WOK"))
    client = WOSClient(config.wos_api_key, cache_dir=config.cache_dir / "wos")
    if omega:
        ids = sorted({r.wos_ut for r in omega_records(omega) if r.wos_ut and not is_research_commons_uid(r.wos_ut)})
        pages = client.get_by_ids(ids, database_id=db, use_cache=not no_cache)
        mode, query, requested_ids = "omega_ids", None, ids
    else:
        query = f'OG=("{organization}") AND PY={year}'
        pages = client.search_pages(query, database_id=db, use_cache=not no_cache)
        mode, requested_ids = "institution_discovery", None
    records = compact_wos_pages(pages, organization=organization)
    payload = {"format": "monverify-wos-compact-v1", "mode": mode, "query": query, "database_id": db, "requested_ids": requested_ids, "retrieved_at": datetime.now(timezone.utc).isoformat(), "records": records}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    typer.echo(f"Saved {len(records)} compact WoS record(s) to {output}")


def _run_verification(ministry: Path | None, omega: Path, quartiles: Path, rules_path: Path, output_dir: Path, wos_json: list[Path], scival_csv: Path, manual_overrides: Path | None) -> dict[str, Path]:
    rules = RuleEngine.from_yaml(rules_path)
    claim = _claim(ministry, rules)
    pubs = build_canonical_publications(omega_path=omega, quartiles_path=quartiles, rules_path=rules_path, wos_json=wos_json, scival_csv=scival_csv, manual_overrides_csv=manual_overrides)
    source_files = {"ministry": ministry, "omega": omega, "quartiles": quartiles, "rules": rules_path, "wos_json": wos_json, "scival_csv": scival_csv, "manual_overrides": manual_overrides}
    return write_reports(pubs, claim, rules, output_dir, source_files=source_files)


@app.command("verify")
def verify(
    omega: Path = typer.Option(..., exists=True),
    quartiles: Path = typer.Option(..., exists=True),
    scival_csv: Path = typer.Option(..., "--scival-csv", exists=True),
    wos_json: list[Path] = typer.Option([], "--wos-json", exists=True),
    manual_overrides: Path | None = typer.Option(None, "--manual-overrides", exists=True, help="CSV with canonical_id, manual_institution_count, remove, note."),
    ministry: Path | None = typer.Option(None, exists=True),
    rules_path: Path = typer.Option(Path("config/rules_2025.yaml"), exists=True),
    output_dir: Path = typer.Option(Path("data/output")),
) -> None:
    outputs = _run_verification(ministry, omega, quartiles, rules_path, output_dir, wos_json, scival_csv, manual_overrides)
    for name, path in outputs.items():
        typer.echo(f"{name}: {path}")


@app.command("make-overrides")
def make_overrides(
    omega: Path = typer.Option(..., exists=True),
    quartiles: Path = typer.Option(..., exists=True),
    scival_csv: Path = typer.Option(..., "--scival-csv", exists=True),
    wos_json: list[Path] = typer.Option([], "--wos-json", exists=True),
    rules_path: Path = typer.Option(Path("config/rules_2025.yaml"), exists=True),
    output: Path = typer.Option(Path("data/input/manual_overrides.csv")),
) -> None:
    pubs = build_canonical_publications(omega_path=omega, quartiles_path=quartiles, rules_path=rules_path, wos_json=wos_json, scival_csv=scival_csv)
    frame = overrides_template(pubs)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False, encoding="utf-8-sig")
    typer.echo(f"Saved {len(frame)} unresolved record(s) to {output}")


@app.command("build-corpus")
def build_corpus(
    omega: Path = typer.Option(..., exists=True),
    quartiles: Path = typer.Option(..., exists=True),
    scival_csv: Path = typer.Option(..., "--scival-csv", exists=True),
    wos_json: list[Path] = typer.Option([], "--wos-json", exists=True),
    manual_overrides: Path | None = typer.Option(None, "--manual-overrides", exists=True),
    rules_path: Path = typer.Option(Path("config/rules_2025.yaml"), exists=True),
    output: Path = typer.Option(Path("data/interim/canonical_publications.json")),
) -> None:
    pubs = build_canonical_publications(omega_path=omega, quartiles_path=quartiles, rules_path=rules_path, wos_json=wos_json, scival_csv=scival_csv, manual_overrides_csv=manual_overrides)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps([p.model_dump() for p in pubs], ensure_ascii=False, indent=2), encoding="utf-8")
    typer.echo(f"Saved {len(pubs)} canonical publication(s) to {output}")


@app.command("report")
def report(
    omega: Path = typer.Option(..., exists=True),
    quartiles: Path = typer.Option(..., exists=True),
    scival_csv: Path = typer.Option(..., "--scival-csv", exists=True),
    wos_json: list[Path] = typer.Option([], "--wos-json", exists=True),
    manual_overrides: Path | None = typer.Option(None, "--manual-overrides", exists=True),
    ministry: Path | None = typer.Option(None, exists=True),
    rules_path: Path = typer.Option(Path("config/rules_2025.yaml"), exists=True),
    output_dir: Path = typer.Option(Path("data/output")),
) -> None:
    outputs = _run_verification(ministry, omega, quartiles, rules_path, output_dir, wos_json, scival_csv, manual_overrides)
    typer.echo(json.dumps({k: str(v) for k, v in outputs.items()}, indent=2))


@app.command("ui")
def ui() -> None:
    app_path = Path(__file__).resolve().parents[2] / "streamlit_app.py"
    raise typer.Exit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(app_path)]))
