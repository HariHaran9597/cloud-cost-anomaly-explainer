"use strict";

const $ = (id) => document.getElementById(id);
let currentResult = null;
let currentFile = null;

function setError(message = "") {
  const box = $("error");
  box.textContent = message;
  box.hidden = !message;
}

function currency(value, code) {
  try { return new Intl.NumberFormat(undefined, { style: "currency", currency: code, maximumFractionDigits: 2 }).format(value); }
  catch { return `${code} ${Number(value).toFixed(2)}`; }
}

async function loadSample() {
  setError("");
  $("status").textContent = "Loading the bundled synthetic sample…";
  $("sampleButton").disabled = true;
  try {
    const response = await fetch("/api/sample", { headers: { Accept: "application/json" } });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Sample data could not be analyzed.");
    const sampleFile = await fetch("/api/sample.csv");
    if (!sampleFile.ok) throw new Error("Sample CSV could not be loaded.");
    currentFile = new File([await sampleFile.blob()], "synthetic_billing_sample.csv", { type: "text/csv" });
    render(data);
    $("status").textContent = "Synthetic sample loaded. Explore the planted anomalies and their evidence.";
  } catch (error) { setError(error.message || "Could not load sample data."); $("status").textContent = "The sample could not be loaded."; }
  finally { $("sampleButton").disabled = false; }
}

async function upload(file) {
  setError("");
  if (!file) return;
  $("status").textContent = `Analyzing ${file.name}…`;
  currentFile = file;
  try {
    const response = await fetch("/api/analyze", { method: "POST", body: file, headers: { Accept: "application/json", "Content-Type": file.type || "text/csv", "X-File-Name": file.name } });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "The CSV could not be analyzed.");
    render(data);
    $("status").textContent = `Analysis complete. ${data.row_count.toLocaleString()} billing rows were processed in memory.`;
  } catch (error) { setError(error.message || "Could not analyze the CSV."); $("status").textContent = "Fix the CSV and try again."; }
}

function render(data) {
  currentResult = data;
  $("results").hidden = false;
  $("sourceTitle").textContent = data.source;
  $("sampleBadge").hidden = !data.synthetic;
  $("syntheticNotice").hidden = !data.synthetic;
  $("syntheticNotice").textContent = data.synthetic_notice || "Synthetic data only; it does not represent real customer savings.";
  const total = data.daily.reduce((sum, point) => sum + point.actual, 0);
  $("averageSpend").textContent = currency(total / Math.max(1, data.daily.length), data.currency);
  $("alertCount").textContent = data.alerts.length.toString();
  $("serviceCount").textContent = data.service_breakdown.length.toString();
  $("dateRange").textContent = `${data.date_range.start} — ${data.date_range.end}`;
  drawChart(data);
  drawAlerts(data);
  drawServices(data);
  const ul = $("limitations"); ul.replaceChildren();
  for (const limitation of data.limitations) { const li = document.createElement("li"); li.textContent = limitation; ul.append(li); }
  const t = data.thresholds;
  $("thresholds").textContent = `Configured thresholds: minimum ${currency(t.minimum_absolute_delta, data.currency)} and ${(t.minimum_relative_delta * 100).toFixed(0)}% change; robust spread multiplier ${t.mad_multiplier}; ${t.sustained_days} consecutive days for sustained classification. Warm-up requires ${t.minimum_history_observations} prior observations.`;
  $("results").scrollIntoView({ behavior: "smooth", block: "start" });
}

