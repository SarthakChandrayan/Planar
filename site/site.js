// Planar website: theme (shared with the embedded demo), the trace diagram's
// wires, the meeting switcher, the accuracy figures and the copy button.
"use strict";

const $ = (id) => document.getElementById(id);
const THEME_KEY = "planar.theme";
const SUN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
const MOON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (v) => `${Math.round(v * 100)}%`;

/* ---------- theme ---------- */
function theme() {
  return document.documentElement.dataset.theme
    || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
}
function paintTheme() {
  const dark = theme() === "dark";
  $("theme").innerHTML = dark ? SUN : MOON;
  $("theme").title = dark ? "Light theme" : "Dark theme";
}
$("theme").addEventListener("click", () => {
  const next = theme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
  try { $("demo-frame").contentDocument.documentElement.dataset.theme = next; } catch (e) {}
  paintTheme();
});
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", paintTheme);
paintTheme();

/* ---------- trace diagram ---------- */
const trace = $("trace");
const nodes = new Map([...trace.querySelectorAll("[data-id]")].map((el) => [el.dataset.id, el]));
const links = [];
trace.querySelectorAll(".item").forEach((item) => {
  if (item.dataset.from) links.push([item.dataset.from, item.dataset.id]);
  if (item.dataset.to) links.push([item.dataset.id, item.dataset.to]);
});

function drawWires() {
  const svg = $("wires");
  if (getComputedStyle(svg).display === "none") return;
  const box = trace.getBoundingClientRect();
  svg.innerHTML = links.map(([a, b]) => {
    const ra = nodes.get(a).getBoundingClientRect();
    const rb = nodes.get(b).getBoundingClientRect();
    const x1 = ra.right - box.left, y1 = ra.top + ra.height / 2 - box.top;
    const x2 = rb.left - box.left, y2 = rb.top + rb.height / 2 - box.top;
    const dx = (x2 - x1) / 2;
    return `<path data-a="${a}" data-b="${b}" d="M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}"/>`;
  }).join("");
}

// The trail through a node: a line lights its items and their steps; an item
// lights its line and step; a step lights the items feeding it and their lines.
function chain(id) {
  const el = nodes.get(id);
  const items = el.classList.contains("item")
    ? [el]
    : [...trace.querySelectorAll(".item")].filter((i) => i.dataset.from === id || i.dataset.to === id);
  const lit = new Set([id]);
  for (const item of items) {
    lit.add(item.dataset.id);
    if (item.dataset.from) lit.add(item.dataset.from);
    if (item.dataset.to) lit.add(item.dataset.to);
  }
  return lit;
}

function focus(id) {
  const lit = chain(id);
  trace.classList.add("focus");
  nodes.forEach((el, key) => el.classList.toggle("lit", lit.has(key)));
  trace.querySelectorAll(".wires path").forEach((p) => p.classList.toggle("lit", lit.has(p.dataset.a) && lit.has(p.dataset.b)));
  const item = [...lit].map((k) => nodes.get(k)).find((el) => el.classList.contains("item"));
  trace.querySelectorAll(".line.lit").forEach((el) => el.style.setProperty("--c", item ? getComputedStyle(item).getPropertyValue("--c") : ""));
}
function unfocus() {
  trace.classList.remove("focus");
  nodes.forEach((el) => el.classList.remove("lit"));
  trace.querySelectorAll(".wires path").forEach((p) => p.classList.remove("lit"));
}
nodes.forEach((el, id) => {
  el.addEventListener("mouseenter", () => focus(id));
  el.addEventListener("mouseleave", unfocus);
});
drawWires();
addEventListener("resize", drawWires);
document.fonts?.ready.then(drawWires);

/* ---------- meeting switcher ---------- */
const frame = $("demo-frame");
fetch("demo/runs.json")
  .then((r) => (r.ok ? r.json() : []))
  .then((runs) => {
    const bar = $("meetings");
    const pills = [{ id: "", title: "All meetings" }, ...runs.map((r) => ({ id: r.id, title: r.title.split(/\s[—&]\s/)[0].replace(/\s+(Planning\s+)?Meeting$/, "") }))];
    bar.innerHTML = pills.map((p, i) =>
      `<button type="button" role="tab" data-run="${esc(p.id)}" aria-selected="${i === 0}">${esc(p.title)}</button>`).join("");
    bar.addEventListener("click", (e) => {
      const btn = e.target.closest("button");
      if (!btn) return;
      bar.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", String(b === btn)));
      frame.src = btn.dataset.run ? `app/?run=${encodeURIComponent(btn.dataset.run)}` : "app/";
    });
  })
  .catch(() => {});

/* ---------- accuracy ---------- */
function bar(value, color) {
  return `<span class="bar"><i style="--v:${pct(value)};--c:var(${color})"></i>${pct(value)}</span>`;
}
fetch("demo/accuracy.json")
  .then((r) => (r.ok ? r.json() : Promise.reject()))
  .then((rows) => {
    if (!rows.length) throw new Error("empty");
    const sum = (k) => rows.reduce((n, r) => n + r[k], 0);
    const total = { title: "All demo meetings", correct: sum("correct"), extracted: sum("extracted"), found: sum("found"), expected: sum("expected") };
    total.precision = total.correct / total.extracted;
    total.recall = total.found / total.expected;
    $("stat-precision").textContent = pct(total.precision);
    $("stat-recall").textContent = pct(total.recall);
    const row = (r, cls) => `<tr${cls ? ` class="${cls}"` : ""}><td>${esc(r.title)}</td>
      <td class="num">${r.correct} of ${r.extracted}</td><td class="num">${r.found} of ${r.expected}</td>
      <td>${bar(r.precision, "--step")}</td><td>${bar(r.recall, "--dec")}</td></tr>`;
    $("scores").innerHTML = rows.map((r) => row(r)).join("") + row(total, "total");
  })
  .catch(() => { $("scores").innerHTML = '<tr><td colspan="5" class="quiet">Scores unavailable.</td></tr>'; });

/* ---------- copy ---------- */
$("copy").addEventListener("click", async () => {
  const text = $("setup").innerText.split("\n").filter((l) => !l.trim().startsWith("#")).join("\n");
  try {
    await navigator.clipboard.writeText(text);
    $("copy").textContent = "Copied";
    setTimeout(() => ($("copy").textContent = "Copy"), 1500);
  } catch (e) {}
});
