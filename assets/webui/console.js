"use strict";
// YH workbench: streaming text + voice dialog + dashboard drawer.
const $ = (id) => document.getElementById(id);
const msgs = $("msgs");
const chat = $("chat");
let busy = false;
let stage = "idle";
const bc = "BroadcastChannel" in window ? new BroadcastChannel("yhlz-avatar") : null;
function bcStage(v) { if (bc) { try { bc.postMessage({ stage: v }); } catch (e) {} } }

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
}

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
function atBottom() { return chat.scrollHeight - chat.scrollTop - chat.clientHeight < 60; }
function scrollBottom() { chat.scrollTop = chat.scrollHeight; }
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
      const b = document.createElement("b");
      b.textContent = it.id;
      li.appendChild(b);
      li.appendChild(document.createTextNode(it.text || ""));
      ul.appendChild(li);
    }
    if (!(r.items || []).length) ul.innerHTML = "<li>（台账查无）</li>";
  } catch (e) { ul.innerHTML = "<li>查询失败</li>"; }
}
function memStatText(lc) {
  if (!lc) return "";
  const bits = ["总 <b>" + lc.items + "</b>", "活跃 <b>" + lc.active + "</b>"];
  if (lc.frozen > 0) bits.push('冻结 <b class="warn">' + lc.frozen + "</b>");
  return "记忆：" + bits.join(" · ");
}
function renderMemStat(r) {
  const el = $("memStat");
  if (!el) return;
  let text = memStatText(r.lifecycle);
  if (r.window && (r.window.start || r.window.end)) {
    text += " · 时间窗 " + (r.window.start || "…") + " ~ " + (r.window.end || "…");
  }
  el.innerHTML = text;
}
async function qMem() {
  const q = $("memQ").value.trim();
  const ul = $("memList");
  const from = ($("memFrom") && $("memFrom").value.trim()) || "";
  const to = ($("memTo") && $("memTo").value.trim()) || "";
  ul.innerHTML = "<li>…</li>";
  try {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (from) params.set("time_start", from);
    if (to) params.set("time_end", to);
    const r = await (await fetch("/mem?" + params.toString(), { cache: "no-store" })).json();
    renderMemStat(r);
    ul.innerHTML = "";
    if (r.ok === false) {
      const li = document.createElement("li");
      li.className = "warn";
      li.textContent = "参数不对：" + (r.error || "未知错误");
      ul.appendChild(li);
      return;
    }
    for (const it of (r.items || [])) {
      const li = document.createElement("li");
      const _ty = ({ fact: "事实", preference: "偏好", event: "事件",
        decision: "决定" })[it.type] || (it.type ?? "");
      let head = "[" + (it.importance ?? "?") + "|" + _ty + "] ";
      if (it.score != null) head = "[" + Number(it.score).toFixed(3) + " " + (it.importance ?? "?") + "|" + _ty + "] ";
      li.textContent = head + it.summary;
      if (it.channels && it.channels.length > 1) {
        const tag = document.createElement("em");
        tag.style.opacity = "0.65";
        tag.textContent = "  ← " + it.channels.join(" + ");
        li.appendChild(tag);
      }
      ul.appendChild(li);
    }
    if (!(r.items || []).length) ul.innerHTML = q ? "<li>（记忆查无）</li>" : "";
  } catch (e) { ul.innerHTML = "<li>查询失败</li>"; }
}
async function memLifecycle() {
  const ul = $("memList");
  try {
    const r = await (await fetch("/mem/lifecycle", { method: "POST" })).json();
    if (r.ok === false) { ul.innerHTML = "<li>维护失败：" + (r.error || "") + "</li>"; return; }
    if (r.enabled === false) { ul.innerHTML = "<li>生命周期维护已关闭（YHLZ_L2_STRENGTH=off）</li>"; return; }
    ul.innerHTML = "<li>维护完成：新冻结 " + (r.frozen ?? 0) + " 条，复活 " + (r.revived ?? 0) +
      " 条，检查 " + (r.checked ?? 0) + " 条</li>";
    await qMem();
  } catch (e) { ul.innerHTML = "<li>维护失败</li>"; }
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
if ($("memMaint")) $("memMaint").addEventListener("click", memLifecycle);
if ($("memFrom")) $("memFrom").addEventListener("keydown", (e) => { if (e.key === "Enter") qMem(); });
if ($("memTo")) $("memTo").addEventListener("keydown", (e) => { if (e.key === "Enter") qMem(); });

async function loadSessions() {
  try {
    const r = await (await fetch("/sessions", { cache: "no-store" })).json();
    const ul = $("sessList");
    ul.innerHTML = "";
    for (const it of (r.items || []).slice(0, 10)) {
      const li = document.createElement("li");
      const b = document.createElement("b");
      b.textContent = it.name;
      li.appendChild(b);
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
    // 8GB 显存只保留 0.6B：旧的 1.7B 设置归一化（ledger 0448）
    $("cf-ttsmodel").value = (s.tts_model === "1.7B" || !s.tts_model)
      ? "0.6B" : s.tts_model;
    // 开发模式（QQ 静默）开关，ledger 0470
    try {
      const dm = await (await fetch("/devmode", { cache: "no-store" })).json();
      $("cf-qqsilent").checked = !!dm.qq_silent;
      if (dm.env) $("cf-qqsilent").title = "已被环境变量 YHLZ_QQ_SILENT 锁定为静默";
    } catch (e) {}
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
$("cf-qqsilent").addEventListener("change", async () => {
  const r = await (await fetch("/devmode", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ qq_silent: $("cf-qqsilent").checked }) })).json();
  if (r.ok) {
    $("cf-qqsilent").checked = !!r.qq_silent;
  } else {
    $("cf-qqsilent").checked = !$("cf-qqsilent").checked;
    alert("切换失败：" + (r.error || ""));
  }
});
$("q-wake").addEventListener("click", async () => {
  const r = await (await fetch("/control", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "napcat_login" }) })).json();
  alert(r.ok ? (r.note || "已唤起 NapCat，请登录元亨号") : ("唤起失败：" + (r.error || "")));
  loadDashboard();
});
async function bridgeAct(action, okMsg) {
  const r = await (await fetch("/control", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }) })).json();
  alert(r.ok ? (r.note || okMsg) : ("操作失败：" + (r.error || "")));
  setTimeout(loadDashboard, 4000);
  setTimeout(loadDashboard, 12000);
}
$("q-start").addEventListener("click", () => bridgeAct("qq_bridge_start", "QQ 桥启动中"));
$("q-restart").addEventListener("click", () => bridgeAct("qq_bridge_restart", "QQ 桥重启中"));
$("q-stop").addEventListener("click", () => bridgeAct("qq_bridge_stop", "QQ 桥已停止自动恢复"));

