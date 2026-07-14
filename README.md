<div align="center">

# 寻迹 · Xunji

**面向 Claude Code 的自主红队工作区 —— 专注 Web 打点（initial access）**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![依赖](https://img.shields.io/badge/依赖-标准库-2ea44f)](#-安装)
[![适配](https://img.shields.io/badge/适配-Claude%20Code-8A2BE2)](https://claude.com/claude-code)
[![安全](https://img.shields.io/badge/安全-机器强制硬底线-c0392b)](#%EF%B8%8F-安全模型)

**中文** ｜ [English](README.en.md)

</div>

---

**这是一件红队武器。** 一个由 Root Orchestrator 编排、多个专职 Subagent 并行产出候选、再由 Single Synthesizer 做唯一最终裁决的 Web 打点（initial access）漏洞发现与**完整武器化利用**工作区，同时让整个过程 **可审计、证据绑定、被一条机器强制的硬底线兜住**。

> 它给 AI 的是 **判断纪律 · 接地识别知识 · 运行态结构 · 一条按效果划定的硬底线** —— 而**不是**扫描器、开箱通杀套件、或 JSON 编排器。
> Root/Agent 编写的武器化利用**自由（方法无上限）**；唯一被硬拦的是**对目标自动执行的、不可逆 / 以伤害为目的的效果**。
> **「不是通杀套件」≠「不是武器」**：项目本身就是武器，被排除的只是"不分目标的机械批量通杀"。

## 🧭 架构总览

```text
                操作者 · 最高权威
                     │  授权目标
                     ▼
        ════════  Root Orchestrator  ════════
        状态图 · 前沿拆解 · Agent 分配 · 冲突调度
                     │
   ╭───────────────┬───────────────╯
   │               │
   │        Subagents: surface · web-hunter · code-audit
   │        exploit · verify · review · report
   │               │
   │        candidates / refutations / conflicts
   │               ▼
   │        Single Synthesizer
   │        证据门 · 去重 · 冲突裁决 · 最终结论
   │
   ├─①  书面运行态        →  runs/<target>/   审计轨迹（不入库，结论的唯一依据）
   │
   ├─②  主动验证          →  probe · render · scan · fetch_assets
   │                       →  guard.py（限速 · 体上限 · 三道熔断器）→  授权目标
   │
   ├─③  每次 Bash 调用    →  safety_gate hook   ✋ L4 不可逆危害 · 硬拦
   │
   ├─④  observe-only 旁路 →  sentinel/   行为检测 · 四级自治 · 会话熔断（永不拦）
   │
   └─⑤  收口/安全关键改动  →  review/   独立复审（硬门）→  写回 runs/

   防线：③ safety_gate 硬拦（执法者） · ② guard 工具层熔断 · ④ sentinel 只观察不拦
```

三条防线各司其职：**`safety_gate` hook** 按效果硬拦不可逆危害（执法者）；**`guard.py`** 在工具层限速、限量、熔断（保护目标也保护你自己的可达性）；**`sentinel/`** 只观察不拦截，给每个动作归因贴级、聚合失控时刹车。

## 🔁 运行循环

```text
Root Orchestrator
  → 更新状态图
  → 拆解前沿并分配 Subagents
  → 合并候选、检查冲突
  → 触发验证 / 否证
  → Single Synthesizer 只报告证据支持的结论
```

只要还有安全的开放前沿，Root 就**不应**等用户指定下一个漏洞类别。它自己选定前沿、记录理由、分配合适 Agent，并持续推进，直到前沿被**确认 / 否决 / 因阻碍搁置（deferred） / 以 Type B 推理收口（closed）**。Subagent 只能产出 `phenomenon` / `candidate` / `refutes`；唯一能把候选提升为报告结论的是 Single Synthesizer 经过证据门后的裁决。

## 🧠 设计思路

整个项目建立在**一个决断**和**三根支柱**之上。

### 核心轴：管「效果」，不管「方法」

被约束的，永远是**一个动作对活靶造成的不可逆效果、以及由谁按下执行键** —— 绝不是技术本身。构造并编写武器化利用（RCE 链、鉴权绕过、反序列化 gadget、上传拿 shell、提权、C2 / 反弹 shell / webshell）是**方法，方法自由**，0day 发现就在这里。唯一的硬线是**对目标自动执行的、不可逆 / 以伤害为目的的效果**（销毁、拖库、DoS、资金移动）—— 而这条线按**效果**、在**代码里**、于**运行时**划定，绝不靠文件名或被禁关键词。

> 一条让 AI 畏手畏脚的软约束（「别写那个 exploit」「别提那个工具名」）是**本末倒置** —— 它阉割了操作者真正需要的能力，对安全却毫无贡献。**安全是 hook 的活，按效果管；能力是 Root/Agent 的活，没有方法上限。**

### 三根支柱，刻意**不做** playbook

| 支柱 | 内容 | 位置 |
|---|---|---|
| **判断纪律** | 如何选前沿、掂量证据、抵抗假阳性、不过早收手 | `docs/cognition/` · `docs/WORKFLOW.md` |
| **接地知识** | 真实产品的识别签名与弱点锚点，作为**变体分析输入**，绝不作开箱 payload | `knowledge/` |
| **机器硬底线** | 按效果划定的拒绝边界 | `.claude/hooks/` |

它**拒绝成为第四样**：清单 / playbook / 扫描器跑批 / JSON 编排器。早期编排器架构已被**刻意移除**，`tools/check_rules.py` 就是防它回潮。论点是：**一个有能力的模型 + 纪律 + 接地识别 + 硬底线，胜过任何固定 playbook —— 而 playbook 只会给模型封顶。**

### Root 编排 · Single Synthesizer · author-and-handoff（编写并交接）

- **编写（Author）** —— 写出完整、可运行、直至完整影响的利用代码，交到操作者手上。**没有上限**；对授权目标**少交付**利用代码是一种失败，与「证明不足」对称。
- **自动执行（Auto-execute）** —— Root/Agent 朝活靶发射的部分。默认**证明即止**：证明漏洞真实存在即停。更深入由**操作者把关**，通常以代码交付、由操作者监督下运行。
- **最终裁决（Synthesize）** —— Agent 并行只扩大观察面，不扩大结论权限。Single Synthesizer 负责去重、冲突裁决、certainty 校准和报告入口；并行 breadth 永远不放松证据门。

### 证据高于自信

信号不是结论；模型自信不是证据；单次观察永远不算确认。运行目录就是审计轨迹，发现只在**其证据支持的 certainty** 上报告（任何 ≥ 0.8 的结论须带一条已记录的 **对照 / 复现**）。

## ✨ 设计亮点

### 1 ｜ 效果 × 执行者的安全模型，由代码强制
三层（自主 / 操作者把关 / 硬拦）按**触碰了什么**和**由谁执行**分级，而非按技术。PreToolUse hook（`safety_gate.py`）只按效果强制**自动执行的硬上限**，从不碰 Root/Agent 为操作者编写的代码。

### 2 ｜ 连「你自己访问」都保护的 guard 层 + 熔断器
所有主动工具走 `tools/harness/guard.py`：限速器（禁高频 —— 也是爆破的真正闸，**按速率不按次数**）、响应体上限（禁拖库）、认证失败兜底（只防死循环）。三道熔断器堵住实战暴露的「打爆自己 / 打爆目标」失败：

- **HostHealth** —— 单主机连续 N 次传输失败 → 自动退避（别再猛捶已经开始封你的主机，也别误读成「整站封了我 IP」）。
- **SessionBudget（会话量硬熔断）** —— 全局滚动窗口的请求数 / 外渗字节超硬阈值 → 工具 abort（单主机熔断看不到的「整场反复打爆各 IP」全局维度）。

### 3 ｜ `sentinel/` 运行态行为检测（observe-only）
从 Claude Code 钩子重建 agent 动作轨迹，按两个**不可伪造**维度归因（locus 在哪 / provenance 谁触发），区分**「我的清理」vs「要警惕的行为」**。给每个动作算出**四级自治**决策，并内置**会话级熔断器**（被劫持 / 风险滚雪球 / 反复越界时**刹车不熄火**：钳住 effectful 动作、proof/recon 照常流）。**永不拦截**——只写告警与风险分，供操作者验证准度后再考虑转 inline。

| 级别 | 含义 | 例子 | 处理 |
|:--:|---|---|---|
| 🟢 **L1 AUTO** | 可逆 / 证明级，无人值守 | SQLi 差异、单条 `id`、上传无害文件 | 直接执行（仅 trace） |
| 🟡 **L2 NOTIFY** | 可逆但值得记 | 读凭据、拆自建容器、累计量 | 执行 + 审计 |
| 🟠 **L3 GATE** | 不可逆但正当 | 拿 shell、提权、写、出界 | 操作者把关 / 排队 |
| 🔴 **L4 BLOCK** | 不可逆 harm-as-purpose | 拖库、DoS、删库、资金、勒索 / 擦除 | 机器硬拦，永不自动 |

### 4 ｜ 反过早收口 + `review/` 独立复审模块（最大亮点）
实战表明最深的失败不是能力，而是急切的模型**过早收口**：凭响应头不看内容一锅端、把「我够不着」等同「它安全」、给错误结论打满自信。**自评治不了自评偏见。** 于是：

- **逐资产检视台账** —— `classify_hosts.py` 按**实时内容**（非 Server 头）给每台主机指纹写入 `coverage.json`；`check_run.py` **每次**运行都读它、列出必须深挖的「独立应用」候选 —— 让一锅端**当下**暴露。
- **独立 Reviewer = 硬门** —— 任何「探尽 / 无攻击面」论断前，一个**全新上下文子 agent**（无收口利益）审计本次运行；`check_run.py` 对**没有 `Independent Review` 记录**的收口论断**硬性失败**。可移植设计见 [`review/review-mechanism.md`](review/review-mechanism.md)。
- **已扩到安全关键代码** —— `.claude/hooks/` · `guard.py` · `sentinel/` 的**行为改动**收口前同样须独立复审、记录到 `review/records/`（窄边界，详见 `docs/WORKFLOW-reference.md`）。这条是实证换来的：一次独立复审在熔断器上抓出了作者自检漏掉的真 bug。
- **台账矛盾 + certainty 管控 + 够不着重跑队列** —— 被 `Refutes:` 却仍 ≥ 0.8 的结论会被标出；≥ 0.8 须带 `Control:` / `Replicated:`；仅「够不着」的资产进标准化队列，`rerun_deferred.py` 稍后换出口重探。

### 5 ｜ 知识库：接地（公开）+ 武器化（本地）—— 攻击者，不是扫描器
目标是**用漏洞 / payload 知识去打**，所以 payload 知识是一等输入，不是要剔除的东西。知识库分两层，分界是**发不发布**，而非"是不是武器"：

- **接地层 `knowledge/*.md`（公开 · 随仓发）**：识别签名 + 弱点锚点（类别 + 机理 + CVE/CNVD）+ 证明级验证原则，**不含裸 payload**（因为公开）。
- **武器化层 `knowledge/weaponized/`（本地 · gitignore）**：working payload / 利用链 / PoC，按识别挂钩，**不入库**（同 `poc_library/xday`）。

唯一被禁的是**盲扫描器**：不分目标照跑的清单 —— **有没有 payload 都算**。区分攻击者与扫描器的是**使用方式**(识别后查 · 按目标适配 · 过证据门),不是有没有 payload。`check_knowledge.py` 只管公开层(payload 落公开层 = 发布路由错，硬失败，挪去 `weaponized/`)。

### 6 ｜ 一条小而无依赖、全程走 guard 的流水线
`ingest_recon`（recon 报告 → 资产表 + 可达矩阵）→ `classify_hosts`（按内容分类 → `coverage.json`）→ `fetch_assets`（抓**全部** SPA chunk + 完整性断言）→ `probe / render / scan`（主动验证传感器，全程走 guard、UTF-8 安全）→ `rerun_deferred`（出口重跑）。核心路径纯标准库；浏览器、SOCKS 代理、开发 lint 分别用可选 extras。

### 7 ｜ `check_rules` 守的是架构，不是武器
仓库纪律检查「已废弃的编排器 / playbook 面」没回潮、教义文件存在 —— **刻意不**管 exp/poc/scanner 文件（那些是方法、自由；危害在运行时按效果管）。框架不退化回 playbook，武器化部分完全不设限。

## 🛡️ 安全模型

**分层执法**：硬危害由 hook 硬拦，工具量由 guard 熔断，行为由 sentinel 观察。

| 层 | 角色 | 是否真拦 |
|---|---|:--:|
| `.claude/hooks/safety_gate.py` | L4 不可逆危害硬底线（执法者） | ✅ 硬拦 |
| `tools/harness/guard.py` | 限速 / 体上限 / 三道熔断器 | ✅ 工具 abort |
| `sentinel/` | 行为归因 + 四级贴级 + 会话熔断 | ⬜ observe-only |

hook 拦截：不可逆销毁（主机/文件抹除、`DROP`/`TRUNCATE`/无范围 `DELETE`/`UPDATE`）、目标资源删除、海量外带 / 拖库、资金移动、DoS / 高频。**上传证明用产物不拦**（Root 裁量）；拿 shell、越过 Web 层等更重动作**不被机器拦**但需**操作者把关**。

> 被拦的动作**不会**因人工批准而解锁 —— 换一个安全、非破坏性的证明方式。
> scope 不写进 hook。操作者是最高权威，其指令凌驾软约束、除上述硬边界外处处生效。

## 🗂️ 模块地图

| 模块 | 作用 |
|---|---|
| `CLAUDE.md` | 始终加载的简短操作契约（角色 · 驱动 · 方法） |
| `AGENTS.md` · `docs/ARCHITECTURE.md` | Codex 辅助契约 · Claude/Codex 共用的架构设计索引与变更协议 |
| `docs/ROUTER.md` · `docs/WORKFLOW.md` · `docs/cognition/` | 路由 · 运行态工作流 · 判断纪律 |
| `.claude/hooks/` | `safety_gate.py` + `safety_rules.json` —— L4 硬底线 |
| `tools/harness/guard.py` | 限速 / 体上限 / 熔断器 / 会话预算 / 上传登记 |
| **`sentinel/`** | 运行态行为检测：归因 · 四级自治 · 会话熔断（observe-only）· 阈值见 `TUNING.md` |
| **`review/`** | 独立复审模块：可移植规范 · 复审员模板 · `records/` 复审实例 |
| `docs/templates/agents/` · `tools/workers.py` | Agent board：前沿分配、上下文包、候选合并、冲突检查、综合草案 |
| `knowledge/` | 接地识别签名 + 弱点锚点（非武器，`check_knowledge.py` 把关） |
| `tools/` | recon 摄入 · 逐主机分类 · 资产抓全 · 主动验证 · 出口重跑 · 本地检查器 |
| `runs/<target>_<date>/` | 每个授权目标的运行态 = 审计轨迹（不入库） |

**运行态文件**：`target · surface · frontier · hypotheses · evidence · false_positive · decisions · review · report`（空模板在 `docs/templates/run/`）。结论**不**从聊天记忆、模型自信或单个无归因信号上确认。

## ✅ 本地检查

```bash
# 先激活 venv（见下方「安装」）；未激活 venv 时 macOS/Linux 通常用 python3。
python3 tools/check_rules.py          # 架构漂移守卫
python3 tools/check_hook.py           # hook 拦/放回归
python3 tools/check_run.py runs/<t>   # 运行态门 + 反过早收口
python3 sentinel/replay.py            # 行为检测黄金回放
python3 sentinel/verify_layers.py     # L1-L4 误报 / 有效性
python3 tools/harness/guard.py        # guard + 熔断器自测
```

这些只检视本地文件与 hook 行为，**不接触目标**。

## ⚙️ 安装

全新 clone 几乎零成本：核心工具链**零第三方依赖**（仅 Python 标准库）。可选依赖按用途拆分：Playwright 只供浏览器工具，PySocks 只供 `socks5h://` 交战代理，Ruff 只供开发 lint。

**唯一硬性要求**：PATH 上有 **Python ≥ 3.10**（覆盖 hook、`check_*`、`probe`/`scan`）。hook 用 `$CLAUDE_PROJECT_DIR` 接线，无硬编码路径，跨机可移植。

运行模式默认来自随仓的 `config.example.ini`，即 `mode = normal`。需要本地开发模式时复制一份
`config.ini` 并改为 `mode = dev`；真实 `config.ini` 已被 git 忽略，不再入库。

**跨平台约定**（Windows / macOS / Linux 通用，写命令与代码时遵守）：

- **先激活 venv，再用 `python tools/...`；未激活 venv 时用 `python3 tools/...`**。不要写死解释器路径（`.venv/bin/python` 是 Unix 专用，`.venv\Scripts\python.exe` 是 Windows 专用）。
- **路径一律用正斜杠** `/`：Windows 的 Python 也接受，三平台同一行命令通用。
- **venv 与外部二进制不可移植**：`.venv/` 不入库，换机/换平台要重新 `python -m venv` + `pip install`；`nuclei`/`sqlmap`/`tesseract` 用各平台包管理器（brew / apt / choco）各装一次。
- **换行符已由 `.gitattributes`（`eol=lf`）统一**：跨平台 clone/提交不会再产生 CRLF 假改动。

<details>
<summary><b>浏览器工具（可选 —— 仅供 <code>render.py</code> / 验证码）</b></summary>

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Linux/macOS: source .venv/bin/activate
pip install -e '.[browser]'
playwright install chromium
```
跳过它不影响 `probe.py`、`scan.py`、hook 或检查器。
</details>

<details>
<summary><b>SOCKS 交战代理（可选 —— 仅供 <code>socks5h://</code> / <code>socks4a://</code>）</b></summary>

```bash
pip install -e '.[socks]'
```
未安装时使用 `socks5h://` 会 fail-closed，不会静默直连泄露真实 IP；HTTP 代理不需要该 extra。
</details>

<details>
<summary><b>开发检查（可选 —— Ruff）</b></summary>

```bash
pip install -e '.[dev]'
ruff check .
```
</details>

<details>
<summary><b>clone 不会恢复的部分（刻意如此）</b></summary>

- **自动记忆**：存在仓库外（`~/.claude/projects/.../memory/`），按机器隔离。
- **武器化 0day**（`poc_library/xday/`）：仓库只留文件夹结构；exploit 源码 / 二进制**留本地、不入库**。方法自由 = 允许编写，不等于必须发布。
- **接地知识库**（`knowledge/*.md`）**随仓发布**、clone 即得，意在跨机共享、随实战生长。
- **真实目标发现物**（`runs/` · `reports/` · `poc/`）一律 git 忽略，需要时带外传输。
- **`.claude/settings.local.json`**（权限白名单）是本地的，新机器重新授权一次。
</details>

## 🔐 权限 · 路由

- **权限**：这是 **Claude Code** 的工作区；Root 在用户要求时可编辑项目文件，运行期间拥有运行级文件与 Agent Board。
- **为什么是 Claude Code 专属**：机器强制的安全底线（`.claude/hooks/` 的 PreToolUse 等）、CLAUDE.md 自动加载、skills、memory 都是 Claude Code 的机制。**Codex 等不提供这套 hook，硬底线不会运行、安全保证不成立** —— 因此本项目按 Claude Code 设计与验证，不维护 `.codex/hooks` 镜像，也不声称兼容 Codex 运行时。
- **Codex 的位置**：Claude Code 为主，Codex 为辅。Codex 可用于异构复审、交战建议、分歧补盲或被委派协作；不另立运行时或安全边界，仍以同一运行态台账、证据门、guard/hook 边界与复审要求为准。
- **路由**：用 [`docs/ROUTER.md`](docs/ROUTER.md) 决定哪些指引生效；始终生效的有 `CLAUDE.md` · `docs/WORKFLOW.md` · `docs/cognition/README.md` · `src-safety-boundary` skill。
