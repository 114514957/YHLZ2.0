# see_now + 系统 OCR：安装与改动留档

> 2026-11-05 · 利贞
> 用途：老爹要「已经装的就统计、留档」。本文是这条线（给元亨看屏幕 / 读屏幕字）的**完整变更清单**，
> 数字均为本机实测（`research/inventory_see_now.py` 采集）。
> 关联记录：台账 1076 / 1080 / 1082 / 1088 / 1089 / 1090 / 1091 / 1092。

---

## 1. pip 侧：装了什么

| 包 | 版本 | wheel | 落盘 | 用途 | 来源 |
|---|---|---|---|---|---|
| **winsdk** | **1.0.0b10** | 12.0 MB | **43.8 MB / 949 个文件** | Windows.Media.Ocr（系统 OCR）、WinRT 绑定 | 清华镜像 `pypi.tuna.tsinghua.edu.cn` |
| rapidocr_onnxruntime | — | 14.9 MB | **未装成** | （计划中的 OCR 备选） | PyPI 直连 2 次超时 |

**未装成 / 无残留**（逐项核过 `site-packages`）：

```
rapidocr_onnxruntime : no
opencv_python        : no
shapely              : no
```

**复用的既有依赖**（不是这条线装的，只是被用到）：

| 包 | 版本 | 用途 |
|---|---|---|
| onnxruntime | 1.20.1 | （rapidocr 本来要用，未用上） |
| imageio_ffmpeg | 0.6.0 | 自带 `ffmpeg-win-x86_64-v7.1.exe`（87.6 MB），**未复制、未改 PATH**，由 `ffmpeg_path()` 动态定位 |

卸载（若要走回头路）：

```cmd
.venv\Scripts\python.exe -m pip uninstall -y winsdk
```

---

## 2. 代码：新增 3 个文件，改 3 个文件

### 新增

| 文件 | 规模 | 作用 |
|---|---|---|
| `backend/see_now.py` | 10,757 B / 248 行 | 元亨侧接口：`capture()` / `capture_native()` / `capability_result()` / `ffmpeg_path()` / `TOOL_SPEC` / `SeeNowArgs`；节流 + 日志 |
| `backend/ocr.py` | 5,156 B / 141 行 | 系统 OCR：`available()` / `languages()` / `read(png)` / `read_screen(region)` / `capability_result()`；中文空格清理 |
| `tools/see_now_bridge.mjs` | 11,107 B / 279 行 | Node 桥：`--probe`（不依赖 ffmpeg）/ `--capture`（拼图）/ `--raw`（原生裁剪，读字）；末行 JSON |

### 修改

| 文件 | 改了什么 |
|---|---|
| `backend/target_capability_registry.py` | `Capability` 增字段 `once_per_turn: bool = False` |
| `backend/target_orchestrator.py` | ① 新增 `_tool_image_enabled()` / `_tool_image_part()`；② 工具回填支持 `content=[text, image_url]`（handler 返回 dict 带 image 时）；③ 新增 `ran_once` 硬闸（`once_per_turn` 的工具一轮只执行一次） |
| `backend/target_scheduler_tools.py` | ① `import os`；② 新增 `_screen_text_caps()` 与 `_see_now_caps()`；③ `scheduler_capabilities()` 列表首部展开两者；④ 两个工具的描述（含"读字用 raw"的指引） |

`git status` 现状：

```
 M backend/target_capability_registry.py
 M backend/target_orchestrator.py
 M backend/target_scheduler_tools.py
?? backend/ocr.py
?? backend/see_now.py
?? tools/see_now_bridge.mjs
```

---

## 3. 配置：`.env` 多了两行

```
YHLZ_SEE_NOW=1          # 总开关：关掉时 see_now 与 screen_text 都不注册
YHLZ_SEE_NOW_GAP=20     # 两次成功的读屏之间最小间隔（秒）
```