/* ── 群聊白名单（2026-11-13）─────────────────────────────────
   要求：元亨新加了群，这里要**及时出现**。所以
   · 进页面拉一次，之后每 60 秒自动刷新一次（页面隐藏时暂停）
   · 新出现的群标「新」，并在状态行提示
   · 刷新**不冲掉**你正在勾但还没保存的选择（dirty 时以你的勾选为准）
*/
let qqGroupsCache = [];
let qqKnownIds = null;      // 已知群号集合；null=首次
let qqDirty = false;        // 有未保存的勾选
let qqNewIds = new Set();
function gStatus(t) { const e = $("g-status"); if (e) e.textContent = t; }
function gNote(t) { const e = $("g-note"); if (e) e.textContent = t; }

function gCurrentSel() {
  return new Set(Array.from(document.querySelectorAll('#qqGroups input[type=checkbox]'))
    .filter(c => c.checked).map(c => c.dataset.gid));
}

async function loadQQGroups(opts) {
  const silent = !!(opts && opts.silent);
  if (!silent) gStatus("拉取中…");
  let r;
  try {
    r = await (await fetch("/qq/groups", { cache: "no-store" })).json();
  } catch (e) { gStatus("拉取失败：" + e); return; }
  if (!r.ok) { gStatus("失败：" + (r.error || "未知")); return; }

  const groups = r.groups || [];
  const serverOn = new Set((r.whitelist && r.whitelist.groups) || []);
  const sel = qqDirty ? gCurrentSel() : serverOn;

  // 新群判定（首次不算"新"，只记录）
  qqNewIds = new Set();
  if (qqKnownIds) {
    for (const g of groups) if (!qqKnownIds.has(g.id)) qqNewIds.add(g.id);
  }
  qqKnownIds = new Set(groups.map(g => g.id));

  qqGroupsCache = groups;
  const ul = $("qqGroups");
  ul.innerHTML = "";
  if (!groups.length) ul.innerHTML = '<li style="opacity:.7">没拉到群（可能没登录）</li>';
  for (const g of groups) {
    const li = document.createElement("li");
    li.style.cssText = "display:flex;gap:6px;align-items:center;font-size:12px;padding:2px 0";
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.dataset.gid = g.id; cb.checked = sel.has(g.id);
    cb.addEventListener("change", () => { qqDirty = true; });
    const sp = document.createElement("span");
    sp.textContent = g.name + " · " + g.id + " · " + g.count + "人";
    li.appendChild(cb); li.appendChild(sp);
    if (qqNewIds.has(g.id)) {
      const tag = document.createElement("b");
      tag.textContent = "新";
      tag.style.cssText = "color:#ffcf5c;font-size:11px;border:1px solid #ffcf5c;border-radius:4px;padding:0 3px";
      li.appendChild(tag);
    }
    ul.appendChild(li);
  }

  gNote(serverOn.size ? ("已启用 " + serverOn.size + " 群（其余群不读不回）")
                      : "全不勾＝不限制（所有群都读）");
  const t = new Date().toLocaleTimeString();
  let s = "共 " + groups.length + " 群｜来源 " + ((r.whitelist && r.whitelist.source) || "-") + "｜" + t;
  if (qqNewIds.size) {
    s += "｜⚠ 新加 " + qqNewIds.size + " 群（未在白名单内，她不会读）";
  }
  if (qqDirty) s += "｜有未保存的勾选";
  gStatus(s);
}

