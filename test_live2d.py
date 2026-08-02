"""测试 Live2D 模型文件完整性"""
import json
from pathlib import Path

print("=== 测试 Live2D 模型文件 ===")
live2d_dir = Path("assets/live2d")
model_dir = live2d_dir / "hiyori_vts"

files_to_check = [
    model_dir / "hiyori.model3.json",
    model_dir / "hiyori.moc3",
    model_dir / "hiyori.physics3.json",
    model_dir / "hiyori.cdi3.json",
    model_dir / "hiyori.2048" / "texture_00.png",
    live2d_dir / "pixi.min.js",
    live2d_dir / "pixi-live2d-display.min.js",
    live2d_dir / "live2dcubismcore.min.js",
    live2d_dir / "live2d_viewer.html",
]

all_ok = True
for f in files_to_check:
    if f.exists():
        size = f.stat().st_size
        print(f"  OK {f.name} ({size/1024:.1f} KB)")
    else:
        print(f"  FAIL {f.name} 不存在!")
        all_ok = False

# 检查模型配置
model_cfg_path = model_dir / "hiyori.model3.json"
if model_cfg_path.exists():
    with open(model_cfg_path, "r") as fp:
        model_cfg = json.load(fp)
    print(f"  model3: version={model_cfg.get('Version')}")
    print(f"  fileReferences: {list(model_cfg.get('FileReferences', {}).keys())}")

# 检查动画
anim_dir = model_dir / "animations"
if anim_dir.exists():
    anims = list(anim_dir.glob("*.motion3.json"))
    print(f"  动画文件: {len(anims)} 个")
    for a in anims[:5]:
        print(f"    - {a.name}")

if all_ok:
    print("OK 所有 Live2D 模型文件完整")
else:
    print("FAIL Live2D 模型文件缺失")