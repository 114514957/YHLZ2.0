"use strict";
// YHLZ workbench: streaming text + voice dialog + dashboard drawer.
const $ = (id) => document.getElementById(id);
const msgs = $("msgs");
let busy = false;
let stage = "idle";

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
function addMsg(role, who, text) {
  const d = document.createElement("div");
  d.className = "msg " + (role === "u" ? "u" : "a");
  const w = document.createElement("div"); w.className = "who"; w.textContent = who;
  const t = document.createElement("div"); t.textContent = text;
  d.appendChild(w); d.appendChild(t);
  msgs.appendChild(d);
  msgs.scrollTop = msgs.scrollHeight;
  return t;
}
function busyOn(v) { busy = v; $("send").disabled = v; $("voiceBtn").disabled = v; }
function setStage(v) { stage = v; setLamp("l-busy", v); }

/* ---------- dashboard drawer ---------- */
$("dashBtn").addEventListener("click", () => $("side").classList.add("open"));
$("dashClose").addEventListener("click", () => $("side").classList.remove("open"));
$("clearBtn").addEventListener("click", async () => {
  if (!confirm("清空当前对话并开新会话？")) return;
  try { await fetch("/reset", { method: "POST" }); } catch (e) {}
  msgs.innerHTML = "";
});

function dot(id, ok) { const d = $(id); d.className = "dot " + (ok ? "ok" : "down"); }
function bar(id, pct) { $(id).style.width = Math.max(0, Math.min(100, pct)) + "%"; }

async function loadDashboard() {
  try {
    const s = await (await fetch("/state", { cache: "no-store" })).json();
    dot("s-gemma", s.gemma === "ok");
    dot("s-daemon", s.daemon === "ok");
    $("m-turns").textContent = s.history ?? "?";
    $("m-l2").textContent = s.l2 ?? "?";
    $("m-persona").textContent = s.persona ? "有" : "-";
    $("m-stage").textContent = stage === "idle" ? "空闲" : stage;
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
  await streamFetch("/talk", { text }, {
    state: (e) => setStage(e.value),
    delta: (e) => { box.textContent += e.delta || ""; },
    turn_done: (e) => { if (e.text) box.textContent = e.text; },
    error: (e) => { box.textContent = "(出错) " + (e.message || ""); },
  });
  busyOn(false); setStage("idle"); loadDashboard();
}

async function voice() {
  busyOn(true); setStage("listening"); setVad(0, false);
  addMsg("u", "你", "(语音) 正在聆听…说完停3秒自动断");
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
    turn_done: (e) => { if (e.text && box) box.textContent = e.text; },
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

$("talk").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const v = $("in").value.trim();
  if (!v || busy) return;
  addMsg("u", "你", v);
  $("in").value = "";
  talk(v);
});
$("voiceBtn").addEventListener("click", () => { if (!busy) voice(); });

loadHistory();
loadDashboard();
setInterval(loadDashboard, 3000);
