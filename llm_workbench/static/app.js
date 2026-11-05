'use strict';

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmtSize = (n) => n > 1048576 ? (n / 1048576).toFixed(2) + ' MB' : (n / 1024).toFixed(1) + ' KB';
const fmtTime = (s) => s ? new Date(s * 1000).toLocaleString('zh-CN') : '-';

const S = {
  registry: null, server: null, evalState: null, runs: [],
  sel: null, sysPrompt: '', chatMsgs: [], streaming: false,
  evalFile: null,
};

async function api(path, opt) {
  const r = await fetch(path, opt);
  const txt = await r.text();
  let data = null;
  try { data = txt ? JSON.parse(txt) : null; } catch (e) { data = { raw: txt }; }
  if (!r.ok) throw new Error((data && (data.detail || data.error)) || ('HTTP ' + r.status));
  return data;
}

/* ---------------------------------------------------------------- 状态 */
async function loadState() {
  const st = await api('/api/state');
  S.registry = st.registry;
  S.server = st.server;
  S.evalState = st.eval;
  S.runs = st.runs || [];
  if (!S.sysPrompt) S.sysPrompt = st.system_prompt || '';
  if (!S.sel && S.registry.versions.length) {
    S.sel = (S.registry.versions.find(v => v.serviceable) || S.registry.versions[0]).id;
  }
  // ?ver=v7b 直接定位某个版本（方便贴链接）
  const want = new URLSearchParams(location.search).get('ver');
  if (want) {
    const hit = S.registry.versions.find(v => v.version === want || v.id === want);
    if (hit) S.sel = hit.id;
  }
  renderAll();
  if (S.evalState && S.evalState.running) pollEval();
  applyHash();
}

function renderAll() {
  renderVersions();
  renderVersionCard();
  renderServer();
  renderBase();
  renderRuns();
  fillPorts();
}

function renderVersions() {
  const box = $('verList');
  const vs = S.registry ? S.registry.versions : [];
  $('verCount').textContent = vs.length + ' 个';
  const gg = vs.filter(v => v.kind === 'gguf-lora');
  const ad = vs.filter(v => v.kind === 'adapter');
  let h = '';
  const item = (v) => {
    const badges = [];
    if (v.kind === 'gguf-lora') badges.push('<span class="tag gg">GGUF</span>');
    else badges.push('<span class="tag ad">adapter</span>');
    if (v.integrity && v.integrity.ok === false) badges.push('<span class="tag bad">残缺</span>');
    const label = (v.notes && v.notes.label) || v.version;
    return `<div class="ver ${v.id === S.sel ? 'sel' : ''}" data-id="${esc(v.id)}">
      <span class="nm">${esc(label)}</span>${badges.join('')}
      <span class="sz">${fmtSize(v.size)}</span></div>`;
  };
  if (gg.length) h += '<div class="grp">可服务 · GGUF LoRA</div>' + gg.map(item).join('');
  if (ad.length) h += '<div class="grp">版本档案 · adapter</div>' + ad.map(item).join('');
  box.innerHTML = h || '<div class="empty">没扫到版本</div>';
  box.querySelectorAll('.ver').forEach(el => {
    el.onclick = () => { S.sel = el.dataset.id; renderVersions(); renderVersionCard(); };
  });
}

function currentVersion() {
  return (S.registry && S.registry.versions || []).find(v => v.id === S.sel) || null;
}

