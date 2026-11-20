"""``sqlagent`` command-line interface.

T4 adds the ``data`` command group (``info``, ``verify``, ``build``); the
``ask``, ``eval``, ``serve`` and ``doctor`` groups arrive in later tasks.
"""

from __future__ import annotations

import threading
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from sqlagent import __version__
from sqlagent.adapters.benchmark.yaml_repository import YamlBenchmarkRepository
from sqlagent.adapters.cli.doctor import run_doctor
from sqlagent.adapters.cli.render import answer_to_json, render_answer
from sqlagent.adapters.llm.cassette import RecordingLLM
from sqlagent.adapters.reporting.markdown import MarkdownHtmlReportWriter
from sqlagent.adapters.warehouse.etl import (
    ATTRIBUTION,
    BUNDLE_DIR,
    LICENSE,
    MANIFEST_NAME,
    TABLE_ORDER,
    build_warehouse,
    download_and_build,
    load_manifest,
    verify_bundle,
)
from sqlagent.adapters.web.app import create_app
from sqlagent.application.evaluation.benchmark import Category
from sqlagent.application.evaluation.runner import TrackingLLM
from sqlagent.application.use_cases.ask import AskQuestion
from sqlagent.application.use_cases.evaluate import (
    EvaluationRequest,
    RunEvaluation,
    model_slug,
    verify_benchmark_lock,
)
from sqlagent.bootstrap import build_agent, build_llm, default_cassette_path
from sqlagent.bootstrap import build_warehouse as build_runtime_warehouse
from sqlagent.config import Settings
from sqlagent.domain.errors import (
    CassetteMiss,
    ConfigError,
    LLMError,
    SqlAgentError,
    WarehouseUnavailable,
)
from sqlagent.domain.models import Language, Status
from sqlagent.domain.sql_policy import SqlPolicy
from sqlagent.logging import configure_logging

_LLM_BACKENDS = {"ollama", "replay"}
_LANGUAGES = {"auto", "es", "en"}
_MAX_PORT = 65535

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


@app.command("eval")
def eval_command(  # noqa: PLR0912, PLR0913, PLR0915, PLR0917 - D25 contract
    llm: Annotated[
        str,
        typer.Option("--llm", help="LLM backend: ollama (live) or replay (recorded)."),
    ] = "ollama",
    model: Annotated[
        str | None,
        typer.Option("--model", help="Model name override (default from settings)."),
    ] = None,
    benchmark: Annotated[
        str,
        typer.Option("--benchmark", help="Benchmark version to evaluate."),
    ] = "v1",
    category: Annotated[
        list[str] | None,
        typer.Option("--category", help="Restrict to a D19 category (repeatable)."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="Evaluate only the first N selected items."),
    ] = None,
    record: Annotated[
        bool,
        typer.Option("--record", help="Record every model call to the bundled cassette."),
    ] = False,
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Output directory for the four report artifacts."),
    ] = None,
    compare: Annotated[
        Path | None,
        typer.Option("--compare", help="Baseline summary.json for the regression gate."),
    ] = None,
    max_drop: Annotated[
        float,
        typer.Option("--max-drop", help="Allowed per-metric drop for --compare."),
    ] = 0.0,
    with_narration: Annotated[
        bool,
        typer.Option("--with-narration", help="Enable the NARRATE LLM call (eval default off)."),
    ] = False,
    max_repairs: Annotated[
        int | None,
        typer.Option("--max-repairs", help="Override the repair budget (ablations)."),
    ] = None,
    no_retrieval: Annotated[
        bool,
        typer.Option("--no-retrieval", help="Ablation: skip BM25 and send all tables."),
    ] = False,
) -> None:
    """Run benchmark v1, write reports and optionally fail the regression gate."""

    if llm not in _LLM_BACKENDS:
        typer.echo(f"error: --llm must be one of {sorted(_LLM_BACKENDS)}", err=True)
        raise typer.Exit(2)
    if limit is not None and limit < 1:
        typer.echo("error: --limit must be a positive integer", err=True)
        raise typer.Exit(2)
    if max_repairs is not None and max_repairs < 0:
        typer.echo("error: --max-repairs must be >= 0", err=True)
        raise typer.Exit(2)
    if record and llm != "ollama":
        typer.echo("error: --record requires --llm ollama", err=True)
        raise typer.Exit(2)
    try:
        categories = tuple(Category(value) for value in (category or ()))
    except ValueError as exc:
        typer.echo(f"error: unknown --category: {exc}", err=True)
        raise typer.Exit(2) from exc

    settings = Settings()
    updates: dict[str, object] = {"llm_backend": llm}
    if model:
        updates["model"] = model
    if max_repairs is not None:
        updates["max_repairs"] = max_repairs
    settings = settings.model_copy(update=updates)
    configure_logging(settings)
    now = datetime.now(tz=UTC)
    run_id = f"{now:%Y%m%dT%H%M%SZ}-{model_slug(settings.model)}"
    out_dir = out if out is not None else Path("eval/reports") / run_id
    warehouse = None
    try:
        repository = YamlBenchmarkRepository()
        benchmark_model = repository.load(benchmark)
        verify_benchmark_lock(
            repository.benchmark_dir,
            benchmark,
            Path(BUNDLE_DIR) / MANIFEST_NAME,
        )
        base_llm = build_llm(settings)
        active_llm = base_llm
        if record:
            active_llm = RecordingLLM(base_llm, default_cassette_path(settings.model))
        tracker: TrackingLLM | None = None
        if llm == "replay":
            tracker = TrackingLLM(active_llm)
            active_llm = tracker
        warehouse = build_runtime_warehouse(settings)
        agent = build_agent(
            settings,
            llm=active_llm,
            warehouse=warehouse,
            narrate=with_narration,
            retrieve=not no_retrieval,
        )
        policy = SqlPolicy(
            catalog_tables=warehouse.catalog().table_names(),
            max_rows=settings.max_rows,
        )
        outcome = RunEvaluation(
            benchmark=benchmark_model,
            agent=agent,
            llm=active_llm,
            warehouse=warehouse,
            policy=policy,
            writer=MarkdownHtmlReportWriter(),
            settings=settings,
        ).execute(
            EvaluationRequest(
                categories=categories,
                limit=limit,
                with_narration=with_narration,
                retrieval=not no_retrieval,
                out_dir=out_dir,
                run_id=run_id,
                created_at=now.isoformat(timespec="seconds"),
                compare=compare,
                max_drop=max_drop,
            )
        )
        if tracker is not None and tracker.last_error is not None:
            raise tracker.last_error
        overall = outcome.summary.metrics["overall"]
        typer.echo(f"run id: {outcome.summary.run_id}")
        typer.echo(f"items: {len(outcome.results)} (answerable {overall['n']})")
        typer.echo(
            f"EX: {overall['ex']:.4f} "
            f"[{overall['ex_ci_low']:.4f}, {overall['ex_ci_high']:.4f}] "
            f"| valid SQL {overall['valid_sql_rate']:.4f} "
            f"| refusal acc {overall['refusal_acc']:.4f}"
        )
        typer.echo(f"report: {outcome.out_dir / 'report.html'}")
        if outcome.gate is not None:
            if not outcome.gate.ok:
                for line in outcome.gate.render():
                    typer.echo(line, err=True)
                typer.echo(
                    "eval gate failed: refresh the baseline only after reviewing the regression",
                    err=True,
                )
                raise typer.Exit(1)
            for line in outcome.gate.render():
                typer.echo(line)
    except CassetteMiss as exc:
        typer.echo(f"error: stale cassette: {exc}", err=True)
        raise typer.Exit(4) from exc
    except ConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    except WarehouseUnavailable as exc:
        typer.echo(f"error: warehouse unavailable: {exc}", err=True)
        raise typer.Exit(3) from exc
    except LLMError as exc:
        typer.echo(f"error: LLM backend: {exc}", err=True)
        raise typer.Exit(3) from exc
    except SqlAgentError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(3) from exc
    finally:
        if warehouse is not None:
            warehouse.close()


