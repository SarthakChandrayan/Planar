// Planar website: theme switch (shared with the embedded demo) and the accuracy table.
"use strict";

const THEME_KEY = "planar.theme";
const SUN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
const MOON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';

function currentTheme() {
  const picked = document.documentElement.dataset.theme;
  if (picked) return picked;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function paintThemeButton() {
  const dark = currentTheme() === "dark";
  const btn = document.getElementById("theme");
  btn.innerHTML = dark ? SUN : MOON;
  btn.title = dark ? "Light theme" : "Dark theme";
}

document.getElementById("theme").addEventListener("click", () => {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
  // Same origin: switch the embedded demo too.
  try { document.getElementById("demo-frame").contentDocument.documentElement.dataset.theme = next; } catch (e) {}
  paintThemeButton();
});
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", paintThemeButton);
paintThemeButton();

/* ---------- accuracy table, from the same runs the demo shows ---------- */
const pct = (v) => `${Math.round(v * 100)}%`;
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function meter(value, color) {
  return `<span class="meter"><i style="--v:${pct(value)};--c:var(${color})"></i>${pct(value)}</span>`;
}

fetch("demo/accuracy.json")
  .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
  .then((rows) => {
    const body = document.getElementById("scores");
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="5" class="muted">No recorded runs yet.</td></tr>';
      return;
    }
    const sum = (k) => rows.reduce((n, r) => n + r[k], 0);
    const total = {
      title: "All demo meetings",
      correct: sum("correct"), extracted: sum("extracted"), found: sum("found"), expected: sum("expected"),
    };
    total.precision = total.correct / total.extracted;
    total.recall = total.found / total.expected;
    const row = (r, strong) => `<tr${strong ? ' class="total"' : ""}>
      <td>${strong ? `<b>${esc(r.title)}</b>` : esc(r.title)}</td>
      <td class="num">${r.correct} of ${r.extracted}</td>
      <td class="num">${r.found} of ${r.expected}</td>
      <td>${meter(r.precision, "--c-step")}</td>
      <td>${meter(r.recall, "--c-decision")}</td></tr>`;
    body.innerHTML = rows.map((r) => row(r, false)).join("") + row(total, true);
  })
  .catch(() => {
    document.getElementById("scores").innerHTML = '<tr><td colspan="5" class="muted">Scores unavailable.</td></tr>';
  });
