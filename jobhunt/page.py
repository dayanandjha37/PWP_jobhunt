"""The UI page served at /. Kept as one static string: no build step, no CDN —
the whole tool keeps working offline, same as the rest of jobhunt.

Palette is the digest's palette (digest.py), so the email and the UI read as
one product.
"""
from __future__ import annotations

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>jobhunt</title>
<style>
  :root {
    --bg: #0f1115; --card: #171a21; --line: #262b36;
    --text: #e6e8ec; --muted: #8b93a3; --accent: #7c9cff;
    --green: #3fb950; --amber: #d29922; --red: #f85149;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text);
         font: 15px/1.5 -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
  a { color: var(--accent); }
  header { display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
           padding: 16px 22px; border-bottom: 1px solid var(--line);
           position: sticky; top: 0; background: var(--bg); z-index: 5; }
  .brand { font-size: 20px; font-weight: 800; letter-spacing: -.02em; }
  .brand span { color: var(--accent); }
  select, input, button, textarea { font: inherit; color: var(--text);
           background: var(--card); border: 1px solid var(--line);
           border-radius: 8px; padding: 7px 11px; }
  select:focus, input:focus, textarea:focus { outline: 1px solid var(--accent); }
  .stats { display: flex; gap: 10px; margin-left: auto; }
  .tile { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
          padding: 6px 14px; text-align: center; min-width: 74px; }
  .tile b { display: block; font-size: 18px; }
  .tile i { font-style: normal; color: var(--muted); font-size: 11px;
            text-transform: uppercase; letter-spacing: .08em; }
  .tile.ok b { color: var(--green); }

  #runbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
            padding: 14px 22px 0; }
  .btn { cursor: pointer; font-weight: 600; }
  .btn.primary { background: var(--accent); border-color: var(--accent); color: #0f1115; }
  .btn.ghost { background: transparent; }
  .btn.danger { background: transparent; color: var(--red); }
  .btn:disabled { opacity: .5; cursor: default; }
  #runmsg { color: var(--muted); font-size: 13px; }
  #runmsg.err { color: var(--red); }
  .log { display: none; margin: 10px 0 0; padding: 12px; max-height: 240px;
         overflow: auto; background: #0d1017; border: 1px solid var(--line);
         border-radius: 10px; font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
         white-space: pre-wrap; color: var(--muted); }
  #runlog { margin: 10px 22px 0; }

  nav { display: flex; gap: 4px; padding: 16px 22px 0; }
  .tab { cursor: pointer; padding: 7px 14px; border-radius: 8px; color: var(--muted);
         border: 1px solid transparent; background: none; font-weight: 600; }
  .tab.on { color: var(--text); background: var(--card); border-color: var(--line); }
  .tab small { color: var(--muted); font-weight: 400; margin-left: 5px; }

  #q { margin: 12px 22px 0; width: calc(100% - 44px); max-width: 420px; }

  main { max-width: 760px; margin: 14px auto 60px; padding: 0 22px; }
  .empty { color: var(--muted); background: var(--card); border: 1px solid var(--line);
           border-radius: 12px; padding: 22px; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
          padding: 18px; margin-bottom: 14px; }
  .card.applied { opacity: .72; }
  .chead { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
  .chead h2 { margin: 0; font-size: 17px; }
  .badge { flex: none; background: var(--muted); color: #0f1115; font-weight: 700;
           padding: 3px 10px; border-radius: 999px; font-size: 13px; }
  .badge.hi { background: var(--green); } .badge.mid { background: var(--amber); }
  .meta { color: var(--muted); font-size: 13px; margin-top: 5px; }
  .reason { margin: 10px 0 0; color: var(--text); }
  .sec { margin-top: 14px; }
  .sec > h3 { margin: 0 0 6px; color: var(--muted); font-size: 11px; letter-spacing: .09em;
              text-transform: uppercase; }
  .sec ul { margin: 0; padding-left: 18px; }
  .sec li { margin-bottom: 6px; font-size: 14px; }
  .sec.gaps li { color: var(--amber); }
  textarea { width: 100%; min-height: 120px; resize: vertical; line-height: 1.6;
             background: #0d1017; }
  .row { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; align-items: center; }
  .saved { color: var(--green); font-size: 12px; opacity: 0; transition: opacity .3s; }
  .saved.show { opacity: 1; }
  .jid { color: var(--muted); font-size: 11px; }
  .applied-on { color: var(--green); font-size: 13px; }
  .apply { display: inline-block; background: var(--accent); color: #0f1115; font-weight: 700;
           text-decoration: none; padding: 10px 18px; border-radius: 8px; font-size: 14px; }
  .done { border-color: var(--green); color: var(--green); }

  .field { margin-bottom: 12px; }
  .field > label { display: block; font-size: 12px; color: var(--muted);
                   margin-bottom: 4px; }
  .field code { color: var(--text); font-size: 12px; }
  .field .inrow { display: flex; gap: 8px; }
  .field input { flex: 1; }
  .sechead { color: var(--muted); font-size: 11px; letter-spacing: .09em;
             text-transform: uppercase; margin: 18px 0 8px; }
  .card > .sechead:first-child { margin-top: 0; }
  .hint { color: var(--muted); font-size: 13px; margin: 8px 0 0; }
  .err { color: var(--red); font-size: 13px; white-space: pre-wrap; }
</style>
</head>
<body>
<header>
  <div class="brand">job<span>hunt</span></div>
  <select id="user" title="user"></select>
  <button class="btn ghost" id="add-user" title="create a user directory under users/">+ user</button>
  <button class="btn danger" id="remove-user" title="delete this user's directory under users/">– user</button>
  <div class="stats">
    <div class="tile"><b id="s-tracked">–</b><i>seen</i></div>
    <div class="tile"><b id="s-emailed">–</b><i>in digest</i></div>
    <div class="tile ok"><b id="s-applied">–</b><i>applied</i></div>
  </div>
</header>

<div id="runbar">
  <button class="btn primary" id="run-real">Run pipeline</button>
  <button class="btn" id="run-mock">Offline dry run</button>
  <span id="runmsg"></span>
</div>
<pre id="runlog"></pre>

<nav id="tabs"></nav>
<input id="q" placeholder="filter by title or company…">
<main id="list"><div class="empty">loading…</div></main>

<script>
"use strict";
const $ = (s) => document.querySelector(s);
const state = { user: null, tab: "todo", q: "", jobs: [], threshold: 7,
                stats: {}, polling: null, buildPolling: null,
                profile: null, envFields: null, configText: null };

// ---- helpers -------------------------------------------------------------
function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v != null && v !== false) n.setAttribute(k, v);  // "" sets e.g. disabled
  }
  for (const kid of kids) if (kid != null) n.append(kid);
  return n;
}
function section(label, ...kids) {
  if (!kids.length) return null;
  return el("div", { class: "sec" + (label === "Honest gaps" ? " gaps" : "") },
             el("h3", {}, label), ...kids);
}
function copy(text, btn) {
  const done = () => { const t = btn.textContent;
                       btn.textContent = "Copied ✓";
                       setTimeout(() => (btn.textContent = t), 1200); };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done);
    return;
  }
  const tmp = el("textarea", {});  // legacy fallback
  tmp.value = text; document.body.append(tmp); tmp.select();
  document.execCommand("copy"); tmp.remove(); done();
}

