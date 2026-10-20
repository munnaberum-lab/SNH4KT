import { card, esc, ic, skeletons } from "./cards.js";
import { api, toast } from "./social.js";
const body = document.getElementById("lib-body");
let tab = "likes";
const tabs = document.querySelectorAll("[data-tab]");
tabs.forEach((b) => b.addEventListener("click", () => { tab = b.dataset.tab; tabs.forEach((x) => x.setAttribute("aria-current", x === b ? "true" : "false")); show(); }));

async function show() { tab === "likes" ? likes() : playlists(); }

async function likes(page = 1, append = false) {
  if (!append) body.innerHTML = `<div class="grid">${skeletons(4)}</div>`;
  try {
    const d = await api(`/me/likes?page=${page}`);
    if (!append) body.innerHTML = d.items.length ? '<div class="grid" id="lgrid"></div><div class="more"></div>' : `<div class="state">${ic("heart", "big")}<p>You have not liked any video yet.</p></div>`;
    const g = document.getElementById("lgrid"); if (!g) return;
    g.insertAdjacentHTML("beforeend", d.items.map(card).join(""));
    const more = body.querySelector(".more"); more.innerHTML = d.has_more ? '<button class="btn ghost" type="button">Show more</button>' : "";
    more.querySelector("button")?.addEventListener("click", () => likes(page + 1, true));
  } catch (e) { body.innerHTML = `<div class="state"><p>${esc(e.message)}</p></div>`; }
}

async function playlists() {
  body.innerHTML = '<div class="state"><p>Loading…</p></div>';
  try {
    const rows = (await api("/me/playlists")).items;
    body.innerHTML = `<form class="pl-new inline" id="newpl"><input name="name" placeholder="New playlist name" maxlength="60" aria-label="Playlist name"><button class="btn" type="submit">${ic("list")}<span>Create</span></button></form>
      <div class="pl-grid">${rows.map((p) => `<button class="pl-card" data-id="${esc(p.id)}" type="button">${ic("list", "big")}<b>${esc(p.name)}</b><span class="muted">${p.count} video${p.count === 1 ? "" : "s"}</span></button>`).join("") || `<div class="state"><p>No playlists yet.</p></div>`}</div>`;
    document.getElementById("newpl").addEventListener("submit", async (e) => {
      e.preventDefault(); const name = e.target.name.value.trim(); if (!name) return;
      try { await api("/me/playlists", { method: "POST", body: JSON.stringify({ name }) }); playlists(); } catch (err) { toast(err.message); }
    });
    body.querySelectorAll(".pl-card").forEach((b) => b.addEventListener("click", () => openPlaylist(b.dataset.id)));
  } catch (e) { body.innerHTML = `<div class="state"><p>${esc(e.message)}</p></div>`; }
}

async function openPlaylist(id) {
  body.innerHTML = `<div class="grid">${skeletons(4)}</div>`;
  try {
    const p = await api(`/me/playlists/${id}`);
    body.innerHTML = `<div class="page-head"><h2>${ic("list")} ${esc(p.name)}</h2><div class="actions"><button class="btn ghost sm" id="back" type="button">${ic("left")}<span>All playlists</span></button><button class="btn ghost sm" id="ren" type="button">Rename</button><button class="btn ghost sm" id="del" type="button">Delete</button></div></div>
      ${p.items.length ? '<div class="grid" id="pgrid"></div>' : `<div class="state"><p>This playlist is empty. Use the Save button on a video.</p></div>`}`;
    const g = document.getElementById("pgrid");
    if (g) p.items.forEach((v) => { const w = document.createElement("div"); w.className = "pl-item"; w.innerHTML = card(v) + `<button class="btn ghost sm rm" type="button" data-sid="${esc(v.id)}">Remove</button>`; g.appendChild(w); });
    document.getElementById("back").onclick = playlists;
    document.getElementById("ren").onclick = async () => { const n = prompt("New name", p.name); if (!n) return; try { await api(`/me/playlists/${id}`, { method: "PATCH", body: JSON.stringify({ name: n }) }); openPlaylist(id); } catch (e) { toast(e.message); } };
    document.getElementById("del").onclick = async () => { if (!confirm("Delete this playlist?")) return; await api(`/me/playlists/${id}`, { method: "DELETE" }); playlists(); };
    g?.addEventListener("click", async (e) => { const b = e.target.closest(".rm"); if (!b) return; await api(`/me/playlists/${id}/items/${b.dataset.sid}`, { method: "DELETE" }); b.closest(".pl-item").remove(); });
  } catch (e) { body.innerHTML = `<div class="state"><p>${esc(e.message)}</p></div>`; }
}
show();
