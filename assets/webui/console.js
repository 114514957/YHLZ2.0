"use strict";
// YHLZ workbench: streaming text + voice dialog + dashboard drawer.
const $ = (id) => document.getElementById(id);
const msgs = $("msgs");
let busy = false;
let stage = "idle";
const bc = "BroadcastChannel" in window ? new BroadcastChannel("yhlz-avatar") : null;
function bcStage(v) { if (bc) { try { bc.postMessage({ stage: v });   } catch (e) {}
}

async function loadGrowth() {
  try {
    const r = await (await fetch("/growth", { cache: "no-store" })).json();
    const ul = $("growthList");
    if (!ul) return;
    ul.innerHTML = "";
    for (const line of (r.items || []).slice(-8)) {
      const li = document.createElement("li");
      li.textContent = line.replace(/^-\s*/, "");
      ul.appendChild(li);
    }
  } catch (e) {}
} }

function setLamp(id, state) {
  const el = $(id);
  el.className = "lamp " + state;
  const txt = state === "ok" ? "daemon 正常" : state === "down" ? "daemon 离线"
    : state === "busy" ? "思考中…" : state === "listening" ? "聆听中…"
    : state === "speaking" ? "说话中…" : "空闲";
  if (id === "l-busy") el.textContent = txt;
}
function setInfo(t) { /* kept minimal; real data lives in dashboard */ }
function setVad(level, speech) {
  const w = Math.min(100, Math.max(2, level * 1400)) + "%";
  const b = $("vadbar");
  b.style.width = w;
  b.classList.toggle("hot", !!speech);
}
let nearBottom = true;
function atBottom() { return msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight < 60; }
function scrollBottom() { msgs.scrollTop = msgs.scrollHeight; }
function follow() {
  if (nearBottom) { scrollBottom(); }
  else { const b = $("toBottom"); if (b) b.style.display = "block"; }
}
function addMsg(role, who, text) {
  const d = document.createElement("div");
  d.className = "msg " + (role === "u" ? "u" : "a");
  const w = document.createElement("div"); w.className = "who"; w.textContent = who;
  const t = document.createElement("div"); t.className = "body"; t.textContent = text;
  d.appendChild(w); d.appendChild(t);
  msgs.appendChild(d);
  follow();
  return t;
}
function busyOn(v) {
  busy = v; $("send").disabled = v; $("voiceBtn").disabled = v;
  $("stopBtn").style.display = v ? "inline-block" : "none";
}
function setStage(v) { stage = v; setLamp("l-busy", v); bcStage(v); }

/* ---------- dashboard drawer ---------- */
$("dashBtn").addEventListener("click", () => $("side").classList.add("open"));
$("dashClose").addEventListener("click", () => $("side").classList.remove("open"));
$("avatarBtn").addEventListener("click", () =>
  window.open("/avatar.html", "yh_avatar",
              "width=560,height=800,resizable=yes,scrollbars=no"));
$("clearBtn").addEventListener("click", async () => {
  if (!confirm("清空当前对话并开新会话？")) return;
  try { await fetch("/reset", { method: "POST" }); } catch (e) {}
  msgs.innerHTML = "";
});

function dot(id, ok) { const d = $(id); d.className = "dot " + (ok ? "ok" : "down"); }
function bar(id, pct) { $(id).style.width = Math.max(0, Math.min(100, pct)) + "%"; }

