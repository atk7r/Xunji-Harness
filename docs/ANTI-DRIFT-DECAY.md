# Anti-Drift Decay -- 长对话规则衰减对策

Xunji 自主驱动依赖 CLAUDE.md + anti-drift anchor hook + Stop gate 约束行为。
但在长对话（20-30 轮后）中，模型对中段规则的注意力衰减，出现三类漂移：

- **自主性衰减**：列出选项等待确认而非直接执行
- **回合协议违规**：结尾出现 ? / 是否 / 继续还是（`output_gate.py` 可检测但仅警告）
- **隧道视野**：忘记 Reason pass（重读整个 frontier），只盯着当前 front

三种已提出的对策如下，下面逐条给出在当前框架下的可落地设计。

---

## 一、现有防漂移机制盘点

| 层级 | 机制 | 触发时机 | 作用 | 局限性 |
|------|------|----------|------|--------|
| L0 静态规则 | `CLAUDE.md` | SessionStart | 项目角色/操作循环/自主驱动/证据门 | 早期 context，长对话中沉入 "lost in the middle" |
| L1 动态注入 | `tools/anti_drift.py` | UserPromptSubmit | 每回合在 recency zone 注入绑定规则 + 当前 run 状态 | 规则是**静态列表**，不随会话长度/阶段自适应；无会话级状态追踪 |
| L2 末尾检测 | `.claude/hooks/output_gate.py` | Stop | 检测 Assistant 回复末尾的漂移话术，打印 systemMessage 警告 | fail-open advisory only；检测到只警告，不改变下一回合的行为倾向 |
| L3 收口闸门 | `.claude/hooks/run_gate.py` | Stop | 收尾阶段结构性硬门（覆盖台账/假证据/复审） | 仅在"终版报告已写入"时触发，不覆盖中段自主性衰减 |
| L4 安全边界 | `.claude/hooks/safety_gate.py` | PreToolUse | 阻断不可逆破坏性命令 | 不涉及行为协议 |
| L5 行为监控 | `sentinel/monitor.py` | 全域 | 行为分类 + 检测器 + 断路器（observe-only） | 不注入纠正信息 |

**现有机制的共同缺口**：都是**无状态、无自适应**的——不知道这是第几轮、不知道模型已漂移多少轮、不知道上次"Reason pass"是多久前。

---

## 二、关键架构约束：自指悖论与外部化原则

### 2.0 自指悖论

任何在 **UserPromptSubmit hook**（模型产出的**上游**）中维护漂移计数器的设计都存在自指悖论：

- `anti_drift.py` 在模型**产出之前**运行，其输出注入到模型上下文
- 如果模型本身已漂移，它看到的计数是**上一轮 Stop 时**的陈旧快照
- 模型无法可靠地"自我计数漂移"——计数者与被计数者是同一实体
- 漂移信号**只有在模型产出文本之后**才可见

**结论：漂移检测必须外部化到 Stop hook（output_gate.py），计数器由钩子维护，anti_drift.py 只读不写。**

### 2.1 外部可无状态检测的信号（output_gate.py 在 Stop 时已经能看到）

| 信号 | 检测方式 | 对应漂移类型 |
|------|----------|------------|
| 输出末尾出现 `?` / `是否` / `继续还是` | 尾 500 字符正则匹配 | 回合协议违规 |
| 输出中出现编号选项列表（`1. xxx\n2. xxx`） | 正则匹配 `^\d+\.\s` 行 ≥ 2 条 | 自主性衰减（列选项等确认） |
| `frontier.md` mtime 距今超过阈值 | `os.stat` 时间戳比较 | Reason pass 遗漏 |
| 连续多轮未 Exec 任何新 probe | 计数器（output_gate 维护） | 停滞 |
| 连续多轮围绕同一 front（无 front 切换） | 计数器（output_gate 维护） | 隧道视野 |

**原则**：output_gate.py 在每次 Stop 时检测上述信号，将结果写入 `runs/<active_run>/state/session_state.json`；anti_drift.py 在每次 UserPromptSubmit 时**只读**该文件，根据状态选择闪卡模式。根目录 `session_state.json` 仅作为历史兼容读取路径，新的写入权威是 `state/session_state.json`。检测到的信号直接作用于**下回合**——模型不需要"意识到"自己漂移。

### 2.2 session_state.json — 由谁写入

**写入者：`output_gate.py`（Stop hook，模型产出之后）**
**读取者：`anti_drift.py`（UserPromptSubmit hook，模型输入之前）**

