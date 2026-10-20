import { esc, ic } from "./cards.js";
import { api, toast } from "./social.js";
const $ = (s) => document.querySelector(s);
const A = (p, o) => api("/admin" + p, o);
const j = (o) => JSON.stringify(o);
let q = "", filt = "", page = 1, shown = {};
const msg = (t) => ($("#a-msg").textContent = t);

// ---- login: ID + password, then the code sent to Telegram -------------------------------
let challenge = "";
$("#a-login")?.addEventListener("submit", async (e) => {
  e.preventDefault(); msg("");
  try { challenge = (await A("/auth/start", { method: "POST", body: j({ id: e.target.id.value, password: e.target.password.value }) })).challenge; e.target.hidden = true; $("#a-code").hidden = false; msg("A code was sent to your Telegram. It is valid for 5 minutes."); }
  catch (err) { msg(err.message); }
});
$("#a-code")?.addEventListener("submit", async (e) => {
  e.preventDefault(); msg("");
  try { await A("/auth/verify", { method: "POST", body: j({ challenge, code: e.target.code.value }) }); location.reload(); }
  catch (err) { msg(err.message); }
});
$("#a-logout")?.addEventListener("click", async () => { await A("/logout", { method: "POST" }).catch(() => {}); location.reload(); });

// ---- tabs ---------------------------------------------------------------------------------
document.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll("[data-tab]").forEach((x) => x.setAttribute("aria-current", x === b ? "true" : "false"));
  ["videos", "settings", "users", "audit"].forEach((t) => ($("#tab-" + t).hidden = t !== b.dataset.tab));
  if (b.dataset.tab === "settings") loadConfig(); if (b.dataset.tab === "audit") loadAudit();
}));

async function stats() {
  const s = await A("/stats");
  const names = { files: "Files", videos: "Videos", shorts: "Shorts", longs: "Long", premium_videos: "Premium videos", hidden: "Hidden", accounts: "Accounts", users: "Bot users", premium: "Premium users", banned: "Banned", views: "Views", active_streams: "Streams" };
  $("#stats").innerHTML = Object.entries(names).map(([k, n]) => `<div><b>${s[k] ?? 0}</b><span>${n}</span></div>`).join("");
}

// ---- videos ---------------------------------------------------------------------------------
const row = (v) => `<tr data-id="${esc(v.id)}"><td><input type="checkbox" class="sel" aria-label="Select"></td>
  <td><div class="vcell"><img src="/thumb/${esc(v.id)}.jpg" alt="" loading="lazy"><div><b>${esc(v.title)}</b><div class="muted">${v.tags.map((t) => "#" + esc(t)).join(" ") || "no tags"}</div>
  ${v.premium ? '<span class="tag prem">PREMIUM</span> ' : ""}${v.hidden ? '<span class="tag">hidden</span> ' : ""}${v.ok === false ? '<span class="tag">gone</span>' : ""}</div></div></td>
  <td>${esc(v.kind)}${v.kind_set ? " (set)" : ""}</td><td>${v.views}</td>
  <td><div class="a"><button data-act="edit">Edit</button><button data-act="prem">${v.premium ? "Make free" : "Make premium"}</button><button data-act="thumb">New thumb</button><button data-act="del">Delete</button></div></td></tr>`;
async function list(reset) {
  if (reset) { page = 1; shown = {}; $("#rows").innerHTML = ""; $("#selall").checked = false; bulk(); }
  const d = await A(`/videos?q=${encodeURIComponent(q)}&page=${page}&limit=20${filt ? "&" + filt + "=1" : ""}`);
  d.items.forEach((v) => (shown[v.id] = v));
  $("#rows").insertAdjacentHTML("beforeend", d.items.map(row).join(""));
  $("#amore").hidden = !d.has_more;
}
const selected = () => [...document.querySelectorAll(".sel:checked")].map((c) => c.closest("tr").dataset.id);
function bulk() { const n = selected().length; $("#bulk").hidden = !n; $("#bulk-n").textContent = n + " selected"; }
$("#rows").addEventListener("change", (e) => { if (e.target.classList.contains("sel")) bulk(); });
$("#selall").addEventListener("change", (e) => { document.querySelectorAll(".sel").forEach((c) => (c.checked = e.target.checked)); bulk(); });
$("#asearch").addEventListener("click", () => { q = $("#aq").value.trim(); filt = $("#afilter").value; list(true); });
$("#amore").addEventListener("click", () => { page += 1; list(false); });
$("#bulk").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-bulk]"); if (!b) return;
  let [action, val] = b.dataset.bulk.split(":"), value = val === undefined ? null : val === "1";
  if (action.endsWith("_tag")) { value = prompt("Tag"); if (!value) return; }
  try { const r = await A("/videos/bulk", { method: "POST", body: j({ ids: selected(), action, value }) }); toast(`${r.changed} videos updated`); await stats(); await list(true); } catch (err) { toast(err.message); }
});

