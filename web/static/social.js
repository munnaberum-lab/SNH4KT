import { esc, ic } from "./cards.js";
export const user = () => document.body.dataset.user || "";
export const bot = () => document.body.dataset.bot || "";
const H = { "X-Requested-With": "fetch", "Content-Type": "application/json" };

export async function api(path, opts = {}) {
  const r = await fetch("/api/v1" + path, { credentials: "same-origin", headers: H, ...opts });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(data.error?.message || r.status); e.code = data.error?.code; e.status = r.status; throw e; }
  return data;
}
export function toast(msg) {
  let t = document.getElementById("toast");
  if (!t) { t = document.createElement("div"); t.id = "toast"; t.className = "toast"; t.setAttribute("role", "status"); document.body.appendChild(t); }
  t.textContent = msg; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), 2200);
}
export function modal(inner) {
  const d = document.createElement("dialog");
  d.className = "modal"; d.innerHTML = inner;
  document.body.appendChild(d);
  d.addEventListener("close", () => d.remove());
  d.addEventListener("click", (e) => { if (e.target === d || e.target.closest("[data-close]")) d.close(); });
  d.showModal();
  return d;
}
export function needLogin(message = "Login to continue") {
  modal(`<div class="form"><h2>${esc(message)}</h2><p class="muted">Likes, playlists and premium need an account. The ID is created in our Telegram bot in a few seconds and also works on this website.</p>
    <div class="actions"><a class="btn" href="/login?next=${encodeURIComponent(location.pathname)}">${ic("user")}<span>Login</span></a>
    <a class="btn ghost" href="https://t.me/${esc(bot())}?start=acct" rel="noopener">${ic("send")}<span>Create account on Telegram</span></a></div>
    <button class="btn ghost" type="button" data-close>Close</button></div>`);
}
function handleAuthError(e) { if (e.status === 401) { needLogin("Please login again"); return true; } return false; }

export async function toggleLike(sid, btn) {
  if (!user()) return needLogin("Login to like videos");
  const want = !btn.classList.contains("on");
  try {
    const r = await api(`/videos/${sid}/like`, { method: "POST", body: JSON.stringify({ like: want }) });
    btn.classList.toggle("on", r.liked); btn.setAttribute("aria-pressed", r.liked);
    const c = btn.querySelector(".lbl") || btn.parentElement.querySelector(".lc");
    if (c) c.textContent = r.likes;
  } catch (e) { if (!handleAuthError(e)) toast(e.message); }
}

export async function openSave(sid) {
  if (!user()) return needLogin("Login to save videos");
  let rows;
  try { rows = (await api(`/me/playlists?video=${sid}`)).items; } catch (e) { if (!handleAuthError(e)) toast(e.message); return; }
  const d = modal(`<div class="form"><h2>Save to playlist</h2><div class="pl-list"></div>
    <form class="pl-new"><input name="name" placeholder="New playlist name" maxlength="60" aria-label="New playlist name"><button class="btn" type="submit">Create</button></form>
    <button class="btn ghost" type="button" data-close>Done</button></div>`);
  const list = d.querySelector(".pl-list");
  const paint = () => {
    list.innerHTML = rows.length ? rows.map((p) => `<label class="check"><input type="checkbox" data-pid="${esc(p.id)}" ${p.has ? "checked" : ""}> ${esc(p.name)} <span class="muted">(${p.count})</span></label>`).join("") : '<p class="muted">No playlists yet. Create your first one below.</p>';
  };
  paint();
  list.addEventListener("change", async (e) => {
    const cb = e.target, pid = cb.dataset.pid;
    try {
      if (cb.checked) await api(`/me/playlists/${pid}/items`, { method: "POST", body: JSON.stringify({ video: sid }) });
      else await api(`/me/playlists/${pid}/items/${sid}`, { method: "DELETE" });
      const p = rows.find((x) => x.id === pid); p.has = cb.checked; p.count += cb.checked ? 1 : -1; paint();
      toast(cb.checked ? "Added to playlist" : "Removed from playlist");
    } catch (err) { cb.checked = !cb.checked; toast(err.message); }
  });
  d.querySelector(".pl-new").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = e.target.name.value.trim(); if (!name) return;
    try {
      const r = await api("/me/playlists", { method: "POST", body: JSON.stringify({ name, video: sid }) });
      rows.unshift({ id: r.id, name, count: 1, has: true }); e.target.reset(); paint(); toast("Playlist created");
    } catch (err) { toast(err.message); }
  });
}

document.addEventListener("click", (e) => {
  const like = e.target.closest("[data-like]"); if (like) { e.preventDefault(); toggleLike(like.dataset.like, like); return; }
  const save = e.target.closest("[data-save]"); if (save) { e.preventDefault(); openSave(save.dataset.save); }
});