这是一个单向数据流：Stop 检测 → 写文件 → 下回合 UserPromptSubmit 读取 → 注入纠正信号。模型永远不参与计数过程。

---

## 三、对策一：强制重读速查卡（Flashcard Injection）—— 修正后

### 3.1 实现方案

**核心思路**：增强 `anti_drift.py`，从 `session_state.json` **读取** output_gate.py 维护的会话状态，根据状态选择分模式闪卡注入，让重复注入的规则随会话状态变化而变化，避免模型对"一样的文字"产生注意力习惯化。

**修改文件**：
- `.claude/hooks/output_gate.py` — **新增**会话状态检测 + `session_state.json` 写入（写）
- `tools/anti_drift.py` — **新增**会话状态读取 + 分模式闪卡注入（读）

**数据流**：
```
Stop 事件 → output_gate.py 检测漂移信号 → 写 session_state.json
                                                    ↓
UserPromptSubmit 事件 → anti_drift.py 读 session_state.json → 选择闪卡模式 → 注入
```

#### 3.1.1 会话状态文件 schema（output_gate.py 写入）

```json
{
  "started_at": "2026-06-22T14:30:00+08:00",
  "started_at_ts": 1750573800.0,
  "total_turns": 27,
  "last_flashcard_at": 15,
  "last_frontier_read_at": 22,
  "last_direction_switch_at": 18,
  "active_front": "F-003",
  "active_front_turns": 9,
  "drift_signals": 3,
  "last_probe_turn": 25,
  "stagnation_turns": 2,
  "flashcard_mode": "refocus"
}
```

字段说明：

| 字段 | 类型 | 写入者 | 含义 |
|------|------|--------|------|
| `started_at` | str | output_gate（首次创建） | 会话开始时间 ISO 格式 |
| `started_at_ts` | float | output_gate（首次创建） | 会话开始时间 Unix 戳 |
| `total_turns` | int | **output_gate**（每次 Stop +1） | 累计回合数 |
| `last_flashcard_at` | int | anti_drift（只读后用 output_gate 日志交叉校验）或 output_gate | 上次闪卡注入的回合号（供 anti_drift 判断间隔） |
| `last_frontier_read_at` | int | **output_gate**（检测 frontier.md mtime） | 上次 Reason pass 的回合号 |
| `last_direction_switch_at` | int | **output_gate**（检测 active_front 变化） | 上次切换 front 的回合号 |
| `active_front` | str | **output_gate**（解析 frontier.md） | 当前活跃前沿 |
| `active_front_turns` | int | **output_gate**（连续同一 front 计数） | 当前 front 已连续多少轮 |
| `drift_signals` | int | **output_gate**（每次检测到漂移 +1） | 累计漂移信号次数 |
| `last_probe_turn` | int | **output_gate**（检测到新 probe 执行时更新） | 最后一次执行新 probe 的回合号 |
| `stagnation_turns` | int | **output_gate**（连续无新 probe 计数） | 连续多少轮未执行新 probe |
| `flashcard_mode` | str | anti_drift（注入时回写，供 output_gate 交叉校验） | 当前闪卡模式：normal/refocus/refresh/pre_report |

**注意**：`flashcard_mode` 由 anti_drift 在注入闪卡后**回写**，这是一个**非计数字段**（不参与漂移检测），仅用于 output_gate 交叉校验"注入是否真的生效了"。这不会重新引入自指悖论，因为模式选择依赖的是 output_gate 写入的客观计数器。

#### 3.1.2 output_gate.py 新增检测逻辑

在现有 `detect_drift()` 之外，output_gate.py 新增以下检测函数（每次 Stop 调用）：

```python
def detect_option_list(msg: str) -> bool:
    """检测输出中是否出现编号选项列表（自主性衰减信号）"""
    lines = msg.splitlines()
    option_lines = [l for l in lines if re.match(r'^\d+[\.\)、]\s', l.strip())]
    return len(option_lines) >= 2

def check_reason_pass(run_dir: Path, state: dict) -> int | None:
    """检测 frontier.md 的 mtime：如果距上次记录有变化，返回当前 turn 作为新的 last_frontier_read_at"""
    f = run_dir / "frontier.md"
    if not f.exists():
        return None
    last_read_at = state.get("last_frontier_read_at", 0)
    last_read_ts = state.get("_frontier_mtime", 0)
    current_mtime = f.stat().st_mtime
    if current_mtime > last_read_ts:
        return state.get("total_turns", 0)
    return None

def load_session_state(run_dir: Path) -> dict:
    """读取现有 session_state.json，不存在则返回初始状态"""
    sf = run_dir / "session_state.json"
    if not sf.exists():
        return {}
    try:
        return json.loads(sf.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_session_state(run_dir: Path, state: dict) -> None:
    """写入 session_state.json"""
    sf = run_dir / "session_state.json"
    sf.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
```

