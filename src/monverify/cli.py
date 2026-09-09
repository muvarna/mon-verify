from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import typer

from .clients.scopus import ScopusClient
from .clients.wos import WOSClient
from .config import AppConfig
from .incites import QuartileIndex
from .ministry import parse_ministry_workbook
from .omega import load_omega, omega_records
from .reporting import write_reports
from .rules import RuleEngine
from .scival import inspect_scival
from .verification import build_canonical_publications

app = typer.Typer(no_args_is_help=True, help="Verify MU-Varna Ministry bibliometric indicators.")


def _logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@app.command("inspect-ministry")
def inspect_ministry(path: Path = typer.Argument(..., exists=True, readable=True)) -> None:
    claim = parse_ministry_workbook(path)
    typer.echo(json.dumps(claim.model_dump(), ensure_ascii=False, indent=2))


@app.command("inspect-omega")
def inspect_omega(path: Path = typer.Argument(..., exists=True, readable=True)) -> None:
    frame = load_omega(path)
    summary = {
        "rows": len(frame),
        "columns": list(frame.columns),
        "publication_types": frame["publicationType"].value_counts(dropna=False).to_dict(),
        "issue_years": frame["Issue year"].value_counts(dropna=False).to_dict(),
        "wos_id_present": int(
            frame["WoSId"].replace({"n/a": "", "N/A": ""}).astype(str).str.strip().ne("").sum()
        ),
        "scopus_id_present": int(
            frame["ScopusId"].replace({"n/a": "", "N/A": ""}).astype(str).str.strip().ne("").sum()
        ),
    }
    typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))