function renderVersionCard() {
  const v = currentVersion();
  const box = $('verCard');
  if (!v) { box.innerHTML = '<h3>版本详情</h3><div class="empty">左边选一个版本</div>'; return; }
  const notes = v.notes || {};
  const integ = v.integrity || {};
  const integTxt = v.kind === 'gguf-lora'
    ? '<span class="ok">GGUF 文件（转换产物，完整性由 llama-server 装载时校验）</span>'
    : (integ.ok
      ? `<span class="ok">完整</span> · ${integ.tensors} 张量 · ${integ.expect} 字节自洽`
      : `<span class="bad">不完整：${esc(integ.err || '未知')}</span>`);
  const canServe = v.kind === 'gguf-lora';
  const lb = (S.registry && S.registry.bases) || {};
  const b = v.base || {};
  const baseTxt = b.hint
    ? `${b.hint === 'qat' ? 'QAT 基座' : (b.hint === 'it' ? '普通 it 基座' : esc(b.hint))}
       ${b.local ? '<span class="ok">与当前基座一致</span>'
                 : `<span class="bad">当前基座是「${esc(lb.local_kind || '?')}」——不是它，跑分不作数</span>`}`
    : '<span class="muted">没读到 adapter_config（无训练记录）</span>';
  box.innerHTML = `<h3>版本详情 <span class="muted" style="font-weight:400">${esc(v.id)}</span></h3>
    <div class="kv">
      <div class="k">版本</div><div class="v">${esc(v.version)}${canServe ? '' : ' <span class="muted">（adapter，转 GGUF 后才能服务）</span>'}</div>
      <div class="k">文件</div><div class="v">${esc(v.file)}</div>
      <div class="k">大小</div><div class="v">${v.size.toLocaleString()} 字节 · ${fmtSize(v.size)}</div>
      <div class="k">SHA256</div><div class="v">${esc(v.sha256_16)}…</div>
      <div class="k">修改</div><div class="v">${fmtTime(v.mtime)}</div>
      <div class="k">完整性</div><div class="v">${integTxt}</div>
      <div class="k">训练基座</div><div class="v">${baseTxt}</div>
      <div class="k">可服务</div><div class="v">${canServe ? '<span class="ok">是</span>' : '<span class="warn">否</span>'}</div>
    </div>
    <div class="row" style="margin-top:12px">
      <input id="noteLabel" placeholder="显示名（如 v9t6 · 身份样本136条）" value="${esc(notes.label || '')}" style="flex:1;min-width:200px">
      <input id="noteTags" placeholder="标签，逗号分隔" value="${esc((notes.tags || []).join(','))}" style="width:190px">
    </div>
    <textarea id="noteText" placeholder="备注：这一版改了什么、分数多少、踩了什么坑" style="width:100%;margin-top:8px;height:64px">${esc(notes.note || '')}</textarea>
    <div class="row" style="margin-top:8px">
      <button id="btnNote">保存备注</button>
      ${canServe ? '<button class="primary" id="btnStart2">用这个版本启动</button>' : ''}
      ${v.kind === 'adapter' ? '<button id="btnConvert">转成 GGUF</button>' : ''}
    </div>
    <pre class="log" id="convBox" style="display:none;margin-top:10px"></pre>`;
  $('btnNote').onclick = async () => {
    await api('/api/versions/' + encodeURIComponent(v.version) + '/note', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        label: $('noteLabel').value, note: $('noteText').value,
        tags: $('noteTags').value.split(',').map(s => s.trim()).filter(Boolean),
      }),
    });
    await refreshRegistry();
  };
  if ($('btnStart2')) $('btnStart2').onclick = () => startServer(v.id);
  if ($('btnConvert')) $('btnConvert').onclick = () => convertVersion(v);
}

async function convertVersion(v) {
  const def = 'yuanheng-' + v.version + '-lora.gguf';
  const out = prompt('输出文件名（写到 models/gguf-lora/）', def);
  if (out == null) return;
  const box = $('convBox');
  box.style.display = 'block';
  box.textContent = '启动转换…';
  try {
    await api('/api/convert', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version_id: v.id, out_name: out }),
    });
  } catch (e) {
    box.textContent = '起不来：' + e.message;
    return;
  }
  const t0 = Date.now();
  for (;;) {
    await new Promise(r => setTimeout(r, 2000));
    const st = await api('/api/convert/state');
    box.textContent = `转换 ${v.version} … ${((Date.now() - t0) / 1000).toFixed(0)}s\n\n` +
      (st.log_tail || '');
    box.scrollTop = box.scrollHeight;
    if (!st.running) {
      if (st.ok) {
        box.textContent += '\n\n✅ 转换完成：' + st.out;
        await refreshRegistry();
      } else {
        box.textContent += '\n\n❌ 失败：' + (st.error || '未知');
      }
      break;
    }
  }
}

async function refreshRegistry() {
  S.registry = await api('/api/scan');
  renderVersions(); renderVersionCard(); renderBase();
}