#### 3.1.3 output_gate.py 主流程修正

在 `main()` 中，现有 drift 检测之后，新增状态更新流程：

```python
# 1. 加载当前状态
run_dir = find_active_run(RUNS)
state = load_session_state(run_dir) if run_dir else {}

# 2. 初始化首次状态
if not state:
    state = {
        "started_at": datetime.now().isoformat(),
        "started_at_ts": time.time(),
        "total_turns": 0,
        "active_front_turns": 0,
        "drift_signals": 0,
        "stagnation_turns": 0,
    }

# 3. 递增 total_turns（每次 Stop 必然 +1）
state["total_turns"] = state.get("total_turns", 0) + 1

# 4. 检测漂移信号
drift_hits = detect_drift(msg)
option_list = detect_option_list(msg)
if drift_hits or option_list:
    state["drift_signals"] = state.get("drift_signals", 0) + 1

# 5. 检测 Reason pass（frontier.md mtime 变化）
rp_turn = check_reason_pass(run_dir, state)
if rp_turn is not None:
    state["last_frontier_read_at"] = rp_turn
    state["_frontier_mtime"] = (run_dir / "frontier.md").stat().st_mtime

# 6. 检测 front 切换与隧道视野
current_front = parse_active_front(run_dir)  # 从 frontier.md 解析
prev_front = state.get("active_front")
if current_front == prev_front:
    state["active_front_turns"] = state.get("active_front_turns", 0) + 1
else:
    state["active_front_turns"] = 1
    state["last_direction_switch_at"] = state["total_turns"]
state["active_front"] = current_front

# 7. 检测停滞（需从 event 中检查 tool calls）
# output_gate 的 Stop event 包含 last_assistant_message，但不直接包含 tool_use 信息
# 停滞检测降级方案：如果 output 长度 < 阈值 且无 probe 相关关键字 → 疑似停滞
if not _output_has_probe_action(msg):
    state["stagnation_turns"] = state.get("stagnation_turns", 0) + 1
else:
    state["stagnation_turns"] = 0
    state["last_probe_turn"] = state["total_turns"]

# 8. 写入
save_session_state(run_dir, state)
```

**注意**：output_gate.py 的 Stop event 中可用的字段有限（`last_assistant_message`、`stop_hook_active`）。停滞检测的精确版本需要检查是否调用了 probe/scan 工具，这信息在 Stop event 中不一定直接可用。**MVP 降级方案**：用文本特征判断——如果输出末尾是 "下一行动" 且无新 probe 描述 → 标记停滞。

#### 3.1.4 anti_drift.py 闪卡模式判定（读 session_state.json，不写计数器）

```python
def _load_session_state(run: Path) -> dict:
    """只读 session_state.json；不存在或损坏 → 返回 {}"""
    sf = run / "session_state.json"
    if not sf.exists():
        return {}
    try:
        return json.loads(sf.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _flashcard_mode(run: Path, state: dict) -> str:
    """Return: 'normal' | 'refocus' | 'refresh' | 'pre_report'
    
    所有判定依据来自 output_gate.py 写入的 session_state.json，
    anti_drift.py 只读不写计数器。"""
    if not state:
        return "normal"
    
    turns = state.get("total_turns", 0)
    active_turns = state.get("active_front_turns", 0)
    
    # REFOCUS: 同一 front 超过 8 轮无新增 ≥0.8 证据 → 隧道视野风险
    if active_turns >= 8 and not _recent_confirmation(run, turns=8):
        return "refocus"
    
    # REFRESH: 距上次闪卡超过 12 轮 → 规则逐渐下沉
    last_flash = state.get("last_flashcard_at", 0)
    if turns - last_flash >= 12:
        return "refresh"
    
    # PRE_REPORT: report.md 在最近 5 轮内被修改
    rpt = run / "report.md"
    if rpt.exists():
        rpt_age = time.time() - rpt.stat().st_mtime
        if rpt_age < 600:  # 10 min
            return "pre_report"
    
    # 漂移累积：output_gate 检测到 ≥2 次漂移信号
    if state.get("drift_signals", 0) >= 2:
        return "refocus"
    
    # 停滞：连续 ≥3 轮无新 probe
    if state.get("stagnation_turns", 0) >= 3:
        return "refocus"
    
    return "normal"
```

