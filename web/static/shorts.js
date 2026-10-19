import { esc, views, ago } from "./cards.js";
const body = document.body, feed = document.getElementById("feed");
const dlPublic = body.dataset.dlPublic === "1";
const batch = Number(body.dataset.batch) || 10;
const store = { get: (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } } };
let muted = store.get("shorts_muted") !== "0";
let items = [], cur = -1, more = true, loading = false, endAdded = false;

const toast = (m) => { const t = document.getElementById("toast"); t.textContent = m; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), 1600); };

function build(v, idx) {
  const ratio = v.w && v.h ? v.w / v.h : 9 / 16;
  const fit = Math.abs(ratio - 9 / 16) / (9 / 16) > 0.08;
  const dl = dlPublic ? `/download/${v.id}` : v.urls.telegram;
  const el = document.createElement("section");
  el.className = "item"; el.dataset.sid = v.id;
  el.innerHTML = `<div class="wrap2"><div class="stage${fit ? " fit" : ""}">
    <div class="backdrop" style="background-image:url('/thumb/${esc(v.id)}.jpg')"></div>
    <img class="poster" src="/thumb/${esc(v.id)}.jpg" alt="" ${idx === 0 ? 'fetchpriority="high"' : 'loading="lazy"'} decoding="async">
    <video playsinline loop muted preload="none"></video>
    <div class="s-top"><button class="rb back" type="button" aria-label="Back">‹</button><b>Shorts</b><button class="rb mute" type="button" aria-label="Mute"></button></div>
    <div class="s-bot"><div class="t" role="button" tabindex="0">${esc(v.title)}</div><div class="m">${views(v.views)}${v.added ? " · " + ago(v.added) : ""}</div></div>
    <div class="bar" role="slider" aria-label="Seek" aria-valuemin="0" aria-valuemax="100"><i></i></div>
    <div class="flash" aria-hidden="true">▶</div><div class="spin"></div>
    <div class="err"><p>This video could not be played.</p><div class="row2"><button class="btn retry" type="button">Retry</button><button class="btn ghost skip" type="button">Skip</button></div></div>
    ${v.playable ? "" : `<div class="dlonly"><a class="btn" href="${esc(dl)}" ${dlPublic ? "download" : ""}>Download only</a></div>`}
  </div>
  <div class="rail">
    <div class="col"><button class="rb share" type="button" aria-label="Share">⤴</button>Share</div>
    <div class="col"><a class="rb" href="${esc(dl)}" ${dlPublic ? "download" : ""} aria-label="Download">⬇</a>Save</div>
    <div class="col"><a class="rb" href="${esc(v.urls.telegram)}" rel="noopener" aria-label="Open in Telegram">✈</a>Telegram</div>
    <div class="col"><button class="rb mute" type="button" aria-label="Mute"></button>Sound</div>
  </div></div>`;
  const it = { v, el, stage: el.querySelector(".stage"), video: el.querySelector("video"), counted: false, i: idx };
  wire(it);
  return it;
}

function wire(it) {
  const { el, video, stage, v } = it;
  const spin = el.querySelector(".spin"), err = el.querySelector(".err"), bar = el.querySelector(".bar"), fill = bar.firstElementChild, flash = el.querySelector(".flash");
  el.querySelector(".back").onclick = () => (history.length > 1 ? history.back() : (location.href = "/"));
  el.querySelectorAll(".mute").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); setMuted(!muted); }));
  el.querySelector(".share").onclick = async () => {
    try { if (navigator.share) await navigator.share({ title: v.title, url: v.urls.page }); else { await navigator.clipboard.writeText(v.urls.page); toast("Link copied"); } }
    catch (e) { /* cancelled */ }
  };
  el.querySelector(".t").onclick = (e) => e.currentTarget.classList.toggle("open");
  stage.addEventListener("click", (e) => {
    if (e.target.closest("button,a,.bar,.t,.err")) return;
    if (!video.getAttribute("src")) return;
    if (video.paused) video.play().catch(() => {}); else video.pause();
    flash.textContent = video.paused ? "❚❚" : "▶";
    flash.classList.remove("on"); void flash.offsetWidth; flash.classList.add("on");
  });
  video.addEventListener("waiting", () => spin.classList.add("on"));
  video.addEventListener("stalled", () => spin.classList.add("on"));
  ["playing", "canplay", "seeked"].forEach((n) => video.addEventListener(n, () => spin.classList.remove("on")));
  video.addEventListener("error", () => { if (video.getAttribute("src")) { spin.classList.remove("on"); err.classList.add("on"); } });
  video.addEventListener("loadedmetadata", () => {
    const r = video.videoWidth / video.videoHeight;
    stage.classList.toggle("fit", Math.abs(r - 9 / 16) / (9 / 16) > 0.08);
  });
  video.addEventListener("timeupdate", () => {
    if (video.duration) fill.style.width = (video.currentTime / video.duration) * 100 + "%";
    if (it.i === cur && video.currentTime >= 1 && items[it.i + 1]) attach(items[it.i + 1]);  // next starts loading after 1 s of play
    if (it.i === cur && !it.counted && video.currentTime >= 2) { it.counted = true; fetch(`/api/v1/videos/${v.id}/view`, { method: "POST" }).catch(() => {}); }
  });
  el.querySelector(".retry").onclick = () => { err.classList.remove("on"); detach(it); attach(it); play(it); };
  el.querySelector(".skip").onclick = () => go(1);
  const seek = (e) => { const r = bar.getBoundingClientRect(); if (video.duration) video.currentTime = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) * video.duration; };
  bar.addEventListener("pointerdown", (e) => { bar.setPointerCapture(e.pointerId); seek(e); bar.onpointermove = seek; });
  bar.addEventListener("pointerup", () => (bar.onpointermove = null));
  bar.addEventListener("pointercancel", () => (bar.onpointermove = null));
  paintMute(el);
}