function renderServer() {
  const sv = S.server || {};
  const own = sv.own || {};
  const sp = sv.starting || {};
  const on = !!own.running;
  $('dotSrv').className = 'dot ' + (on ? (own.healthy ? 'on' : 'warn') : (sp.running ? 'warn' : 'off'));
  $('srvTxt').textContent = on
    ? `${own.version || '?'} :${own.port}${own.healthy ? '' : '（无响应）'}`
    : (sp.running ? `启动中 ${String(sp.version || '').split(':').pop()}` : '未启动');
  $('pidTxt').textContent = on ? own.pid : '-';
  $('vram').textContent = sv.gpu_free_mb != null ? sv.gpu_free_mb + ' MB' : 'n/a';

  const ex = sv.externals || [];
  $('externals').innerHTML = ex.length ? ('<div class="muted" style="margin-bottom:6px">外部实例（不是工作台起的）</div>' +
    ex.map(e => `<div class="row" style="margin:4px 0">
      <span class="chip"><span class="dot on"></span>${esc(e.alias || '?')} :${e.port} · pid ${e.pid || '?'}</span>
      <button class="danger" data-port="${e.port}">停掉它</button></div>`).join('')) : '';
  $('externals').querySelectorAll('button[data-port]').forEach(b => {
    b.onclick = () => stopExternal(Number(b.dataset.port));
  });
  if (own.log_tail) {
    $('logTail').style.display = 'block';
    $('logTail').textContent = own.log_tail;
  }
}

function renderBase() {
  const b = (S.registry && S.registry.bases) || {};
  const qat = b.has_qat_weights
    ? '<span class="ok">有</span>'
    : '<span class="warn">没有</span> <span class="muted">（QAT 基座上训的版本在本机跑不了，分数不作数）</span>';
  $('baseInfo').innerHTML = `
    <div class="k">基座 GGUF</div><div class="v">${esc(b.gguf || '缺')}<br><span class="muted">${b.gguf_size ? fmtSize(b.gguf_size) : ''}</span></div>
    <div class="k">基座类型</div><div class="v">${esc(b.local_kind || '?')} <span class="muted">（本机只有这一路）</span></div>
    <div class="k">QAT 权重</div><div class="v">${qat}</div>
    <div class="k">mmproj</div><div class="v">${esc(b.mmproj || '缺')}</div>`;
}

function fillPorts() {
  const sv = S.server || {};
  const own = sv.own || {};
  const opts = [];
  if (own.running && own.healthy) opts.push({ p: own.port, t: `${own.version} :${own.port}（工作台）` });
  (sv.externals || []).forEach(e => opts.push({ p: e.port, t: `${e.alias || '?'} :${e.port}（外部）` }));
  if (!opts.length) opts.push({ p: 8091, t: '8091（未启动）' });
  const html = opts.map(o => `<option value="${o.p}">${esc(o.t)}</option>`).join('');
  for (const id of ['chatPort', 'evalPort']) {
    const sel = $(id); const old = sel.value;
    sel.innerHTML = html;
    if (opts.some(o => String(o.p) === old)) sel.value = old;
  }
}

/* ---------------------------------------------------------------- 服务 */
async function startServer(versionId) {
  if (!versionId) { alert('先选一个 GGUF 版本'); return; }
  const port = Number($('port').value || 8091);
  const ctx = Number($('ctx').value || 8192);
  $('btnStart').disabled = true;
  try {
    await api('/api/server/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version_id: versionId, port, ctx, force: $('force').checked }),
    });
    $('logTail').style.display = 'none';
    $('chatHint').textContent = '启动中（加载 4.8 GB，几十秒）…';
    const t0 = Date.now();
    for (;;) {
      await new Promise(r => setTimeout(r, 1500));
      const st = await api('/api/server/status');
      S.server = st; renderServer(); fillPorts();
      const sp = st.starting || {};
      if (sp.running) {
        $('chatHint').textContent = `加载中 ${((Date.now() - t0) / 1000).toFixed(0)}s…`;
        continue;
      }
      if (sp.error) { alert('启动失败：' + sp.error); break; }
      if (st.own.running) {
        alert(`起来了：:${st.own.port}，pid ${st.own.pid}，加载 ${st.own.load_s}s`);
        break;
      }
      if (Date.now() - t0 > 300000) { alert('等太久了，看看日志'); break; }
    }
  } catch (e) {
    alert('启动失败：' + e.message);
  } finally {
    $('btnStart').disabled = false;
  }
}

