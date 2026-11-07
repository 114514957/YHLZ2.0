/* 翻唱工作站（2026-11-07）：上传 → /sing → 轮询 /sing/status → 成品库 */
(() => {
  const $ = (id) => document.getElementById(id);
  const fmt = (s) => {
    s = Math.max(0, Math.round(s));
    return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  };
  let file = null;
  let timer = null;
  let poller = null;

  /* 主题 */
  const theme = (() => { try { return localStorage.getItem("yh.theme") || "dark"; } catch (e) { return "dark"; } })();
  document.body.dataset.theme = theme;
  $("themeBtn").textContent = theme === "light" ? "☾" : "◐";
  $("themeBtn").addEventListener("click", () => {
    const t = document.body.dataset.theme === "light" ? "dark" : "light";
    document.body.dataset.theme = t;
    $("themeBtn").textContent = t === "light" ? "☾" : "◐";
    try { localStorage.setItem("yh.theme", t); } catch (e) {}
  });

  /* 选文件 */
  function pick(f) {
    if (!f) return;
    file = f;
    $("fileName").textContent = `${f.name} · ${(f.size / 1048576).toFixed(1)} MB`;
    $("startBtn").disabled = false;
    $("audioOrig").src = URL.createObjectURL(f);
  }
  $("file").addEventListener("change", (e) => pick(e.target.files[0]));
  const drop = $("drop");
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => {
    e.preventDefault(); drop.classList.add("over");
  }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => {
    e.preventDefault(); drop.classList.remove("over");
    if (ev === "drop" && e.dataTransfer.files.length) pick(e.dataTransfer.files[0]);
  }));

  function setStep(idx, done = false) {
    document.querySelectorAll("#steps li").forEach((li, i) => {
      li.classList.toggle("on", idx >= 0 && !done && i === idx);
      li.classList.toggle("done", done || (idx >= 0 && i < idx));
    });
  }

  async function upload() {
    const r = await fetch("/sing/upload?name=" + encodeURIComponent(file.name), {
      method: "POST", body: file,
    });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || "上传失败");
    return j.path;
  }

  async function start() {
    if (!file) return;
    $("startBtn").disabled = true;
    $("msg").textContent = "";
    $("stageTitle").textContent = "上传中…";
    try {
      const path = await upload();
      $("stageTitle").textContent = "启动中…";
      const r = await fetch("/sing", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target: path, voice: $("voice").value, presets: $("preset").value }),
      });
      const j = await r.json();
      if (!j.ok) {
        $("msg").textContent = j.error || "启动失败";
        $("startBtn").disabled = false;
        return;
      }
      $("jobState").className = "pill running";
      $("jobState").textContent = "运行中";
      setStep(1);
      poll();
    } catch (e) {
      $("msg").textContent = String(e.message || e);
      $("startBtn").disabled = false;
    }
  }
  $("startBtn").addEventListener("click", start);

  function tick(started) {
    if (timer) clearInterval(timer);
    const upd = () => {
      const el = started ? (Date.now() / 1000 - started) : 0;
      $("jobTime").textContent = fmt(el);
      $("stageTimer").textContent = fmt(el);
      const pct = Math.min(92, (el / 420) * 100);
      const bar = $("bar");
      if (bar.dataset.done !== "1") bar.style.width = pct.toFixed(1) + "%";
    };
    upd();
    timer = setInterval(upd, 1000);
  }

  function stageFromLog(log) {
    if (log.includes('"S4-S6"')) return 6;
    if (log.includes('"S3"')) return 4;
    if (log.includes('"S2"')) return 2;
    if (log.includes('"S1"')) return 1;
    return 1;
  }

  async function poll() {
    if (poller) clearTimeout(poller);
    let s;
    try {
      s = await (await fetch("/sing/status", { cache: "no-store" })).json();
    } catch (e) {
      poller = setTimeout(poll, 2500);
      return;
    }
    const st = String(s.status || "idle");
    $("jobState").className = "pill " + (st === "running" ? "running" : st === "done" ? "done" : st === "error" ? "error" : "idle");
    $("jobState").textContent = st === "running" ? "运行中" : st === "done" ? "完成" : st === "error" ? "失败" : "空闲";
    $("stageTitle").textContent = s.step || "等待开始";
    $("log").textContent = (s.log || "").trim() || "还没有任务。";
    if (s.sep) $("sepLine").textContent = "分轨链：" + s.sep;

    if (st === "running") {
      tick(s.started);
      setStep(stageFromLog(String(s.log || "")));
      poller = setTimeout(poll, 2500);
    } else if (st === "done") {
      if (timer) { clearInterval(timer); timer = null; }
      $("bar").dataset.done = "1";
      $("bar").style.width = "100%";
      setStep(7, true);
      $("resultLine").textContent = "成品：" + (s.result || "已生成");
      if (s.result) {
        const id = await findSongId(s.result);
        if (id) {
          $("audioOut").preload = "metadata";
          $("audioOut").src = "/songs/audio?id=" + encodeURIComponent(id);
        }
      }
      $("startBtn").disabled = !file;
      $("jobTime").textContent = fmt((s.finished || Date.now() / 1000) - (s.started || 0));
      $("stageTimer").textContent = $("jobTime").textContent;
      refreshSongs();
    } else if (st === "error") {
      if (timer) { clearInterval(timer); timer = null; }
      $("msg").textContent = s.error || "任务失败";
      $("startBtn").disabled = !file;
    } else {
      $("startBtn").disabled = !file;
      setStep(-1);
    }
  }

  async function findSongId(finalPath) {
    try {
      const j = await (await fetch("/songs", { cache: "no-store" })).json();
      const items = j.items || [];
      const name = String(finalPath).split(/[\\/]/).pop();
      const hit = items.find((it) => String(it.path || "").endsWith(name));
      return hit ? hit.id : (items[0] && items[0].id);
    } catch (e) { return ""; }
  }

  async function refreshSongs() {
    const box = $("songs");
    try {
      const j = await (await fetch("/songs", { cache: "no-store" })).json();
      const items = (j.items || []).filter((it) =>
        String(it.source || "").includes("cover") ||
        (it.tags || []).includes("翻唱") ||
        String(it.title || "").includes("翻唱"));
      if (!items.length) { box.innerHTML = '<div class="empty">还没有翻唱成品</div>'; return; }
      box.innerHTML = "";
      items.slice(0, 30).forEach((it) => {
        const row = document.createElement("div");
        row.className = "song";
        const t = document.createElement("div");
        t.className = "t";
        const b = document.createElement("b");
        b.textContent = it.title || it.id;
        const sp = document.createElement("span");
        const dt = it.created ? new Date(it.created * 1000).toLocaleString() : "";
        sp.textContent = [dt, it.source || ""].filter(Boolean).join(" · ");
        t.appendChild(b); t.appendChild(sp);
        const play = document.createElement("button");
        play.className = "ghost"; play.textContent = "试听";
        play.onclick = () => {
          $("audioOut").src = "/songs/audio?id=" + encodeURIComponent(it.id);
          $("audioOut").play().catch(() => {});
        };
        const tag = document.createElement("span");
        tag.className = "tag"; tag.textContent = "翻唱";
        row.appendChild(t); row.appendChild(tag); row.appendChild(play);
        box.appendChild(row);
      });
    } catch (e) {
      box.innerHTML = '<div class="empty">成品库读取失败</div>';
    }
  }
  $("refreshSongs").addEventListener("click", refreshSongs);

  poll();
  refreshSongs();
})();