生效方式：**daemon 重启**（`backend.config` 用 `load_dotenv(override=True)` 读 .env，注册表在启动时装配）。
今天为让改动生效，daemon 重启过 3 次，均由 launcher 的 `ensure_stack` 自动拉起（`cache/logs/launcher.log` 有 `spawn daemon: requested`）。

---

## 4. 能力：两个工具，现在共 47 个

| 工具 | 参数 | 成本 | 返回 |
|---|---|---|---|
| `see_now` | `seconds` 3–20（默认 6）、`quality` low/standard/high/ultra、`region` "x,y,w,h"、`raw` bool | 拼图 low = **222 token**；`raw` 420×240 ≈ **124 token**；图片 token 之外只有一句摘要 | 图片（拼图或原生裁剪）+ 一句文本摘要 |
| `screen_text` | `region`（可选）、`limit`（默认 120 行） | **0 图片 token**，0.77–0.81 s | 纯文字（最多 4000 字） |

限制（写进描述里了）：
- `see_now` 的 low 档**只够看布局**，读不了小字；问字要用 `raw` + `region`；
- `screen_text` 与手机「提取文字」同引擎，小字/艺术字会错（`deepseek`→`deepseel`、`新会话`→`新会讠舌`）；
- `see_now` 一轮只执行一次（`once_per_turn`），第二次直接返回「本轮已经用过」；两次成功读屏间隔 ≥ 20 s，超频只回提示**不抓屏**。

日志：`cache/logs/see_now.log`（每次 capture / throttled 一行）。

---

## 5. 实测数据（留档用）

| 场景 | 数字 |
|---|---|
| 全屏拼图 low（2560×1600 → 798×462） | 222 token；静止 2 s 内 22 帧只留 1 帧 |
| 原生裁剪 420×240（读字） | 56,733 B，prompt **124 token**，读对「五、现在怎么用」 |
| 系统 OCR 整屏 | 98–100 行，**767–807 ms**，0 图片 token，`zh-Hans-CN` |
| 真模型三轮（46 工具） | 「看我屏幕」→ 调 `see_now`；追问 → 被 20s 挡住；「几点」→ 不误触发 |
| 假 LLM 管线验证 | `content_parts = ["text","image_url"]` |

---

## 6. 回滚（三级，任选）

1. **只关能力**：`.env` 里 `YHLZ_SEE_NOW=0` → 重启 daemon → 两个工具消失（代码与包都留着）。
2. **卸包**：`pip uninstall -y winsdk` → `screen_text` 失效（`see_now` 不受影响）。
3. **撤代码**：删 `backend/see_now.py`、`backend/ocr.py`、`tools/see_now_bridge.mjs`，并 `git checkout -- backend/target_capability_registry.py backend/target_orchestrator.py backend/target_scheduler_tools.py`。

校验命令：

```cmd
.venv\Scripts\python.exe -m pip show winsdk
.venv\Scripts\python.exe research\inventory_see_now.py
node tools\see_now_bridge.mjs --probe
.venv\Scripts\python.exe -c "import sys;sys.path.insert(0,'.');import backend.config;from backend.target_scheduler_tools import setup_scheduler_capabilities as s;print(len(s().export_openai_tools()))"
```

---

## 7. 过程产物（可删，不影响运行）

`research/` 下 15 个 `see_now_*.py`（探针、三臂实验、P2/P3/P4 验收、保真度对比、切片实验）+
`research/_ocr_test.txt`、`_ocr_screen.txt`、`_screen_text.txt`、`_ocr_compare*.txt`、`_tiles*`。
它们是过程证据，删掉不影响任何能力；要留就留。

---

## 8. 一句话状态

**装了的：`winsdk 1.0.0b10`（43.8 MB、949 文件）。**
**没装成的：`rapidocr`（零残留）。**
**代码：+3 新文件 / 改 3 个文件。配置：`.env` 两行。能力：`see_now`（看图）+ `screen_text`（读字），共 47 工具，已上线。**