async function saveQQWhitelist() {
  const ids = Array.from(gCurrentSel());
  gStatus("保存中…");
  try {
    const r = await (await fetch("/qq/whitelist", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ groups: ids }) })).json();
    if (r.ok) {
      qqDirty = false;
      qqNewIds = new Set();
      gNote((r.groups || []).length
        ? ("已启用 " + r.groups.length + " 群（其余群不读不回）")
        : "全不勾＝不限制（所有群都读）");
      gStatus("已保存 " + (r.groups || []).length + " 群，下一句生效");
      loadQQGroups({ silent: true });
    } else { gStatus("保存失败：" + (r.error || "未知")); }
  } catch (e) { gStatus("保存失败：" + e); }
}

if ($("g-refresh")) $("g-refresh").addEventListener("click", () => loadQQGroups());
if ($("g-save")) $("g-save").addEventListener("click", saveQQWhitelist);
// 自动刷新：60 秒一次；标签页隐藏时不跑，切回来立刻补一次
setInterval(() => { if (!document.hidden && $("qqGroups")) loadQQGroups({ silent: true }); }, 60000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && $("qqGroups")) loadQQGroups({ silent: true });
});

/* ── 提示词分块（2026-11-13）────────────────────────────────
   后端：GET /prompt/blocks、GET /prompt/preview、POST /prompt/set、POST /prompt/reset
   渲染每轮现做，所以保存后下一句生效，不用重启任何服务。
*/
let ptBlocks = [];
function ptInfo(t) { const e = $("pt-info"); if (e) e.textContent = t; }

async function ptLoad(keepKey) {
  try {
    const r = await (await fetch("/prompt/blocks", { cache: "no-store" })).json();
    if (!r.ok) { ptInfo("读取失败：" + (r.error || "")); return; }
    ptBlocks = r.blocks || [];
    const sel = $("pt-block");
    const prev = keepKey || sel.value;
    sel.innerHTML = "";
    for (const b of ptBlocks) {
      const o = document.createElement("option");
      o.value = b.key;
      o.textContent = (b.changed ? "✎ " : "") + b.title + "（" + b.len + "字）";
      sel.appendChild(o);
    }
    if (prev && ptBlocks.some(b => b.key === prev)) sel.value = prev;
    ptInfo("共 " + ptBlocks.length + " 块｜已改 " + (r.count_changed || 0) + " 块");
    ptShow();
  } catch (e) { ptInfo("读取失败：" + e); }
}

