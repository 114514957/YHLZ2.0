"use strict";
// YHLZ workbench: streaming text + voice dialog.
const $ = (id) => document.getElementById(id);
const msgs = $("msgs");
let busy = false;

function setLamp(id, state) {
  const el = $(id);
  const map = { daemon: "daemon", gemma: "gemma", busy: "空闲" };
  el.className = "lamp " + state;
  if (id === "l-busy") {
    el.textContent = state === "busy" ? "思考中…"
      : state === "listening" ? "聆听中…"
      : state === "speaking" ? "说话中…"
      : "空闲";
  } else {
    const label = map[id] || id;
    el.textContent = state === "ok" ? label + " 正常"
      : state === "down" ? label + " 离线" : label + " " + state;
  }
}
function setInfo(t) { $("l-info").textContent = t; }
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

async function poll() {
  try {
    const s = await (await fetch("/state", { cache: "no-store" })).json();
    setLamp("l-gemma", s.gemma === "ok" ? "ok" : "down");
    setLamp("l-daemon", s.daemon === "ok" ? "ok" : "down");
    setInfo("历史 " + (s.history ?? "?") + " 轮 · L2 " + (s.l2 ?? "?"));
  } catch (e) { setLamp("l-daemon", "down"); }
}

async function streamFetch(path, payload, ev) {
  // ev: {state, delta, turn_done, voice_text, voice_done, level, error}
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
  busyOn(true); setLamp("l-busy", "busy");
  const box = addMsg("a", "元亨", "");
  await streamFetch("/talk", { text }, {
    state: (e) => setLamp("l-busy", e.value),
    delta: (e) => { box.textContent += e.delta || ""; },
    turn_done: (e) => { if (e.text) box.textContent = e.text; },
    error: (e) => { box.textContent = "(出错) " + (e.message || ""); },
  });
  busyOn(false); setLamp("l-busy", "idle"); poll();
}

async function voice() {
  busyOn(true); setLamp("l-busy", "listening"); setVad(0, false);
  addMsg("u", "你", "(语音) 正在聆听…说完停3秒自动断");
  let box = null;
  await streamFetch("/voice", { speak: 1 }, {
    level: (e) => setVad(e.value, e.speech),
    state: (e) => setLamp("l-busy", e.value),
    voice_text: (e) => {
      if (e.kind === "user") {
        // replace the placeholder user line with the heard text
        const last = msgs.lastElementChild;
        if (last) { const t = last.querySelector("div:last-child"); if (t) t.textContent = e.text; }
      }
      if (e.kind === "asr") {
        const t = addMsg("u", "你", "");
        t.textContent = e.text;
        box = addMsg("a", "元亨", "");
      }
    },
    delta: (e) => { if (!box) box = addMsg("a", "元亨", ""); box.textContent += e.delta || ""; },
    turn_done: (e) => { if (e.text && box) box.textContent = e.text; },
    voice_done: () => setVad(0, false),
    error: (e) => {
      const t = addMsg("a", "元亨", ""); t.textContent = "(语音出错) " + (e.message || "");
    },
  });
  busyOn(false); setLamp("l-busy", "idle"); setVad(0, false); poll();
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
  } catch (e) { /* ignore */ }
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
poll();
setInterval(poll, 4000);