// ---- data ----------------------------------------------------------------
async function api(path, opts) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error || r.status);
  return body;
}
async function loadUsers(preselect) {
  const { users } = await api("/api/users");
  const sel = $("#user");
  sel.replaceChildren();
  for (const u of users) sel.append(el("option", { value: u.name },
    `${u.name} (${u.tracked})`));
  const wanted = preselect || new URLSearchParams(location.search).get("user");
  state.user = users.some((u) => u.name === wanted) ? wanted : users[0]?.name;
  if (state.user) { sel.value = state.user; await loadTab(); }
  else $("#list").replaceChildren(el("div", { class: "empty" },
    "No users under users/ yet — add one with the “+ user” button above."));
}
async function addUser() {
  const name = prompt("New user name — becomes a directory under users/:", "");
  if (!name || !name.trim()) return;
  try {
    const d = await api("/api/users", post({ name: name.trim() }));
    await loadUsers(d.user);  // reload the list with the new user selected
  } catch (e) { alert(e.message); }
}
async function removeUser() {
  if (!state.user) return;
  const name = state.user;
  const ok = confirm(`Delete users/${name}?\n` +
    "Everything inside goes too — config, resume, profile.json, .env secrets, " +
    "the seen.json tracker and its application history. No undo.");
  if (!ok) return;
  try {
    await api("/api/users?user=" + encodeURIComponent(name), { method: "DELETE" });
    state.user = null;
    await loadUsers();  // falls back to the first remaining user
  } catch (e) { alert(e.message); }
}
async function loadJobs() {
  if (!state.user) return;
  try {
    const d = await api("/api/jobs?user=" + encodeURIComponent(state.user));
    state.jobs = d.jobs; state.threshold = d.threshold; state.stats = d.stats;
    render();
  } catch (e) { $("#list").replaceChildren(el("div", { class: "empty" }, e.message)); }
}