async function stopExternal(port) {
  if (!confirm(`要停掉外部实例 :${port} 吗？\n它可能是老爹正在用的，停了就没了。`)) return;
  try {
    const r = await api('/api/server/stop-external', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ port, confirm: true }),
    });
    await refreshServer();
    alert(r.still_up ? `:${port} 还在监听，没停掉` : `已停 :${port}（pid ${r.pid}）`);
  } catch (e) { alert('停失败：' + e.message); }
}

async function refreshServer() {
  S.server = await api('/api/server/status');
  renderServer(); fillPorts();
}

/* ---------------------------------------------------------------- 对话 */
function renderMsgs() {
  const box = $('msgs');
  if (!S.chatMsgs.length) { box.innerHTML = '<div class="empty">先选实例，然后说话</div>'; return; }
  box.innerHTML = S.chatMsgs.map(m => {
    const cls = m.role === 'user' ? 'user' : (m.role === 'system' ? 'sys' : 'assistant');
    const meta = m.meta ? `<span class="meta">${esc(m.meta)}</span>` : '';
    return `<div class="msg ${cls}">${esc(m.content)}${meta}</div>`;
  }).join('');
  box.scrollTop = box.scrollHeight;
}

async function send() {
  if (S.streaming) return;
  const text = $('input').value.trim();
  if (!text) return;
  const port = Number($('chatPort').value);
  $('input').value = '';
  S.chatMsgs.push({ role: 'user', content: text });
  renderMsgs();
  const el = document.createElement('div');
  el.className = 'msg assistant typing';
  el.textContent = '';
  $('msgs').appendChild(el);
  S.streaming = true; $('btnSend').disabled = true;
  $('chatHint').textContent = '生成中…';

  let acc = '';
  try {
    const resp = await fetch('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        port,
        system: $('useSys').checked ? S.sysPrompt : '',
        messages: S.chatMsgs.map(m => ({ role: m.role, content: m.content })),
        temperature: Number($('temp').value || 0.7),
        max_tokens: Number($('maxTok').value || 512),
        tools_enabled: $('useTools').checked,
      }),
    });
    if (!resp.ok) throw new Error('HTTP ' + resp.status + ' ' + (await resp.text()).slice(0, 200));
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    let done = null;
    for (;;) {
      const { value, done: fin } = await reader.read();
      if (fin) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const raw = buf.slice(0, i); buf = buf.slice(i + 2);
        if (!raw.startsWith('data:')) continue;
        let d; try { d = JSON.parse(raw.slice(5).trim()); } catch (e) { continue; }
        if (d.type === 'delta') {
          acc += d.text; el.textContent = acc; $('msgs').scrollTop = $('msgs').scrollHeight;
        } else if (d.type === 'done') {
          done = d;
        } else if (d.type === 'error') {
          throw new Error(d.error);
        }
      }
    }
    el.classList.remove('typing');
    const metaBits = [];
    if (done) {
      if (done.ttft != null) metaBits.push('首字 ' + done.ttft + 's');
      if (done.elapsed != null) metaBits.push('总 ' + done.elapsed + 's');
      if (done.tps != null) metaBits.push(done.tps + ' tok/s');
      if (done.called && done.called.length) metaBits.push('调用: ' + done.called.join(','));
      $('chatHint').textContent = metaBits.join('｜') || '完成';
      const m = document.createElement('span');
      m.className = 'meta'; m.textContent = metaBits.join('｜');
      el.appendChild(m);
    }
    S.chatMsgs.push({ role: 'assistant', content: acc, meta: metaBits.join('｜') });
  } catch (e) {
    el.classList.remove('typing');
    el.classList.add('bad');
    el.textContent = '[错误] ' + e.message;
    $('chatHint').textContent = '出错：' + e.message;
    S.chatMsgs.pop();
  } finally {
    S.streaming = false; $('btnSend').disabled = false;
  }
}

async function saveChat() {
  if (!S.chatMsgs.length) { alert('还没有对话'); return; }
  const v = currentVersion();
  const title = (S.chatMsgs.find(m => m.role === 'user') || {}).content || 'chat';
  const r = await api('/api/chats', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: title.slice(0, 30), version: v ? v.version : '',
      messages: S.chatMsgs, meta: { port: $('chatPort').value },
    }),
  });
  $('chatHint').textContent = '已保存：' + r.file;
}

