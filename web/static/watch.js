import { card } from "./cards.js";
const $ = (s, r = document) => r.querySelector(s);
const video = $("#player");
const sid = ($("#meta") || {}).dataset?.sid;
const store = { get: (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } }, del: (k) => { try { localStorage.removeItem(k); } catch (e) { /* ignore */ } } };

if (video) {
  if (window.Plyr) {
    video.removeAttribute("controls");
    // eslint-disable-next-line no-new
    new window.Plyr(video, {
      controls: ["play-large", "play", "progress", "current-time", "mute", "volume", "settings", "pip", "fullscreen"],
      settings: ["speed"], speed: { selected: 1, options: [0.5, 0.75, 1, 1.25, 1.5, 2] },
      keyboard: { focused: true, global: true }, captions: { active: false }, resetOnEnd: false,
    });
  }
  const key = "pos:" + sid;
  video.addEventListener("loadedmetadata", () => {
    const p = parseFloat(store.get(key));
    if (p > 5 && p < video.duration - 10) video.currentTime = p;
  });
  let last = 0, counted = false, played = 0;
  video.addEventListener("timeupdate", () => {
    const now = Date.now();
    if (now - last > 2000) { last = now; store.set(key, String(video.currentTime)); }
    if (!counted && video.currentTime > 3) { counted = true; fetch(`/api/v1/videos/${sid}/view`, { method: "POST" }).catch(() => {}); }
  });
  video.addEventListener("ended", () => store.del(key));
} else {
  // browsers cannot play this file: external player buttons first
  const ext = $(".ext");
  const first = $(".actions");
  if (ext && first) first.before(ext);
}

$("#copy")?.addEventListener("click", async (e) => {
  const b = e.currentTarget;
  try { await navigator.clipboard.writeText(b.dataset.url); b.textContent = "Copied"; } catch (err) { prompt("Copy this link", b.dataset.url); }
  setTimeout(() => (b.textContent = "Copy link"), 1500);
});

const ext = $(".ext");
if (ext) {
  const url = new URL(ext.dataset.url, location.href).href, title = ext.dataset.title || "";
  const e = encodeURIComponent;
  ext.querySelector('[data-app="vlc"]').href = `vlc://${url}`;
  ext.querySelector('[data-app="mx"]').href = `intent:${url}#Intent;package=com.mxtech.videoplayer.ad;S.title=${e(title)};end`;
  ext.querySelector('[data-app="playit"]').href = `playit://playerv2/video?url=${e(url)}&title=${e(title)}`;
}

const btn = $("#sugg-more"), list = $("#sugg-list");
btn?.addEventListener("click", async () => {
  const have = [...list.querySelectorAll("a.card")].map((a) => a.getAttribute("href").split("/").pop());
  btn.disabled = true;
  try {
    const r = await fetch(`/api/v1/videos/${btn.dataset.sid}/suggest?limit=12&exclude=${have.concat(btn.dataset.sid).join(",")}`);
    if (!r.ok) throw new Error(r.status);
    const items = (await r.json()).items.filter((v) => !have.includes(v.id));
    if (!items.length) { btn.remove(); return; }
    list.insertAdjacentHTML("beforeend", items.map(card).join(""));
    btn.disabled = false;
  } catch (err) { btn.disabled = false; btn.textContent = "Retry"; }
});
