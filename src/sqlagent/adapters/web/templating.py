"""Shared Jinja environment for the web adapter (D23)."""

# ruff: noqa: S704 - json_attr escapes HTML before returning Markup.

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from sqlagent.adapters.web.highlight import highlight_sql
from sqlagent.adapters.web.i18n import (
    catalog,
    example_questions,
    phase_label,
    translate,
)

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def json_attr(value: Any) -> Markup:
    """Serialise a value for an HTML attribute, safe for quotes and dates."""

    raw = json.dumps(value, ensure_ascii=False, default=str)
    return Markup(html.escape(raw, quote=True))


templates.env.filters["highlight_sql"] = highlight_sql
templates.env.filters["json_attr"] = json_attr
templates.env.globals["catalog"] = catalog
templates.env.globals["example_questions"] = example_questions
templates.env.globals["phase_label"] = phase_label
templates.env.globals["translate"] = translate


def render_template(name: str, **context: object) -> str:
    """Render one template without a request object (SSE fragments)."""

    return templates.env.get_template(name).render(**context)


__all__ = ["TEMPLATES_DIR", "WEB_DIR", "json_attr", "render_template", "templates"]