/* ---------------------------------------------------------------- 评测 */
async function restartForColdEval(port) {
  const own = (S.server && S.server.own) || {};
  if (!own.running || Number(own.port) !== Number(port)) return false;
  $('evalProg').textContent = '重启实例（冷态）…';
  await api('/api/server/stop', { method: 'POST' });
  await api('/api/server/start', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      version_id: own.version, port,
      ctx: Number($('ctx').value || 8192),
    }),
  });
  const t0 = Date.now();
  for (;;) {
    await new Promise(r => setTimeout(r, 1500));
    const st = await api('/api/server/status');
    S.server = st; renderServer(); fillPorts();
    if (!st.starting.running) {
      if (st.starting.error) throw new Error('重启失败：' + st.starting.error);
      break;
    }
    if (Date.now() - t0 > 180000) throw new Error('重启超时');
  }
  return true;
}

async function startEval() {
  const suite = $('suite').value;
  const port = Number($('evalPort').value);
  const body = {
    suite, port,
    tag: $('evalTag').value || 'run',
    max_tokens: Number($('evalMax').value || 300),
    cold: false,
  };
  $('btnEval').disabled = true;
  $('evalResult').innerHTML = '';
  try {
    if ($('evalCold').checked) {
      body.cold = await restartForColdEval(port);
      if (!body.cold) {
        $('evalProg').textContent = '注意：评的是外部实例，不能冷启动——分数可能比冷态低 1 分';
      }
    }
    await api('/api/eval/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    pollEval();
  } catch (e) {
    alert('起不来：' + e.message);
    $('btnEval').disabled = false;
  }
}

async function pollEval() {
  const st = await api('/api/eval/state');
  S.evalState = st;
  const pct = st.total ? Math.round(100 * st.done / st.total) : 0;
  $('evalBar').style.width = pct + '%';
  $('evalProg').textContent = st.running
    ? `跑 ${st.suite}（:${st.port}） ${st.done}/${st.total} 当前 ${st.last_id || ''}`
    : (st.error ? '出错：' + st.error : '—');
  if (st.running) { setTimeout(pollEval, 900); return; }
  $('btnEval').disabled = false;
  if (st.result) {
    renderEvalResult(st.result);
    S.runs = await api('/api/runs');
    renderRuns();
  }
}

function renderEvalResult(d, targetId) {
  const box = $(targetId || 'evalResult');
  const cats = d.by_cat && Object.keys(d.by_cat).length
    ? '<div class="cats">' + Object.entries(d.by_cat).map(([k, v]) =>
      `<div>${esc(k)} <b>${v[0]}/${v[1]}</b></div>`).join('') + '</div>' : '';
  const pct = d.total ? (100 * d.ok / d.total).toFixed(1) : '0';
  const rows = (d.results || []).map(r => {
    const ok = r.ok === true ? '<span class="ok">OK</span>'
      : (r.ok === false ? '<span class="bad">FAIL</span>' : '<span class="muted">—</span>');
    return `<tr class="${r.ok === true ? 'p' : (r.ok === false ? 'f' : '')}">
      <td>${esc(r.id)}</td><td>${esc(r.cat || '')}</td><td>${ok}</td>
      <td>${esc(r.q || '')}</td>
      <td class="ans">${esc(r.answer || '')}${r.called && r.called.length ? '\n→ 工具: ' + esc(r.called.join(',')) : ''}</td>
      <td class="muted">${esc(r.why || '')}${r.error ? ' ' + esc(r.error) : ''}</td></tr>`;
  }).join('');
  const gate = d.gate_ok === false
    ? `<div style="margin:8px 0;padding:8px 12px;border:1px solid #7c302a;background:#3a1714;border-radius:7px">
         <b class="bad">⛔ 安全闸门未过</b>
         <span class="muted">　挂：${esc((d.gate_fail || []).join(','))}　—　这套分不算过（台账 1013/1077）</span></div>`
    : (d.gate_ok === true
      ? `<div style="margin:8px 0"><span class="ok">✔ 安全闸门 过</span>
         <span class="muted">　判据 v${esc(String(d.judge_version || '?'))}</span></div>`
      : '');
  box.innerHTML = `<div class="card">
    <h3>${esc(d.suite || '')} · ${esc(d.tag || '')} · :${d.port || ''}
      ${d.cold === true ? '<span class="tag gg" style="margin-left:6px">冷态</span>'
        : (d.cold === false ? '<span class="tag ad" style="margin-left:6px">热态</span>' : '')}</h3>
    ${d.ok != null ? `<span class="score">${d.ok}/${d.total}（${pct}%）</span>` : `<span class="score">${d.total} 题</span>`}
    ${gate}
    ${cats}
    <div style="margin-top:12px;max-height:520px;overflow:auto">
      <table><thead><tr><th>id</th><th>类</th><th>判</th><th>问</th><th>答</th><th>理由</th></tr></thead>
      <tbody>${rows}</tbody></table>
    </div></div>`;
}

/* ---------------------------------------------------------------- 记录 */
function renderRuns() {
  const box = $('runList');
  if (!S.runs.length) { box.className = 'empty'; box.textContent = '还没有记录'; return; }
  box.className = '';
  box.innerHTML = S.runs.map(r => `<div class="ver" data-file="${esc(r.file)}">
    <span class="nm">${esc(r.tag || r.file)}</span>
    <span class="tag">${esc(r.suite || '')}</span>
    ${r.cold === true ? '<span class="tag gg">冷态</span>' : (r.cold === false ? '<span class="tag ad">热态</span>' : '')}
    ${r.gate_ok === false ? '<span class="tag bad">⛔ 闸门未过</span>' : ''}
    <span class="sz">${r.ok != null ? r.ok + '/' + r.total : r.total + ' 题'} · ${fmtTime(r.finished_at)}</span>
  </div>`).join('');
  box.querySelectorAll('.ver').forEach(el => {
    el.onclick = async () => {
      const d = await api('/api/runs/' + encodeURIComponent(el.dataset.file));
      renderEvalResult(d, 'runDetail');
      location.hash = 'runs';
    };
  });
  fillDiffSelects();
}

/* ---------------------------------------------------------------- 对比 */
function fillDiffSelects() {
  const cand = (S.runs || []).filter(r => r.ok != null && r.suite === 'persona56');
  const html = cand.map(r => `<option value="${esc(r.file)}">${esc(r.tag || r.file)} · ${r.ok}/${r.total} · ${fmtTime(r.finished_at)}</option>`).join('');
  // ?a=<file>&b=<file> 可以直接钉住两条记录
  const q = new URLSearchParams(location.search);
  const wantA = q.get('a'), wantB = q.get('b');
  for (const id of ['diffA', 'diffB']) {
    const sel = $(id); const old = sel.value;
    sel.innerHTML = html || '<option value="">（没有可用于对比的记录）</option>';
    if (cand.some(r => r.file === old)) sel.value = old;
  }
  if (wantA && cand.some(r => r.file === wantA)) $('diffA').value = wantA;
  if (wantB && cand.some(r => r.file === wantB)) $('diffB').value = wantB;
  if (cand.length >= 2 && !$('diffA').value) $('diffA').value = cand[0].file;
  if (cand.length >= 2 && !$('diffB').value) $('diffB').value = cand[1].file;
  $('btnDiff').disabled = cand.length < 2;
}

async function doDiff() {
  const a = $('diffA').value, b = $('diffB').value;
  if (!a || !b) { alert('选两条记录'); return; }
  if (a === b) { alert('两条选的是同一条'); return; }
  try {
    const d = await api(`/api/diff?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
    S.lastDiff = d;
    renderDiff(d);
  } catch (e) { alert('对比失败：' + e.message); }
}

function renderDiff(d) {
  S.lastDiff = d;
  const only = $('diffOnly').checked;
  const rows = (d.items || []).filter(i => !only || i.kind !== 'both_ok');
  const kindTxt = { a_only: 'A 过 / B 没过', b_only: 'B 过 / A 没过', both_fail: '都不过', both_ok: '都过' };
  const trs = rows.map(i => `<tr class="${i.kind === 'a_only' ? 'p' : (i.kind === 'b_only' ? 'f' : '')}">
      <td>${esc(i.id)}</td><td>${esc(i.cat || '')}</td>
      <td class="muted">${kindTxt[i.kind]}</td>
      <td>${esc(i.q || '')}</td>
      <td class="ans">${esc(i.a_answer || '')}${i.a_why ? '\n（' + esc(i.a_why) + '）' : ''}</td>
      <td class="ans">${esc(i.b_answer || '')}${i.b_why ? '\n（' + esc(i.b_why) + '）' : ''}</td>
    </tr>`).join('');
  const cats = (d.cats || []).map(c =>
    `<tr><td>${esc(c.cat)}</td><td>${c.a[0]}/${c.a[1]}</td><td>${c.b[0]}/${c.b[1]}</td>
      <td class="${c.delta > 0 ? 'ok' : (c.delta < 0 ? 'bad' : 'muted')}">${c.delta > 0 ? '+' : ''}${c.delta}</td></tr>`).join('');
  const cold = (r) => r.cold === true ? '冷态' : (r.cold === false ? '热态' : '?');
  $('diffView').innerHTML = `<div class="card">
    <h3>对比 · ${esc(d.a.tag)}（${cold(d.a)}）vs ${esc(d.b.tag)}（${cold(d.b)}）</h3>
    <div class="cats">
      <div>A <b>${d.a.ok}/${d.a.total}</b></div>
      <div>B <b>${d.b.ok}/${d.b.total}</b></div>
      <div>差 <b class="${d.total.delta > 0 ? 'ok' : (d.total.delta < 0 ? 'bad' : '')}">${d.total.delta > 0 ? '+' : ''}${d.total.delta}</b></div>
      <div>只有A过 <b>${d.counts.a_only}</b></div>
      <div>只有B过 <b>${d.counts.b_only}</b></div>
      <div>都不过 <b>${d.counts.both_fail}</b></div>
    </div>
    <table style="margin-top:12px;width:auto">
      <thead><tr><th>类</th><th>A</th><th>B</th><th>差</th></tr></thead><tbody>${cats}</tbody></table>
    <div style="margin-top:12px;max-height:520px;overflow:auto">
      <table><thead><tr><th>id</th><th>类</th><th>判定</th><th>问</th>
        <th>A：${esc(d.a.tag)}</th><th>B：${esc(d.b.tag)}</th></tr></thead>
      <tbody>${trs || '<tr><td colspan="6" class="muted">这两条在这一栏没有差异</td></tr>'}</tbody></table>
    </div>
  </div>`;
}

/* ---------------------------------------------------------------- 深链 */
const TABS = ['overview', 'chat', 'eval', 'runs'];
function activate(tab) {
  document.querySelectorAll('.tab').forEach(x =>
    x.classList.toggle('on', x.dataset.tab === tab));
  document.querySelectorAll('.page').forEach(x =>
    x.classList.toggle('on', x.id === 'pg-' + tab));
  if (tab === 'eval' && $('evalTag').value === 'local') {
    const v = currentVersion();
    if (v) $('evalTag').value = v.version;
  }
  if (tab === 'runs' && S.runs.length && !$('runDetail').innerHTML) {
    api('/api/runs/' + encodeURIComponent(S.runs[0].file))
      .then(d => renderEvalResult(d, 'runDetail')).catch(() => {});
  }
  if (tab === 'runs' && !S.lastDiff) {
    const a = $('diffA').value, b = $('diffB').value;
    if (a && b && a !== b) doDiff();
  }
}
function applyHash() {
  const h = (location.hash || '').replace('#', '');
  activate(TABS.includes(h) ? h : 'overview');
}

/* ---------------------------------------------------------------- 绑定 */
document.querySelectorAll('.tab').forEach(t => {
  t.onclick = () => { location.hash = t.dataset.tab; };
});
$('btnScan').onclick = refreshRegistry;
$('btnStop').onclick = async () => {
  const r = await api('/api/server/stop', { method: 'POST' });
  await refreshServer();
  $('chatHint').textContent = r.stopped ? '已停 pid ' + r.pid : '本来就没跑';
};
$('btnStart').onclick = () => startServer(S.sel);
$('btnSend').onclick = send;
$('input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});
$('btnClearChat').onclick = () => { S.chatMsgs = []; renderMsgs(); $('chatHint').textContent = '—'; };
$('btnSaveChat').onclick = saveChat;
$('btnEval').onclick = startEval;
$('btnDiff').onclick = doDiff;
$('diffOnly').onchange = () => { if (S.lastDiff) renderDiff(S.lastDiff); };
$('btnSys').onclick = () => {
  const v = prompt('系统提示（留空=不带）', S.sysPrompt);
  if (v != null) { S.sysPrompt = v; $('chatHint').textContent = '系统提示 ' + v.length + ' 字'; }
};

loadState().catch(e => alert('工作台加载失败：' + e.message));
window.onhashchange = applyHash;
setInterval(() => { refreshServer().catch(() => {}); }, 8000);
