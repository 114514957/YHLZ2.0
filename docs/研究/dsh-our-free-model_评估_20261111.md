# dsh-our-free-model 评估：免费前沿模型的代价

> 2026-11-11 · 利贞
> 对象：`Ebony-Vinyl/dsh-our-free-model`（MIT，JavaScript，**v2.8.3**，★69,429 / fork 1,871，建仓 2026-09-24，今日仍在推）
> 方法：GitHub API 直读 README（93,792 B）、package.json、全树（855 项）、`feed/manifest.json`、`feed/announcements.json`、`scripts/update-magpie-engine.mjs`。**未安装、未下载 72 MB 二进制、未运行。**
> 结论先给：**不装在生产机上**。理由不是"免费可疑"，是四条具体证据。

---

## 1. 它是什么

DSH 插件。装完即用，不用登录/注册/填 Key，就能用 DeepSeek V4.1 Flash、Kimi K3 等模型。

版本页自己写的三条车道：

1. **免费车道**：OpenCode 的公开免密网关 + Kilo AI 的公共免费池；
2. **EAC 车道**（桌面端专属）：作者自建的"协付"网关，**GitHub 登录 + 给本仓库 star 才发令牌**；
3. **十个账号渠道**：LobsterAI、Qoder（含中国版）、TRAE、Cline、Loomy、Raccoon、MiniMax Code、ZCode、Gemini——登录、账号池、每日积分领取、本地 OpenAI 网关（默认 `127.0.0.1:8326`）。

外加：用量看板、局域网转发中继、公告中心、应用内一键升级、OFM 插件中心（另一仓库 `ofm-extensions`）。

---

## 2. 它是怎么"免费"的（机制，逐条有出处）

| 车道 | 真实来源 | 我们看到的证据 |
|---|---|---|
| OpenCode 免费 | `https://opencode.ai/inference/v1/*`，凭据就是 `Authorization: Bearer public` | README「上游是哪些源」表；代码在 `src/upstream.js` |
| Kilo 免费池 | `https://api.kilo.ai/api/gateway`，`isFree` 模型，无账号 | `src/kilo.js`；README 引用了上游模型卡原文："Prompts may be logged by the upstream provider…" |
| EAC 协付 | 作者自建网关（宝塔 Node 形态），凭据 AES-256-GCM 密文 + 三片掩码分片派生，**令牌只发给「GitHub 登录 + 已 star」**，每 12 小时复查 star，取消 star 即吊销 | README「EAC 渠道」 |
| 十个账号渠道 | 登录各家后复用其免费额度、每日领积分 | README「十个账号渠道，一体接入」 |
| magpie 引擎 | `vendor/magpie/bin/magpie-win32-x64.exe`，**72.7 MB**，是 `yetone/magpie` 的"未修改构建"（pin 在 `scripts/build-magpie-engine.mjs`），另带约 28 MB 分片 `src/engine-parts/*.part` | 文件树 + `scripts/update-magpie-engine.mjs` 头注释 |

**一句话**：它的"免费"不是模型免费，是**别人免费额度的再分配**（外加作者自掏的协付池）。

---

## 3. 它做得好的地方（这些要承认）

README 的工程披露水平高于绝大多数同类项目：

- **上游表逐条列出**：请求发哪里、带什么凭据，连"`Bearer public`"都写了；
- **升级链**：Ed25519 签名清单 → 公钥 pin 在 `src/updater.js` → 逐文件 SHA-256 + 字节数 → staging 回读 → 安装后回读 → 任一步失败回滚；
- **公告与升级解耦**（v1.3.2）：README 自己承认早期"改一个 feedUrl 就等于在宿主进程里执行任意代码"——事故换来的一条硬规则；
- **请求信任围栏**：插件路由前缀在 webServer 最长前缀分发下会覆盖内核 `/api`，这是真实漏洞类型，他们修了并写了断言；
- **公告 HTML 白名单** + XSS 语料测试；中继只绑回环、`timingSafeEqual` 比 Key、路径白名单、环路 508；
- **不依赖浏览器**：`llm` 是硬依赖，没有 webServer 的 composition（如 tui）也能起。

