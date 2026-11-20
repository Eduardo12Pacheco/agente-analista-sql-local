"""Executable entry point for ``python -m sqlagent``."""

from sqlagent.adapters.cli.main import app


def run() -> None:
    """Invoke the Typer application."""
    app()


if __name__ == "__main__":
    run()
