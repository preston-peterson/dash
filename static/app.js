"use strict";

/* --------------------------------------------------------------------- */
/* State                                                                 */
/* --------------------------------------------------------------------- */
const state = {
  links: [],
  search: "",
  activeTags: new Set(),
  view: localStorage.getItem("dash.view") || "tiles", // "tiles" | "rows"
  theme: localStorage.getItem("dash.theme") || "dark", // "dark" | "light"
  user: null,
  pwTarget: null,
  update: null,
  pollTimer: null,
};

const $ = (sel) => document.querySelector(sel);

// Tags selected in the Add/Edit modal (token input).
let modalTags = [];

/* --------------------------------------------------------------------- */
/* API helper                                                            */
/* --------------------------------------------------------------------- */
async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = formatError(data.detail) || detail;
    } catch (_) {}
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

// Returns true if the error was a 401 (handled by bouncing to the login screen).
function onApiError(e) {
  if (e && e.status === 401) {
    state.user = null;
    showScreen("login");
    return true;
  }
  return false;
}

function formatError(detail) {
  if (!detail) return null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((e) => {
        const field = Array.isArray(e.loc) ? e.loc[e.loc.length - 1] : "";
        return `${field}: ${e.msg}`;
      })
      .join(", ");
  }
  return String(detail);
}

/* --------------------------------------------------------------------- */
/* Helpers                                                               */
/* --------------------------------------------------------------------- */
function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c) node.append(c.nodeType ? c : document.createTextNode(c));
  }
  return node;
}

const openUrl = (link) => `${link.scheme}://${link.host}:${link.port}`;
const parseTags = (s) => (s || "").split(",").map((t) => t.trim()).filter(Boolean);

