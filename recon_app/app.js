// Virgo Recon PWA — talks to virgo_recon_server.py over REST + SSE.
"use strict";

const API = location.origin + "/api";
let profiles = {};
let es = null;

const $ = (s) => document.querySelector(s);

function setConn(on) {
  const el = $("#conn");
  el.className = "conn " + (on ? "on" : "off");
  el.textContent = on ? "● online" : "● offline";
}

async function loadProfiles() {
  try {
    const r = await fetch(API + "/profiles");
    profiles = await r.json();
    const sel = $("#profile");
    sel.innerHTML = "";
    for (const [k, v] of Object.entries(profiles)) {
      const o = document.createElement("option");
      o.value = k;
      o.textContent = k + " — " + v.desc;
      sel.appendChild(o);
    }
    setConn(true);
  } catch (e) {
    setConn(false);
  }
}

async function loadJobs() {
  try {
    const r = await fetch(API + "/jobs");
    const jobs = await r.json();
    renderJobs(jobs);
    setConn(true);
  } catch (e) {
    setConn(false);
  }
}

function renderJobs(jobs) {
  const box = $("#jobs");
  if (!jobs.length) {
    box.innerHTML = '<p class="muted">No scans yet.</p>';
    return;
  }
  box.innerHTML = "";
  for (const j of jobs) {
    const div = document.createElement("div");
    div.className = "job";
    div.innerHTML =
      '<div class="row"><span class="tgt">' +
      esc(j.target) + '</span><span class="badge ' + j.status + '">' +
      j.status + "</span></div>" +
      '<div class="muted" style="font-size:12px;margin-top:4px;">' +
      esc(j.profile) + " · " + esc(shortTime(j.created)) + "</div>";
    div.onclick = () => showDetail(j.id);
    box.appendChild(div);
  }
}

async function showDetail(id) {
  try {
    const r = await fetch(API + "/jobs/" + id);
    const j = await r.json();
    $("#detail-title").textContent = j.profile + " → " + j.target + " [" + j.status + "]";
    let body = "";
    if (j.cmd) body += "$ " + j.cmd + "\n\n";
    if (j.result) body += j.result;
    if (j.stderr) body += "\n\n--- stderr ---\n" + j.stderr;
    if (j.status === "running") body += "\n\n(running…)";
    $("#detail-body").textContent = body || "(no output)";
    $("#detail").hidden = false;
    $("#detail").scrollIntoView({ behavior: "smooth" });
  } catch (e) {}
}

function startStream() {
  if (es) es.close();
  es = new EventSource(API + "/stream");
  es.onopen = () => setConn(true);
  es.onerror = () => setConn(false);
  es.onmessage = (ev) => {
    try { loadJobs(); } catch (e) {}
  };
}

async function launch() {
  const target = $("#target").value.trim();
  const profile = $("#profile").value;
  if (!target) { alert("Enter a target"); return; }
  $("#gobtn").textContent = "… launching";
  try {
    const r = await fetch(API + "/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile, target }),
    });
    const data = await r.json();
    if (data.error) { alert(data.error); }
    else { $("#target").value = ""; loadJobs(); showDetail(data.id); }
  } catch (e) {
    alert("Server unreachable — is virgo_recon_server running?");
  }
  $("#gobtn").textContent = "▶ Launch";
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function shortTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString();
}

$("#gobtn").addEventListener("click", launch);
$("#refresh").addEventListener("click", loadJobs);

loadProfiles();
loadJobs();
startStream();
// keep in sync if the tab was backgrounded
document.addEventListener("visibilitychange", () => { if (!document.hidden) loadJobs(); });