const dlg = $("#edit");
let editing = null;
$("#rows").addEventListener("click", async (e) => {
  const b = e.target.closest("button"); if (!b) return;
  const id = b.closest("tr").dataset.id, v = shown[id], act = b.dataset.act;
  try {
    if (act === "edit") {
      editing = id; const f = $("#edit-form");
      f.title.value = v.title; f.tags.value = v.tags.join(", "); f.premium.checked = v.premium; f.hidden.checked = v.hidden; f.kind_set.value = v.kind_set || "";
      dlg.showModal(); return;
    }
    if (act === "prem") await A(`/videos/${id}`, { method: "PATCH", body: j({ premium: !v.premium }) });
    else if (act === "thumb") { const at = prompt("Take the frame at second", "3"); if (at === null) return; await A(`/videos/${id}/thumb`, { method: "POST", body: j({ regenerate: true, at: Number(at) }) }); toast("Thumbnail updated"); }
    else if (act === "del") { if (!confirm("Delete this video record?")) return; const copy = confirm("Also delete the stream copy in the BIN channel?"); await A(`/videos/${id}`, { method: "DELETE", body: j({ stream_copy: copy }) }); }
    await stats(); await list(true);
  } catch (err) { toast(err.message); }
});
$("#edit-form").addEventListener("submit", async (e) => {
  if (e.submitter?.value !== "save") return;
  const f = e.target;
  try {
    await A(`/videos/${editing}`, { method: "PATCH", body: j({ title: f.title.value, tags: f.tags.value, premium: f.premium.checked, hidden: f.hidden.checked, kind_set: f.kind_set.value || null }) });
    toast("Saved"); await list(true);
  } catch (err) { e.preventDefault(); toast(err.message); }
});

// ---- access rules -------------------------------------------------------------------------------
const FIELDS = [
  ["premium_mode", "bool", "Premium mode", "OFF = everything is free for everyone. ON = the rules below apply."],
  ["require_login", "bool", "Website needs login to play", "Visitors must have an account to watch."],
  ["free_watch_per_day", "int", "Free videos to watch per day", "For free users when premium mode is ON. 0 = unlimited."],
  ["free_get_per_day", "int", "Free downloads per day", "Website downloads and bot files. 0 = unlimited."],
  ["new_account_trial_days", "int", "Free premium days for new accounts", "Given when someone creates an account. 0 = none."],
  ["default_new_premium", "bool", "New videos start as premium-only", "Applies to videos indexed from now on."],
];
async function loadConfig() {
  const { config } = await A("/config");
  $("#cfg-form").innerHTML = FIELDS.map(([k, t, label, help]) => t === "bool"
    ? `<label class="check"><input type="checkbox" name="${k}" ${config[k] ? "checked" : ""}> <span><b>${label}</b><br><span class="muted">${help}</span></span></label>`
    : `<label>${label}<input type="number" name="${k}" min="0" max="1000" value="${config[k]}"><span class="muted">${help}</span></label>`).join("") + '<button class="btn" type="submit">Save rules</button>';
}
$("#cfg-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = {}; FIELDS.forEach(([k, t]) => (body[k] = t === "bool" ? e.target[k].checked : Number(e.target[k].value)));
  try { await A("/config", { method: "PUT", body: j(body) }); toast("Saved"); } catch (err) { toast(err.message); }
});

// ---- users ------------------------------------------------------------------------------------------
$("#usearch").addEventListener("click", async () => {
  const v = $("#uq").value.trim(); if (!v) return;
  const { items } = await A(`/users?q=${encodeURIComponent(v)}`);
  const u = items[0];
  $("#ubox").innerHTML = u ? `<div class="card-box"><h2>${esc(u.aid || "no account")} <span class="muted">· Telegram ${u.uid}</span></h2><p>${esc(u.name)} · joined ${u.joined} · ${u.banned ? "BANNED" : "active"} · premium days left: <b>${u.premium_days}</b></p>
    <div class="actions">${[1, 7, 30, 365].map((d) => `<button class="btn ghost sm" data-uact="add" data-d="${d}">+${d} day${d > 1 ? "s" : ""}</button>`).join("")}<button class="btn ghost sm" data-uact="rm">Remove premium</button>
    <button class="btn ghost sm" data-uact="${u.banned ? "unban" : "ban"}">${u.banned ? "Unban" : "Ban"}</button></div></div>` : '<div class="state"><p>No user found.</p></div>';
  $("#ubox").dataset.uid = u ? u.uid : "";
});
$("#ubox").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-uact]"); if (!b) return;
  const uid = $("#ubox").dataset.uid, a = b.dataset.uact;
  try {
    if (a === "add") await A(`/users/${uid}/premium`, { method: "POST", body: j({ days: Number(b.dataset.d) }) });
    else if (a === "rm") await A(`/users/${uid}/premium`, { method: "DELETE" });
    else await A(`/users/${uid}/ban`, { method: "POST", body: j({ ban: a === "ban" }) });
    toast("Done"); $("#usearch").click();
  } catch (err) { toast(err.message); }
});

async function loadAudit() {
  const { items } = await A("/audit");
  $("#arows").innerHTML = items.map((r) => `<tr><td>${esc(r.at)}</td><td>${r.uid}</td><td>${esc(r.action)}</td><td>${esc(r.detail)}</td><td>${esc(r.ip)}</td></tr>`).join("");
}

if ($("#admin").dataset.in === "1") { stats().then(() => list(true)).catch((e) => toast(e.message)); }