/* ledger + memory queries */
async function qLedger() {
  const q = $("ledgerQ").value.trim();
  const ul = $("ledgerList");
  ul.innerHTML = "<li>…</li>";
  if (!q) { ul.innerHTML = ""; return; }
  try {
    const r = await (await fetch("/ledger?q=" + encodeURIComponent(q))).json();
    ul.innerHTML = "";
    for (const it of (r.items || [])) {
      const li = document.createElement("li");
      li.innerHTML = "<b>" + it.id + "</b>" + (it.text || "");
      ul.appendChild(li);
    }
    if (!(r.items || []).length) ul.innerHTML = "<li>（台账查无）</li>";
  } catch (e) { ul.innerHTML = "<li>查询失败</li>"; }
}
async function qMem() {
  const q = $("memQ").value.trim();
  const ul = $("memList");
  ul.innerHTML = "<li>…</li>";
  if (!q) { ul.innerHTML = ""; return; }
  try {
    const r = await (await fetch("/mem?q=" + encodeURIComponent(q))).json();
    ul.innerHTML = "";
    for (const it of (r.items || [])) {
      const li = document.createElement("li");
      const _ty = ({ fact: "事实", preference: "偏好", event: "事件",
        decision: "决定" })[it.type] || (it.type ?? "");
      li.textContent = "[" + (it.importance ?? "?") + "|" + _ty + "] " + it.summary;
      ul.appendChild(li);
    }
    if (!(r.items || []).length) ul.innerHTML = "<li>（记忆查无）</li>";
  } catch (e) { ul.innerHTML = "<li>查询失败</li>"; }
}
async function loadLogs() {
  try {
    const r = await (await fetch("/logs", { cache: "no-store" })).json();
    const ul = $("logsList");
    ul.innerHTML = "";
    const logs = (r.logs || []).slice(-8);
    for (const l of logs) {
      const li = document.createElement("li");
      const d = new Date(l.t * 1000);
      li.textContent = d.toTimeString().slice(0, 8) + " " + l.event + (l.detail ? " " + l.detail : "");
      ul.appendChild(li);
    }
  } catch (e) {}
}
$("ledgerBtn").addEventListener("click", qLedger);
$("ledgerQ").addEventListener("keydown", (e) => { if (e.key === "Enter") qLedger(); });
$("memBtn").addEventListener("click", qMem);
$("memQ").addEventListener("keydown", (e) => { if (e.key === "Enter") qMem(); });

async function loadSessions() {
  try {
    const r = await (await fetch("/sessions", { cache: "no-store" })).json();
    const ul = $("sessList");
    ul.innerHTML = "";
    for (const it of (r.items || []).slice(0, 10)) {
      const li = document.createElement("li");
      li.innerHTML = "<b>" + it.name + "</b>";
      const t = document.createElement("div");
      t.textContent = it.turns + "轮 · " + it.title;
      li.appendChild(t);
      li.style.cursor = "pointer";
      li.title = "载入此会话";
      li.addEventListener("click", async () => {
        if (!confirm("载入会话 " + it.name + "？当前对话将先自动存档。")) return;
        const rr = await fetch("/session", { method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: it.name }) });
        const j = await rr.json();
        if (j.ok) { msgs.innerHTML = ""; loadHistory(); alert("已载入 " + it.name); }
        else alert("载入失败 " + (j.error || ""));
      });
      ul.appendChild(li);
    }
    if (!(r.items || []).length) ul.innerHTML = "<li>（暂无档案）</li>";
  } catch (e) {}
}

/* link settings */
async function loadSettings() {
  try {
    const r = await (await fetch("/settings", { cache: "no-store" })).json();
    const s = r.settings || {};
    const dv = $("cf-device");
    dv.innerHTML = "";
    const devs = await (await fetch("/devices", { cache: "no-store" })).json();
    for (const d of (devs.devices || [])) {
      const o = document.createElement("option");
      o.value = d.index; o.textContent = d.index + " " + d.name;
      if (String(d.index) === String(s.device)) o.selected = true;
      dv.appendChild(o);
    }
    $("cf-denoise").value = s.denoise || "rnnoise";
    $("cf-duration").value = String(s.duration || 3);
    $("cf-speaker").value = s.tts_speaker || "Vivian";
    $("cf-speak").checked = s.tts_speak !== false;
    $("cf-ttsmodel").value = s.tts_model || "0.6B";
  } catch (e) {}
}
$("cf-save").addEventListener("click", async () => {
  const body = {
    device: parseInt($("cf-device").value, 10) || 1,
    denoise: $("cf-denoise").value,
    duration: parseFloat($("cf-duration").value) || 3,
    tts_speaker: $("cf-speaker").value,
    tts_speak: $("cf-speak").checked,
    tts_model: $("cf-ttsmodel").value,
  };
  await fetch("/settings", { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  alert("设置已保存并热生效");
});
$("cf-free").addEventListener("click", async () => {
  await fetch("/control", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "release_vram" }) });
  alert("已请求释放 ASR/TTS 显存");
});
$("q-wake").addEventListener("click", async () => {
  const r = await (await fetch("/control", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "napcat_login" }) })).json();
  alert(r.ok ? (r.note || "已唤起 NapCat，请登录元亨号") : ("唤起失败：" + (r.error || "")));
  loadDashboard();
});
async function launch(action, okMsg) {
  const r = await (await fetch("/control", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }) })).json();
  alert(r.ok ? (r.note || okMsg) : ("启动失败：" + (r.error || "")));
}
$("petBtn").addEventListener("click", () => launch("launch_pet", "已启动桌宠"));
$("allBtn").addEventListener("click", () => launch("launch_all", "已启动全家桶"));
async function driveAct(action, id, name) {
  const body = { action, id };
  if (name) body.name = name;
  await fetch("/control", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) });
  loadDashboard();
}
$("driveAdd").addEventListener("click", () => {
  const n = $("driveName").value.trim();
  if (n) { driveAct("drives_add", "", n); $("driveName").value = ""; }
});