// ---- render --------------------------------------------------------------
function visible() {
  const q = state.q.toLowerCase();
  return state.jobs.filter((j) => {
    if (q && !((j.title + " " + j.company).toLowerCase().includes(q))) return false;
    if (state.tab === "todo") return j.score != null && j.score >= state.threshold && !j.applied;
    if (state.tab === "applied") return !!j.applied;
    return true;
  });
}
function renderTabs() {
  const n = { todo: 0, applied: 0, all: state.jobs.length };
  for (const j of state.jobs) {
    if (j.applied) n.applied++;
    else if (j.score != null && j.score >= state.threshold) n.todo++;
  }
  const tabs = [["todo", "To apply"], ["applied", "Applied"], ["all", "All"],
                ["profile", "Profile"], ["settings", "Settings"],
                ["config", "Config"]];
  $("#tabs").replaceChildren(...tabs.map(([id, label]) =>
    el("button", {
      class: "tab" + (state.tab === id ? " on" : ""),
      onclick: () => { state.tab = id; loadTab(); },
    }, label, n[id] != null ? el("small", {}, String(n[id])) : null)));
}
function loadTab() {
  if (state.tab === "profile") return loadProfile();
  if (state.tab === "settings") return loadEnv();
  if (state.tab === "config") return loadConfig();
  return loadJobs();
}
function panelError(msg) {
  $("#list").replaceChildren(el("div", { class: "empty" }, msg));
}
function render() {
  renderTabs();
  $("#q").style.display = ["profile", "settings", "config"].includes(state.tab)
    ? "none" : "";
  if (state.tab === "profile") { renderProfile(); return; }
  if (state.tab === "settings") { renderSettings(); return; }
  if (state.tab === "config") { renderConfig(); return; }
  $("#s-tracked").textContent = state.stats.tracked ?? "–";
  $("#s-emailed").textContent = state.stats.emailed ?? "–";
  $("#s-applied").textContent = state.stats.applied ?? "–";

  const jobs = visible();
  const list = $("#list");
  if (!jobs.length) {
    list.replaceChildren(el("div", { class: "empty" },
      state.tab === "todo"
        ? "Nothing waiting. Run the pipeline, or loosen score_threshold in config.yaml."
        : "Nothing here yet."));
    return;
  }
  list.replaceChildren(...jobs.map(card));
}
function card(j) {
  const d = j.draft || {};
  const s = j.score;
  const badge = el("span", {
    class: "badge" + (s >= 8.5 ? " hi" : s >= state.threshold ? " mid" : ""),
  }, s == null ? "—" : Number(s).toFixed(1));

  const note = el("textarea", { spellcheck: "false" });
  note.value = d.cover_note || "";
  const saved = el("span", { class: "saved" }, "saved");
  const save = async () => {
    if (note.value === (d.cover_note || "")) return;
    try {
      await api("/api/note", post({ user: state.user, job_id: j.job_id,
                                    cover_note: note.value }));
      d.cover_note = note.value;
      saved.classList.add("show"); setTimeout(() => saved.classList.remove("show"), 1500);
    } catch (e) { alert(e.message); }
  };
  note.addEventListener("blur", save);

  const copyBtn = el("button", { class: "btn",
    onclick: () => copy(note.value, copyBtn) }, "Copy");
  const bullets = (d.tailored_bullets || []).join("\n• ");
  const copyBullets = el("button", { class: "btn ghost",
    onclick: (e) => copy("• " + bullets, e.target) }, "Copy all");
  const bulletsBtns = (d.tailored_bullets || []).length
    ? el("div", { class: "row" }, copyBullets) : null;

  const apply = el("a", { class: "apply", href: j.url, target: "_blank",
                          rel: "noopener" }, "Open & apply →");
  const mark = j.applied
    ? el("button", { class: "btn done",
        onclick: () => setApplied(j, false) }, "Applied ✓ (undo)")
    : el("button", { class: "btn",
        onclick: () => setApplied(j, true) }, "Mark applied");

  return el("article", { class: "card" + (j.applied ? " applied" : "") },
    el("div", { class: "chead" }, el("h2", {}, j.title), badge),
    el("div", { class: "meta" },
      [j.company, j.location || "—", j.ats, j.first_seen?.slice(0, 10)]
        .filter(Boolean).join(" · ")),
    j.reason ? el("p", { class: "reason" }, j.reason) : null,
    section("Why it fits", d.fit_summary ? el("p", {}, d.fit_summary) : null),
    section("Resume bullets for this role", bulletsBtns,
      (d.tailored_bullets || []).length
        ? el("ul", {}, ...d.tailored_bullets.map((b) => el("li", {}, b))) : null),
    section("Honest gaps", (d.gaps || []).length
      ? el("ul", {}, ...d.gaps.map((g) => el("li", {}, g))) : null),
    section("Cover note (edit before sending)", note,
      el("div", { class: "row" }, copyBtn, saved)),
    section("Ask them", (d.questions_to_ask || []).length
      ? el("ul", {}, ...d.questions_to_ask.map((q) => el("li", {}, q))) : null),
    el("div", { class: "row" }, apply, mark,
      j.applied && j.applied_on
        ? el("span", { class: "applied-on" }, "on " + j.applied_on.slice(0, 10)) : null,
      el("span", { class: "jid" }, j.job_id)));
}
const post = (body) => ({ method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body) });

