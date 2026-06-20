(() => {
  const dataNode = document.getElementById("recipe-performance-data");
  const chartNode = document.querySelector("[data-recipe-performance-chart]");
  const select = document.querySelector("[data-recipe-performance-select]");
  if (!dataNode || !chartNode || !select) return;

  const svg = chartNode.querySelector("svg");
  const series = JSON.parse(dataNode.textContent || "[]");
  if (!svg || !series.length) return;

  const allSpeeds = series.flatMap((row) => row.shots.map((shot) => Number(shot.speed)));
  const allShotCounts = series.map((row) => row.shots.length);
  const yMinRaw = Math.min(...allSpeeds);
  const yMaxRaw = Math.max(...allSpeeds);
  const yPadding = Math.max((yMaxRaw - yMinRaw) * 0.08, 10);
  const yMin = Math.max(0, Math.floor((yMinRaw - yPadding) / 10) * 10);
  const yMax = Math.ceil((yMaxRaw + yPadding) / 10) * 10;
  const allXMax = Math.max(...allShotCounts, 1);
  const colors = ["#315f46", "#8a5b12", "#5c5a89", "#9e382f", "#2f6573", "#6b5a2d"];

  const draw = () => {
    const selected = select.value;
    const visible = selected === "all" ? series : series.filter((row) => row.id === selected);
    const xMax = selected === "all" ? allXMax : Math.max(visible[0]?.shots.length || 1, 1);
    render(svg, visible, { xMax, yMin, yMax, colors });
  };

  select.addEventListener("change", draw);
  draw();
})();

function render(svg, series, options) {
  const width = 920;
  const height = 420;
  const margin = { top: 24, right: 32, bottom: 58, left: 76 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const x = (value) => margin.left + ((value - 1) / Math.max(options.xMax - 1, 1)) * plotWidth;
  const y = (value) => margin.top + ((options.yMax - value) / Math.max(options.yMax - options.yMin, 1)) * plotHeight;
  const nodes = [];

  const line = (x1, y1, x2, y2, className = "chart-axis") => {
    nodes.push(`<line class="${className}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"></line>`);
  };
  line(margin.left, margin.top, margin.left, height - margin.bottom);
  line(margin.left, height - margin.bottom, width - margin.right, height - margin.bottom);

  yTicks(options.yMin, options.yMax).forEach((tick) => {
    const yy = y(tick);
    line(margin.left, yy, width - margin.right, yy, "chart-grid");
    nodes.push(`<text class="chart-tick" x="${margin.left - 10}" y="${yy + 4}" text-anchor="end">${tick}</text>`);
  });

  xTicks(options.xMax).forEach((tick) => {
    const xx = x(tick);
    nodes.push(`<text class="chart-tick" x="${xx}" y="${height - margin.bottom + 24}" text-anchor="middle">${tick}</text>`);
  });

  nodes.push(`<text class="chart-label" x="${margin.left + plotWidth / 2}" y="${height - 16}" text-anchor="middle">Shot number</text>`);
  nodes.push(`<text class="chart-label" transform="translate(22 ${margin.top + plotHeight / 2}) rotate(-90)" text-anchor="middle">Speed (fps)</text>`);

  series.forEach((row, index) => {
    const color = options.colors[index % options.colors.length];
    const points = row.shots.map((shot) => `${x(Number(shot.shot))},${y(Number(shot.speed))}`).join(" ");
    if (points) {
      nodes.push(`<polyline class="chart-line" points="${points}" stroke="${color}"></polyline>`);
    }
    row.shots.forEach((shot) => {
      const cx = x(Number(shot.shot));
      const cy = y(Number(shot.speed));
      nodes.push(`<circle class="chart-point" cx="${cx}" cy="${cy}" r="4" fill="${color}"><title>${escapeHtml(row.label)} shot ${shot.shot}: ${Number(shot.speed).toFixed(1)} fps</title></circle>`);
    });
  });

  const legend = series.map((row, index) => {
    const color = options.colors[index % options.colors.length];
    const yPos = 24 + index * 20;
    return `<g><circle cx="${width - 250}" cy="${yPos - 4}" r="4" fill="${color}"></circle><text class="chart-legend" x="${width - 238}" y="${yPos}">${escapeHtml(row.label)}</text></g>`;
  }).join("");
  nodes.push(legend);

  svg.innerHTML = nodes.join("");
}

function yTicks(min, max) {
  const ticks = [];
  const step = Math.max(10, Math.ceil((max - min) / 5 / 10) * 10);
  for (let value = min; value <= max; value += step) {
    ticks.push(value);
  }
  if (ticks[ticks.length - 1] !== max) ticks.push(max);
  return ticks;
}

function xTicks(max) {
  const ticks = [];
  const step = Math.max(1, Math.ceil(max / 8));
  for (let value = 1; value <= max; value += step) {
    ticks.push(value);
  }
  if (ticks[ticks.length - 1] !== max) ticks.push(max);
  return ticks;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}
