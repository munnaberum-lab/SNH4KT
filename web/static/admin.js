const $ = (s) => document.querySelector(s);
const H = { "X-Requested-With": "fetch", "Content-Type": "application/json" };
const api = async (path, opts = {}) => {
  const r = await fetch("/api/v1/admin" + path, { credentials: "same-origin", headers: H, ...opts });
  if (r.status === 401) { $("#panel").hidden = true; $("#login").hidden = false; throw new Error("login"); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error?.message || r.status);
  return data;
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let page = 1, q = "";

async function stats() {
  const s = await api("/stats");
  const names = { files: "Files", videos: "Videos", shorts: "Shorts", longs: "Long", hidden: "Hidden", users: "Users", premium: "Premium", banned: "Banned", views: "Views", active_streams: "Streams" };
  $("#stats").innerHTML = Object.entries(names).map(([k, n]) => `<div><b>${s[k] ?? 0}</b><span>${n}</span></div>`).join("");
}
function row(v) {
  return `<tr data-id="${esc(v.id)}"><td><div style="display:flex;gap:8px;align-items:center"><img src="/thumb/${esc(v.id)}.jpg" alt="" loading="lazy"><span>${esc(v.title)}${v.hidden ? ' <b class="tag">hidden</b>' : ""}${v.ok === false ? ' <b class="tag">gone</b>' : ""}</span></div></td>
  <td><select data-act="kind" aria-label="Kind"><option value="" ${!v.kind_set ? "selected" : ""}>auto (${esc(v.kind)})</option><option value="short" ${v.kind_set === "short" ? "selected" : ""}>short</option><option value="long" ${v.kind_set === "long" ? "selected" : ""}>long</option></select></td>
  <td>${v.views}</td><td><div class="a"><button data-act="title">Rename</button><button data-act="hide">${v.hidden ? "Unhide" : "Hide"}</button><button data-act="thumb">New thumb</button><button data-act="del">Delete</button></div></td></tr>`;
}
async function list(reset) {
  if (reset) { page = 1; $("#rows").innerHTML = ""; }
  const d = await api(`/videos?q=${encodeURIComponent(q)}&page=${page}&limit=20`);
  $("#rows").insertAdjacentHTML("beforeend", d.items.map(row).join(""));
  $("#amore").hidden = !d.has_more;
}
async function boot() { try { await stats(); await list(true); } catch (e) { /* login shown */ } }

$("#login").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { await api("/login", { method: "POST", body: JSON.stringify({ password: $("#pw").value }) }); $("#login").hidden = true; $("#panel").hidden = false; boot(); }
  catch (err) { $("#login-msg").textContent = err.message; }
});
$("#logout").addEventListener("click", async () => { await api("/logout", { method: "POST" }).catch(() => {}); location.reload(); });
$("#asearch").addEventListener("click", () => { q = $("#aq").value.trim(); list(true); });
$("#amore").addEventListener("click", () => { page += 1; list(false); });
$("#rows").addEventListener("click", async (e) => {
  const b = e.target.closest("button"); if (!b) return;
  const tr = b.closest("tr"), id = tr.dataset.id, act = b.dataset.act;
  try {
    if (act === "title") { const t = prompt("New title"); if (!t) return; await api(`/videos/${id}`, { method: "PATCH", body: JSON.stringify({ title: t }) }); }
    else if (act === "hide") await api(`/videos/${id}`, { method: "PATCH", body: JSON.stringify({ hidden: b.textContent === "Hide" }) });
    else if (act === "thumb") { const at = prompt("Take the frame at second", "3"); if (at === null) return; await api(`/videos/${id}/thumb`, { method: "POST", body: JSON.stringify({ regenerate: true, at: Number(at) }) }); }
    else if (act === "del") { if (!confirm("Delete this video record?")) return; const copy = confirm("Also delete the stream copy in the BIN channel?"); await api(`/videos/${id}`, { method: "DELETE", body: JSON.stringify({ stream_copy: copy }) }); }
    await boot();
  } catch (err) { alert(err.message); }
});
$("#rows").addEventListener("change", async (e) => {
  if (e.target.dataset.act !== "kind") return;
  const id = e.target.closest("tr").dataset.id;
  try { await api(`/videos/${id}`, { method: "PATCH", body: JSON.stringify({ kind_set: e.target.value || null }) }); await boot(); } catch (err) { alert(err.message); }
});
if ($("#admin").dataset.in === "1") boot();