async function setApplied(j, applied) {
  try {
    await api("/api/applied", post({ user: state.user, job_id: j.job_id,
                                     applied }));
    await loadJobs();  // cheap: file read, and keeps counts honest
  } catch (e) { alert(e.message); }
}

// ---- profile tab: resume -> profile.json ----------------------------------
async function loadProfile() {
  if (!state.user) return;
  try {
    state.profile = await api("/api/profile?user=" + encodeURIComponent(state.user));
    render();
  } catch (e) { panelError(e.message); }
}

function renderProfile() {
  const d = state.profile || { user: state.user, resume: null, profile: null };

  // -- resume upload
  const file = el("input", { type: "file", accept: ".pdf,.docx,.txt,.md" });
  const upMsg = el("span", { class: "hint" });
  const upload = el("button", { class: "btn primary", onclick: async () => {
    if (!file.files.length) { upMsg.textContent = "pick a file first"; return; }
    const f = file.files[0];
    try {
      upMsg.textContent = `uploading ${f.name}…`;
      const r = await fetch("/api/resume?user=" + encodeURIComponent(state.user),
        { method: "POST", headers: { "X-Filename": f.name }, body: f });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.error || r.status);
      upMsg.textContent = "";
      await loadProfile();  // refresh resume name + build button state
    } catch (e) { upMsg.textContent = ""; alert(e.message); }
  }}, "Upload");
  const resumeCard = el("div", { class: "card" },
    el("h3", { class: "sechead" }, "Resume"),
    el("p", { class: "hint" }, d.resume
      ? `on file: ${d.resume} — uploading a new one replaces it`
      : "no resume yet — upload a .pdf, .docx, .txt or .md"),
    el("div", { class: "row" }, file, upload, upMsg),
    el("div", { class: "row" },
      el("button", { class: "btn", disabled: !d.resume ? "" : null,
        onclick: startBuild },
        "Build profile from resume"),
      el("span", { class: "hint" },
        "runs the LLM extraction (needs a key in Settings) and writes profile.json")),
    el("pre", { id: "buildlog", class: "log" }));

  // -- profile.json editor
  const editor = el("textarea", { spellcheck: "false" });
  editor.value = d.profile ? JSON.stringify(d.profile, null, 2) : "";
  const perr = el("span", { class: "err" });
  const saved = el("span", { class: "saved" }, "saved");
  const save = el("button", { class: "btn primary", onclick: async () => {
    let parsed;
    try { parsed = JSON.parse(editor.value); }
    catch (e) { perr.textContent = "invalid JSON: " + e.message; return; }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      perr.textContent = "profile must be a JSON object"; return;
    }
    perr.textContent = "";
    try {
      await api("/api/profile", post({ user: state.user, profile: parsed }));
      saved.classList.add("show"); setTimeout(() => saved.classList.remove("show"), 1500);
    } catch (e) { perr.textContent = e.message; }
  }}, "Save profile");
  const editorCard = el("div", { class: "card" },
    el("h3", { class: "sechead" }, "profile.json"),
    el("p", { class: "hint" }, d.profile
      ? "editable — the pipeline reads this file on every run"
      : "nothing here yet: upload a resume above and press Build, or paste JSON and save"),
    editor,
    el("div", { class: "row" }, save, saved, perr));

  $("#list").replaceChildren(resumeCard, editorCard);
}

