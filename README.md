# 寻迹 (Xunji)

> **中文** | [English](README.en.md)

寻迹是面向 Claude Code / Codex 的**自主红队工作区**，专注于 Web 打点（initial
access）。它支撑 AI 驱动的漏洞发现与利用，同时让整个过程**可审计、证据绑定、并被一条
机器强制的硬底线兜住**。

它不是扫描器、不是开箱即用的批量利用套件、也不是 JSON 编排器 —— 它给 AI 的是
**判断纪律、接地的识别知识、运行态结构、以及一条机器强制的硬底线**（见下方"设计思路"）。
驱动者亲手编写的武器化利用是**允许的（方法自由）**；只有**对目标自动执行的不可逆危害**
才被硬拦。

## 项目逻辑（Project Logic）

核心思路：

```text
单一 AI 驱动者
  -> 维护书面运行态
  -> 自主选择下一个探索前沿
  -> 用证据验证
  -> 复审浅层工作与假阳性
  -> 只报告证据支持的结论
```

只要还有安全的开放前沿，AI 就**不应**等用户来指定下一个漏洞类别。它应自己选定前沿、
记录理由，并持续推进，直到该前沿被确认、被否决、因阻碍被搁置（deferred），或以
Type B 推理收口（closed）。

## 设计思路（Design Philosophy）

整个项目建立在**一个决断**和**三根支柱**之上。

### 核心轴：管"效果"，不管"方法"（gate EFFECTS, not METHODS）

被约束的，永远是**一个动作对活靶造成的不可逆效果、以及由谁按下执行键** —— 绝不是技术
本身。构造并编写武器化利用（RCE 链、鉴权绕过、反序列化 gadget、上传拿 shell、提权、
C2 / 反弹 shell / webshell 代码）是**方法，而方法是自由的**；0day 发现就在这里。唯一的
硬线，是**对目标自动执行的、不可逆 / 以伤害为目的的效果**（销毁、拖库、DoS、资金移动）
—— 而这条线是按**效果**、在**代码里**、于**运行时**划定的，绝不靠文件名或某个被禁的
关键词。

为什么这很关键：一条让 AI 畏手畏脚的软约束（"别写那个 exploit""别提那个工具名"）是
**本末倒置** —— 它阉割了操作者真正需要的能力，却对安全毫无贡献。安全是 hook 的活，
按效果管；能力是驱动者的活，没有方法上限。

### 三根支柱，刻意**不做** playbook

框架只给 AI 三样东西，并拒绝成为第四样：

1. **判断纪律** —— 如何选前沿、如何掂量证据、如何抵抗假阳性、如何不过早收手
   （`docs/cognition/`、`docs/WORKFLOW.md`）。
2. **接地知识** —— 真实产品的识别签名与弱点锚点，作为**变体分析输入**，绝不作为
   开箱即用的 payload（`knowledge/`）。
3. **机器强制的硬底线** —— 按效果划定的拒绝边界（`.claude/hooks/`）。

它**不是**清单 / playbook / 扫描器跑批 / JSON 编排器。早期的编排器架构已被**刻意移除**；
`tools/check_rules.py` 的存在就是为了防它回潮。论点是：一个有能力的模型 + 纪律 +
接地识别 + 硬底线，胜过任何固定 playbook —— 而 playbook 只会给模型封顶。

### 单一自主驱动者，author-and-handoff（编写并交接）

一个 AI 完成推理、选工具、利用、验证、起草报告。它把操作者关心的两件事**分开对待**：

- **编写（Author）** —— 写出完整、可运行、直至完整影响的利用代码，交到操作者手上。
  **没有上限**；对授权目标**少交付**利用代码是一种失败，与"证明不足"对称。
- **自动执行（Auto-execute）** —— 驱动者自己朝活靶发射的部分。默认**证明即止
  （proof-level）**：证明漏洞真实存在，即停。在活靶上更深入由**操作者把关**，通常以
  代码交付、由操作者在监督下运行。

### 证据高于自信（Evidence over confidence）

一个信号不是结论；模型自信不是证据；单次观察永远不算确认。运行目录就是审计轨迹，一个
发现只在**其证据支持的 certainty** 上报告（任何 ≥ 0.8 的结论都要带一条已记录的
对照 / 复现）。"证明即止"被落地为一套**无害验证配方**
（`docs/cognition/harmless-verification.md`）：用**假的 / 非生产 / 单发 / 只读**的输入，
让一个端点的**响应**证明缺陷存在，而不触发它的危害。