---

## 4. 四条风险（每条都有证据，不是感觉）

### 4.1 数据出网，且上游明说会记录

- 你的 prompt、工具结果、随附图片都会发到上游——和调用任何 API 一样；
- **Kilo 免费池的模型卡原文**："Prompts may be logged by the upstream provider and used to improve their services. Not suitable for production or sensitive data workloads."；
- 免费车道按客户端指纹计额度，会因地区 403、超量 429。

对元亨意味着：**她的对话里有私人内容、记忆片段、群聊原文**——这些一旦走免费车道，等于交给一个明确会记录的第三方。

### 4.2 星标闸门 + 求 Star 的"紧急公告"

- EAC 通道的令牌**只发给「登录 + star」的 GitHub 账号**，12 小时复查，取消 star 即吊销；
- `feed/announcements.json` 里有一条 `level: "urgent"`（触发全屏弹窗）、`holdSeconds: 3` 的公告，标题是「说点心里话：这三个项目，想请你顺手点个 Star」。

6 周 69k star，至少有一部分是**机制驱动的**，不是口碑驱动的。这不违规，但它让"star 数"失去参考价值——我们自己别拿它当质量证据。

### 4.3 闭源二进制 + 远程代码通道

- 72.7 MB 的 magpie 引擎在仓库里是**预构建产物**，源码在上游 `yetone/magpie`，我们无法核对"未修改"这句话；
- 但"零依赖/无构建步骤"的叙事与它并存，容易被忽略；
- 升级清单与公告都来自维护者的仓库：**谁管仓库，谁就能把代码送进所有实例**（有签名，但信任锚就是仓库里的公钥）；
- 同一条链路还能**热重载**——升级即生效，不重启。

### 4.4 十个商业账号的登录与池化

- 自动登录 + 账号池 + 每日积分领取，几乎必然违反各家 ToS；封号后果落在使用者；
- 凭据虽然"只写宿主凭据库、浏览器拿不到明文"，但**宿主进程本身**能拿到——而这个宿主进程就是我们的 DSH/元亨进程。

---

## 5. 对 YHLZ 的具体风险

| 我们机器上的东西 | 插件跑在同进程/同宿主里意味着 |
|---|---|
| `YH\.env`（DEEPSEEK_API_KEY、HF_TOKEN） | 任何插件代码都能读 |
| `cache/memory`、L2 库、日记、台账 | 私人数据与项目史 |
| QQ 会话（NapCat 3001）、B 站号 | 身份与社交关系 |
| 8321 工作台、8081 模型 | 本机服务与推理通道 |

所以结论不是"它危险"，而是**它的权限模型和我们家的东西不匹配**：一个会自更新、会拉远程公告、会驱动十个第三方登录的插件，不该住在元亨的宿主里。

---

## 6. 建议

1. **不装**。生产机不装，利贞这边也不装（DSH 里同样有我们的 `.dsh` 凭据与插件）。
2. 如果一定要看效果：**独立 Windows 沙箱/VM** + 一次性 DSH profile + 不挂载 `YH` 目录 + 事后删盘。别在真机上试。
3. 口径记一笔：**"免费不限量"= 别人的免费额度 + 作者的协付池，不是模型本身免费**；能持续多久取决于上游脸色。

---

## 7. 值得偷的四个工程点（与是否安装无关）

| # | 借什么 | 用在哪儿 |
|---|---|---|
| 1 | **Ed25519 签名升级清单 + 逐文件 SHA-256 + staging 回读 + 失败回滚** | 我们 `plugins/dsh-music/install.mjs` 现在只有"备份 + junction"，可以照这个把"装/升"做成可验证的 |
| 2 | **插件路由的最长前缀覆盖检查** | 我们以后若给插件加 HTTP 端点，这是必查项（内核 `/api` 被覆盖是真实漏洞类型） |
| 3 | **思考强度两种语义**：有档位的按原值下发 `reasoning_effort`（上游会 400 校验集合）；没档位的走 token 预算阶梯（Light/Balanced/Deep = 2k/8k/上限，不可关思考的翻倍） | 和我们"token 预算守卫"是同一题，它的表述比我们清楚 |
| 4 | **公告源与升级源彻底解耦** | 我们做插件升级/公告时，一条设置项不能同时改两个东西 |