async function startBuild() {
  try {
    await api("/api/profile/build", post({ user: state.user }));
    if (state.buildPolling) clearInterval(state.buildPolling);
    state.buildPolling = setInterval(pollBuild, 1000);
    pollBuild();
  } catch (e) { alert(e.message); }
}
async function pollBuild() {
  const d = await api("/api/build/status").catch(() => null);
  if (!d) return;
  const logEl = $("#buildlog");
  if (logEl && d.log) {
    logEl.style.display = "block";
    logEl.textContent = d.log;
    logEl.scrollTop = logEl.scrollHeight;
  }
  if (d.running) return;
  clearInterval(state.buildPolling); state.buildPolling = null;
  if (d.rc === 0 && state.tab === "profile") await loadProfile();
}

// ---- settings tab: the user's .env ----------------------------------------
async function loadEnv() {
  if (!state.user) return;
  try {
    const d = await api("/api/env?user=" + encodeURIComponent(state.user));
    state.envFields = d.fields;
    render();
  } catch (e) { panelError(e.message); }
}

function renderSettings() {
  const bySection = new Map();
  for (const f of state.envFields || []) {
    if (!bySection.has(f.section)) bySection.set(f.section, []);
    bySection.get(f.section).push(f);
  }
  const inputs = {};
  const cards = [...bySection.entries()].map(([section, fs]) =>
    el("div", { class: "card" },
      el("h3", { class: "sechead" }, section),
      ...fs.map((f) => {
        const input = el("input", { type: f.secret ? "password" : "text",
                                    autocomplete: "off", spellcheck: "false",
                                    placeholder: f.secret ? "not set" : "" });
        input.value = f.value;
        inputs[f.name] = input;
        const toggle = f.secret ? el("button", { class: "btn ghost",
          onclick: () => {
            const show = input.type === "password";
            input.type = show ? "text" : "password";
            toggle.textContent = show ? "hide" : "show";
          }}, "show") : null;
        return el("div", { class: "field" },
          el("label", {}, el("code", {}, f.name), " — " + f.label),
          el("div", { class: "inrow" }, input, toggle));
      })));

  const saved = el("span", { class: "saved" }, "saved");
  const save = el("button", { class: "btn primary", onclick: async () => {
    const payload = {};
    for (const [k, input] of Object.entries(inputs)) payload[k] = input.value;
    try {
      await api("/api/env", post({ user: state.user, fields: payload }));
      saved.classList.add("show"); setTimeout(() => saved.classList.remove("show"), 1500);
      await loadEnv();
    } catch (e) { alert(e.message); }
  }}, "Save settings");

  const intro = el("div", { class: "card" },
    el("h3", { class: "sechead" }, "Secrets & providers"),
    el("p", { class: "hint" },
      `Written to users/${state.user}/.env and applied scoped during their runs — ` +
      "one user's key never leaks into another's. Empty values stay unset."));

  $("#list").replaceChildren(intro, ...cards,
    el("div", { class: "row" }, save, saved));
}

