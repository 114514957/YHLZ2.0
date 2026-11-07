/* 训练工作台 · 仪表盘（2026-11-07）
   只读 /api/state，算 persona56 的最新/最佳/闸门与趋势；不改 app.js。 */
(() => {
  const $ = (id) => document.getElementById(id);
  const HAS = () => $("statLatest") && $("trend");

  function fmtTime(ts) {
    if (!ts) return "—";
    const d = new Date(ts * 1000);
    return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }

  function drawTrend(runs) {
    const cv = $("trend");
    if (!cv) return;
    const dpr = window.devicePixelRatio || 1;
    const w = cv.clientWidth || 320, h = cv.clientHeight || 40;
    cv.width = Math.round(w * dpr);
    cv.height = Math.round(h * dpr);
    const ctx = cv.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    if (!runs.length) return;

    const vals = runs.map((r) => r.ok);
    const lo = Math.max(0, Math.min(...vals) - 2);
    const hi = Math.min(56, Math.max(...vals) + 2);
    const x = (i) => (runs.length === 1 ? w / 2 : 8 + (i * (w - 16)) / (runs.length - 1));
    const y = (v) => h - 6 - ((v - lo) / Math.max(1, hi - lo)) * (h - 12);

    // 网格
    ctx.strokeStyle = "rgba(138,151,168,.18)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, y(lo)); ctx.lineTo(w, y(lo));
    ctx.moveTo(0, y(hi)); ctx.lineTo(w, y(hi));
    ctx.stroke();

    // 折线
    ctx.strokeStyle = "#5aa7ff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    runs.forEach((r, i) => (i ? ctx.lineTo(x(i), y(r.ok)) : ctx.moveTo(x(i), y(r.ok))));
    ctx.stroke();

    // 点
    runs.forEach((r, i) => {
      ctx.beginPath();
      ctx.arc(x(i), y(r.ok), 2.5, 0, Math.PI * 2);
      ctx.fillStyle = r.gate_ok === false ? "#e2564a" : "#46c088";
      ctx.fill();
    });
  }

  async function load() {
    if (!HAS()) return;
    let S;
    try {
      S = await (await fetch("/api/state", { cache: "no-store" })).json();
    } catch (e) {
      return;
    }
    const runs = (S.runs || [])
      .filter((r) => r.suite === "persona56" && r.ok != null && r.total)
      .sort((a, b) => (a.finished_at || 0) - (b.finished_at || 0));

    if (!runs.length) {
      $("statLatest").textContent = "—";
      $("statLatestSub").textContent = "还没有 persona56 记录";
      $("statBest").textContent = "—";
      $("statBestSub").textContent = "—";
      $("statGate").textContent = "—";
      $("statGateSub").textContent = "—";
      drawTrend([]);
      return;
    }

    const latest = runs[runs.length - 1];
    const best = runs.reduce((a, b) => (b.ok > a.ok ? b : a), runs[0]);

    $("statLatest").textContent = `${latest.ok}/${latest.total}`;
    $("statLatestSub").textContent = `${latest.tag || "未命名"} · ${fmtTime(latest.finished_at)}`;

    $("statBest").textContent = `${best.ok}/${best.total}`;
    $("statBestSub").textContent = `${best.tag || "未命名"} · ${fmtTime(best.finished_at)}`;

    const gateOk = latest.gate_ok;
    $("statGate").textContent = gateOk === true ? "✅ 通过" : gateOk === false ? "⛔ 未过" : "—";
    $("statGate").className = "stat-v " + (gateOk === true ? "ok" : gateOk === false ? "bad" : "");
    $("statGateSub").textContent = gateOk === true
      ? "最近一次 persona56 闸门通过"
      : gateOk === false ? "最近一次有闸门题失败" : "最近一次没有闸门标记";

    drawTrend(runs.slice(-12));
  }

  window.addEventListener("resize", () => load());
  load();
  setInterval(load, 15000);
})();
