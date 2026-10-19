import { card, esc } from "./cards.js";
const $ = (s, r = document) => r.querySelector(s);

// theme toggle
$("#theme")?.addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("theme", next); } catch (e) { /* ignore */ }
});

// live search suggestions (debounce 200 ms, top 6, keyboard up/down/enter)
(function () {
  const input = $("#q"), list = $("#sugg");
  if (!input || !list) return;
  let timer, items = [], sel = -1, ctl;
  const close = () => { list.hidden = true; sel = -1; };
  const paint = () => [...list.children].forEach((li, i) => li.setAttribute("aria-selected", i === sel));
  const go = (it) => { location.href = (it.kind === "short" ? "/shorts/" : "/watch/") + it.id; };
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) return close();
    timer = setTimeout(async () => {
      ctl?.abort(); ctl = new AbortController();
      try {
        const r = await fetch("/api/v1/search/suggest?q=" + encodeURIComponent(q), { signal: ctl.signal });
        if (!r.ok) return close();
        items = (await r.json()).items;
        list.innerHTML = items.map((it) => `<li role="option"><img src="/thumb/${esc(it.id)}.jpg" alt="" width="48" height="32" loading="lazy"><span>${esc(it.title)}</span></li>`).join("");
        [...list.children].forEach((li, i) => li.addEventListener("mousedown", (e) => { e.preventDefault(); go(items[i]); }));
        list.hidden = !items.length; sel = -1;
      } catch (e) { /* aborted */ }
    }, 200);
  });
  input.addEventListener("keydown", (e) => {
    if (list.hidden) return;
    if (e.key === "ArrowDown") { sel = (sel + 1) % items.length; paint(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { sel = (sel - 1 + items.length) % items.length; paint(); e.preventDefault(); }
    else if (e.key === "Enter" && sel >= 0) { e.preventDefault(); go(items[sel]); }
    else if (e.key === "Escape") close();
  });
  input.addEventListener("blur", () => setTimeout(close, 120));
})();

// shorts shelf arrows (768px and wider)
(function () {
  const shelf = $("#shelf");
  if (!shelf) return;
  const l = $(".arrow.left"), r = $(".arrow.right");
  const upd = () => { l.hidden = shelf.scrollLeft < 8; r.hidden = shelf.scrollLeft + shelf.clientWidth >= shelf.scrollWidth - 8; };
  l.addEventListener("click", () => shelf.scrollBy({ left: -shelf.clientWidth * 0.8, behavior: "smooth" }));
  r.addEventListener("click", () => shelf.scrollBy({ left: shelf.clientWidth * 0.8, behavior: "smooth" }));
  shelf.addEventListener("scroll", upd, { passive: true }); addEventListener("resize", upd); upd();
})();

// load more (button or infinite scroll), with skeleton, empty and error states
async function loadPage(holder, target) {
  const sep = holder.dataset.api.includes("?") ? "&" : "?";
  const page = Number(holder.dataset.page) + 1;
  target.insertAdjacentHTML("beforeend", '<div class="skeleton" data-sk></div>'.repeat(3));
  try {
    const r = await fetch(`${holder.dataset.api}${sep}page=${page}&limit=12`);
    if (!r.ok) throw new Error(r.status);
    const data = await r.json();
    target.querySelectorAll("[data-sk]").forEach((n) => n.remove());
    target.insertAdjacentHTML("beforeend", data.items.map(card).join(""));
    holder.dataset.page = page;
    return data.has_more;
  } catch (e) {
    target.querySelectorAll("[data-sk]").forEach((n) => n.remove());
    throw e;
  }
}
const more = $("#more");
if (more) {
  more.addEventListener("click", async () => {
    more.disabled = true;
    try { (await loadPage(more, document.getElementById(more.dataset.target))) ? (more.disabled = false) : more.remove(); }
    catch (e) { more.disabled = false; more.textContent = "Retry"; }
  });
}
const sentinel = $("#sentinel");
if (sentinel && !sentinel.hidden) {
  let busy = false;
  const target = document.getElementById(sentinel.dataset.target);
  const io = new IntersectionObserver(async (entries) => {
    if (busy || !entries.some((e) => e.isIntersecting)) return;
    busy = true;
    try { if (!(await loadPage(sentinel, target))) { io.disconnect(); sentinel.remove(); } }
    catch (e) {
      io.disconnect();
      sentinel.outerHTML = '<div class="more"><button class="btn" id="retry" type="button">Retry</button></div>';
      $("#retry").addEventListener("click", () => location.reload());
    }
    busy = false;
  }, { rootMargin: "600px" });
  io.observe(sentinel);
}