// ---- config tab: the user's config.yaml -----------------------------------
async function loadConfig() {
  if (!state.user) return;
  try {
    const d = await api("/api/config?user=" + encodeURIComponent(state.user));
    state.configText = d.config;
    render();
  } catch (e) { panelError(e.message); }
}

function renderConfig() {
  const editor = el("textarea", { spellcheck: "false" });
  editor.value = state.configText ?? "";
  const err = el("span", { class: "err" });
  const saved = el("span", { class: "saved" }, "saved");
  const save = el("button", { class: "btn primary", onclick: async () => {
    try {
      await api("/api/config", post({ user: state.user, config: editor.value }));
      err.textContent = "";
      state.configText = editor.value;
      saved.classList.add("show"); setTimeout(() => saved.classList.remove("show"), 1500);
    } catch (e) { err.textContent = e.message; }  // the server is the YAML gatekeeper
  }}, "Save config");
  $("#list").replaceChildren(el("div", { class: "card" },
    el("h3", { class: "sechead" }, "config.yaml"),
    el("p", { class: "hint" },
      `users/${state.user}/config.yaml — filters, thresholds and file paths ` +
      "for this user only. Saved as-is: comments and key order survive."),
    editor,
    el("div", { class: "row" }, save, saved, err)));
}

// ---- run pipeline --------------------------------------------------------
async function startRun(mock) {
  try {
    await api("/api/run", post({ user: state.user, mock }));
    $("#runlog").style.display = "block";
    msg(mock ? "running offline dry run…" : "running pipeline…");
    if (state.polling) clearInterval(state.polling);
    state.polling = setInterval(pollRun, 1500);
    pollRun();
  } catch (e) { msg(e.message, true); }
}
async function pollRun() {
  const d = await api("/api/run/status");
  $("#runlog").textContent = d.log;
  $("#runlog").scrollTop = $("#runlog").scrollHeight;
  if (d.running) return;
  clearInterval(state.polling); state.polling = null;
  msg(d.rc === 0 ? "done ✓" : `finished with errors (exit ${d.rc})`, d.rc !== 0);
  await loadJobs();
}
function msg(text, err) {
  const m = $("#runmsg"); m.textContent = text;
  m.className = err ? "err" : "";
}

// ---- wire up -------------------------------------------------------------
$("#user").addEventListener("change", async (e) => {
  state.user = e.target.value; await loadTab();
});
$("#add-user").addEventListener("click", addUser);
$("#remove-user").addEventListener("click", removeUser);
$("#q").addEventListener("input", (e) => { state.q = e.target.value; render(); });
$("#run-real").addEventListener("click", () => startRun(false));
$("#run-mock").addEventListener("click", () => startRun(true));
loadUsers();
</script>
</body>
</html>
"""