**关键改变**：`total_turns`、`drift_signals`、`active_front_turns`、`stagnation_turns` 全部由 output_gate.py 在 Stop 时写入。`anti_drift.py` 只负责**读取和判定**，并在注入闪卡后**回写** `last_flashcard_at` 和 `flashcard_mode`（这两个是注入行为本身的记录，不是漂移计数）。回写 `last_flashcard_at` 是为了让 output_gate 知道"提醒已发出"，避免重复触发。

#### 3.1.5 闪卡注入位置优化

当前 `anti_drift.py` 的输出作为 `systemMessage`（通过 `print()` to stdout）注入到 **下一轮用户消息之前**（UserPromptSubmit hook 的输出），位于 recency zone 的**最顶部**——这是注意力最强的位置。

**不改变注入位置**，只改变注入内容的**首尾结构**：关键指令置顶，协议格式置底（详见第四节）。

### 3.2 速查卡内容（最多 8 行，基于实际项目规则）

速查卡在不同模式下内容不同，但都控制在 8 行以内。最通用的 `refresh` 模式速查卡：

```text
[速查卡 — 本轮必读]
1. 自主驱动: safe前沿非空 → 直接选下一个执行, 不列选项, 不等确认
2. Reason pass: 先重读整个 frontier.md(所有open+deferred) 再选 → 防隧道视野
3. 回合协议: 结尾仅"下一行动: F-xxx <动作>"或"BLOCKED: <外部原因>" 禁止?/是否/继续还是
4. 证据门: 单一信号≤0.5, ≥0.8才确认; 负面/环境结论也存产物; scripts≠证据(replay才有效)
5. 消费Guanlan跳过不可达; 前沿只重排不关闭(Reviewer的活); BLOCKED先判A类vs B类
6. ≥0.8确认后跑 peer_review; codex BLOCKER先修; 不过度工程(能进闸门别写prose)
7. 重breadth: 保持≥3不同资产的独立前沿; blocked不妨碍其他前沿继续
8. 操作员指令=最高优先级; hints.md 的内容每周期重读
```

`refocus` 模式（隧道视野/漂移累积/停滞风险）只显示前 4 行 + 当前 front 的特别提醒。`pre_report` 模式只显示第 4-6 行。

---

## 四、对策二：会话重启（Session Restart）—— 修正后

### 4.1 实现方案

**核心思路**：当累计轮数超过阈值时，stop hook 阻止会话继续，要求 driver 输出结构化交接摘要，然后由操作员在新会话中重启。

**修改文件**：
- `.claude/hooks/run_gate.py` — 新增从 `session_state.json` 读取 turn 计数 + 阈值检测
- `tools/anti_drift.py` — 从 `session_state.json` 读取 turn 计数，在接近阈值时预警

**新增文件**：
- `docs/templates/session_handoff.md` — 交接模板

**修正要点**：turn 计数不再由 anti_drift.py 维护，而是由 output_gate.py 写入 `session_state.json`，run_gate.py 和 anti_drift.py 都从该文件读取。

### 4.2 触发条件

| 阶段 | 条件 | 动作 |
|------|------|------|
| **预警 (Advisory)** | `total_turns >= 40`（从 session_state.json 读取） | anti_drift 注入："[会话预警] 已40轮，本轮完成后准备交接摘要…" |
| **软阻断 (Soft Block)** | `total_turns >= 50` 且 `stop_hook_active == false` | Stop hook 返回 `{"decision":"block","reason":"…写 session_handoff.md 后重启会话…"}` |
| **放行 (Bypass)** | `total_turns >= 50` 且 `stop_hook_active == true`（已因本 hook 续跑过一次）| 降级为 systemMessage advisory，不再 block（防死循环） |
| **强制放行** | `session_handoff.md` 已存在且 mtime > 当前 Stop 事件时间 | 放行，driver 已写完交接 |

### 4.3 触发条件的位置

**在 `run_gate.py` 中新增判断**（而非新建独立 hook）——理由：

- `run_gate.py` 已有的 `decide()` 函数天然支持 "首次 block / 再次 notify" 的防循环模式
- 共用 `find_active_run()` 和 `stop_hook_active` 逻辑，避免代码重复
- 收口闸门 + 会话重启 = 同一个 "结构闸门" 的两种触发条件

新增代码示意（`run_gate.py` 中）：

