/* Browser behaviour for the chat: theme, health pill, composer, charts, copy (D23/S29). */
(() => {
  "use strict";

  const THEME_KEY = "sqlagent-theme";
  const root = document.documentElement;
  const charts = new WeakMap();
  const prefersDark = () => window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;

  function readStoredTheme() {
    try {
      const value = window.localStorage.getItem(THEME_KEY);
      return value === "light" || value === "dark" ? value : null;
    } catch (_error) {
      return null;
    }
  }

  function storeTheme(theme) {
    try {
      window.localStorage.setItem(THEME_KEY, theme);
    } catch (_error) {
      /* storage can be unavailable; the toggle still works for this page. */
    }
  }

  function currentTheme() {
    return root.dataset.theme || (prefersDark() ? "dark" : "light");
  }

  function applyTheme(theme) {
    root.dataset.theme = theme;
    const toggle = document.getElementById("theme-toggle");
    if (toggle) {
      toggle.setAttribute("aria-pressed", String(theme === "dark"));
    }
  }

  function cssVariable(name) {
    return getComputedStyle(root).getPropertyValue(name).trim();
  }

  function chartPalette() {
    return [1, 2, 3, 4, 5, 6].map((index) => cssVariable("--chart-" + index));
  }

  function columnNames(data) {
    return (data.columns || []).map((column) => (typeof column === "string" ? column : column.name));
  }

  function columnIndex(names, wanted, fallback) {
    const index = wanted == null ? -1 : names.indexOf(wanted);
    return index >= 0 ? index : fallback;
  }

  function isNumeric(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  function datasetFor(data, names, spec) {
    const palette = chartPalette();
    const rows = data.rows || [];
    const seriesIndex = columnIndex(names, spec.series, -1);
    const xIndex = columnIndex(names, spec.x, 0);
    const yName = (spec.y || [])[0];
    const yIndex = columnIndex(names, yName, 1);
    if (spec.kind === "scatter") {
      return {
        labels: rows.map((row) => row[xIndex]),
        datasets: [
          {
            label: yName || "value",
            data: rows.map((row) => ({ x: row[xIndex], y: row[yIndex] })),
            backgroundColor: palette[0],
            borderColor: palette[0],
          },
        ],
      };
    }
    const groups = new Map();
    rows.forEach((row) => {
      const key = seriesIndex >= 0 ? String(row[seriesIndex]) : (yName || "value");
      if (!groups.has(key)) {
        groups.set(key, []);
      }
      groups.get(key).push(row);
    });
    const labels = [...new Set(rows.map((row) => String(row[xIndex] ?? "")))];
    const datasets = [...groups.entries()].map(([label, groupRows], index) => {
      const byLabel = new Map(groupRows.map((row) => [String(row[xIndex] ?? ""), row[yIndex]]));
      const values = labels.map((labelText) => {
        const value = byLabel.get(labelText);
        return isNumeric(value) ? value : null;
      });
      return {
        label,
        data: values,
        backgroundColor: spec.kind === "line" ? palette[index % palette.length] : palette[index % palette.length],
        borderColor: palette[index % palette.length],
        borderWidth: 2,
        pointRadius: spec.kind === "line" ? 2 : 0,
        tension: 0.25,
      };
    });
    return { labels, datasets };
  }

  function renderChart(container) {
    if (container.dataset.rendered === "true" || typeof window.Chart === "undefined") {
      return;
    }
    const canvas = container.querySelector("canvas");
    if (!canvas) {
      return;
    }
    let data;
    try {
      data = JSON.parse(container.dataset.chart || "{}");
    } catch (_error) {
      return;
    }
    const spec = data.spec || {};
    const names = columnNames(data);
    const chartData = datasetFor(data, names, spec);
    const grid = cssVariable("--border");
    const text = cssVariable("--text");
    const chart = new window.Chart(canvas, {
      type: spec.kind === "hbar" ? "bar" : spec.kind === "scatter" ? "scatter" : spec.kind,
      data: chartData,
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: spec.kind === "hbar" ? "y" : "x",
        plugins: {
          legend: {
            display: (spec.y || []).length > 0 && spec.series != null,
            labels: { color: text },
          },
          tooltip: { enabled: true },
        },
        scales: {
          x: { ticks: { color: text }, grid: { color: grid }, beginAtZero: true },
          y: { ticks: { color: text }, grid: { color: grid } },
        },
      },
    });
    charts.set(container, chart);
    container.dataset.rendered = "true";
  }

  function renderCharts(scope) {
    (scope || document).querySelectorAll("[data-chart]").forEach(renderChart);
  }

  function refreshCharts() {
    document.querySelectorAll("[data-chart]").forEach((container) => {
      const chart = charts.get(container);
      if (chart) {
        chart.destroy();
        charts.delete(container);
      }
      container.dataset.rendered = "false";
    });
    renderCharts(document);
  }

  function focusAnswer(target) {
    if (!target || !target.closest) {
      return;
    }
    const card = target.closest(".answer-card");
    if (card) {
      card.setAttribute("tabindex", "-1");
      card.focus({ preventScroll: false });
    }
  }

  function submitQuestion(question) {
    const textarea = document.getElementById("question");
    const form = document.getElementById("composer");
    if (!textarea || !form) {
      return;
    }
    textarea.value = question;
    form.requestSubmit();
  }

  function setupTheme() {
    applyTheme(readStoredTheme() || (prefersDark() ? "dark" : "light"));
    const toggle = document.getElementById("theme-toggle");
    if (!toggle) {
      return;
    }
    toggle.addEventListener("click", () => {
      const next = currentTheme() === "dark" ? "light" : "dark";
      applyTheme(next);
      storeTheme(next);
      refreshCharts();
    });
    if (window.matchMedia) {
      const media = window.matchMedia("(prefers-color-scheme: dark)");
      media.addEventListener("change", () => {
        if (!readStoredTheme()) {
          applyTheme(media.matches ? "dark" : "light");
          refreshCharts();
        }
      });
    }
  }

  function setupHealth() {
    const pill = document.getElementById("health-pill");
    if (!pill || !window.fetch) {
      return;
    }
    window
      .fetch(pill.dataset.healthUrl, { headers: { Accept: "application/json" } })
      .then((response) => (response.ok ? response.json() : Promise.reject(response.status)))
      .then((health) => {
        const ready = Boolean(health.ollama_ok) || Boolean(health.demo);
        pill.textContent = ready ? pill.dataset.okLabel : pill.dataset.downLabel;
        pill.classList.toggle("pill--ok", ready);
        pill.classList.toggle("pill--muted", !ready);
        pill.dataset.backend = health.backend || "";
      })
      .catch(() => {
        pill.textContent = pill.dataset.downLabel;
      });
  }

  function setupComposer() {
    const textarea = document.getElementById("question");
    const form = document.getElementById("composer");
    if (textarea && form) {
      textarea.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
          event.preventDefault();
          form.requestSubmit();
        }
      });
    }
    document.querySelectorAll(".example").forEach((button) => {
      button.addEventListener("click", () => submitQuestion(button.dataset.question || ""));
    });
    document.body.addEventListener("htmx:beforeRequest", (event) => {
      const target = event.detail.elt;
      if (target && target.id === "composer") {
        const emptyState = document.getElementById("empty-state");
        if (emptyState) {
          emptyState.hidden = true;
        }
        const submit = target.querySelector("button[type='submit']");
        if (submit) {
          submit.disabled = true;
        }
      }
    });
    document.body.addEventListener("htmx:afterRequest", (event) => {
      const target = event.detail.elt;
      if (target && target.id === "composer") {
        const submit = target.querySelector("button[type='submit']");
        if (submit) {
          submit.disabled = false;
        }
      }
    });
    document.body.addEventListener("htmx:afterSwap", (event) => {
      renderCharts(event.detail.target || document);
      const target = event.detail.target;
      if (target && target.id && target.id.startsWith("narrative-")) {
        focusAnswer(target);
        const run = target.closest(".run");
        if (run) {
          run.setAttribute("aria-busy", "false");
        }
      }
    });
    document.body.addEventListener("htmx:sseMessage", (event) => {
      if (!event.detail || event.detail.type !== "answer") {
        return;
      }
      const source = event.target && event.target.closest ? event.target.closest(".run") : null;
      const card = source ? source.querySelector(".answer-card") : null;
      if (card) {
        card.setAttribute("tabindex", "-1");
        card.focus({ preventScroll: false });
        source.setAttribute("aria-busy", "false");
      }
    });
    document.body.addEventListener("htmx:sseClose", (event) => {
      const run = event.detail && event.detail.elt ? event.detail.elt.closest(".run") : null;
      if (run) {
        run.setAttribute("aria-busy", "false");
      }
    });
  }

  function setupCopy() {
    document.body.addEventListener("click", (event) => {
      const button = event.target.closest && event.target.closest("[data-copy-sql]");
      if (!button) {
        return;
      }
      const block = button.closest(".sql-block");
      const code = block ? block.querySelector("pre code") : null;
      if (!code || !navigator.clipboard) {
        return;
      }
      navigator.clipboard.writeText(code.textContent || "").then(() => {
        const original = button.textContent;
        button.textContent = button.dataset.copied || "✓";
        window.setTimeout(() => {
          button.textContent = original;
        }, 1500);
      });
    });
  }

  function boot() {
    setupTheme();
    setupHealth();
    setupComposer();
    setupCopy();
    renderCharts(document);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