@app.command("serve")
def serve(  # noqa: PLR0913, PLR0917 - every D25 flag is part of the CLI contract
    host: Annotated[
        str,
        typer.Option("--host", help="Interface to bind (loopback by default)."),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option("--port", help="Local port (17000-17999 by portfolio convention)."),
    ] = 17080,
    llm: Annotated[
        str,
        typer.Option("--llm", help="LLM backend: ollama (live) or replay (recorded)."),
    ] = "ollama",
    model: Annotated[
        str | None,
        typer.Option("--model", help="Model name override (default from settings)."),
    ] = None,
    demo: Annotated[
        bool,
        typer.Option("--demo", help="Replay recorded outputs offline (implies --llm replay)."),
    ] = False,
    open_browser: Annotated[
        bool,
        typer.Option("--open", help="Open the chat in the default browser."),
    ] = False,
    manifest: Annotated[
        Path | None,
        typer.Option("--manifest", help="External lakehouse manifest (T11 adapter)."),
    ] = None,
) -> None:
    """Serve the local web chat (FastAPI + HTMX + SSE)."""

    if llm not in _LLM_BACKENDS:
        typer.echo(f"error: --llm must be one of {sorted(_LLM_BACKENDS)}", err=True)
        raise typer.Exit(2)
    if not 0 <= port <= _MAX_PORT:
        typer.echo("error: --port must be between 0 and 65535", err=True)
        raise typer.Exit(2)
    updates: dict[str, object] = {"llm_backend": "replay" if demo else llm}
    if model:
        updates["model"] = model
    if manifest is not None:
        updates["lakehouse_manifest"] = manifest
    settings = Settings().model_copy(update=updates)
    configure_logging(settings)
    try:
        application = create_app(settings)
    except ConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    except WarehouseUnavailable as exc:
        typer.echo(f"error: warehouse unavailable: {exc}", err=True)
        raise typer.Exit(3) from exc
    except LLMError as exc:
        typer.echo(f"error: LLM backend: {exc}", err=True)
        raise typer.Exit(3) from exc
    url = f"http://{host}:{port}/"
    typer.echo(f"sqlagent web: {url} ({'demo/replay' if demo else llm})")
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    try:
        uvicorn.run(application, host=host, port=port, log_level="info")
    except KeyboardInterrupt:  # pragma: no cover - interactive shutdown
        raise typer.Exit(130) from None


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