```python
SESSION_TURN_WARN = 40
SESSION_TURN_HARD = 50

def _session_state(run_dir: Path) -> dict:
    """从 output_gate.py 维护的 session_state.json 读取 turn 计数"""
    sf = run_dir / "session_state.json"
    if not sf.exists():
        return {}
    try:
        return json.loads(sf.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _handoff_exists(run_dir: Path, state: dict) -> bool:
    hf = run_dir / "session_handoff.md"
    if not hf.exists():
        return False
    # 交接文件必须在 turn >= warn 之后生成才有效（防止陈旧交接）
    return hf.stat().st_mtime > state.get("started_at_ts", 0)
```

在 `main()` 中的 `run_gate` 逻辑之后追加：

```python
state = _session_state(run_dir)
turns = state.get("total_turns", 0)
if turns >= SESSION_TURN_HARD and not _handoff_exists(run_dir, state):
    mode = "notify" if stop_active else "block"
    msg = _build_handoff_demand(run_dir, turns)
    if mode == "block":
        print(json.dumps({"decision": "block", "reason": msg}, ensure_ascii=False))
        sys.exit(0)
    else:
        print(json.dumps({"systemMessage": msg}, ensure_ascii=False))
```

**注意**：会话重启 hook 的优先级**低于** `gate_skipped`——如果操作员已在 report.md 标注 `session-restart: skip`，跳过此检查。这遵循 `run_gate.py` 已有的豁免模式。

### 4.4 交接格式

文件路径：`runs/<target_slug>_<date>/session_handoff.md`

```markdown
# Session Handoff — 2026-06-22T23:15:00+08:00

## Run State
- Run: <slug>_<date>
- Phase: <Driver / Hunter / Reviewer>
- Total turns this session: <N>
- Last Reason pass: turn <X> (on front F-<xxx>)

## Frontier
- Active front: <F-xxx> — <summary>
- Open: <count> — <list with one-line status>
- Deferred: <count> — <list with reason>
- Blocked (Type A): <list>
- Blocked (Type B, pending close/defer): <list>

## Evidence Summary
- Confirmed (>=0.8): <N> — <key IDs>
- Suspected (0.5-0.8): <N>
- Rejected / False Positive: <N>

## Pending
- [ ] <next specific action with front ID>
- [ ] <next specific action>

## Operator Hints Active
- HINT-<xxx>: <summary> (turn <N>)
<!-- or: None -->

## Decisions (last 5)
- <turn>: <decision and rationale>

## Restart Instructions
Copy the run slug above and tell the new session:
"Continue run runs/<slug>_<date>. Read session_handoff.md first."
```

### 4.5 新会话冷启动

新会话无需额外机制。`CLAUDE.md` + `anti_drift.py` 自动加载，`anti_drift.py` 检测到 `session_handoff.md` 存在时在 anchor 中追加一行：

```text
  · 会话交接存在: 先读 runs/<slug>/session_handoff.md 再继续
```

---

## 五、对策三：规则首尾分布（Priority-Positioned Rules）

### 5.1 实现方案

**核心思路**：不增加新内容，而是**重新排列已有规则**，把"容易被遗忘的中段规则"放到注意力衰减曲线上更有利的位置。

**修改文件**：
- `tools/anti_drift.py` — 重组 `BINDING_RULES` 顺序 + `build_anchor()` 输出结构
- `CLAUDE.md`（可选，效果有限）— 移动 Autonomous Drive 节到文件末尾

**此对策不涉及任何状态追踪，无自指悖论风险，独立于对策一和对策二。**

### 5.2 anti_drift 输出结构调整

**当前结构**（整体是扁平列表）：

```
[ANTI-DRIFT ANCHOR — 每回合自检, 漂移=没按下面走]
绑定规则: 中文回答 · 自主驱动 · 回合协议 · 消费Guanlan · 证据门 · 不过度工程 · 阶段检查点 · codex复审
当前 run: xxx (最后改动 Xm 前) | 阶段: Driver
  · evidence 3 条 / confirmed 0
```

**调整后结构**（首尾分离）：

