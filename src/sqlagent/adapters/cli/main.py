"""``sqlagent`` command-line interface.

Only ``--version`` exists in T1; the ``ask``, ``eval``, ``serve``, ``doctor``
and ``data`` command groups are added by their respective tasks.
"""

from __future__ import annotations

from typing import Annotated

import typer

from sqlagent import __version__

app = typer.Typer(
    name="sqlagent",
    help="Local-first AI data analyst over a bundled DuckDB warehouse.",
    add_completion=False,
    no_args_is_help=True,
)


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


if __name__ == "__main__":  # pragma: no cover - exercised through the console script
    main()
