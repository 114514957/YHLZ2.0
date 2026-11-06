"""仓库根目录结构检查（台账 1103）：根只放入口/文档/配置，其余归位。

规则（白名单）：
- 根文件：入口 bat/cmd、README/STRUCTURE/AGENTS、requirements*、.env*、.gitignore、
  生成物 jieba.cache；
- 根目录：只允许项目既有目录（见 ALLOWED_DIRS）；
- 其余一切（pip-*、tmp*、*.log、*.wav、install 目录、一次性脚本……）都算违规。

用法：
    python tools/structure_lint.py            # 人读
    python tools/structure_lint.py --json     # 机读
    python tools/structure_lint.py --fix-hint # 附带建议目录

退出码：0 = 干净；1 = 有违规。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

# 根目录允许存在的目录
ALLOWED_DIRS = {
    ".git", ".venv", ".archify", ".tmp_probe", "_pylib", "archive", "artifacts",
    "assets", "backend", "cache", "config", "data", "desktop", "dist", "docs",
    "finetune_bundle", "GPT-SoVITS", "llm_workbench", "logs", "memory", "models",
    "plugins", "research", "Seed-VC", "tests", "tools", "vendor", "venv-dsh",
    "venv-gsv5",
    # 历史/资产目录（live 代码按根名引用，不能搬）：
    "对话DEMO", "角色皮套", "音频素材",
    # 模型实验站（2026-11-06 起，台账 1114/1117；由模型实验线维护）
    "experiments",
}

# 根目录允许存在的文件：名字精确匹配或模式
ALLOWED_FILE_PATTERNS = [
    r"^\.env($|\.example$)",
    r"^\.gitignore$",
    r"^AGENTS\.md$",
    r"^README\.md$",
    r"^STRUCTURE\.md$",
    r"^requirements.*\.txt$",
    r"^[^.]*\.bat$",          # 入口脚本（YH_*/YHLZ_*/start_*/启动*）
    r"^[^.]*\.cmd$",
    r"^jieba\.cache$",        # jieba 生成的本地缓存（已 gitignore）
]

# 明显该进子目录/该删的形态
JUNK_PATTERNS = [
    (r"^pip-", "pip 临时目录 → 删；TEMP/TMP 收到 cache/tmp"),
    (r"^tmp", "测试临时目录 → 删；单测用 tempfile 指向 cache/tmp"),
    (r".*\.(log|err)$", "日志 → cache/logs/"),
    (r".*\.(wav|mp3|flac)$", "音频 → assets/ 或 archive/"),
    (r".*\.(html|htm)$", "抓取页 → archive/ 或删"),
    (r".*\.(png|jpg|jpeg)$", "图片 → assets/ 或 archive/"),
    (r".*\.(bak|old|orig)$", "备份 → archive/ 或删"),
    (r"^__pycache__$", "缓存 → 删（已 gitignore，但别留在根）"),
    (r".*\.(py|mjs|js|ts)$", "脚本 → tools/ 或 desktop/"),
]


def scan() -> dict:
    files, dirs = [], []
    for p in ROOT.iterdir():
        if p.is_dir():
            if p.name not in ALLOWED_DIRS:
                dirs.append(p.name)
        else:
            name = p.name
            if not any(re.match(pat, name) for pat in ALLOWED_FILE_PATTERNS):
                files.append(name)
    violations = []
    for name in files:
        hint = "根目录只放入口/文档/配置；移到子目录或删"
        for pat, why in JUNK_PATTERNS:
            if re.match(pat, name):
                hint = why
                break
        violations.append({"kind": "file", "name": name, "hint": hint})
    for name in dirs:
        hint = "根目录不新增目录；按用途放进 docs/ tools/ assets/ cache/ 或 archive/"
        for pat, why in JUNK_PATTERNS:
            if re.match(pat, name):
                hint = why
                break
        violations.append({"kind": "dir", "name": name, "hint": hint})
    return {
        "ok": not violations,
        "root": str(ROOT),
        "files": len(files),
        "dirs": len(dirs),
        "violations": sorted(violations, key=lambda v: (v["kind"], v["name"])),
        "allowed_dirs": len(ALLOWED_DIRS),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fix-hint", action="store_true", help="show hints (default on)")
    args = ap.parse_args()
    rep = scan()
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        print(f"root={rep['root']}")
        if rep["ok"]:
            print("结构检查：干净（根目录无违规项）")
        else:
            print(f"结构检查：{len(rep['violations'])} 项违规")
            for v in rep["violations"]:
                print(f"  [{v['kind']}] {v['name']}  -> {v['hint']}")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