```
[ANTI-DRIFT ANCHOR — 每回合自检]

=== 本轮必做（优先级自上而下）===
1. Reason pass: 重读整个 frontier.md（所有 open + deferred）再选行动
2. 自主驱动: safe 前沿非空 → 直接选下一个执行，不列选项不等确认
3. 回合协议: 结尾仅 "下一行动: F-xxx <动作>" 或 "BLOCKED: <原因>"；禁止 ? / 是否

=== 当前状态 ===
run: xxx (Xm 前) · 阶段: Driver · evidence 3 / confirmed 0 · 同一 front 已 5 轮
  · codex 检查点 due: >=0.8 确认且评审未覆盖 → 跑 peer_review --into-run

=== 约束速查（需要时再看）===
证据门: 单一信号<=0.5, >=0.8才确认 · 负面结论也存产物 · scripts!=证据(replay有效)
消费Guanlan跳过不可达 · 不重做OSINT · 前沿只重排不关闭 · BLOCKED先判A类vsB类
breadth>=3独立前沿 · 不过度工程 · codex复审必须走CODEX_PROXY · 中文回答
```

**关键改变**：
1. "本轮必做"（Reason pass + 自主驱动 + 回合协议）置顶——这三条正是长对话中最先衰减的
2. 当前状态居中——连接规则与现实（其中 "同一 front 已 N 轮" 的数据来自 output_gate.py 写入的 session_state.json）
3. 约束速查置底——长尾规则，需要时扫一眼

### 5.3 CLAUDE.md 结构调整（可选，辅助）

将 `## Autonomous Drive` 和 `## Operating Loop` 两个节移到文件末尾（`## Repository Discipline` 之后）。理由：CLAUDE.md 在 SessionStart 加载，长对话中早期 context 沉入 "lost in the middle"，末尾内容反而获得 recency advantage。

**注意**：这个调整在长对话中效果有限（因为 CLAUDE.md 整体沉入中段），主要靠 anti_drift 的每轮注入。但作为无成本调整，值得做。

---

## 六、优先级排序与实施路线

### 6.1 三条对策对比

| 维度 | 对策三：首尾分布 | 对策一：速查卡（修正后） | 对策二：会话重启（修正后） |
|------|-----------------|--------------------------|---------------------------|
| 实现难度 | 极低（纯文本重排） | 中（output_gate 写状态 + anti_drift 读状态） | 高（多文件协作 + Stop 拦截） |
| 新增文件 | 0 | 0（仅改 output_gate.py + anti_drift.py） | 1（handoff 模板） |
| 自指悖论风险 | 零（不涉及计数） | 零（计数器由 output_gate 外部维护） | 零（计数器由 output_gate 外部维护） |
| 新增风险 | 零（内容调整，fail-safe） | 低（状态文件异常 → anti_drift fallback 静态规则；output_gate 写入失败 → 静默放行） | 中（Stop block 可能卡死会话，有防循环设计但需实战验证） |
| 每轮延迟增量 | 0ms | ~5ms（output_gate JSON 写 + anti_drift JSON 读） | 0ms（仅在 Stop 时检查） |
| 对隧道视野的效果 | 间接（Reason pass 置顶增加被注意概率） | 直接（refocus 模式强制提醒 + active_front_turns 外部计数） | 直接（新会话 = 完整 attention budget 重置） |
| 对回合协议的效果 | 直接（协议要求置顶） | 直接（output_gate 检测到漂移 → drift_signals 递增 → 触发 refocus） | 间接（新会话初始注意力高） |
| 对自主性的效果 | 直接（自主驱动置顶） | 直接（选项列表检测 → 触发 refocus） | 间接 |
| 可独立测试 | 是 | 是 | 是 |

### 6.2 推荐顺序

**Phase 1（立即，< 1 小时）：对策三 —— 规则首尾分布**

- 改动范围最小：只改 `anti_drift.py` 的 `BINDING_RULES` 排序 + `build_anchor()` 输出格式
- 零新增文件，零新增依赖，零自指悖论
- 可直接在现有会话中生效（下次 UserPromptSubmit 即可）
- 回滚成本 = 一次 git revert
- **ROI 最高：改动最小，但直接作用于每回合的注意力热点**

**Phase 2（1-3 天，Phase 1 生效后观察）：对策一 —— 强制重读速查卡（修正版）**

- **先改 output_gate.py**：新增 `session_state.json` 写入（检测 + 计数）
- **再改 anti_drift.py**：新增 `session_state.json` 读取 + 分模式闪卡注入
- 实现四种闪卡模式：normal / refocus / refresh / pre_report
- 新增 `detect_option_list()`、`check_reason_pass()` 等辅助函数
- selftest 扩展覆盖新逻辑（output_gate.py 和 anti_drift.py 两边）
- 需 2-3 个实际 run 验证效果
- **ROI 高：动态自适应注入，解决"模型对固定文本习惯化"的根因；外部计数消除自指悖论**

**Phase 3（Phase 2 稳定后）：对策二 —— 会话重启**

