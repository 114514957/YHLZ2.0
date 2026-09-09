"use strict";
// YHLZ workbench M1: streaming text dialog + status lamps.
const $ = (id) => document.getElementById(id);
const msgs = $("msgs");
let busy = false;

function setLamp(id, state) {
  const el = $(id);
  el.className = "lamp " + state;
  const label = { daemon: "daemon", gemma: "gemma", busy: "空闲",
                  info: "info" }[id] || id;
  const txt = { daemon: "daemon", gemma: "gemma", ok: "正常", down: "离线",
                busy: "思考中…", idle: "空闲" }[state] || state;
  el.textContent = (id === "l-busy") ? (state === "busy" ? "思考中…" : "空闲")
                   : (state === "ok" ? label + " 正常"
                      : state === "down" ? label + " 离线"
                      : label + " " + txt);
}
function setInfo(t) { $("l-info").textContent = t; }

function addMsg(role, who, text) {
  const d = document.createElement("div");
  d.className = "msg " + (role === "u" ? "u" : "a");
  d.innerHTML = "";
  const w = document.createElement("div"); w.className = "who"; w.textContent = who;
  d.appendChild(w);
  const t = document.createElement("div"); t.textContent = text;
  d.appendChild(t);
  msgs.appendChild(d);
  msgs.scrollTop = msgs.scrollHeight;
  return { box: d, text: t };
}

async function poll() {
  try {
    const r = await fetch("/state", { cache: "no-store" });
    const s = await r.json();
    if (s.gemma === "ok") setLamp("l-gemma", "ok"); else setLamp("l-gemma", "down");
    setLamp("l-daemon", s.daemon === "ok" ? "ok" : "down");
    setInfo("历史 " + (s.history ?? "?") + " 轮 · L2 " + (s.l2 ?? "?"));
  } catch (e) { setLamp("l-daemon", "down"); }
}

async function talk(text) {
  busy = true; setLamp("l-busy", "busy"); $("send").disabled = true;
  const box = addMsg("a", "元亨", "");
  try {
    const r = await fetch("/talk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!r.ok) { box.text.textContent = "(请求失败 " + r.status + ")"; return; }
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    let acc = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, i); buf = buf.slice(i + 2);
        for (const ln of frame.split("\n")) {
          if (!ln.startsWith("data:")) continue;
          let ev; try { ev = JSON.parse(ln.slice(5)); } catch (e) { continue; }
          if (ev.type === "delta") { acc += ev.delta || ""; box.text.textContent = acc; }
          else if (ev.type === "turn_done") { if (ev.text) { box.text.textContent = ev.text; } }
          else if (ev.type === "error") { box.text.textContent = "(出错) " + (ev.message || ""); }
        }
        msgs.scrollTop = msgs.scrollHeight;
      }
    }
  } catch (e) {
    box.text.textContent = "(连接错误) " + e;
  } finally {
    busy = false; setLamp("l-busy", "idle"); $("send").disabled = false;
    poll();
  }
}

$("talk").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const v = $("in").value.trim();
  if (!v || busy) return;
  addMsg("u", "你", v);
  $("in").value = "";
  talk(v);
});
$("in").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) e.preventDefault(); });

poll();
setInterval(poll, 4000);
