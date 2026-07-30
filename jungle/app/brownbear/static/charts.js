/* Inline-SVG chart primitives.
 *
 * Hand-rolled rather than a charting library: this stack is meant to run on a
 * machine with no internet, so a CDN script tag is not an option and vendoring
 * a bundle would dwarf the dashboard itself.
 *
 * Mark specs are fixed here, not per call site: 2px lines with round joins,
 * markers at r>=4 carrying a 2px surface ring, bars capped at 24px with a 4px
 * rounded data-end and square baseline, hairline solid gridlines one step off
 * the surface. Every chart ships a table twin, and text never wears a series
 * colour — identity comes from a swatch beside the text.
 */

const NS = "http://www.w3.org/2000/svg";

const BB = {};

BB.fmtCompact = (value) => {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e9) return (value / 1e9).toFixed(1).replace(/\.0$/, "") + "B";
  if (abs >= 1e6) return (value / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  if (abs >= 10000) return (value / 1e3).toFixed(1).replace(/\.0$/, "") + "K";
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
};

BB.fmtBytes = (bytes) => {
  if (!bytes && bytes !== 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 100 || unit === 0 ? 0 : 1)} ${units[unit]}`;
};

BB.fmtMoney = (value) => "$" + (value || 0).toFixed(value && value < 1 ? 4 : 2);

BB.fmtPercent = (value) =>
  value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;

BB.fmtTime = (iso) => {
  const date = new Date(iso);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
};

BB.fmtDate = (iso) => {
  const date = new Date(iso);
  return date.toLocaleDateString([], { month: "short", day: "numeric" });
};

function el(name, attrs = {}, parent = null) {
  const node = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attrs)) {
    if (value !== null && value !== undefined) node.setAttribute(key, value);
  }
  if (parent) parent.appendChild(node);
  return node;
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Axis ticks rounded to clean numbers, so the axis carries unlabelled values. */
function niceTicks(min, max, count = 4) {
  if (min === max) return [min, min + 1];
  const span = max - min;
  const rawStep = span / count;
  const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const normalised = rawStep / magnitude;
  const step = (normalised >= 5 ? 5 : normalised >= 2 ? 2 : 1) * magnitude;
  const ticks = [];
  for (let value = Math.floor(min / step) * step; value <= max + step / 2; value += step) {
    ticks.push(Number(value.toFixed(10)));
  }
  return ticks;
}

function ensureTooltip(wrap) {
  let tip = wrap.querySelector(".tooltip");
  if (!tip) {
    tip = document.createElement("div");
    tip.className = "tooltip";
    wrap.appendChild(tip);
  }
  return tip;
}

function placeTooltip(wrap, tip, x, y) {
  const width = wrap.clientWidth;
  const tipWidth = tip.offsetWidth || 140;
  let left = x + 14;
  if (left + tipWidth > width - 4) left = x - tipWidth - 14;
  if (left < 4) left = 4;
  tip.style.left = `${left}px`;
  tip.style.top = `${Math.max(4, y - 10)}px`;
}

/**
 * Line / area chart.
 * spec: { series: [{name, color, points: [{x, y}]}], xLabels, yFormat,
 *         valueFormat, area, yMin, yMax, height }
 */
BB.lineChart = function lineChart(wrap, spec) {
  const render = () => {
    wrap.querySelectorAll("svg").forEach((node) => node.remove());
    const width = Math.max(wrap.clientWidth, 260);
    const height = spec.height || 240;
    const pad = { top: 14, right: 18, bottom: 30, left: 54 };
    const series = spec.series.filter((s) => s.points.length);

    const svg = el("svg", { width, height, role: "img" }, wrap);
    svg.setAttribute("aria-label", spec.ariaLabel || "line chart");

    if (!series.length) {
      el("text", {
        x: width / 2,
        y: height / 2,
        "text-anchor": "middle",
        fill: cssVar("--text-muted"),
        "font-size": 13,
      }, svg).textContent = "No data yet";
      return;
    }

    const count = Math.max(...series.map((s) => s.points.length));
    const values = series.flatMap((s) => s.points.map((p) => p.y));
    const rawMax = Math.max(...values, 0);
    const yMin = spec.yMin ?? 0;
    const yMax = spec.yMax ?? (rawMax === 0 ? 1 : rawMax);
    const ticks = niceTicks(yMin, yMax);
    const top = Math.max(...ticks);

    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const xAt = (i) => pad.left + (count === 1 ? plotW / 2 : (plotW * i) / (count - 1));
    const yAt = (v) => pad.top + plotH - ((v - yMin) / (top - yMin || 1)) * plotH;

    // Gridlines: hairline, solid, recessive. Horizontal only.
    for (const tick of ticks) {
      const y = yAt(tick);
      el("line", {
        x1: pad.left, x2: width - pad.right, y1: y, y2: y,
        stroke: cssVar("--gridline"), "stroke-width": 1,
      }, svg);
      el("text", {
        x: pad.left - 8, y: y + 4, "text-anchor": "end",
        fill: cssVar("--text-muted"), "font-size": 11,
        style: "font-variant-numeric: tabular-nums",
      }, svg).textContent = (spec.yFormat || BB.fmtCompact)(tick);
    }

    el("line", {
      x1: pad.left, x2: width - pad.right,
      y1: pad.top + plotH, y2: pad.top + plotH,
      stroke: cssVar("--axis"), "stroke-width": 1,
    }, svg);

    const labels = spec.xLabels || [];
    const labelIdx = count === 1 ? [0] : [0, Math.floor((count - 1) / 2), count - 1];
    for (const i of [...new Set(labelIdx)]) {
      if (!labels[i]) continue;
      el("text", {
        x: xAt(i), y: height - 10,
        "text-anchor": i === 0 ? "start" : i === count - 1 ? "end" : "middle",
        fill: cssVar("--text-muted"), "font-size": 11,
      }, svg).textContent = labels[i];
    }

    for (const s of series) {
      const color = cssVar(s.color);
      const path = s.points.map((p, i) => `${i ? "L" : "M"}${xAt(i)},${yAt(p.y)}`).join(" ");

      if (spec.area && series.length === 1) {
        // Area fill is a ~10% wash, never a saturated block.
        el("path", {
          d: `${path} L${xAt(s.points.length - 1)},${yAt(yMin)} L${xAt(0)},${yAt(yMin)} Z`,
          fill: color, "fill-opacity": 0.1, stroke: "none",
        }, svg);
      }

      el("path", {
        d: path, fill: "none", stroke: color,
        "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round",
      }, svg);

      // End marker: r>=4 with a 2px surface ring so it stays legible on crossings.
      const last = s.points[s.points.length - 1];
      el("circle", {
        cx: xAt(s.points.length - 1), cy: yAt(last.y), r: 4.5,
        fill: color, stroke: cssVar("--surface-1"), "stroke-width": 2,
      }, svg);
    }

    // --- hover layer: crosshair + tooltip, keyboard-reachable ---
    const tip = ensureTooltip(wrap);
    const crosshair = el("line", {
      y1: pad.top, y2: pad.top + plotH,
      stroke: cssVar("--axis"), "stroke-width": 1, opacity: 0,
    }, svg);
    const focusDots = series.map((s) =>
      el("circle", {
        r: 4.5, fill: cssVar(s.color),
        stroke: cssVar("--surface-1"), "stroke-width": 2, opacity: 0,
      }, svg)
    );

    let active = -1;
    const show = (index) => {
      active = index;
      const x = xAt(index);
      crosshair.setAttribute("x1", x);
      crosshair.setAttribute("x2", x);
      crosshair.setAttribute("opacity", 1);

      const fmt = spec.valueFormat || BB.fmtCompact;
      let rows = "";
      series.forEach((s, si) => {
        const point = s.points[index];
        const dot = focusDots[si];
        if (!point) {
          dot.setAttribute("opacity", 0);
          return;
        }
        dot.setAttribute("cx", x);
        dot.setAttribute("cy", yAt(point.y));
        dot.setAttribute("opacity", 1);
        rows +=
          `<div class="tooltip-row"><span class="name">` +
          `<span class="legend-key" style="background:${cssVar(s.color)}"></span>${s.name}` +
          `</span><span class="val">${fmt(point.y)}</span></div>`;
      });
      tip.innerHTML = `<div class="tooltip-title">${labels[index] || ""}</div>${rows}`;
      tip.classList.add("visible");
      placeTooltip(wrap, tip, x, pad.top + 10);
    };

    const hide = () => {
      crosshair.setAttribute("opacity", 0);
      focusDots.forEach((dot) => dot.setAttribute("opacity", 0));
      tip.classList.remove("visible");
    };

    // Full-plot overlay: the hit target is the whole column, never the mark.
    const overlay = el("rect", {
      x: pad.left, y: pad.top, width: plotW, height: plotH,
      fill: "transparent", style: "cursor:crosshair",
    }, svg);

    overlay.addEventListener("mousemove", (event) => {
      const box = svg.getBoundingClientRect();
      const ratio = (event.clientX - box.left - pad.left) / (plotW || 1);
      show(Math.max(0, Math.min(count - 1, Math.round(ratio * (count - 1)))));
    });
    overlay.addEventListener("mouseleave", hide);

    wrap.tabIndex = 0;
    wrap.addEventListener("keydown", (event) => {
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        event.preventDefault();
        const next = active < 0 ? 0 : active + (event.key === "ArrowRight" ? 1 : -1);
        show(Math.max(0, Math.min(count - 1, next)));
      } else if (event.key === "Escape") {
        hide();
      }
    });
    wrap.addEventListener("blur", hide);
  };

  render();
  if (wrap._bbResize) window.removeEventListener("resize", wrap._bbResize);
  wrap._bbResize = () => render();
  window.addEventListener("resize", wrap._bbResize);
};

/**
 * Horizontal bar chart — one series, one colour.
 * A value ramp across nominal categories would double-encode length as hue.
 * spec: { bars: [{label, value}], color, valueFormat }
 */
BB.barChart = function barChart(wrap, spec) {
  const render = () => {
    wrap.querySelectorAll("svg").forEach((node) => node.remove());
    const bars = spec.bars || [];
    const width = Math.max(wrap.clientWidth, 260);
    const rowH = 30;
    const pad = { top: 6, right: 64, bottom: 6, left: 0 };
    const labelW = Math.min(160, Math.max(80, Math.round(width * 0.28)));
    const height = pad.top + pad.bottom + Math.max(bars.length, 1) * rowH;

    const svg = el("svg", { width, height, role: "img" }, wrap);
    svg.setAttribute("aria-label", spec.ariaLabel || "bar chart");

    if (!bars.length) {
      el("text", {
        x: width / 2, y: height / 2, "text-anchor": "middle",
        fill: cssVar("--text-muted"), "font-size": 13,
      }, svg).textContent = "No data yet";
      return;
    }

    const max = Math.max(...bars.map((b) => b.value), 1);
    const trackX = labelW + 12;
    const trackW = Math.max(20, width - trackX - pad.right);
    const color = cssVar(spec.color || "--series-1");
    const fmt = spec.valueFormat || BB.fmtCompact;
    const tip = ensureTooltip(wrap);
    // Bars are capped at 24px so the band keeps some air.
    const barH = Math.min(24, rowH - 10);

    bars.forEach((bar, i) => {
      const y = pad.top + i * rowH;
      const barY = y + (rowH - barH) / 2;
      const barW = Math.max(2, (bar.value / max) * trackW);

      el("text", {
        x: labelW, y: y + rowH / 2 + 4, "text-anchor": "end",
        fill: cssVar("--text-secondary"), "font-size": 12,
      }, svg).textContent = bar.label;

      // 4px rounded data-end, square at the baseline.
      const r = Math.min(4, barW);
      el("path", {
        d:
          `M${trackX},${barY} H${trackX + barW - r} ` +
          `A${r},${r} 0 0 1 ${trackX + barW},${barY + r} ` +
          `V${barY + barH - r} A${r},${r} 0 0 1 ${trackX + barW - r},${barY + barH} ` +
          `H${trackX} Z`,
        fill: color,
      }, svg);

      // Value at the tip, in a text token — never the series colour.
      el("text", {
        x: trackX + barW + 8, y: barY + barH / 2 + 4,
        fill: cssVar("--text-secondary"), "font-size": 12,
        style: "font-variant-numeric: tabular-nums",
      }, svg).textContent = fmt(bar.value);

      // Hit target spans the whole row, comfortably past the 24px minimum.
      const hit = el("rect", {
        x: 0, y, width, height: rowH, fill: "transparent",
      }, svg);
      hit.addEventListener("mousemove", (event) => {
        const box = svg.getBoundingClientRect();
        tip.innerHTML =
          `<div class="tooltip-title">${bar.label}</div>` +
          `<div class="tooltip-row"><span class="name">` +
          `<span class="legend-key" style="background:${color}"></span>${spec.seriesName || "Value"}` +
          `</span><span class="val">${fmt(bar.value)}</span></div>`;
        tip.classList.add("visible");
        placeTooltip(wrap, tip, event.clientX - box.left, y);
      });
      hit.addEventListener("mouseleave", () => tip.classList.remove("visible"));
    });
  };

  render();
  if (wrap._bbResize) window.removeEventListener("resize", wrap._bbResize);
  wrap._bbResize = () => render();
  window.addEventListener("resize", wrap._bbResize);
};

/** Legend — always present for two or more series. */
BB.legend = function legend(node, series) {
  node.innerHTML = series
    .map(
      (s) =>
        `<span class="legend-item"><span class="legend-key" style="background:${cssVar(
          s.color
        )}"></span>${s.name}</span>`
    )
    .join("");
};

/** The table twin. Every chart has one, so no value is reachable only by hover. */
BB.table = function table(node, columns, rows) {
  if (!rows.length) {
    node.innerHTML = '<p class="empty">No data yet</p>';
    return;
  }
  const head = columns.map((c) => `<th class="${c.num ? "num" : ""}">${c.label}</th>`).join("");
  const body = rows
    .map(
      (row) =>
        "<tr>" +
        columns
          .map((c) => `<td class="${c.num ? "num" : ""}">${c.render ? c.render(row) : row[c.key]}</td>`)
          .join("") +
        "</tr>"
    )
    .join("");
  node.innerHTML = `<div class="table-scroll"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
};

BB.get = async function get(url) {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
};

window.BB = BB;
