import { api, toast } from "./social.js";
const $ = (s) => document.querySelector(s);
const safe = (p) => (p && p.startsWith("/") && !p.startsWith("//") ? p : "/");
$("#login-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target, msg = $("#login-msg"); msg.textContent = "";
  try { await api("/auth/login", { method: "POST", body: JSON.stringify({ id: f.id.value, password: f.password.value }) }); location.href = safe(f.dataset.next); }
  catch (err) { msg.textContent = err.message; }
});
$("#pw-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target, msg = $("#pw-msg"); msg.textContent = "";
  try { await api("/me/password", { method: "POST", body: JSON.stringify({ current: f.current.value, new: f.new.value }) }); f.reset(); msg.textContent = "Password changed. Other devices were logged out."; msg.classList.add("ok"); }
  catch (err) { msg.classList.remove("ok"); msg.textContent = err.message; }
});
$("#logout")?.addEventListener("click", async () => { await api("/auth/logout", { method: "POST" }).catch(() => {}); location.href = "/"; });