async function loadDashboard() {
  try {
    const s = await (await fetch("/state", { cache: "no-store" })).json();
    dot("s-gemma", s.gemma === "ok");
    dot("s-daemon", s.daemon === "ok");
    dot("s-ollama", s.ollama === "ok");
    $("m-turns").textContent = s.history ?? "?";
    $("m-l2").textContent = s.l2 ?? "?";
    $("m-persona").textContent = s.persona ? "有" : "-";
    $("m-stage").textContent = ({ idle: "空闲", busy: "思考中", listening: "聆听中",
      speaking: "说话中" })[stage] || stage;
    const q = s.qq || {};
    if ($("s-qq")) dot("s-qq", !!(q.online && q.bridge));
    $("q-uin").textContent = q.uin ? (q.name ? q.name + " " : "") + q.uin : "-";
    $("q-online").textContent = q.online ? "在线" : "离线";
    $("q-ws").textContent = q.ws ? "已连" : "未连";
    $("q-bridge").textContent = q.bridge ? "运行中" : "未运行";
    const qrWrap = $("qqQrWrap");
    if (qrWrap) {
      if (!q.online) {
        qrWrap.style.display = "block";
        const img = $("qqQr");
        const t = Date.now();
        if (img && (!img.dataset.ts || t - (+img.dataset.ts) > 20000)) {
          img.dataset.ts = t;
          img.onerror = () => { qrWrap.style.display = "none"; };
          img.src = "/qq-qrcode?t=" + t;
        }
      } else {
        qrWrap.style.display = "none";
      }
    }
    const d = s.dev || {};
    const dtag = { idle: "空闲", running: "执行中", awaiting: "待你答复",
                   done: "完成", error: "出错" }[d.status] || d.status || "空闲";
    $("m-dev").textContent = dtag + (d.task && d.status !== "idle" ? "：" + d.task : "");
    const ul = $("drivesList");
    if (ul) {
      ul.innerHTML = "";
      (s.drives || []).forEach((d) => {
        const li = document.createElement("li");
        li.textContent = d.name + "（" + d.category + "·" + d.strength + "） ";
        const b = document.createElement("button");
        b.className = "btn-mini"; b.textContent = "强化";
        b.onclick = () => driveAct("drives_reinforce", d.id);
        const f = document.createElement("button");
        f.className = "btn-mini"; f.textContent = "淡出";
        f.onclick = () => driveAct("drives_fade", d.id);
        li.appendChild(b); li.appendChild(f);
        ul.appendChild(li);
      });
    }
  } catch (e) { dot("s-daemon", false); }
  try {
    const m = await (await fetch("/monitor", { cache: "no-store" })).json();
    if (m.gpu) {
      $("m-gpu").textContent = m.gpu.util + "%";
      $("m-vram").textContent = m.gpu.used_gb + " / " + m.gpu.total_gb + " GB";
      bar("m-gpub", m.gpu.util);
      bar("m-vramb", m.gpu.used_gb / m.gpu.total_gb * 100);
    } else { $("m-gpu").textContent = "n/a"; }
    $("m-cpu").textContent = (m.cpu ?? "?") + "%";
    bar("m-cpub", m.cpu ?? 0);
    $("m-ram").textContent = (m.ram ? m.ram.used_gb + " / " + m.ram.total_gb : "?") + " GB";
    $("m-disk").textContent = (m.disk ? m.disk.used_gb + " / " + m.disk.total_gb : "?") + " GB";
    $("m-work").textContent = "对话链路正常";
    $("m-chain").textContent = "听→识→思→说";
  } catch (e) {}
}

async function streamFetch(path, payload, ev) {
  try {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok) { if (ev.error) ev.error("(请求失败 " + r.status + ")"); return; }
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, i); buf = buf.slice(i + 2);
        for (const ln of frame.split("\n")) {
          if (!ln.startsWith("data:")) continue;
          let e; try { e = JSON.parse(ln.slice(5)); } catch (x) { continue; }
          if (ev[e.type]) ev[e.type](e);
        }
        msgs.scrollTop = msgs.scrollHeight;
      }
    }
  } catch (e) { if (ev.error) ev.error("(连接错误) " + e); }
}