---

## 8. 边界（没做的事）

- 没装、没跑、没下载那 72 MB 二进制，**无法验证它是否被篡改**；
- 没核 GitHub star 的真实性（只记录"星标闸门"这个机制事实，不做指控）；
- README 里"OpenCode Zen 免费额度"的具体政策没去上游核（只引用了仓库里的描述）；
- `ofm-extensions`（插件市场）未展开看。

---

## 9. 归档

`research/ofm/`：`README.md`（93 KB 全文）、`package.json`、`feed__manifest.json`、`feed__announcements.json`、`scripts__update-magpie-engine.mjs`。
脚本：`research/inspect_ofm.py`、`inspect_ofm2.py`、`inspect_ofm3.py`。

---

## 10. 能不能直接装到我们这台 DSH

**技术上能，但我不建议装在 desktop 生产 profile。**

### 10.1 兼容性核对（逐项比过）

| 项 | 它要求 | 我们 | 结论 |
|---|---|---|---|
| 形态 | 标准 bundle：`cordis.patch.yml` 一行 `insert` + `dsh.client` 半身 | 我们自己的 dsh-music 同形态 | ✅ 同一套装法 |
| `@deepseek-ai/dsh-llm` | `^0.1.2-rc.1 \|\| ^0.1.7-rc.2 \|\| **^0.2.0-rc.1**` | DSH **0.2.1-rc.3** | ✅ 落在 `^0.2.0-rc.1` 区间 |
| 同上（commands / credentials） | 同样的三段区间 | 同上 | ✅ |
| `@deepseek-ai/cordis` | `^4.0.2` | rc.3 自带 cordis 4.x | ✅（未逐位核） |
| `engines.node` | `^22.19.0 \|\| >=24.0.0` | 本机 **v22.20.0**；DSH 运行时自带 24.x | ✅ |
| inject | 只有 `['llm']`（webServer 走嵌套 inject） | 桌面版有 llm 与 webServer | ✅ 能激活 |

**注意**：README 顶部徽章写「适配内核 dsh-0.1.5–0.1.7-rc.2」是**过时的**；`package.json` 的 peerDependencies 已经把 0.2.0-rc.1 线写进去了。以 package.json 为准。

但它自己的验收表只测到 **dsh 0.1.7-rc.1（源码构建）** 与 **AIO 6.9.3**，**0.2.x 没测过**——能装不等于行为正确（它靠 duck typing 不 import `dsh-llm`，这是它敢跨版本的原因，也是可能悄悄错位的点）。

### 10.2 装法（真要装的话）

```cmd
:: 桌面 profile 由 Electron 管理，用 CLI 装到独立 profile 更安全
dsh plugin --profile ofm-test add github:Ebony-Vinyl/dsh-our-free-model#v2.8.3
:: 然后重启该 profile；桌面版则需完全退出 DSH 再开
```

### 10.3 为什么还是不建议装桌面生产 profile

1. **同进程**：插件与宿主同一身份，能读 `.env` 的密钥变量、记忆库、日记、台账；
2. **自更新 + 远程公告**：仓库主控者能把代码送进所有实例并热重载；`level:"urgent"` 的全屏弹窗已在 feed 里用上了（求 Star）；
3. **星标闸门**：开 EAC 要 GitHub 登录 + star，还有 12 小时复查；
4. **数据出网**：Kilo 免费池明确"prompt 可能被上游记录"。

### 10.4 如果一定要试，三条硬约束

- 用**独立 profile**（`ofm-test`）或 VM，不碰 desktop；
- **不开**局域网访问、**不配** EAC 授权、**不登录**十个账号渠道——只当只读试用免费车道；
- **不接元亨的会话**：她的 prompt 里有私人内容与群聊原文。