## 设计亮点（Design Highlights）

让它不止是"一个 AI 加一段提示词"的地方：

### 1. 效果 × 执行者的安全模型，由代码强制

一个三层模型 —— **自主（可逆 / 证明级）** · **操作者把关（偏不可逆但合法）** ·
**硬拦（永不正当、机器阻断）** —— 按**触碰了什么**和**由谁执行**分级，而非按技术。
PreToolUse hook（`safety_gate.py`）只按效果强制**自动执行的硬上限**；它从不碰驱动者
为操作者编写的代码。

### 2. 一个连"你自己访问"都会保护的 guard 层

所有主动工具都走 `tools/harness/guard.py`：限速器（禁高频）、响应体上限（禁拖库）、
鉴权失败计数（防失控）。两项新增堵上了实战暴露的一个失败 —— 驱动者因过度探测而
**打爆自己的访问**：

- **HostHealth 熔断器** —— 对某主机连续 N 次传输失败 → 自动退避（别再猛捶一个已经
  开始封你的主机，也别把它误读成"整站封了我 IP"）。
- **SessionBudget 会话预算** —— 一个全局滚动窗口的请求计数器，当整场作业请求量偏高时
  告警。（"别 DoS 目标"的对偶：别烧光你自己的可达性。）

### 3. 反过早收口系统（最大亮点）

最具特色的部分。实战表明最深的失败不是能力 —— 而是一个急切的模型**过早收口**：凭
响应头不看内容就把 N 台主机一锅端（lump）、把"我够不着它"等同于"它是安全的"、或把一个
错误结论打到满自信。**自评治不了自评偏见。** 于是：

- **逐资产检视台账** —— `classify_hosts.py` 按**实时内容**（不是 Server 头）给每台主机
  指纹，写入结构化的 `coverage.json`；`check_run.py` 在**每一次**运行时读它，列出必须
  调查的"独立应用"候选 —— 让"一锅端"在**发生当下**就被点出来，而不是拖到最后。
- **独立 Reviewer，作为硬门** —— 在任何"探索够了 / 没有攻击面"的论断之前，一个
  **全新上下文的子 agent**（无收口利益绑定）审计本次运行
  （`review/independent-reviewer.md`）。`check_run.py` 对**没有
  `Independent Review` 记录**的收口论断**硬性失败**。这把复审从"自评（可被糊弄）"变成
  "独立（被强制）"—— 可移植的设计写在 `review/review-mechanism.md`。
- **台账矛盾 + certainty 管控** —— 一个被另一条目 `Refutes:`（否证）却仍带 ≥ 0.8 的
  结论会被标出（别污染台账）；任何 ≥ 0.8 的条目必须带 `Control:` / `Replicated:` 字段。
- **够不着重跑队列** —— 仅仅是"够不着"（`coverage.json` 里 `reachable=false`）的资产
  构成一个标准化队列；`rerun_deferred.py` 稍后从**任意出口**重新探测它们。"现在够不着"
  保持为一条活的待办，而非一次无声的收口。

### 4. 接地知识，绝不武器化

`knowledge/*.md` 承载识别签名 + 弱点锚点（弱点类别 + 机理 + CVE/CNVD 引用 + 来源），
并**明确不含 payload、步骤或开箱即用套件** —— `check_knowledge.py` 强制这份契约。
这个知识库意在**随你在实战中真正遇到的东西生长**（一条收口期纪律会为任何新指纹的
技术栈补上条目）。

### 5. 一条小而无依赖、全程走 guard 的工具流水线

`ingest_recon`（把 recon 报告折叠成资产表 + 可达性矩阵）→ `classify_hosts`（按内容
逐主机分类 → `coverage.json`）→ `fetch_assets`（抓**全部** SPA chunk + 完整性断言，
让端点枚举真正完整）→ `probe` / `render` / `scan`（主动验证传感器，全程走 guard、
UTF-8 安全）→ `rerun_deferred`（出口重跑队列）。纯标准库；Playwright 是唯一的可选
依赖（浏览器工具）。

### 6. `check_rules` 守的是架构，不是武器