async function talk(text) {
  busyOn(true); setStage("busy");
  const box = addMsg("a", "元亨", "");
  box.classList.add("streaming");
  await streamFetch("/talk", { text }, {
    state: (e) => setStage(e.value),
    delta: (e) => { box.textContent += e.delta || ""; follow(); },
    turn_done: (e) => {
      box.classList.remove("streaming");
      if (e.text) box.textContent = e.text;
      emote(e.text || box.textContent);
    },
    error: (e) => { box.classList.remove("streaming"); box.textContent = "(出错) " + (e.message || ""); },
  });
  busyOn(false); setStage("idle"); loadDashboard();
}

async function emote(answer) {
  if (!answer) return;
  try {
    const r = await fetch("/emotion?text=" + encodeURIComponent(answer.slice(0, 300)));
    const j = await r.json();
    const em = j && j.emotion && j.emotion.emotion;
    if (em && bc) bc.postMessage({ emotion: em,
      confidence: (j.emotion && j.emotion.confidence) || 0 });
  } catch (e) {}
}

async function voice() {
  busyOn(true); setStage("listening"); setVad(0, false);
  let box = null;
  await streamFetch("/voice", { speak: 1 }, {
    level: (e) => setVad(e.value, e.speech),
    state: (e) => setStage(e.value),
    voice_text: (e) => {
      if (e.kind === "user") {
        const last = msgs.lastElementChild;
        if (last) { const t = last.querySelector("div:last-child"); if (t) t.textContent = e.text; }
      }
      if (e.kind === "asr") {
        addMsg("u", "你", "");
        box = addMsg("a", "元亨", "");
      }
    },
    delta: (e) => { if (!box) box = addMsg("a", "元亨", ""); box.textContent += e.delta || ""; },
    turn_done: (e) => { if (e.text && box) box.textContent = e.text; emote(e.text); },
    interrupted: () => { setStage("listening"); },
    voice_done: () => setVad(0, false),
    error: (e) => { const t = addMsg("a", "元亨", ""); t.textContent = "(语音出错) " + (e.message || ""); },
  });
  busyOn(false); setStage("idle"); setVad(0, false); loadDashboard();
}

async function loadHistory() {
  try {
    const h = await (await fetch("/history", { cache: "no-store" })).json();
    if (!h.ok) return;
    for (const m of h.messages || []) {
      if (m.role === "user") addMsg("u", "你", m.content);
      else if (m.role === "assistant") addMsg("a", "元亨", m.content);
    }
    msgs.scrollTop = msgs.scrollHeight;
  } catch (e) {}
}

msgs.addEventListener("scroll", () => {
  nearBottom = atBottom();
  const b = $("toBottom");
  if (b) b.style.display = nearBottom ? "none" : "block";
});
$("toBottom").addEventListener("click", () => {
  scrollBottom(); nearBottom = true; $("toBottom").style.display = "none";
});
$("stopBtn").addEventListener("click", async () => {
  try {
    await fetch("/control", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "cancel_turn", channel: "console" }) });
  } catch (e) {}
});

const _sent = [];
const inp = $("in");
function autoGrow() {
  inp.style.height = "auto";
  inp.style.height = Math.min(140, inp.scrollHeight) + "px";
}
function sendNow() {
  const v = inp.value.trim();
  if (!v || busy) return;
  addMsg("u", "你", v);
  _sent.push(v);
  inp.value = "";
  inp.style.height = "auto";
  localStorage.removeItem("yh_draft");
  talk(v);
}
inp.addEventListener("input", () => {
  autoGrow();
  localStorage.setItem("yh_draft", inp.value);
});
inp.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendNow(); }
  else if (e.key === "ArrowUp" && inp.value === "" && _sent.length) {
    e.preventDefault();
    inp.value = _sent[_sent.length - 1];
    autoGrow();
  }
});
$("talk").addEventListener("submit", (ev) => { ev.preventDefault(); sendNow(); });
$("voiceBtn").addEventListener("click", () => { if (!busy) voice(); });
inp.value = localStorage.getItem("yh_draft") || "";
autoGrow();
inp.focus();

loadHistory();
loadSettings();
loadSessions();
loadDashboard();
loadLogs();
setInterval(() => { loadDashboard(); loadLogs(); loadGrowth(); }, 3000);
window.addEventListener("load", () => {
  setTimeout(() => {
    const b = $("boot");
    if (b) { b.classList.add("hide"); setTimeout(() => { b.remove(); }, 550); }
  }, 900);
});