function ptShow() {
  const key = $("pt-block").value;
  const b = ptBlocks.find(x => x.key === key);
  if (!b) return;
  $("pt-text").value = b.current || "";
  ptInfo(b.title + "｜" + (b.current || "").length + " 字"
         + (b.changed ? "｜已改（原 " + b.default.length + " 字）" : "｜默认"));
}

async function ptSave(text) {
  const key = $("pt-block").value;
  try {
    const r = await (await fetch("/prompt/set", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key, text }) })).json();
    if (!r.ok) { ptInfo("保存失败：" + (r.error || "")); return; }
    ptInfo(r.reset ? ("已恢复默认：" + key) : ("已保存：" + key + "（下一句生效）"));
    await ptLoad(key);
  } catch (e) { ptInfo("保存失败：" + e); }
}

async function ptPreview(pub) {
  try {
    const r = await (await fetch("/prompt/preview?public=" + (pub ? 1 : 0),
                                 { cache: "no-store" })).json();
    if (!r.ok) { ptInfo("预览失败：" + (r.error || "")); return; }
    const pre = $("pt-preview");
    pre.style.display = "block";
    pre.textContent = r.text;
    ptInfo((pub ? "群聊" : "私聊") + "渲染： " + r.chars + " 字｜约 " + r.approx_tokens + " token");
  } catch (e) { ptInfo("预览失败：" + e); }
}

if ($("pt-block")) {
  $("pt-block").addEventListener("change", ptShow);
  $("pt-reload").addEventListener("click", () => ptLoad());
  $("pt-save").addEventListener("click", () => ptSave($("pt-text").value));
  $("pt-revert").addEventListener("click", () => ptSave(""));
  $("pt-prev-priv").addEventListener("click", () => ptPreview(false));
  $("pt-prev-pub").addEventListener("click", () => ptPreview(true));
  $("pt-reset").addEventListener("click", async () => {
    if (!confirm("清掉所有提示词覆盖，恢复代码默认？")) return;
    const r = await (await fetch("/prompt/reset", { method: "POST" })).json();
    ptInfo(r.ok ? "已全部还原" : ("失败：" + (r.error || "")));
    ptLoad();
  });
  ptLoad();
}

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
      $("m-vram").textContent = m.gpu.used_gb + " / " + m.gpu.total_gb + " GB"
        + (m.gpu.free_gb != null ? "（空闲 " + m.gpu.free_gb + "）" : "");
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