@app.command("inspect-quartiles")
def inspect_quartiles(path: Path = typer.Argument(..., exists=True, readable=True)) -> None:
    index = QuartileIndex.from_csv(path)
    frame = index.frame
    typer.echo(
        json.dumps(
            {
                "rows": len(frame),
                "columns": [c for c in frame.columns if not c.startswith("_")],
                "quartiles": frame["_quartile"].value_counts(dropna=False).to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("inspect-scival")
def inspect_scival_command(path: Path = typer.Argument(..., exists=True, readable=True)) -> None:
    """Inspect a standard SciVal publication export and its institution counts."""
    typer.echo(json.dumps(inspect_scival(path), ensure_ascii=False, indent=2))


@app.command("fetch-wos")
def fetch_wos(
    year: int = typer.Option(2025),
    organization: str = typer.Option("Medical University Varna"),
    database_id: str | None = typer.Option(
        None, help="WoS database ID; defaults to rules file (WOK for all databases)."
    ),
    omega: Path | None = typer.Option(
        None, exists=True, help="OMEGA CSV: verify its WoS IDs instead of institutional discovery."
    ),
    rules_path: Path = typer.Option(Path("config/rules_2025.yaml")),
    output: Path = typer.Option(Path("data/raw/wos_2025.json")),
    no_cache: bool = typer.Option(False, help="Ignore page cache."),
    verbose: bool = typer.Option(False),
) -> None:
    _logging(verbose)
    config = AppConfig.from_env(rules_path)
    if not config.wos_api_key:
        raise typer.BadParameter("WOS_API_KEY is not set")
    db = database_id or str(config.rules().get("wos", {}).get("database_id", "WOK"))
    client = WOSClient(config.wos_api_key, cache_dir=config.cache_dir / "wos")
    if omega:
        ids = sorted({r.wos_ut for r in omega_records(omega) if r.wos_ut})
        pages = client.get_by_ids(ids, database_id=db, use_cache=not no_cache)
        payload = {
            "mode": "omega_ids",
            "database_id": db,
            "requested_ids": ids,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "pages": pages,
        }
    else:
        query = f'OG=("{organization}") AND PY={year}'
        pages = client.search_pages(query, database_id=db, use_cache=not no_cache)
        payload = {
            "mode": "institution_discovery",
            "query": query,
            "database_id": db,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "pages": pages,
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    typer.echo(f"Saved {len(pages)} page(s) to {output}")


@app.command("fetch-scopus")
def fetch_scopus(
    year: int = typer.Option(2025),
    affiliation_id: str = typer.Option("60005828"),
    omega: Path | None = typer.Option(
        None, exists=True, help="OMEGA CSV: verify its Scopus IDs instead of institutional discovery."
    ),
    rules_path: Path = typer.Option(Path("config/rules_2025.yaml")),
    output: Path = typer.Option(Path("data/raw/scopus_2025.json")),
    no_cache: bool = typer.Option(False, help="Ignore page cache."),
    verbose: bool = typer.Option(False),
) -> None:
    _logging(verbose)
    config = AppConfig.from_env(rules_path)
    if not config.scopus_api_key:
        raise typer.BadParameter("SCOPUS_API_KEY is not set")
    client = ScopusClient(
        config.scopus_api_key,
        insttoken=config.scopus_insttoken,
        cache_dir=config.cache_dir / "scopus",
    )
    if omega:
        ids = sorted({r.scopus_id for r in omega_records(omega) if r.scopus_id})
        abstracts = client.retrieve_many(ids, use_cache=not no_cache)
        payload = {
            "mode": "omega_ids",
            "requested_ids": ids,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "abstracts": abstracts,
        }
        retrieved_count = len(abstracts)
    else:
        query = f"AF-ID({affiliation_id}) AND PUBYEAR = {year}"
        pages = client.search_pages(query, use_cache=not no_cache)
        payload = {
            "mode": "institution_discovery",
            "query": query,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "pages": pages,
        }
        retrieved_count = len(pages)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    typer.echo(f"Saved {retrieved_count} response unit(s) to {output}")


def _run_verification(
    ministry: Path,
    omega: Path,
    quartiles: Path,
    rules_path: Path,
    output_dir: Path,
    wos_json: list[Path],
    scopus_json: list[Path],
    scival_csv: Path | None,
    scival_count_column: str | None = None,
    scival_doi_column: str | None = None,
    scival_wos_column: str | None = None,
    scival_scopus_column: str | None = None,
) -> dict[str, Path]:
    claim = parse_ministry_workbook(ministry)
    rules = RuleEngine.from_yaml(rules_path)
    pubs = build_canonical_publications(
        omega_path=omega,
        quartiles_path=quartiles,
        rules_path=rules_path,
        wos_json=wos_json,
        scopus_json=scopus_json,
        scival_csv=scival_csv,
        scival_count_column=scival_count_column,
        scival_doi_column=scival_doi_column,
        scival_wos_column=scival_wos_column,
        scival_scopus_column=scival_scopus_column,
    )
    source_files = {
        "ministry": ministry,
        "omega": omega,
        "quartiles": quartiles,
        "rules": rules_path,
        "wos_json": wos_json,
        "scopus_json": scopus_json,
        "scival_csv": scival_csv,
    }
    return write_reports(pubs, claim, rules, output_dir, source_files=source_files)


@app.command("verify")
def verify(
    ministry: Path = typer.Option(..., exists=True),
    omega: Path = typer.Option(..., exists=True),
    quartiles: Path = typer.Option(..., exists=True),
    rules_path: Path = typer.Option(Path("config/rules_2025.yaml"), exists=True),
    output_dir: Path = typer.Option(Path("data/output")),
    wos_json: list[Path] = typer.Option(
        [], "--wos-json", exists=True, help="Repeat for discovery and OMEGA-ID WoS JSON files."
    ),
    scopus_json: list[Path] = typer.Option(
        [], "--scopus-json", exists=True, help="Repeat for discovery and OMEGA-ID Scopus JSON files."
    ),
    scival_csv: Path | None = typer.Option(
        None, "--scival-csv", exists=True, help="Standard SciVal CSV used as third-priority institution-count fallback."
    ),
    scival_count_column: str | None = typer.Option(None),
    scival_doi_column: str | None = typer.Option(None),
    scival_wos_column: str | None = typer.Option(None),
    scival_scopus_column: str | None = typer.Option(None),
) -> None:
    outputs = _run_verification(
        ministry,
        omega,
        quartiles,
        rules_path,
        output_dir,
        wos_json,
        scopus_json,
        scival_csv,
        scival_count_column,
        scival_doi_column,
        scival_wos_column,
        scival_scopus_column,
    )
    for name, path in outputs.items():
        typer.echo(f"{name}: {path}")


@app.command("build-corpus")
def build_corpus(
    omega: Path = typer.Option(..., exists=True),
    quartiles: Path = typer.Option(..., exists=True),
    rules_path: Path = typer.Option(Path("config/rules_2025.yaml"), exists=True),
    output: Path = typer.Option(Path("data/interim/canonical_publications.json")),
    wos_json: list[Path] = typer.Option([], "--wos-json", exists=True),
    scopus_json: list[Path] = typer.Option([], "--scopus-json", exists=True),
    scival_csv: Path | None = typer.Option(None, "--scival-csv", exists=True),
) -> None:
    pubs = build_canonical_publications(
        omega_path=omega,
        quartiles_path=quartiles,
        rules_path=rules_path,
        wos_json=wos_json,
        scopus_json=scopus_json,
        scival_csv=scival_csv,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps([p.model_dump() for p in pubs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    typer.echo(f"Saved {len(pubs)} canonical publication(s) to {output}")


@app.command("report")
def report(
    ministry: Path = typer.Option(..., exists=True),
    omega: Path = typer.Option(..., exists=True),
    quartiles: Path = typer.Option(..., exists=True),
    rules_path: Path = typer.Option(Path("config/rules_2025.yaml"), exists=True),
    output_dir: Path = typer.Option(Path("data/output")),
    wos_json: list[Path] = typer.Option([], "--wos-json", exists=True),
    scopus_json: list[Path] = typer.Option([], "--scopus-json", exists=True),
    scival_csv: Path | None = typer.Option(None, "--scival-csv", exists=True),
) -> None:
    outputs = _run_verification(
        ministry,
        omega,
        quartiles,
        rules_path,
        output_dir,
        wos_json,
        scopus_json,
        scival_csv,
    )
    typer.echo(json.dumps({k: str(v) for k, v in outputs.items()}, indent=2))


@app.command("ui")
def ui() -> None:
    app_path = Path(__file__).resolve().parents[2] / "streamlit_app.py"
    raise typer.Exit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(app_path)]))
