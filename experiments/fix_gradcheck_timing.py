# -*- coding: utf-8 -*-
"""把梯度自检从 on_step_end（已 zero_grad）改到 training_step（backward 后）。

用字符串定位（不用正则，避免换行差异）。
"""
from __future__ import annotations

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\ACE_WAN——PROJECT\YHLZ\YH"
P = os.path.join(ROOT, "dist", "material_v13", "train_v13.py")
t = io.open(P, encoding="utf-8").read()

start = t.find("# ── 2026-11-14：**梯度自检**")
if start < 0:
    sys.exit("没找到旧自检块起点")
mark = "callbacks=[_GradFlowCheck("
mi = t.find(mark, start)
if mi < 0:
    sys.exit("没找到 callbacks 行")
end = t.find("])", mi)
if end < 0:
    sys.exit("没找到 callbacks 行结尾")
end += 2

NEW = '''# ── 2026-11-14：**梯度自检**（不问"开关开没开"，直接看梯度有没有到 LoRA）────
    # ⚠️ 第一版写在 TrainerCallback.on_step_end —— 那一步 Trainer **已经 zero_grad**，
    # 永远读到 0，会把正常训练误判成"白训"（云端实测：loss 5.868→5.502、grad_norm 6.48，
    # 自检却报 0 并中止）。正确时机：backward 之后、optimizer.step() 之前 → 覆盖 training_step。
    from transformers import Trainer as _HFTrainer

    class _GradCheckTrainer(_HFTrainer):
        _gc_at = int(cfg.get("grad_check_step", 10))
        _gc_done = False

        def training_step(self, *args, **kwargs):
            loss = super().training_step(*args, **kwargs)
            step = int(self.state.global_step or 0) + 1
            if self._gc_done or step < self._gc_at:
                return loss
            self._gc_done = True
            seen = nonzero = 0
            per_proj = {}
            for name, p in self.model.named_parameters():
                if "lora_" not in name or not p.requires_grad:
                    continue
                seen += 1
                g = p.grad
                if g is None:
                    continue
                n = float(g.detach().float().norm())
                if n > 0:
                    nonzero += 1
                    key = name.split(".lora_")[0].split(".")[-1]
                    per_proj[key] = per_proj.get(key, 0.0) + n
            print(f"[gradcheck] 第 {step} 步（backward 后）：LoRA 参数 {seen} 个，"
                  f"非零梯度 {nonzero} 个")
            for k, v in sorted(per_proj.items(), key=lambda x: -x[1])[:8]:
                print(f"[gradcheck]    {k:>12} norm={v:.4e}")
            if nonzero == 0:
                opt_states = getattr(self.optimizer, "state", {}) or {}
                touched = 0
                for s in opt_states.values():
                    ea = s.get("exp_avg")
                    if ea is not None and float(ea.abs().sum()) > 0:
                        touched += 1
                print(f"[gradcheck] 梯度为空；优化器 {len(opt_states)} 个状态，"
                      f"{touched} 个已累积动量")
                if touched == 0:
                    raise RuntimeError(
                        "梯度自检失败：第 %d 步 LoRA 既无梯度也无动量。查 "
                        "gradient_checkpointing_kwargs={'use_reentrant': False}、"
                        "enable_input_require_grads()、use_cache=False。" % step)
            return loss

    trainer = _GradCheckTrainer(model=model, args=args, train_dataset=ds_train,
                                eval_dataset=ds_val, data_collator=collator)'''

t2 = t[:start] + NEW + t[end:]
io.open(P, "w", encoding="utf-8").write(t2)
print("替换成功：%d → %d 字节" % (len(t), len(t2)))
print("  含 _GradCheckTrainer：", "_GradCheckTrainer" in t2)
print("  残留 TrainerCallback：", "TrainerCallback" in t2)
print("  残留 _GradFlowCheck：", "_GradFlowCheck" in t2)
