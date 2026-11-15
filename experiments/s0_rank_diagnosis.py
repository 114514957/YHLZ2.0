# -*- coding: utf-8 -*-
"""S0 · FFN key 有效秩诊断（按《实验设计01》，跑在云 A800）

key = 每层 `mlp.down_proj` 的**输入**（中间维，本模型 10240）。

两遍扫描（重要：协方差必须去均值，否则被常数分量主导成秩 1）：
  第一遍：求每层 key 的均值 μ
  第二遍：累加 (k−μ)(k−μ)ᵀ，得协方差 C

指标：ER（参与比）、stable rank、e90/e99、条件数、谱斜率、前缀余弦、Jaccard。
判据：ER ≥ 0.15d 通过；0.05–0.15d 警告；< 0.05d 失败。
"""
from __future__ import annotations

import argparse
import io
import itertools
import json
import os

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

FACTS = [
    ("元亨是谁",), ("老爹是谁",), ("利贞是谁",), ("大肥鱼是什么",),
    ("台账记什么",), ("v9t10 多少分",), ("训练用什么底座",), ("LoRA 挂在哪些层",),
    ("多少层",), ("隐藏维是多少",), ("FFN 中间维",), ("上下文多长",),
    ("谁管 GPU",), ("怎么跑评测",), ("判据版本",), ("闸门有哪几道",),
]
TEMPLATES = [
    "{q}", "请告诉我：{q}", "你知道{q}吗", "简单说一下，{q}",
    "{q}？", "我想了解{q}", "关于{q}，说重点", "{q}，一句话",
]
FILLER = ["今天天气不错，出去走了走。", "这个项目要一步一步来，别急。",
          "她说话短，但每句都有信息。", "训练的时候要盯着 loss 和显存。",
          "把复杂的东西讲简单，比讲复杂更难。", "出了问题先看原始输出，别先信判分。"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", default="/root/yh/results/s0.json")
    ap.add_argument("--layers", default="")
    ap.add_argument("--max-tokens", type=int, default=50000)
    ap.add_argument("--chunk", type=int, default=64)
    ap.add_argument("--corpus", default="", help="真实语料文件（一行一段），不给就用模板句")
    a = ap.parse_args()

    dev = "cuda"
    tok = AutoTokenizer.from_pretrained(a.base, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        a.base, dtype=torch.bfloat16, device_map={"": 0}, trust_remote_code=True,
        low_cpu_mem_usage=True)
    model.eval()

    layers = model.model.language_model.layers
    n = len(layers)
    want = ([int(x) for x in a.layers.split(",") if x.strip()]
            if a.layers else sorted({0, 4, 8, 12, 16, 20, 24, 28, 32, 36, n - 1}))

    fact_prompts = [[t.format(q=q) for t in TEMPLATES] for (q,) in FACTS]
    prompts = [p for vs in fact_prompts for p in vs]
    if a.corpus:
        import io as _io
        lines = [ln.strip() for ln in _io.open(a.corpus, encoding="utf-8", errors="replace")
                 if len(ln.strip()) > 10]
        prompts = lines
        print("语料文件 %d 段" % len(lines))
    else:
        while len(prompts) < 5000:
            prompts.extend(FILLER)
    print("层 %s｜语料 %d 条｜每层上限 %d token" % (want, len(prompts), a.max_tokens),
          flush=True)

    def batches():
        for s in range(0, len(prompts), a.chunk):
            ids = tok(prompts[s:s + a.chunk], return_tensors="pt", padding=True,
                      truncation=True, max_length=512).to(dev)
            yield ids

    # ── 第一遍：均值 ──
    sumv = {i: None for i in want}
    cnt1 = {i: 0 for i in want}

    def mk_sum(i):
        def hook(_m, inputs):
            x = inputs[0].reshape(-1, inputs[0].shape[-1]).float()
            if sumv[i] is None:
                sumv[i] = torch.zeros(x.shape[-1], dtype=torch.float64, device=x.device)
            sumv[i] += x.double().sum(0)
            cnt1[i] += x.shape[0]
        return hook

    hs = [layers[i].mlp.down_proj.register_forward_pre_hook(mk_sum(i)) for i in want]
    with torch.no_grad():
        for ids in batches():
            model(**ids)
    for h in hs:
        h.remove()
    means = {i: (sumv[i] / max(1, cnt1[i])).float() for i in want}
    print("第一遍完成｜均值范数 %s"
          % {i: round(float(means[i].norm()), 2) for i in want}, flush=True)

    # ── 第二遍：中心化协方差 + 活跃通道 ──
    dim = int(means[want[0]].numel())
    # float64 累加：float32 下 10240² 外积累加 5 万次后，尾巴全是舍入噪声（实测 κ 假到 1e13）
    cov = {i: torch.zeros(dim, dim, dtype=torch.float64, device=dev) for i in want}
    hits = {i: torch.zeros(dim, dtype=torch.float32, device=dev) for i in want}
    cnt2 = {i: 0 for i in want}

    def mk_cov(i):
        def hook(_m, inputs):
            if cnt2[i] >= a.max_tokens:
                return
            x = inputs[0].reshape(-1, inputs[0].shape[-1])
            need = a.max_tokens - cnt2[i]
            if x.shape[0] > need:
                x = x[:need]
            xc = (x - means[i].to(x.dtype)).double()
            cov[i] += xc.t() @ xc
            k = max(1, int(0.05 * dim))
            idx = x.abs().topk(k, dim=-1).indices
            hits[i] += torch.zeros_like(hits[i]).scatter_add_(
                0, idx.reshape(-1), torch.ones(idx.numel(), device=dev))
            cnt2[i] += x.shape[0]
        return hook

    hs = [layers[i].mlp.down_proj.register_forward_pre_hook(mk_cov(i)) for i in want]
    with torch.no_grad():
        for ids in batches():
            model(**ids)
            if all(cnt2[i] >= a.max_tokens for i in want):
                break
    for h in hs:
        h.remove()
    print("第二遍完成｜token %s" % {i: cnt2[i] for i in want}, flush=True)

    res = {"base": a.base, "n_layers": n, "ffn_dim": dim,
           "max_tokens": a.max_tokens, "centered": True, "layers": {}}
    for i in want:
        C = (cov[i] / max(1, cnt2[i] - 1)).double()
        ev = torch.flip(torch.clamp(torch.linalg.eigvalsh(C), min=0.0), [0])
        s1 = ev.sum()
        s2 = (ev ** 2).sum()
        er = float(s1 ** 2 / s2)
        stable = float(s1 / ev[0])
        cs = torch.cumsum(ev, 0) / s1
        e90 = int(torch.searchsorted(cs, torch.tensor(0.90, dtype=cs.dtype,
                                                      device=cs.device)) + 1)
        e99 = int(torch.searchsorted(cs, torch.tensor(0.99, dtype=cs.dtype,
                                                      device=cs.device)) + 1)
        nz = ev[ev > ev[0] * 1e-14]
        kappa = float(ev[0] / nz[-1]) if nz.numel() > 1 else float("inf")
        r = torch.arange(1, 301, dtype=torch.float64, device=ev.device)
        y = torch.log10(ev[:300] + 1e-30)
        xm, ym = r.mean(), y.mean()
        slope = float(((r - xm) * (y - ym)).sum() / ((r - xm) ** 2).sum())
        act = (hits[i] > 0).float().mean()
        res["layers"][str(i)] = {
            "participation_ratio": round(er, 1),
            "er_over_d": round(er / dim, 4),
            "stable_rank": round(stable, 1),
            "energy_90_dims": e90, "energy_99_dims": e99,
            "condition_number": round(kappa, 2),
            "spectral_slope": round(slope, 4),
            "active_channels_pct": round(float(act) * 100, 2),
            "tokens": cnt2[i],
            "verdict": ("pass" if er >= 0.15 * dim else
                        "warn" if er >= 0.05 * dim else "fail"),
        }
        print("  L%-3d ER=%7.1f (%.4f·d) stable=%6.1f e90=%5d e99=%5d κ=%.1f "
              "slope=%.2f → %s"
              % (i, er, er / dim, stable, e90, e99, kappa, slope,
                 res["layers"][str(i)]["verdict"]), flush=True)

    # ── 前缀稳定性 ──
    print("\n前缀稳定性…", flush=True)
    kbuf = {i: [] for i in want}
    grab = {"on": False}

    def mk_grab(i):
        def hook(_m, inputs):
            if grab["on"]:
                kbuf[i].append(inputs[0][:, -1, :].float().cpu())
        return hook

    hs = [layers[i].mlp.down_proj.register_forward_pre_hook(mk_grab(i)) for i in want]
    try:
        with torch.no_grad():
            for i in want:
                kbuf[i] = []
                grab["on"] = True
                for variants in fact_prompts:
                    for p in variants:
                        ids = tok(p, return_tensors="pt", truncation=True,
                                  max_length=512).to(dev)
                        model(**ids)
                grab["on"] = False
                ks = [t.reshape(-1) for t in kbuf[i]]
                if len(ks) != len(FACTS) * len(TEMPLATES):
                    res["layers"][str(i)]["prefix_cos"] = None
                    continue
                cs = []
                for fi in range(len(FACTS)):
                    seg = ks[fi * len(TEMPLATES):(fi + 1) * len(TEMPLATES)]
                    for x, y in itertools.combinations(seg, 2):
                        cs.append(float(torch.nn.functional.cosine_similarity(x, y, dim=0)))
                kk = max(1, int(0.05 * dim))
                sets = [set(t.abs().topk(kk).indices.tolist()) for t in ks]
                jac = []
                for x, y in itertools.combinations(sets, 2):
                    jac.append(len(x & y) / max(1, len(x | y)))
                res["layers"][str(i)]["prefix_cos"] = round(sum(cs) / len(cs), 3)
                res["layers"][str(i)]["prefix_cos_min"] = round(min(cs), 3)
                res["layers"][str(i)]["jaccard"] = round(sum(jac) / len(jac), 3)
                print("  L%-3d 前缀余弦 %.3f（min %.3f）｜Jaccard %.3f"
                      % (i, sum(cs) / len(cs), min(cs), sum(jac) / len(jac)), flush=True)
    finally:
        for h in hs:
            h.remove()

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with io.open(a.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("\n写出 %s" % a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
