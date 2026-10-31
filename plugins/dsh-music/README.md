# dsh-music

把元亨的歌库接进 DeepSeek Harness：**列歌、看详情、本机播放、发到 QQ**。

薄壳设计——插件本身只做三件事：读配置、调 `YH/tools/music_cli.py`、把结果包成工具返回值。
**没有任何"第二份"歌库逻辑**：索引格式、路径解析、QQ 发送全部复用 `backend/song_library.py`。

## 四个工具

| 工具 | 作用 | 参数 |
|---|---|---|
| `music_list` | 列出成品歌（按时间倒序） | `query?`（标题/标签/来源过滤）、`limit?`（1–200，默认 20） |
| `music_info` | 看某首歌的详情（文件绝对路径、标签、来源、创建时间） | `handle` |
| `music_play` | 本机扬声器播放（立刻返回，不等待播完） | `handle` |
| `music_send` | 通过 QQ 私聊把成品发给老爹（需 NapCat 在线） | `handle` |

`handle` 接受：歌曲 id（`song_2026...`）、列表序号（`1`）、标题片段、标签。

## 安装

**最省事：双击 `一键安装.cmd`**（卸载双击 `卸载.cmd`）。它等价于下面第一行命令。

```powershell
# 先看清要改什么（不动任何文件）
node plugins\dsh-music\install.mjs --dry-run

# 真装（默认 desktop profile）
node plugins\dsh-music\install.mjs

# 换 profile
node plugins/dsh-music/install.mjs --profile web

# 装到指定目录（测试或非标准安装位置）
node plugins\dsh-music/install.mjs --profile-dir D:\tmp\fakeprofile

# 卸载
node plugins\dsh-music/install.mjs --uninstall
```

它会改三处，全部先备份：

1. `profiles/<p>/package.json` → `dependencies["dsh-music"] = "link:<插件目录>"`
2. 同文件 → `dsh.profile.bundles` 追加 `"dsh-music"`
3. `profiles/<p>/node_modules/dsh-music` → 指回插件目录的 **junction**

> **如果报 `EPERM`**：说明 DSH 正在运行、或你没有写 `~/.dsh` 的权限。关掉 DSH 再跑，
> 或者用 DSH 自带的插件管理器 `install_bundle` 指向本目录。
> 装完 **重启 DSH 或按 F5**——客户端模块图是页面加载时的快照。

## 配置

`config.json`（相对路径按 YH 根解析）：

```json
{
  "python": ".venv\\Scripts\\python.exe",
  "cli": "tools\\music_cli.py",
  "timeouts": { "list": 15000, "info": 15000, "play": 15000, "send": 60000 }
}
```

也可以在 `cordis.patch.yml` 的插件行里写 `config:` 覆盖（行内配置优先）。

## 依赖与边界

- **不需要**任何 npm 依赖；插件是纯 Node ESM。
- 播放：优先 `sounddevice`（元亨同款）；装不上就交给**系统默认播放器**（`os.startfile`）。
- 发送：走 NapCat 的 `upload_private_file`，与 `backend/song_library.send_qq` 同一条路径。
- 只读索引，不写歌库；新增/删除歌曲仍然只在工作台做（操作员规矩：**只有成品才能发**）。

## 目录

```
plugins/dsh-music/
├─ package.json          # dsh.bundle.patch + main
├─ cordis.patch.yml      # 插件行（insert 一行，纯 host）
├─ config.json           # python / cli / 超时
├─ install.mjs           # 装进 profile（备份 + junction + 校验）
├─ 一键安装.cmd / 卸载.cmd
├─ lib/
│  ├─ index.js           # apply(ctx)：注册四个工具
│  └─ library.js         # 配置合并、调 CLI、渲染；无 DSH import，可单测
└─ test/
   ├─ smoke.mjs          # 离线自检：路径、四个工具、list/info、错误分支
   └─ context.mjs        # 用假 ctx 跑 apply()：注册数、effect 生命周期、工具形状、真调一次
```

## 自检

```powershell
node plugins\dsh-music\test\smoke.mjs      # 9 项：路径、CLI、渲染、错误分支
node plugins\dsh-music\test\context.mjs    # 22 项：apply() 注册 + 每个工具的 schema/execute/render
```

两个都跑过 `ALL PASS` 才算可用。
