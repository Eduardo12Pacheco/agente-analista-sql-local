"""``sqlagent`` command-line interface.

T4 adds the ``data`` command group (``info``, ``verify``, ``build``); the
``ask``, ``eval``, ``serve`` and ``doctor`` groups arrive in later tasks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from sqlagent import __version__
from sqlagent.adapters.cli.doctor import run_doctor
from sqlagent.adapters.cli.render import answer_to_json, render_answer
from sqlagent.adapters.warehouse.etl import (
    ATTRIBUTION,
    BUNDLE_DIR,
    LICENSE,
    TABLE_ORDER,
    build_warehouse,
    download_and_build,
    load_manifest,
    verify_bundle,
)
from sqlagent.application.use_cases.ask import AskQuestion
from sqlagent.bootstrap import build_agent
from sqlagent.config import Settings
from sqlagent.domain.errors import ConfigError, SqlAgentError, WarehouseUnavailable
from sqlagent.domain.models import Language, Status
from sqlagent.logging import configure_logging

_LLM_BACKENDS = {"ollama", "replay"}
_LANGUAGES = {"auto", "es", "en"}

app = typer.Typer(
    name="sqlagent",
    help="Local-first AI data analyst over a bundled DuckDB warehouse.",
    add_completion=False,
    no_args_is_help=True,
)
data_app = typer.Typer(
    help="Inspect, verify and rebuild the bundled SERCOP warehouse.",
    no_args_is_help=True,
)
app.add_typer(data_app, name="data")


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"sqlagent {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_show_version,
            is_eager=True,
            help="Show the sqlagent version and exit.",
        ),
    ] = False,
) -> None:
    """Answer analytics questions locally; see README for the full workflow."""


@app.command("ask")
def ask(  # noqa: PLR0913, PLR0917 - every D25 flag is part of the CLI contract
    question: Annotated[str, typer.Argument(help="Analytics question in Spanish or English.")],
    lang: Annotated[
        str,
        typer.Option("--lang", help="Question/answer language: auto, es or en."),
    ] = "auto",
    llm: Annotated[
        str,
        typer.Option("--llm", help="LLM backend: ollama (live) or replay (recorded)."),
    ] = "ollama",
    model: Annotated[
        str | None,
        typer.Option("--model", help="Model name override (default from settings)."),
    ] = None,
    no_narrate: Annotated[
        bool,
        typer.Option("--no-narrate", help="Use the deterministic answer template."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print exactly one JSON document to stdout."),
    ] = False,
    trace: Annotated[
        bool,
        typer.Option("--trace", help="Show phase timings, attempts and guardrail events."),
    ] = False,
    manifest: Annotated[
        Path | None,
        typer.Option("--manifest", help="External lakehouse manifest (T11 adapter)."),
    ] = None,
) -> None:
    """Ask one analytics question: answer, SQL, table, chart and optional trace."""

    if lang not in _LANGUAGES:
        typer.echo(f"error: --lang must be one of {sorted(_LANGUAGES)}", err=True)
        raise typer.Exit(2)
    if llm not in _LLM_BACKENDS:
        typer.echo(f"error: --llm must be one of {sorted(_LLM_BACKENDS)}", err=True)
        raise typer.Exit(2)
    settings = Settings()
    updates: dict[str, object] = {"llm_backend": llm}
    if model:
        updates["model"] = model
    if manifest is not None:
        updates["lakehouse_manifest"] = manifest
    settings = settings.model_copy(update=updates)
    configure_logging(settings)
    language = None if lang == "auto" else Language(lang)
    try:
        agent = build_agent(settings, narrate=not no_narrate)
        answer = AskQuestion(agent).execute(question, language=language)
    except WarehouseUnavailable as exc:
        typer.echo(f"error: warehouse unavailable: {exc}", err=True)
        raise typer.Exit(3) from exc
    except ConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    except SqlAgentError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(3) from exc
    if json_output:
        typer.echo(answer_to_json(answer))
    else:
        render_answer(answer, trace=trace)
    raise typer.Exit(0 if answer.status is not Status.FAILED else 1)


@app.command("doctor")
def doctor(
    offline: Annotated[
        bool,
        typer.Option(
            "--offline",
            help="Skip all network probes; report warehouse and demo availability only.",
        ),
    ] = False,
) -> None:
    """Check Python, warehouse, Ollama, model presence and GPU; suggest next steps."""

    settings = Settings()
    configure_logging(settings)
    report = run_doctor(settings, offline=offline)
    typer.echo("sqlagent doctor")
    for check in report.checks:
        status = "OK" if check.ok else "--"
        typer.echo(f"[{status}] {check.name}: {check.detail}")
    if report.warehouse_ok:
        typer.echo("warehouse OK")
    else:
        typer.echo("warehouse broken", err=True)
    if report.actions:
        typer.echo("")
        typer.echo("Next steps:")
        for action in report.actions:
            typer.echo(f"  {action}")
    raise typer.Exit(report.exit_code)


@data_app.command("info")
def data_info(
    bundle: Annotated[
        Path,
        typer.Option("--bundle", help="Warehouse bundle directory.", show_default=False),
    ] = BUNDLE_DIR,
) -> None:
    """Show table row counts, source and licence for the bundled warehouse."""

    try:
        manifest = load_manifest(bundle)
    except SqlAgentError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(3) from exc
    tables = manifest.get("tables", {})
    if not isinstance(tables, dict):
        typer.echo("error: malformed manifest tables", err=True)
        raise typer.Exit(3)
    typer.echo("SERCOP Ecuador OCDS 2021 warehouse")
    typer.echo("")
    typer.echo(f"{'table':<16}{'rows':>10}")
    for table in TABLE_ORDER:
        entry = tables.get(table)
        rows = entry.get("rows", 0) if isinstance(entry, dict) else 0
        typer.echo(f"{table:<16}{rows:>10}")
    source = manifest.get("source", {})
    if not isinstance(source, dict):
        source = {}
    typer.echo("")
    typer.echo(f"Source: {source.get('url', '')}")
    typer.echo(f"Licence: {LICENSE} (https://creativecommons.org/licenses/by/3.0/ec/)")
    typer.echo(ATTRIBUTION)


@data_app.command("verify")
def data_verify(
    bundle: Annotated[
        Path,
        typer.Option("--bundle", help="Warehouse bundle directory.", show_default=False),
    ] = BUNDLE_DIR,
) -> None:
    """Recompute Parquet hashes, row counts and fingerprints; exit 2 on failure."""

    try:
        report = verify_bundle(bundle)
    except SqlAgentError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    if not report.ok:
        for error in report.errors:
            typer.echo(f"FAIL {error}", err=True)
        raise typer.Exit(2)
    typer.echo(f"{'table':<16}{'rows':>10}")
    for table in TABLE_ORDER:
        if table in report.tables:
            typer.echo(f"{table:<16}{report.tables[table]:>10}")
    typer.echo(f"OK: {sum(report.tables.values())} rows across {len(report.tables)} tables")


@data_app.command("build")
def data_build(
    year: Annotated[int, typer.Option(help="OCDS publication year.")] = 2021,
    source: Annotated[
        Path | None,
        typer.Option("--source", help="Local OCDS CSV directory (skips the download)."),
    ] = None,
    out: Annotated[Path, typer.Option("--out", help="Output bundle directory.")] = BUNDLE_DIR,
    allow_checksum_drift: Annotated[
        bool,
        typer.Option(
            "--allow-checksum-drift",
            help="Accept upstream member changes after a manual review (D6).",
        ),
    ] = False,
) -> None:
    """Rebuild the Parquet bundle from pinned upstream CSVs (network only here)."""

    try:
        if source is not None:
            report = build_warehouse(source, out, allow_drift=allow_checksum_drift)
        else:
            settings = Settings()
            report = download_and_build(
                out,
                year=year,
                cache_dir=settings.data_dir / "cache",
                allow_drift=allow_checksum_drift,
            )
    except SqlAgentError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    for table in TABLE_ORDER:
        typer.echo(f"{table:<16}{report.tables.get(table, 0):>10}")
    typer.echo(f"wrote {report.manifest_path.name} ({report.total_bytes:,} parquet bytes)")


if __name__ == "__main__":  # pragma: no cover - exercised through the console script
    main()