function drawChart(data) {
  const points = data.daily;
  const width = 1000, height = 265, left = 54, right = 18, top = 14, bottom = 32;
  const maxValue = Math.max(1, ...points.map(p => Math.max(p.actual, p.expected))) * 1.12;
  const x = (index) => left + index * (width - left - right) / Math.max(1, points.length - 1);
  const y = (value) => top + (height - top - bottom) * (1 - value / maxValue);
  const path = (key) => points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[key]).toFixed(1)}`).join(" ");
  const ticks = 4;
  let grid = "";
  for (let i = 0; i <= ticks; i++) {
    const value = maxValue * i / ticks, py = y(value);
    grid += `<line x1="${left}" x2="${width-right}" y1="${py}" y2="${py}" stroke="#edf0f1"/><text x="${left-9}" y="${py+4}" text-anchor="end" fill="#829098" font-size="10">${escapeXml(value.toFixed(0))}</text>`;
  }
  const labels = [0, Math.floor((points.length - 1) / 3), Math.floor(2 * (points.length - 1) / 3), points.length - 1];
  const dates = labels.map(i => `<text x="${x(i)}" y="${height-8}" text-anchor="middle" fill="#829098" font-size="10">${escapeXml(points[i].date.slice(5))}</text>`).join("");
  const alertDates = new Set(data.alerts.flatMap(alert => points.filter(p => p.date >= alert.start_date && p.date <= alert.end_date).map(p => p.date)));
  const alertDots = points.map((p, i) => alertDates.has(p.date) ? `<circle cx="${x(i)}" cy="${y(p.actual)}" r="3.5" fill="#e07a3f" stroke="white" stroke-width="1.5"/>` : "").join("");
  $("chart").innerHTML = `<svg viewBox="0 0 ${width} ${height}" aria-hidden="true" xmlns="http://www.w3.org/2000/svg"><g>${grid}${dates}</g><path d="${path("expected")}" fill="none" stroke="#a9b5ba" stroke-width="2" stroke-dasharray="5 5"/><path d="${path("actual")}" fill="none" stroke="#087e78" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>${alertDots}</svg>`;
}

function escapeXml(value) { return String(value).replace(/[<>&"']/g, ch => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&apos;" }[ch])); }

function drawAlerts(data) {
  const host = $("alerts"); host.replaceChildren();
  if (!data.alerts.length) { const empty = document.createElement("div"); empty.className = "empty"; empty.textContent = "No anomalies met the configured thresholds in this period."; host.append(empty); return; }
  for (const alert of data.alerts) {
    const card = document.createElement("article"); card.className = "alert-card";
    const heading = document.createElement("div"); heading.className = "alert-title";
    const title = document.createElement("strong"); title.textContent = `${alert.start_date}${alert.end_date !== alert.start_date ? ` to ${alert.end_date}` : ""}`;
    const badge = document.createElement("span"); badge.className = "alert-kind"; badge.textContent = alert.type.replaceAll("_", " ");
    heading.append(title, badge); card.append(heading);
    const numbers = document.createElement("div"); numbers.className = "alert-numbers"; numbers.textContent = `${currency(alert.observed, data.currency)} actual · ${currency(alert.expected, data.currency)} expected · ${currency(alert.delta, data.currency)} increase`;
    card.append(numbers);
    for (const line of alert.evidence) { const p = document.createElement("p"); p.textContent = line; card.append(p); }
    const score = document.createElement("p"); score.textContent = `Anomaly score: ${alert.score.toFixed(2)} robust deviation units. Unexplained residual: ${currency(alert.unexplained_residual, data.currency)}.`; card.append(score);
    for (const contributor of alert.contributors) {
      const row = document.createElement("div"); row.className = "contrib";
      const name = document.createElement("span"); name.textContent = contributor.service;
      const amount = document.createElement("span"); amount.textContent = `+${currency(contributor.delta, data.currency)}`;
      row.append(name, amount); card.append(row);
    }
    for (const [dimension, entries] of Object.entries(alert.dimension_contributors || {})) {
      for (const contributor of entries.slice(0, 2)) {
        const row = document.createElement("div"); row.className = "contrib";
        const name = document.createElement("span"); name.textContent = `${dimension.toUpperCase()} · ${contributor.name}`;
        const amount = document.createElement("span"); amount.textContent = `+${currency(contributor.delta, data.currency)}`;
        row.append(name, amount); card.append(row);
      }
    }
    host.append(card);
  }
}

function drawServices(data) {
  const host = $("services"); host.replaceChildren();
  const groups = [["Service", data.service_breakdown.map(s => ({ name: s.service, total: s.total }))], ...Object.entries(data.dimension_breakdown || {}).map(([dimension, values]) => [dimension[0].toUpperCase() + dimension.slice(1), values])];
  for (const [heading, entries] of groups) {
    if (!entries.length) continue;
    const groupTitle = document.createElement("h4"); groupTitle.textContent = heading; groupTitle.style.cssText = "font:600 11px Manrope,sans-serif;color:#60727c;margin:17px 0 8px"; host.append(groupTitle);
    const max = Math.max(1, ...entries.map(s => s.total));
    for (const service of entries) {
    const wrapper = document.createElement("div"); wrapper.className = "service-row";
    const label = document.createElement("div"); label.className = "service-label";
    const name = document.createElement("span"); name.textContent = service.name ?? service.service;
    const total = document.createElement("span"); total.textContent = currency(service.total, data.currency);
    label.append(name, total);
    const track = document.createElement("div"); track.className = "bar";
    const fill = document.createElement("i"); fill.style.width = `${Math.max(2, service.total / max * 100)}%`; track.append(fill);
    wrapper.append(label, track); host.append(wrapper);
    }
  }
}

function downloadReport() {
  if (!currentResult) return;
  const blob = new Blob([JSON.stringify({ ...currentResult, generated_at: new Date().toISOString() }, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = "cloud-cost-investigation.json"; a.click(); URL.revokeObjectURL(url);
}

async function checkInvestigator() {
  try {
    const response = await fetch("/api/investigator/status");
    const status = await response.json();
    $("investigator").hidden = !status.enabled;
  } catch { $("investigator").hidden = true; }
}

async function requestInvestigation() {
  if (!currentFile) return;
  const button = $("investigateButton"); button.disabled = true;
  $("investigatorStatus").textContent = "Sending bounded aggregate evidence for a cited summary…";
  $("investigatorOutput").hidden = true;
  try {
    const response = await fetch("/api/investigator", { method: "POST", body: currentFile, headers: { Accept: "application/json", "Content-Type": currentFile.type || "text/csv", "X-File-Name": currentFile.name } });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Investigator request failed.");
    const out = $("investigatorOutput"); out.replaceChildren();
    const summary = document.createElement("p"); summary.textContent = data.summary; out.append(summary);
    for (const item of data.evidence) {
      const evidence = document.createElement("p"); evidence.className = "fineprint"; evidence.textContent = `[${item.id}] ${item.tool}: ${item.result}`; out.append(evidence);
    }
    out.hidden = false; $("investigatorStatus").textContent = "Summary received. Check every statement against its cited figures.";
  } catch (error) { $("investigatorStatus").textContent = error.message || "Investigator request failed."; }
  finally { button.disabled = false; }
}

$("sampleButton").addEventListener("click", loadSample);
$("csvFile").addEventListener("change", (event) => { upload(event.target.files[0]); event.target.value = ""; });
$("downloadButton").addEventListener("click", downloadReport);
$("investigateButton").addEventListener("click", requestInvestigation);
checkInvestigator();
