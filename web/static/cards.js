export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const dur = (s) => { s = Math.floor(s || 0); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60; return h ? `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}` : `${m}:${String(x).padStart(2, "0")}`; };
export const views = (n) => { n = n || 0; return n >= 1e6 ? (n / 1e6).toFixed(1) + "M views" : n >= 1e3 ? (n / 1e3).toFixed(1) + "K views" : `${n} view${n === 1 ? "" : "s"}`; };
export const ago = (iso) => {
  if (!iso) return "";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  for (const [n, name] of [[31536000, "year"], [2592000, "month"], [604800, "week"], [86400, "day"], [3600, "hour"], [60, "minute"]]) {
    if (s >= n) { const k = Math.floor(s / n); return `${k} ${name}${k > 1 ? "s" : ""} ago`; }
  }
  return "just now";
};
export const ic = (n, c = "") => `<svg class="ic ${c}" aria-hidden="true" focusable="false"><use href="#i-${n}"/></svg>`;
export const longCard = (v) => `<a class="card" href="${esc(v.urls.page)}"><div class="thumb"><img src="/thumb/${esc(v.id)}.jpg" width="640" height="360" loading="lazy" decoding="async" alt="">${v.premium ? `<span class="badge prem">${ic("crown")} PREMIUM</span>` : v.quality ? `<span class="badge">${esc(v.quality)}</span>` : ""}${v.dur ? `<span class="dur">${dur(v.dur)}</span>` : ""}<span class="hover-play">${ic("play")}</span></div><h3>${esc(v.title)}</h3><p>${views(v.views)}${v.added ? " · " + ago(v.added) : ""}</p></a>`;
export const shortCard = (v) => `<a class="scard" href="/shorts/${esc(v.id)}"><img src="/thumb/${esc(v.id)}.jpg" width="360" height="640" loading="lazy" decoding="async" alt="">${v.premium ? `<span class="badge prem">${ic("crown")}</span>` : ""}<span class="play" aria-hidden="true">${ic("play")}</span><span class="cap"><b>${esc(v.title)}</b><i>${views(v.views)}</i></span></a>`;
export const card = (v) => (v.kind === "short" ? shortCard(v) : longCard(v));
export const skeletons = (n = 4) => Array.from({ length: n }, () => '<div class="skeleton" data-sk></div>').join("");