- 在 `run_gate.py` 中新增 `SESSION_TURN_WARN/HARD` 阈值检查（读取 output_gate 维护的 turn 计数）
- 新增 `docs/templates/session_handoff.md` 模板
- 需要在一次实际超长 run 中验证完整交接流程
- **ROI 中等：50 轮阈值在实践中只有长跑才触发；手动重启引入操作员中断成本**

### 6.3 为什么首尾分布排第一

1. **零风险**：改变的是规则的排列顺序，不增不减任何逻辑。即使格式错误，fallback 路径（`except: print(static rules)`）不受影响。
2. **即时生效**：`anti_drift.py` 在每次 UserPromptSubmit 运行，下次用户输入即看到新格式。
3. **解决根因**：模型行为衰减的本质原因是"中段信息的注意力权重随对话增长而下降"。把关键规则放到 recency zone 的**绝对顶部**（反比衰减），比增加更多检测更能从源头减少违规。
4. **独立可测**：可以立即对比调整前后的漂移频率（通过 `sentinel` 的 drift 检测计数）。

---

## 七、最小可行实现（MVP）

### 7.1 只改哪两个文件

| 文件 | 改动性质 | 改动量 |
|------|----------|--------|
| `.claude/hooks/output_gate.py` | **新增** session_state.json 写入逻辑（检测 + 计数） | ~80 行 |
| `tools/anti_drift.py` | **新增** session_state.json 读取逻辑（闪卡模式选择）+ 回写 flashcard 字段 | ~60 行 |

### 7.2 加哪几个字段

output_gate.py 在 `session_state.json` 中维护的字段（每次 Stop 更新）：

```
total_turns          int    ← 每次 Stop +1（最核心的计数器）
drift_signals        int    ← 检测到漂移时 +1
active_front         str    ← 从 frontier.md 解析
active_front_turns   int    ← 连续同一 front 的回合数
stagnation_turns     int    ← 连续无新 probe 的回合数
last_frontier_read_at int   ← 上次 Reason pass 的回合号
last_probe_turn      int    ← 上次执行新 probe 的回合号
last_direction_switch_at int ← 上次切换 front 的回合号
```

anti_drift.py 回写的字段（非计数器，仅记录注入行为）：

```
last_flashcard_at    int    ← 上次闪卡注入的回合号
flashcard_mode       str    ← 当前闪卡模式标识
```

### 7.3 MVP 数据流

```
每次 Stop:
  output_gate.py
    ├── detect_drift(msg) → 检测 ?/是否/继续还是
    ├── detect_option_list(msg) → 检测 1. xxx\n2. xxx
    ├── check_reason_pass(run, state) → 检测 frontier.md mtime
    ├── 更新 total_turns, drift_signals, active_front_turns, stagnation_turns
    └── 写入 session_state.json

每次 UserPromptSubmit:
  anti_drift.py
    ├── 读取 session_state.json
    ├── _flashcard_mode(run, state) → 判定 normal/refocus/refresh/pre_report
    ├── 根据模式生成闪卡内容
    ├── 注入到 recency zone
    └── 回写 last_flashcard_at, flashcard_mode
```

### 7.4 为什么这样安全

1. **output_gate.py 是 Stop hook**——它在模型产出**之后**运行，检测的是已经发生的漂移，不存在"模型看到自己的检测结果并自我修正"的循环。
2. **anti_drift.py 只读不写计数器**——它只读取 output_gate 写入的客观计数器来判定闪卡模式，不参与计数。
3. **检测到的信号作用于下回合**——output_gate 在 Stop 时写入 `drift_signals += 1`，下回合 anti_drift 读取到该值后触发 `refocus` 模式，注入更强的纠正提示。模型不需要"意识到"自己漂移。
4. **所有组件 fail-open**——output_gate 写入失败 → 静默放行；anti_drift 读取失败 → fallback 静态规则。不因状态追踪而阻断回合。

---

## 八、实施清单

### Phase 1 — 规则首尾分布

- [ ] `tools/anti_drift.py`: 重组 `BINDING_RULES` 为三段结构（本轮必做 / 当前状态 / 约束速查）
- [ ] `tools/anti_drift.py`: 改写 `build_anchor()` 输出格式，确保 <= 3KB（selftest 已有断言）
- [ ] `tools/anti_drift.py --selftest`: 扩展，验证新格式包含三段标记
- [ ] `CLAUDE.md` (可选): Autonomous Drive + Operating Loop 移到文件末尾
- [ ] 运行 `python tools/selftest_all.py` 确认零回归
- [ ] 在下一个 run 中观测 20+ 轮仍然有效

