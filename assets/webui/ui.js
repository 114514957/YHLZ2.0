/* 元亨工作台 v2 —— 只做布局增强，不碰 console.js 的对话/数据逻辑 */
(() => {
  const $ = (id) => document.getElementById(id);
  const qs = (sel, root = document) => root.querySelector(sel);
  const qsa = (sel, root = document) => [...root.querySelectorAll(sel)];

  /* 面板标签 */
  const tabs = qsa("#drawerTabs .tab");
  const panels = qsa(".drawer-body .panel");
  function showPanel(name) {
    tabs.forEach((t) => t.classList.toggle("on", t.dataset.panel === name));
    panels.forEach((p) => p.classList.toggle("on", p.dataset.panel === name));
    try { localStorage.setItem("yh.panel", name); } catch (e) {}
  }
  tabs.forEach((t) => t.addEventListener("click", () => showPanel(t.dataset.panel)));
  const saved = (() => { try { return localStorage.getItem("yh.panel"); } catch (e) { return ""; } })();
  if (saved && tabs.some((t) => t.dataset.panel === saved)) showPanel(saved);

  /* 明暗主题 */
  const themeBtn = $("themeBtn");
  function applyTheme(t) {
    document.body.dataset.theme = t === "light" ? "light" : "dark";
    if (themeBtn) themeBtn.textContent = t === "light" ? "☾" : "◐";
    try { localStorage.setItem("yh.theme", t); } catch (e) {}
  }
  const savedTheme = (() => { try { return localStorage.getItem("yh.theme"); } catch (e) { return ""; } })();
  applyTheme(savedTheme || "dark");
  themeBtn?.addEventListener("click", () => {
    applyTheme(document.body.dataset.theme === "light" ? "dark" : "light");
  });

  /* 抽屉开合（宽屏收起栏 / 窄屏浮层） */
  const side = $("side");
  const scrim = $("drawerScrim");
  const isWide = () => window.matchMedia("(min-width: 1101px)").matches;
  function openDrawer() {
    document.body.classList.remove("drawer-hidden");
    side.classList.add("open");
    scrim.classList.add("show");
  }
  function closeDrawer() {
    if (isWide()) document.body.classList.add("drawer-hidden");
    else closeFloating();
  }
  function closeFloating() {
    side.classList.remove("open");
    scrim.classList.remove("show");
  }
  $("dashBtn")?.addEventListener("click", () => {
    if (!isWide()) return openDrawer();
    document.body.classList.toggle("drawer-hidden");
  });
  $("dashClose")?.addEventListener("click", closeDrawer);
  scrim?.addEventListener("click", closeFloating);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDrawer();
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      if (isWide()) document.body.classList.remove("drawer-hidden");
      else openDrawer();
    }
  });

  /* 顶栏连接状态 */
  const conn = $("conn-hint");
  async function refreshConn() {
    if (!conn) return;
    try {
      const s = await (await fetch("/state", { cache: "no-store" })).json();
      const parts = [];
      parts.push(s.gemma === "ok" ? "Gemma 在线" : "Gemma 离线");
      if (s.qq) parts.push(s.qq.online ? "QQ 在线" : "QQ 离线");
      conn.textContent = parts.join(" · ");
    } catch (e) {
      conn.textContent = "服务未响应";
    }
  }
  refreshConn();
  setInterval(refreshConn, 15000);

  /* 更多菜单 */
  const moreBtn = $("moreBtn");
  const moreMenu = $("moreMenu");
  moreBtn?.addEventListener("click", (e) => {
    e.stopPropagation();
    moreMenu.classList.toggle("open");
  });
  document.addEventListener("click", (e) => {
    if (moreMenu && !moreMenu.contains(e.target) && e.target !== moreBtn) {
      moreMenu.classList.remove("open");
    }
  });

  /* 顶栏状态灯的文案同步到对话标题旁 */
  const lamp = $("l-busy");
  const chatMeta = $("chatMeta");
  function syncMeta() {
    if (!chatMeta || !lamp) return;
    const t = (lamp.textContent || "").trim();
    chatMeta.textContent = t ? `元亨 · ${t}` : "元亨";
  }
  if (lamp && chatMeta) {
    new MutationObserver(syncMeta).observe(lamp, { childList: true, characterData: true, subtree: true });
    syncMeta();
  }

  /* 输入框：Ctrl+Enter 也发送（Enter 由 console.js 处理） */
  const input = $("in");
  input?.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      $("talk")?.requestSubmit();
    }
  });
})();