const paintMute = (root) => root.querySelectorAll(".mute").forEach((b) => { b.textContent = muted ? "🔇" : "🔊"; b.setAttribute("aria-label", muted ? "Unmute" : "Mute"); });
function setMuted(m) {
  muted = m; store.set("shorts_muted", m ? "1" : "0");
  items.forEach((it) => { it.video.muted = muted; paintMute(it.el); });
}
function attach(it) {
  if (!it.v.playable || it.video.getAttribute("src")) return;
  it.video.preload = "auto"; it.video.src = `/stream/${it.v.id}`;
}
function detach(it) {
  if (!it.video.getAttribute("src")) return;
  it.video.pause(); it.video.removeAttribute("src"); it.video.load(); it.video.preload = "none";
  it.el.querySelector(".err").classList.remove("on"); it.el.querySelector(".spin").classList.remove("on");
}
function play(it) {
  it.video.muted = muted;
  const p = it.video.play();
  if (p) p.catch(() => {});
}
function setCurrent(i) {
  if (i === cur || !items[i]) return;
  cur = i;
  items.forEach((it, k) => { if (k !== i) it.video.pause(); if (Math.abs(k - i) > 2) detach(it); });
  const it = items[i];
  attach(it); play(it);
  history.replaceState(null, "", `/shorts/${it.v.id}`);
  document.title = `${it.v.title} · Shorts`;
  if (i >= items.length - 3) loadMore();
}
function go(d) {
  const target = d > 0 ? (items[cur + 1]?.el || feed.querySelector(".item.end")) : items[cur - 1]?.el;
  target?.scrollIntoView({ behavior: "smooth" });
}

const io = new IntersectionObserver((entries) => {
  entries.forEach((e) => { if (e.isIntersecting && e.intersectionRatio >= 0.65) setCurrent(items.findIndex((it) => it.el === e.target)); });
}, { root: feed, threshold: [0.65] });

function add(list) {
  list.forEach((v) => {
    if (items.some((it) => it.v.id === v.id)) return;
    const it = build(v, items.length);
    items.push(it);
    const end = feed.querySelector(".item.end");
    end ? feed.insertBefore(it.el, end) : feed.appendChild(it.el);
    io.observe(it.el);
  });
}
function addEnd(message) {
  if (endAdded) return; endAdded = true;
  const el = document.createElement("section");
  el.className = "item end";
  el.innerHTML = `<div><h2>${esc(message)}</h2><a href="/long">Watch long videos</a></div>`;
  feed.appendChild(el);
}
async function getJSON(url) { const r = await fetch(url); if (!r.ok) throw new Error(r.status); return r.json(); }

async function loadMore() {
  if (loading || !more) return;
  loading = true;
  try {
    const after = items.length ? items[items.length - 1].v.id : "";
    const d = await getJSON(`/api/v1/shorts?limit=${batch}${after ? "&after=" + after : ""}`);
    add(d.items);
    if (!d.next) { more = false; addEnd(items.length ? "You are all caught up" : "No shorts yet"); }
  } catch (e) { toast("Could not load more. Scroll to retry."); }
  loading = false;
}

document.addEventListener("keydown", (e) => {
  if (e.target.matches("input,textarea")) return;
  const k = e.key;
  if (k === "ArrowDown" || k === "j" || k === "J") { go(1); e.preventDefault(); }
  else if (k === "ArrowUp" || k === "k" || k === "K") { go(-1); e.preventDefault(); }
  else if (k === " " && items[cur]) { const v = items[cur].video; if (v.getAttribute("src")) { v.paused ? v.play().catch(() => {}) : v.pause(); } e.preventDefault(); }
  else if (k === "m" || k === "M") setMuted(!muted);
});
document.getElementById("next").onclick = () => go(1);
document.getElementById("prev").onclick = () => go(-1);
document.addEventListener("visibilitychange", () => {
  const it = items[cur]; if (!it) return;
  if (document.hidden) it.video.pause(); else play(it);
});

(async function init() {
  const sid = body.dataset.sid;
  if (sid) { try { add([await getJSON(`/api/v1/videos/${sid}`)]); } catch (e) { /* fall back to the feed */ } }
  await loadMore();
  if (!items.length && !endAdded) addEnd("No shorts yet");
})();