### Phase 2 — 速查卡（修正版：外部计数）

- [ ] `.claude/hooks/output_gate.py`: 新增 `detect_option_list(msg)` — 检测编号选项列表
- [ ] `.claude/hooks/output_gate.py`: 新增 `check_reason_pass(run_dir, state)` — 检测 frontier.md mtime
- [ ] `.claude/hooks/output_gate.py`: 新增 `load_session_state(run_dir)` / `save_session_state(run_dir, state)`
- [ ] `.claude/hooks/output_gate.py`: 在 `main()` 中集成状态更新流程（total_turns 递增 + 漂移信号计数 + front 追踪 + 停滞检测）
- [ ] `.claude/hooks/output_gate.py --selftest`: 新增 session_state 读写 + 检测逻辑测试
- [ ] `tools/anti_drift.py`: 新增 `_load_session_state(run)` — 只读 session_state.json
- [ ] `tools/anti_drift.py`: 新增 `_flashcard_mode(run, state)` — 四模式判定（读计数器，不写计数器）
- [ ] `tools/anti_drift.py`: `build_anchor()` 集成模式判断 + 闪卡内容生成
- [ ] `tools/anti_drift.py`: 注入后回写 `last_flashcard_at` 和 `flashcard_mode`（仅此两字段）
- [ ] 闪卡文案写入 `BINDING_RULES` / 新增 `FLASHCARD_MODES` 常量
- [ ] `tools/anti_drift.py --selftest`: 新增模式判定 / 状态读取测试
- [ ] 运行 `python tools/selftest_all.py`

### Phase 3 — 会话重启

- [ ] `docs/templates/session_handoff.md`: 新建交接模板
- [ ] `.claude/hooks/run_gate.py`: 新增 `_session_state()` / `_handoff_exists()` — 从 session_state.json 读取 turn 计数
- [ ] `.claude/hooks/run_gate.py`: 新增 session-turn 阈值阻断逻辑
- [ ] `.claude/hooks/run_gate.py`: `_selftest()` 新增 session-turn 阈值测试
- [ ] `tools/anti_drift.py`: 检测 `session_handoff.md` 存在时在 anchor 中追加提示
- [ ] 运行 `python tools/selftest_all.py`
- [ ] 一次实际超长 run（>= 40 轮）中验证完整交接流程

---

## 九、设计决策备注

1. **漂移检测外部化是架构红线**：任何需要在模型上下文内"自我计数"漂移的设计都重蹈自指悖论。计数器必须由 Stop hook（output_gate.py）在模型产出**之后**维护，由 UserPromptSubmit hook（anti_drift.py）在模型输入**之前**消费。数据流单向：Stop 检测 → 写文件 → 下回合 UserPromptSubmit 读取 → 注入纠正信号。
2. **不新增独立 hook 文件**：所有逻辑归入已有的 `output_gate.py`（检测+计数）、`anti_drift.py`（读取+注入）和 `run_gate.py`（会话重启阻断），避免 hook 数量膨胀增加每轮延迟。
3. **anti_drift 保持 fail-open**：`session_state.json` 损坏/不存在 → fallback 到静态规则，绝不因状态追踪而阻断回合。output_gate 写入失败 → 静默放行，不因计数故障而卡死会话。两个组件独立 fail-open。
4. **对策三不为对策一的前置依赖**：可以先上线首尾分布，独立观察效果；速查卡的会话状态追踪可以作为增强叠加。但对策一的 MVP 必须先实现 output_gate 的外部计数——没有它，闪卡模式判定缺乏可靠的数据源。
5. **会话重启是安全网而非主要对策**：如果前两条生效，50 轮阈值可能很少触发——这是好事，因为会话中断有操作员成本。会话重启的 turn 计数同样来自 output_gate 维护的 `session_state.json`。
6. **所有会话状态文件放在 run 目录下**（运行态写入 `state/session_state.json`，人工交接仍是 `session_handoff.md`），而非 `.claude/.state/`——因为状态的生命周期绑定于 run，而非全局会话。根目录 `session_state.json` 是旧路径兼容，不是新写入目标。
7. **停滞检测的 MVP 降级**：Stop event 中不直接包含 tool_use 信息，精确的 "是否执行了新 probe" 需要解析 tool call 记录。MVP 用文本特征近似（输出中是否有 probe 相关描述/关键字），后续可升级为解析完整 Stop event 的 `tool_use` 字段（如果 Claude Code 在 Stop event 中暴露）。