async function streamFetch(path, payload, ev, signal) {
  try {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: signal,
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
        follow();
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

let voiceAbort = null;
async function voice(continuous) {
  if (voiceAbort) { try { voiceAbort.abort(); } catch (e) {} voiceAbort = null; return; }
  voiceAbort = new AbortController();
  busyOn(true); setStage("listening"); setVad(0, false);
  let box = null;
  let userBox = null;
  const ensureUser = () => { if (!userBox) { userBox = addMsg("u", "你", ""); } return userBox; };
  try {
    await streamFetch("/voice", { speak: 1, continuous: continuous ? 1 : 0 }, {
      level: (e) => setVad(e.value, e.speech),
      state: (e) => {
        if (e.value === "listening") { userBox = null; box = null; }
        setStage(e.value);
      },
      partial: (e) => { ensureUser().textContent = e.text || ""; follow(); },
      voice_text: (e) => {
        if (e.kind === "user") { ensureUser().textContent = e.text || ""; userBox = null; }
      },
      delta: (e) => { if (!box) { box = addMsg("a", "元亨", ""); box.classList.add("streaming"); } box.textContent += e.delta || ""; follow(); },
      turn_done: (e) => { if (box) box.classList.remove("streaming"); if (e.text && box) box.textContent = e.text; emote(e.text); },
      interrupted: () => setStage("listening"),
      voice_done: () => setVad(0, false),
      error: (e) => { const t = addMsg("a", "元亨", ""); t.textContent = "(语音出错) " + (e.message || ""); },
    }, voiceAbort.signal);
  } catch (e) {
  } finally {
    voiceAbort = null;
    busyOn(false); setStage("idle"); setVad(0, false); loadDashboard();
    const cb = $("contBtn"); if (cb) cb.classList.remove("on");
  }
}

async function loadHistory() {
  try {
    const h = await (await fetch("/history", { cache: "no-store" })).json();
    if (!h.ok) return;
    for (const m of h.messages || []) {
      if (m.role === "user") addMsg("u", "你", m.content);
      else if (m.role === "assistant") addMsg("a", "元亨", m.content);
    }
    scrollBottom();
  } catch (e) {}
}

chat.addEventListener("scroll", () => {
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
$("voiceBtn").addEventListener("click", () => { if (!busy) voice(false); });
$("contBtn").addEventListener("click", () => {
  if (voiceAbort) { try { voiceAbort.abort(); } catch (e) {} }
  else { $("contBtn").classList.add("on"); voice(true); }
});
inp.value = localStorage.getItem("yh_draft") || "";
autoGrow();
inp.focus();

/* ---------- 对话模式：文本 / 语音 ---------- */
let mode = localStorage.getItem("yh_mode") || "text";
function setMode(m) {
  mode = m;
  localStorage.setItem("yh_mode", m);
  const t = $("talk"), v = $("voiceCtrls");
  if (t) t.style.display = m === "text" ? "flex" : "none";
  if (v) v.style.display = m === "voice" ? "flex" : "none";
  $("modeText").classList.toggle("on", m === "text");
  $("modeVoice").classList.toggle("on", m === "voice");
  if (m === "text") { try { inp.focus(); } catch (e) {} }
}
$("modeText").addEventListener("click", () => {
  if (voiceAbort) { try { voiceAbort.abort(); } catch (e) {} }
  setMode("text");
});
$("modeVoice").addEventListener("click", () => setMode("voice"));
setMode(mode);

loadHistory();
loadSettings();
loadSessions();
loadDashboard();
loadLogs();
qMem();           // 记忆页进来先拉一次状态（总/活跃/冻结），不等查询
loadQQGroups();   // 群聊白名单：进页面拉一次，之后手动刷新
setInterval(() => { loadDashboard(); loadLogs(); loadGrowth(); }, 3000);
window.addEventListener("load", () => {
  setTimeout(() => {
    const b = $("boot");
    if (b) { b.classList.add("hide"); setTimeout(() => { b.remove(); }, 550); }
  }, 900);
});

// ---- singing module (Phase B, ledger 0457) ----
(function () {
  const f = $("sing-file"), go = $("sing-go"), st = $("sing-status"), au = $("sing-audio");
  if (!go) return;
  let timer = null;
  const setSt = (t) => { if (st) st.textContent = t; };
  async function loadSongs() {
    const box = $("songs-list");
    if (!box) return;
    try {
      const j = await (await fetch("/songs")).json();
      box.innerHTML = "";
      const items = j.items || [];
      if (!items.length) { box.textContent = "歌曲库：暂无成品"; return; }
      const label = document.createElement("span");
      label.textContent = "歌曲库：";
      box.appendChild(label);
      for (const s of items) {
        const b = document.createElement("button");
        b.className = "btn-mini";
        b.textContent = "▶ " + (s.title || s.id);
        b.onclick = () => {
          if (au) {
            au.src = "/songs/audio?id=" + encodeURIComponent(s.id);
            au.style.display = "block";
            au.play();
          }
        };
        box.appendChild(b);
      }
    } catch (e) {}
  }
  async function poll() {
    try {
      const s = await (await fetch("/sing/status")).json();
      if (s.status === "running") {
        const el = s.started ? Math.round(Date.now() / 1000 - s.started) : 0;
        setSt("进行中：" + (s.step || "") + "（" + el + "s）");
        if (go) go.disabled = true;
        return true;
      }
      if (timer) { clearInterval(timer); timer = null; }
      if (go) go.disabled = false;
      if (s.status === "done") {
        setSt("完成 ✓（只换干声，和声/伴奏原声；成品+分层已存 翻唱产出/ 并入库）");
        if (au) { au.src = "/sing/result?t=" + Date.now(); au.style.display = "block"; }
        loadSongs();
      } else if (s.status === "error") {
        setSt("失败：" + (s.error || "未知错误"));
      }
      return false;
    } catch (e) { return true; }
  }
  go.addEventListener("click", async () => {
    const file = f && f.files && f.files[0];
    if (!file) { alert("先选一个音频文件（人声/哼唱效果最好）"); return; }
    setSt("上传中…");
    let up;
    try {
      up = await (await fetch("/sing/upload?name=" + encodeURIComponent(file.name),
        { method: "POST", body: file })).json();
    } catch (e) { setSt("上传失败：网络错误"); return; }
    if (!up.ok) { setSt("上传失败：" + (up.error || "")); return; }
    setSt("启动翻唱…");
    let r;
    try {
      const voice = $("sing-voice") ? $("sing-voice").value : "bright";
      r = await (await fetch("/sing", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target: up.path,
                               voice: voice }) })).json();
    } catch (e) { setSt("启动失败：网络错误"); return; }
    if (!r.ok) { setSt("启动失败：" + (r.error || "")); return; }
    if (au) au.style.display = "none";
    if (timer) clearInterval(timer);
    timer = setInterval(poll, 2000); poll();
  });
  poll().then((running) => { if (running && !timer) timer = setInterval(poll, 2000); });
  loadSongs();
})();

// ---- 启动入口：NapCat 面板 + 翻唱链路官方 UI（台账 0792） ----
(function () {
  const nap = $("ln-napcat"), off = $("ln-official");
  const stopB = $("ln-official-stop"), st = $("ln-status");
  const napSt = $("ln-napcat-status");
  if (!nap || !off) return;
  let offState = { status: "idle" };
  const setSt = (t) => { if (st) st.textContent = t; };
  const setNap = (t) => { if (napSt) napSt.textContent = t; };

  nap.addEventListener("click", async () => {
    setNap("NapCat 面板：检查中…");
    let r;
    try {
      r = await (await fetch("/control", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "napcat_ui" }) })).json();
    } catch (e) { setNap("NapCat 面板：网络错误"); return; }
    if (!r.ok) { setNap("NapCat 面板：" + (r.error || "失败")); return; }
    if (r.up) { window.open(r.url, "_blank"); setNap(r.note || "NapCat 面板已打开"); }
    else { setNap(r.note || "NapCat 启动中…"); }
  });

  function renderOff() {
    const s = (offState && offState.status) || "idle";
    if (s === "running") {
      off.textContent = "打开官方UI"; off.disabled = false;
      if (stopB) stopB.style.display = "inline-block";
      setSt("官方UI 运行中：" + (offState.url || "") +
        (offState.attached ? "（接住外部实例）" : "") + "（聊天暂停中）");
    } else if (s === "starting") {
      off.textContent = "启动中…"; off.disabled = true;
      if (stopB) stopB.style.display = "none";
      setSt("官方UI 启动中：" + (offState.step || ""));
    } else if (s === "stopping") {
      off.disabled = true;
      if (stopB) stopB.style.display = "none";
      setSt("官方UI 关闭中（恢复聊天服务）…");
    } else if (s === "error") {
      off.textContent = "重试官方UI"; off.disabled = false;
      if (stopB) stopB.style.display = "none";
      setSt("官方UI 启动失败：" + (offState.error || ""));
    } else {
      off.textContent = "翻唱官方UI"; off.disabled = false;
      if (stopB) stopB.style.display = "none";
      setSt("官方UI 未开启（独占唱窗，启动后聊天暂停）");
    }
  }
  async function pollOff() {
    try {
      offState = await (await fetch("/official-ui/status",
        { cache: "no-store" })).json();
    } catch (e) {}
    renderOff();
  }
  off.addEventListener("click", async () => {
    if (offState.status === "running") {
      window.open(offState.url || "http://127.0.0.1:7861", "_blank");
      return;
    }
    if (offState.status === "starting" || offState.status === "stopping") return;
    off.disabled = true;
    let r;
    try {
      r = await (await fetch("/control", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "official_ui_start" }) })).json();
    } catch (e) { off.disabled = false; setSt("官方UI：网络错误"); return; }
    if (!r.ok) { off.disabled = false; setSt("官方UI 启动失败：" + (r.error || "")); return; }
    setSt("官方UI 启动中…（开唱窗约 1-2 分钟）");
    pollOff();
  });
  if (stopB) stopB.addEventListener("click", async () => {
    if (!confirm("关闭官方UI并把聊天服务拉回来？")) return;
    stopB.disabled = true;
    try {
      const r = await (await fetch("/control", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "official_ui_stop" }) })).json();
      if (!r.ok) alert("关闭失败：" + (r.error || ""));
    } catch (e) {}
    stopB.disabled = false;
    pollOff();
  });
  pollOff();
  setInterval(pollOff, 3000);
})();