仓库纪律检查"已废弃的编排器 / playbook 面"没有回潮、且教义文件存在 —— 它**刻意不**
管 exp/poc/scanner 文件（那些是方法、自由；危害在运行时按效果管）。这让框架不会退化回
playbook，同时把武器化部分完全不设限。

## 权限模型（Authority Model）

这是 Claude Code / Codex 的工作区。当用户要求改动项目时，驱动者可编辑项目文件；在一次
运行期间，它拥有运行级文件。

这里**不运行 DeepSeek**。DeepSeek 有自己独立的项目，嵌套在 `deepseek-project/`，有自己
的基线。不要跨那条边界操作（见"路由"）。

## 路由（Routing）

用 [docs/ROUTER.md](docs/ROUTER.md) 决定哪些指引生效。

始终生效：

- [CLAUDE.md](CLAUDE.md)
- [docs/WORKFLOW.md](docs/WORKFLOW.md)
- [docs/cognition/README.md](docs/cognition/README.md)
- [.claude/skills/src-safety-boundary/SKILL.md](.claude/skills/src-safety-boundary/SKILL.md)

仅按需加载（仅当操作者明确要求用 SRC skill 时 —— 不自动加载）：

- [.claude/skills/src-rules/SKILL.md](.claude/skills/src-rules/SKILL.md) —— SRC /
  众测项目规则（如 EDUSRC 无害化原则）。

嵌套的 DeepSeek 项目：

- `deepseek-project/` 是本项目独立的 DeepSeek 副本。它在自己的根目录里由 DeepSeek 驱动，
  不属于本工作区的范围。

## 文件地图（File Map）

### 核心规则

- `CLAUDE.md`：始终加载的简短操作契约。
- `docs/ROUTER.md`：确定性的模式路由与权限边界。
- `docs/WORKFLOW.md`：运行态工作流与文件模板。
- `docs/cognition/README.md`：判断纪律、假阳性抵抗、浅层工作的气味。

### 安全边界

- `.claude/settings.json`：为 Bash 注册 PreToolUse hook。
- `.claude/hooks/safety_gate.py`：确定性的拒绝边界。
- `.claude/hooks/safety_rules.json`：拒绝规则配置。
- `.claude/skills/src-safety-boundary/SKILL.md`：只管边界的 skill。
- `.claude/skills/src-rules/SKILL.md`：SRC / 众测项目规则 —— 仅在操作者明确要求时加载，
  非始终生效。

### 嵌套的 DeepSeek 项目

- `deepseek-project/`：本项目一份独立、自包含的 DeepSeek 副本，有自己的基线、由
  DeepSeek 驱动。独立于本工作区；唯一关系是嵌套在其下。

### 运行态（Run State）

每个授权目标的运行都落在：

```text
runs/<target_slug>_<date>/
  target.md
  surface.md
  frontier.md
  hypotheses.md
  evidence.md
  false_positive.md
  decisions.md
  review.md
  report.md
```

运行目录就是审计轨迹。结论**不**从聊天记忆、模型自信或单个无归因信号上确认。

### 模板

- `docs/templates/run/`：可在开始新目标时复制的空运行文件。

### 本地检查

- `tools/check_rules.py`：架构漂移守卫 —— 检查已废弃的 JSON 编排器 / playbook 面
  （legacy 目录 + 引用）没有被重新引入、且教义文件存在。它不管武器：exp/poc/scanner
  代码是方法（自由）；不可逆危害在运行时由 hook 按效果管，不靠文件名。
- `tools/check_hook.py`：用被拦 / 放行的命令样例测试本地 hook。
- `tools/check_run.py`：运行态门 —— 必备审计文件 / 标记，外加反过早收口守卫（无
  `Independent Review` 记录的收口**硬性失败**；对未检视资产、台账矛盾、≥0.8 却无对照的
  情形给出咨询性告警）。
- `tools/check_knowledge.py`：让 `knowledge/` 保持接地（无 payload/exploit/step 字段；
  每个锚点都带引用 + 来源）。

### 主动验证与作业工具

全部走 `tools/harness/guard.py`（限速、响应体上限、熔断器、会话预算），并输出 UTF-8。

- `tools/ingest_recon.py`：把 recon/OSINT 报告折叠成可直接进 `surface.md` 的资产表、
  入口点、可达性矩阵。