function timeAgo(iso) {
  if (!iso) return "never";
  const then = Date.parse(iso);
  if (isNaN(then)) return "";
  const s = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function timeAgoShort(iso) {
  if (!iso) return "";
  const then = Date.parse(iso);
  if (isNaN(then)) return "";
  const s = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

function fmtLatency(ms) {
  return ms === 0 ? "<1 ms" : `${ms} ms`;
}

function statusText(link) {
  if (link.status === "online" && link.latency_ms != null) return fmtLatency(link.latency_ms);
  return link.status;
}

/* --------------------------------------------------------------------- */
/* Rendering                                                             */
/* --------------------------------------------------------------------- */
function visibleLinks() {
  const q = state.search.trim().toLowerCase();
  return state.links.filter((link) => {
    if (state.activeTags.size) {
      const tags = new Set(parseTags(link.tags));
      for (const t of state.activeTags) if (!tags.has(t)) return false;
    }
    if (!q) return true;
    const hay = `${link.name} ${link.description} ${link.host} ${link.tags} ${link.resolved || ""}`.toLowerCase();
    return hay.includes(q);
  });
}

function render() {
  // Summary counts (over all links, not filtered)
  $("#c-online").textContent = state.links.filter((l) => l.status === "online").length;
  $("#c-offline").textContent = state.links.filter((l) => l.status === "offline").length;

  renderTagFilters();
  updateSettingsMenu();

  const content = $("#content");
  content.className = "content " + (state.view === "rows" ? "rows" : "tiles");
  content.replaceChildren();

  const empty = state.links.length === 0;
  const items = visibleLinks();
  $("#empty-state").hidden = !empty;
  $("#no-results").hidden = empty || items.length > 0;

  if (empty || items.length === 0) return;

  if (state.view === "rows") {
    const table = el("div", { class: "rows-table" });
    table.append(rowHeader());
    for (const link of items) table.append(buildRow(link));
    content.append(table);
  } else {
    for (const link of items) content.append(buildCard(link));
  }
}

function renderTagFilters() {
  const counts = new Map();
  for (const link of state.links) for (const t of parseTags(link.tags)) counts.set(t, (counts.get(t) || 0) + 1);
  const wrap = $("#tag-filters");
  wrap.replaceChildren();
  const tags = [...counts.keys()].sort();
  wrap.hidden = tags.length === 0;
  if (tags.length === 0) return;
  wrap.append(
    el("button", {
      class: "tag-chip" + (state.activeTags.size === 0 ? " active" : ""),
      text: "all",
      onclick: () => { state.activeTags.clear(); render(); },
    })
  );
  for (const t of tags) {
    wrap.append(
      el("button", {
        class: "tag-chip" + (state.activeTags.has(t) ? " active" : ""),
        text: `${t}`,
        onclick: () => {
          state.activeTags.has(t) ? state.activeTags.delete(t) : state.activeTags.add(t);
          render();
        },
      })
    );
  }
}

/* Inline SVG icons (no icon font; works fully offline). */
const ICONS = {
  open: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>',
  edit: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/></svg>',
  trash: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>',
};

function iconBtn(icon, title, cls, onclick) {
  const b = el("button", { class: "icon-btn" + (cls ? " " + cls : ""), title, type: "button" });
  b.innerHTML = ICONS[icon];
  b.addEventListener("click", (e) => { e.stopPropagation(); onclick(); });
  return b;
}

// withOpen adds an explicit "open service" shortcut (used in the rows view).
function itemActions(link, withOpen) {
  const btns = [];
  if (withOpen) btns.push(iconBtn("open", `Open ${openUrl(link)}`, "", () => window.open(openUrl(link), "_blank", "noopener")));
  btns.push(iconBtn("edit", "Edit", "", () => openModal(link)));
  btns.push(iconBtn("trash", "Delete", "danger", () => deleteLink(link)));
  return btns;
}

// The status light doubles as a per-item re-check control.
function statusDot(link) {
  return el("span", {
    class: "dot " + link.status, role: "button", title: "Re-check now",
    onclick: (e) => { e.stopPropagation(); refreshOne(link.id); },
  });
}

// Service icon: the service's favicon (or a colored initial) with a status badge.
// Also doubles as the per-item re-check control.
function serviceAvatar(link) {
  const av = el("div", {
    class: "avatar " + link.status, role: "button", title: "Re-check now",
    onclick: (e) => { e.stopPropagation(); refreshOne(link.id); },
  });
  const setInitial = () => {
    av.classList.add("noimg");
    let h = 0;
    for (const c of (link.name || "?")) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    av.style.background = `hsl(${h % 360}, 45%, 42%)`;
    av.append(el("span", { class: "avatar-initial", text: ((link.name || "?").trim()[0] || "?").toUpperCase() }));
  };
  if (link.favicon) {
    const img = el("img", { src: `/api/links/${link.id}/favicon?v=${encodeURIComponent(link.favicon)}`, alt: "", loading: "lazy" });
    img.addEventListener("error", () => { img.remove(); setInitial(); });
    av.append(img);
  } else {
    setInitial();
  }
  av.append(el("span", { class: "avatar-badge" }));
  return av;
}

function tagNodes(link) {
  return parseTags(link.tags).map((t) =>
    el("span", {
      class: "tag", text: t,
      onclick: (e) => { e.stopPropagation(); state.activeTags.add(t); render(); },
    })
  );
}

function rowStatus(link) {
  const wrap = el("div", { class: "row-status status-" + link.status });
  if (link.last_checked) wrap.title = `Checked ${timeAgo(link.last_checked)}`;
  if (link.status === "online") {
    wrap.append(el("span", { class: "status-main", text: link.latency_ms != null ? fmtLatency(link.latency_ms) : "online" }));
  } else if (link.status === "offline") {
    wrap.append(
      el("span", { class: "status-main", text: "down" }),
      el("span", { class: "status-sub", text: timeAgoShort(link.last_checked) })
    );
  } else if (link.status === "checking") {
    wrap.append(el("span", { class: "status-main", text: "checking…" }));
  } else {
    wrap.append(el("span", { class: "status-main", text: "—" }));
  }
  return wrap;
}

function buildCard(link) {
  const card = el("div", {
    class: "card", title: `Open ${openUrl(link)}`,
    onclick: () => window.open(openUrl(link), "_blank", "noopener"),
  });
  card.append(
    ...[
      el("div", { class: "item-actions" }, itemActions(link, false)),
      el("div", { class: "card-head" }, [
        serviceAvatar(link),
        el("span", { class: "card-name", text: link.name }),
      ]),
      el("div", { class: "card-addr", text: `${link.host}:${link.port}` }),
      link.resolved ? el("div", { class: "card-host", title: "Resolved via DNS", text: link.resolved }) : null,
      el("div", { class: "card-desc", text: link.description || "" }),
      el("div", { class: "card-foot" }, [
        el("div", { class: "card-tags" }, tagNodes(link)),
        el("span", { class: "latency", title: `Checked ${timeAgo(link.last_checked)}`, text: statusText(link) }),
      ]),
    ].filter(Boolean)
  );
  return card;
}

function rowHeader() {
  return el("div", { class: "row-header" }, [
    el("span", {}),
    el("span", { text: "Service" }),
    el("span", { text: "Address" }),
    el("span", { text: "Tags" }),
    el("span", { text: "Status" }),
    el("span", {}),
  ]);
}

function buildRow(link) {
  const row = el("div", {
    class: "row", title: `Open ${openUrl(link)}`,
    onclick: () => window.open(openUrl(link), "_blank", "noopener"),
  });
  row.append(
    serviceAvatar(link),
    el("div", { class: "row-service" }, [
      el("div", { class: "row-name", text: link.name }),
      link.description ? el("div", { class: "row-desc", text: link.description }) : null,
    ]),
    el("div", { class: "row-addr" }, [
      el("div", { class: "row-addr-ip", text: `${link.host}:${link.port}` }),
      link.resolved ? el("div", { class: "row-host", title: "Resolved via DNS", text: link.resolved }) : null,
    ]),
    el("div", { class: "row-tags" }, tagNodes(link)),
    rowStatus(link),
    el("div", { class: "row-actions" }, itemActions(link, true))
  );
  return row;
}

/* --------------------------------------------------------------------- */
/* Data actions                                                          */
/* --------------------------------------------------------------------- */
async function loadLinks() {
  try {
    state.links = await api("GET", "/api/links");
    render();
  } catch (e) {
    if (!onApiError(e)) console.error("loadLinks", e);
  }
}

async function refreshAll() {
  const btn = $("#btn-refresh");
  btn.disabled = true;
  try {
    await api("POST", "/api/check-all");
    await loadLinks();
  } catch (e) {
    if (!onApiError(e)) console.error(e);
  } finally {
    btn.disabled = false;
  }
}

async function refreshOne(id) {
  try {
    const updated = await api("POST", `/api/links/${id}/check`);
    const i = state.links.findIndex((l) => l.id === id);
    if (i >= 0) state.links[i] = updated;
    render();
  } catch (e) {
    if (!onApiError(e)) console.error(e);
  }
}

async function deleteLink(link) {
  if (!confirm(`Delete "${link.name}"?`)) return;
  try {
    await api("DELETE", `/api/links/${link.id}`);
    await loadLinks();
  } catch (e) {
    if (!onApiError(e)) alert("Delete failed: " + e.message);
  }
}

/* --------------------------------------------------------------------- */
/* Export / import                                                       */
/* --------------------------------------------------------------------- */
function exportLinks() {
  closeMenus();
  const links = state.links.map((l) => ({
    name: l.name, description: l.description, host: l.host, port: l.port,
    tags: l.tags, check_type: l.check_type, scheme: l.scheme,
  }));
  const payload = { dash: "links", version: 1, exported_at: new Date().toISOString(), links };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = el("a", { href: url, download: `dash-links-${new Date().toISOString().slice(0, 10)}.json` });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function handleImportFile(file) {
  if (!file) return;
  let parsed;
  try {
    parsed = JSON.parse(await file.text());
  } catch (_) {
    alert("Import failed: that file isn't valid JSON.");
    return;
  }
  const links = Array.isArray(parsed) ? parsed : (parsed && parsed.links);
  if (!Array.isArray(links)) {
    alert('Import failed: no "links" array found in the file.');
    return;
  }
  try {
    const res = await api("POST", "/api/links/import", { links });
    await loadLinks();
    const skip = res.skipped ? `, skipped ${res.skipped} duplicate${res.skipped === 1 ? "" : "s"}` : "";
    alert(`Imported ${res.added} link${res.added === 1 ? "" : "s"}${skip}.`);
  } catch (e) {
    if (!onApiError(e)) alert("Import failed: " + e.message);
  }
}

/* --------------------------------------------------------------------- */
/* Modal (add / edit)                                                    */
/* --------------------------------------------------------------------- */
/* --- Tag token input ------------------------------------------------- */
function tagAllKnown() {
  const set = new Set();
  for (const link of state.links) for (const t of parseTags(link.tags)) set.add(t);
  return [...set].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
}

function addTags(raw) {
  for (const part of (raw || "").split(",")) {
    const v = part.trim();
    if (v && !modalTags.some((x) => x.toLowerCase() === v.toLowerCase())) modalTags.push(v);
  }
  renderTagInput();
}

function removeTag(t) {
  modalTags = modalTags.filter((x) => x !== t);
  renderTagInput();
}

function renderTagInput() {
  const box = $("#f-tags-box"), entry = $("#f-tags-entry");
  box.querySelectorAll(".tag-token").forEach((n) => n.remove());
  for (const t of modalTags) {
    box.insertBefore(
      el("span", { class: "tag-token" }, [
        document.createTextNode(t),
        el("button", { type: "button", class: "tag-x", title: "Remove", text: "×", onclick: () => removeTag(t) }),
      ]),
      entry
    );
  }
  const selected = new Set(modalTags.map((x) => x.toLowerCase()));
  const sug = $("#f-tags-suggest");
  sug.replaceChildren();
  for (const t of tagAllKnown()) {
    if (selected.has(t.toLowerCase())) continue;
    sug.append(el("button", { type: "button", class: "tag-sug", text: t, onclick: () => addTags(t) }));
  }
  $("#f-tags").value = modalTags.join(", ");
}

function openModal(link) {
  const editing = !!link;
  $("#modal-title").textContent = editing ? "Edit service" : "Add service";
  $("#f-id").value = editing ? link.id : "";
  $("#f-name").value = editing ? link.name : "";
  $("#f-description").value = editing ? link.description : "";
  $("#f-host").value = editing ? link.host : "";
  $("#f-port").value = editing ? link.port : "";
  modalTags = editing ? parseTags(link.tags) : [];
  $("#f-tags-entry").value = "";
  renderTagInput();
  $("#f-check_type").value = editing ? link.check_type : "tcp";
  $("#f-scheme").value = editing ? link.scheme : "http";
  $("#form-error").hidden = true;
  updateUrlPreview();
  $("#modal").hidden = false;
  $("#f-name").focus();
}

function closeModal() { $("#modal").hidden = true; }

function updateUrlPreview() {
  const scheme = $("#f-scheme").value || "http";
  const host = $("#f-host").value.trim() || "host";
  const port = $("#f-port").value.trim() || "port";
  $("#url-preview").textContent = `${scheme}://${host}:${port}`;
}

async function submitForm(e) {
  e.preventDefault();
  // Commit any tag still typed in the entry box.
  if ($("#f-tags-entry").value.trim()) { addTags($("#f-tags-entry").value); $("#f-tags-entry").value = ""; }
  const id = $("#f-id").value;
  const payload = {
    name: $("#f-name").value,
    description: $("#f-description").value,
    host: $("#f-host").value,
    port: parseInt($("#f-port").value, 10),
    tags: $("#f-tags").value,
    check_type: $("#f-check_type").value,
    scheme: $("#f-scheme").value,
  };
  try {
    if (id) await api("PUT", `/api/links/${id}`, payload);
    else await api("POST", "/api/links", payload);
    closeModal();
    await loadLinks();
  } catch (err) {
    if (onApiError(err)) return;
    const box = $("#form-error");
    box.textContent = err.message;
    box.hidden = false;
  }
}

/* --------------------------------------------------------------------- */
/* Screens & auth                                                        */
/* --------------------------------------------------------------------- */
function showErr(node, msg) { node.textContent = msg; node.hidden = false; }

function showScreen(which) {
  if (which !== "app") stopPolling();
  $("#setup-screen").hidden = which !== "setup";
  $("#login-screen").hidden = which !== "login";
  $("#app").hidden = which !== "app";
  if (which !== "app") {
    for (const id of ["#modal", "#users-modal", "#account-modal"]) $(id).hidden = true;
  }
  if (which === "setup") $("#setup-username").focus();
  if (which === "login") $("#login-username").focus();
}

function applyUser() {
  const u = state.user;
  $("#user-menu").hidden = !u;
  if (u) {
    $("#user-name").textContent = u.username;
    $("#user-badge").hidden = !u.is_admin;
    $("#mi-users").hidden = !u.is_admin;
  }
  closeMenus();
}

function closeMenus() {
  $("#user-dropdown").hidden = true;
  $("#user-chip").setAttribute("aria-expanded", "false");
  $("#settings-dropdown").hidden = true;
  $("#settings-chip").setAttribute("aria-expanded", "false");
}

function toggleMenu(chipSel, dropSel) {
  const willOpen = $(dropSel).hidden;
  closeMenus();
  $(dropSel).hidden = !willOpen;
  $(chipSel).setAttribute("aria-expanded", String(willOpen));
}

function toggleUserMenu(e) { e.stopPropagation(); toggleMenu("#user-chip", "#user-dropdown"); }
function toggleSettingsMenu(e) { e.stopPropagation(); toggleMenu("#settings-chip", "#settings-dropdown"); }

function enterApp() {
  showScreen("app");
  applyUser();
  loadLinks();
  loadUpdate();
  startPolling();
}

/* --------------------------------------------------------------------- */
/* Update status                                                         */
/* --------------------------------------------------------------------- */
function stripV(s) { return (s || "").replace(/^v/i, ""); }

async function loadUpdate() {
  try {
    state.update = await api("GET", "/api/update");
  } catch (e) {
    if (onApiError(e)) return;
  }
  renderUpdate();
}

function renderUpdate() {
  const u = state.update;
  $("#update-current").textContent = u && u.current ? `dash v${stripV(u.current)}` : "dash";
  const avail = !!(u && u.available && u.latest);
  $("#settings-chip").classList.toggle("has-update", avail);
  $("#update-apply").hidden = !avail;
  $("#update-check").hidden = !(u && u.configured);
  const st = $("#update-status");
  st.classList.toggle("avail", avail);
  if (!u || !u.configured) st.textContent = "";
  else if (avail) st.textContent = `v${stripV(u.latest)} available`;
  else if (u.ok === true) st.textContent = "up to date";
  else if (u.ok === false) st.textContent = "check failed";
  else st.textContent = "";
  if (avail) {
    $("#update-cmd").textContent = u.command || "";
    const notes = $("#update-notes");
    notes.hidden = !u.release_url;
    if (u.release_url) notes.href = u.release_url;
  }
}

async function checkUpdate() {
  const btn = $("#update-check"), st = $("#update-status");
  btn.disabled = true;
  st.textContent = "checking…";
  st.classList.remove("avail");
  try {
    state.update = await api("POST", "/api/update/check");
    renderUpdate();
  } catch (e) {
    if (!onApiError(e)) st.textContent = "check failed";
  } finally {
    btn.disabled = false;
  }
}

async function copyUpdateCommand() {
  const cmd = state.update && state.update.command;
  if (!cmd) return;
  try {
    await navigator.clipboard.writeText(cmd);
    const b = $("#update-copy"), prev = b.textContent;
    b.textContent = "Copied!";
    setTimeout(() => { b.textContent = prev; }, 1200);
  } catch (_) {}
}

async function checkAuthAndStart() {
  const me = await api("GET", "/api/me");
  if (me.setup_required) { state.user = null; showScreen("setup"); return; }
  if (!me.authenticated) { state.user = null; showScreen("login"); return; }
  state.user = me.user;
  enterApp();
}

async function doSetup(e) {
  e.preventDefault();
  const err = $("#setup-error"); err.hidden = true;
  const username = $("#setup-username").value.trim();
  const pw = $("#setup-password").value, pw2 = $("#setup-password2").value;
  if (pw.length < 8) return showErr(err, "Password must be at least 8 characters.");
  if (pw !== pw2) return showErr(err, "Passwords do not match.");
  try {
    const res = await api("POST", "/api/setup", { username, password: pw });
    state.user = res.user;
    $("#setup-password").value = $("#setup-password2").value = "";
    enterApp();
  } catch (e2) {
    showErr(err, e2.message);
  }
}

async function doLogin(e) {
  e.preventDefault();
  const err = $("#login-error"); err.hidden = true;
  try {
    const res = await api("POST", "/api/login", {
      username: $("#login-username").value.trim(),
      password: $("#login-password").value,
    });
    state.user = res.user;
    $("#login-password").value = "";
    enterApp();
  } catch (e2) {
    showErr(err, e2.status === 401 ? "Invalid username or password" : e2.message);
  }
}

async function doLogout() {
  try { await api("POST", "/api/logout"); } catch (_) {}
  state.user = null;
  showScreen("login");
}

/* --------------------------------------------------------------------- */
/* User management                                                       */
/* --------------------------------------------------------------------- */
async function openUsersModal() {
  $("#users-error").hidden = true;
  $("#user-add-form").reset();
  $("#users-modal").hidden = false;
  await loadUsers();
}

async function loadUsers() {
  let users;
  try {
    users = await api("GET", "/api/users");
  } catch (e) {
    if (!onApiError(e)) showErr($("#users-error"), e.message);
    return;
  }
  const list = $("#users-list");
  list.replaceChildren();
  for (const u of users) {
    const isSelf = state.user && u.id === state.user.id;
    const row = el("div", { class: "user-row" });
    row.append(el("span", { class: "u-name", text: u.username }));
    if (u.is_admin) row.append(el("span", { class: "badge-admin", text: "admin" }));
    row.append(el("span", { class: "u-spacer" }));
    row.append(el("button", { class: "link-btn", text: "reset password", onclick: () => openAccountModal(u) }));
    if (isSelf) row.append(el("span", { class: "u-meta", text: "you" }));
    else row.append(el("button", { class: "link-btn danger", text: "delete", onclick: () => deleteUser(u) }));
    list.append(row);
  }
}

async function addUser(e) {
  e.preventDefault();
  const err = $("#users-error"); err.hidden = true;
  const username = $("#nu-username").value.trim();
  const password = $("#nu-password").value;
  const password2 = $("#nu-password2").value;
  if (password.length < 8) return showErr(err, "Password must be at least 8 characters.");
  if (password !== password2) return showErr(err, "Passwords do not match.");
  try {
    await api("POST", "/api/users", { username, password, is_admin: $("#nu-admin").checked });
    $("#user-add-form").reset();
    await loadUsers();
  } catch (e2) {
    if (!onApiError(e2)) showErr(err, e2.message);
  }
}

async function deleteUser(u) {
  if (!confirm(`Delete user "${u.username}"?`)) return;
  try {
    await api("DELETE", `/api/users/${u.id}`);
    await loadUsers();
  } catch (e) {
    if (!onApiError(e)) showErr($("#users-error"), e.message);
  }
}

/* Change own password, or (admin) reset another user's. target defaults to self. */
function openAccountModal(target) {
  const u = target && target.id ? target : state.user;
  state.pwTarget = u;
  const self = state.user && u.id === state.user.id;
  $("#account-title").textContent = self ? "Change password" : "Reset password";
  $("#account-sub").textContent = self ? `Signed in as ${u.username}` : `For user ${u.username}`;
  $("#account-password").value = $("#account-password2").value = "";
  $("#account-error").hidden = true;
  $("#account-modal").hidden = false;
  $("#account-password").focus();
}

async function submitAccount(e) {
  e.preventDefault();
  const err = $("#account-error"); err.hidden = true;
  const pw = $("#account-password").value, pw2 = $("#account-password2").value;
  if (pw.length < 8) return showErr(err, "Password must be at least 8 characters.");
  if (pw !== pw2) return showErr(err, "Passwords do not match.");
  const target = state.pwTarget || state.user;
  try {
    await api("POST", `/api/users/${target.id}/password`, { password: pw });
    $("#account-modal").hidden = true;
  } catch (e2) {
    if (!onApiError(e2)) showErr(err, e2.message);
  }
}

/* --------------------------------------------------------------------- */
/* Polling                                                               */
/* --------------------------------------------------------------------- */
function startPolling() {
  stopPolling();
  state.pollTimer = setInterval(loadLinks, 15000);
}
function stopPolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = null;
}

/* --------------------------------------------------------------------- */
/* View & theme                                                          */
/* --------------------------------------------------------------------- */
const _mediaDark = window.matchMedia("(prefers-color-scheme: dark)");
function resolvedTheme() {
  return state.theme === "auto" ? (_mediaDark.matches ? "dark" : "light") : state.theme;
}
function applyTheme() { document.documentElement.setAttribute("data-theme", resolvedTheme()); }
_mediaDark.addEventListener("change", () => { if (state.theme === "auto") applyTheme(); });

function setView(view) {
  state.view = view;
  localStorage.setItem("dash.view", view);
  render();
}

function setTheme(theme) {
  state.theme = theme;
  localStorage.setItem("dash.theme", theme);
  applyTheme();
  updateSettingsMenu();
}

function updateSettingsMenu() {
  for (const b of document.querySelectorAll("#settings-dropdown [data-view]"))
    b.classList.toggle("active", b.dataset.view === state.view);
  for (const b of document.querySelectorAll("#settings-dropdown [data-theme]"))
    b.classList.toggle("active", b.dataset.theme === state.theme);
}

/* --------------------------------------------------------------------- */
/* Wire up                                                               */
/* --------------------------------------------------------------------- */
function init() {
  applyTheme();
  updateSettingsMenu();

  $("#search").addEventListener("input", (e) => { state.search = e.target.value; render(); });
  $("#btn-refresh").addEventListener("click", refreshAll);
  $("#btn-add").addEventListener("click", () => openModal(null));

  $("#user-chip").addEventListener("click", toggleUserMenu);
  $("#mi-account").addEventListener("click", () => { closeMenus(); openAccountModal(); });
  $("#mi-users").addEventListener("click", () => { closeMenus(); openUsersModal(); });
  $("#mi-logout").addEventListener("click", doLogout);

  $("#settings-chip").addEventListener("click", toggleSettingsMenu);
  for (const b of document.querySelectorAll("#settings-dropdown [data-view]"))
    b.addEventListener("click", () => setView(b.dataset.view));
  for (const b of document.querySelectorAll("#settings-dropdown [data-theme]"))
    b.addEventListener("click", () => setTheme(b.dataset.theme));
  $("#update-check").addEventListener("click", checkUpdate);
  $("#update-copy").addEventListener("click", copyUpdateCommand);
  $("#mi-export").addEventListener("click", exportLinks);
  $("#mi-import").addEventListener("click", () => { closeMenus(); $("#import-file").click(); });
  $("#import-file").addEventListener("change", (e) => { handleImportFile(e.target.files[0]); e.target.value = ""; });

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#user-menu") && !e.target.closest("#settings-menu")) closeMenus();
  });

  $("#setup-form").addEventListener("submit", doSetup);
  $("#login-form").addEventListener("submit", doLogin);
  $("#link-form").addEventListener("submit", submitForm);
  $("#user-add-form").addEventListener("submit", addUser);
  $("#account-form").addEventListener("submit", submitAccount);
  $("#f-host").addEventListener("input", updateUrlPreview);
  $("#f-port").addEventListener("input", updateUrlPreview);
  $("#f-scheme").addEventListener("change", updateUrlPreview);

  $("#f-tags-entry").addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addTags(e.target.value); e.target.value = ""; }
    else if (e.key === "Backspace" && !e.target.value && modalTags.length) { removeTag(modalTags[modalTags.length - 1]); }
  });
  $("#f-tags-entry").addEventListener("blur", (e) => { if (e.target.value.trim()) { addTags(e.target.value); e.target.value = ""; } });
  $("#f-tags-box").addEventListener("mousedown", (e) => { if (e.target.id === "f-tags-box") { e.preventDefault(); $("#f-tags-entry").focus(); } });

  // Close buttons/backdrops dismiss their own modal.
  for (const node of document.querySelectorAll("[data-close]")) {
    node.addEventListener("click", () => {
      const m = node.closest(".modal");
      if (m) m.hidden = true;
    });
  }
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!$("#user-dropdown").hidden || !$("#settings-dropdown").hidden) { closeMenus(); return; }
    for (const id of ["#account-modal", "#users-modal", "#modal"]) {
      if (!$(id).hidden) { $(id).hidden = true; return; }
    }
  });

  // Re-check immediately when the tab regains focus.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && !$("#app").hidden) loadLinks();
  });

  checkAuthAndStart().catch((e) => {
    if (!onApiError(e)) console.error(e);
  });
}

init();