- `tools/classify_hosts.py`：按实时内容逐主机分类 → 结构化 `coverage.json`（反一锅端的
  检视台账）。
- `tools/fetch_assets.py`：抓取一个 SPA 引用的**全部** JS（含 webpack chunk），并在
  宣称"端点枚举完成"前做完整性断言。
- `tools/rerun_deferred.py`：稍后从任意出口重新探测"够不着（egress 受限）"的资产。
- `tools/probe.py` · `tools/render.py` · `tools/scan.py`：主动验证传感器
  （HTTP 探测器 / 无头浏览器 / 扫描器即传感器封装）。

## 安全模型（Safety Model）

hook 拦截不可逆销毁（主机 / 文件抹除，加上数据销毁 —— DROP/TRUNCATE/无范围
DELETE/UPDATE）、目标资源删除、海量数据外带 / 数据库拖库、资金移动，以及 DoS 式 /
高频行为。上传一个证明用产物**不**被拦（由驱动者裁量）。拿 shell、越过 Web 层、以及其他
更重的动作同样**不被机器拦**，但需**操作者把关** —— 驱动者先取得操作者同意。

被拦的动作**不会**因人工批准而解锁。换一个安全、非破坏性的证明方式。

scope 不写进 hook。操作者是最高权威、运行授权目标；他们的指令凌驾于软约束之上，是除了
上述硬边界之外处处生效的控制性命令。

## 安装（Setup）

全新 clone 几乎不需要任何东西：核心工具链**零第三方依赖**（仅 Python 标准库）。唯一的
可选依赖是 Playwright，只被浏览器工具用到（`render.py`、验证码求解器）。

### 唯一的硬性要求

- **PATH 上有 Python ≥ 3.10。** 覆盖 PreToolUse hook（`safety_gate.py`）、`check_*`
  检查器、`probe.py` / `scan.py`。hook 用 `$CLAUDE_PROJECT_DIR` 接线（无硬编码路径），
  因此跨机可移植、无需改动。

### 浏览器工具（可选 —— 仅供 `render.py` / 验证码求解）

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Linux/macOS: source .venv/bin/activate
pip install playwright
playwright install chromium
```

`render.py` 与验证码求解器在 venv 的 python 下运行（Windows 上
`.venv\Scripts\python.exe`，其他系统 `.venv/bin/python`）。跳过它不影响 `probe.py`、
`scan.py`、hook 或检查器。

### 目录与状态

`runs/`、`knowledge/`、`poc_library/` 已通过随仓的 `.gitkeep` / `README` 文件存在。
guard 的限速 / 计数状态（`tools/harness/.state/`）在首次运行时自动创建；`reports/` 与
`poc/` 按需创建。无需手动建目录。

### clone 不会恢复的部分（刻意如此）

- **自动记忆** 存在仓库之外（`~/.claude/projects/.../memory/`），按机器隔离 —— clone
  不携带它。
- **武器化 0day 利用**（`poc_library/xday/`）：仓库**只保留 `xday/` 文件夹结构**
  （`.gitkeep`）；具体 exploit 源码 / 二进制**留在本地、不进仓、不 push**（操作者裁量）。
  方法自由是指允许编写,不等于必须发布——武器内容带外传输。
- **接地知识库**（`knowledge/*.md`）**随仓发布**、clone 即得：它是识别签名 + 弱点锚点
  （接地、非武器，由 `check_knowledge.py` 把关），意在跨机共享、随实战生长。
- **其余仍 git 忽略、clone 不会恢复**：`tools/poc_ours_upload/`（某 xday 武器的冗余旧
  构建）、`runs/`、`reports/`、`poc/`，以及任何真实目标发现物 —— 需要时带外传输。
- **运行发现**（`runs/<target>/`）不提交；较旧的运行还引用机器本地的 OSINT 路径，在别处
  不存在。
- **`.claude/settings.local.json`**（权限白名单）是本地的 —— 在新机器上重新授权一次。

## 本地检查（Local Checks）

```powershell
.\.venv\Scripts\python.exe tools\check_rules.py
.\.venv\Scripts\python.exe tools\check_hook.py
.\.venv\Scripts\python.exe tools\check_run.py runs\<target_slug>_<date>
```

这些工具只检视本地文件与 hook 行为，不接触目标。
