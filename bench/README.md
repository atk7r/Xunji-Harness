# bench/ — R-1 自评 fixtures(度量, 非驱动)

这把尺子量的是 **driver 的产出**, 它自己绝不变成 driver。`tools/bench.py` 只读一个
【已完成 run】的产物, 对照一份【真值 truth.json】打分 —— 不发包、不做攻击判断。

> **ROADMAP R-1**: 没有它, 框架的每一个"改进"都只是机制听起来合理(plausible mechanism
> != better)。有了它, 一个改动能被 A/B: 同一 fixture 改前/改后各跑一次 run, 比分数。

## 铁律

- **fixture 只用良性已知漏洞靶** —— DVWA / Juice Shop / 有意可漏容器 / 公开靶场, 或一个
  录制 run 的真值标注。**绝不放真实交战的发现物**(真实目标 run 是红线, 不进本目录)。
- 打分是**近似**(按 marker 子串匹配确认条目), 用于回归与改动前后比对, **不是裁决**。
- 它**度量** driver, 不**替代** driver: 跑 fixture 的那次 run 仍由 driver(agent)亲自打,
  bench 只在事后量产出。

## 目录布局

```
bench/
  <fixture-name>/
    truth.json        # 真值: 期望发现 / 陷阱 / 预算 / 指向待评 run
    sample_run/       # (可选)随附的样例 run, 让 score-all 能直接跑(示例/回归)
      evidence.md ...
```

## truth.json schema

```json
{
  "name": "dvwa-sqli-low",
  "run": "sample_run",                  // score-all 用: 相对 truth.json 的待评 run 目录
  "expected_findings": [
    {"id": "sqli",
     "markers": ["sql injection", "union"],   // 确认条目块文本须【全含】这些子串(大小写不敏感)
     "min_certainty": 0.8},                    // 命中条目 certainty 须达此下限才算"已校准"
    {"id": "xss-reflected", "markers": ["reflected xss"], "min_certainty": 0.8}
  ],
  "must_not_flag": [                    // 陷阱: 这些【不是漏洞】, 被【正向确认】命中即记误报
    {"id": "login-page", "markers": ["login page present"]}
  ],
  "expected_closure": {                  // 可选: recorded closure fixture, 期望没有正向 finding
    "markers": ["closure", "no confirmed findings"],
    "requires_independent_review": true,
    "requires_no_positive_findings": true
  },
  "expected_process": [                  // 可选: 过程断言, 只读 run 产物中的能力踪迹
    {"id": "consulted-knowledge", "signals": ["knowledge_match"], "must": true}
  ],
  "expected_collaboration": {            // 可选: Ultra-native Agent Board 断言, 进入 clean 门
    "min_agent_coverage": 1.0,
    "front_roles": {"F-001": ["web-auth", "verify"]},
    "require_conflicts_resolved": true,
    "max_requests_per_agent": 2,
    "require_no_missed_high_value": true
  },
  "expected_tool_friction": {             // 可选: 显式启用 typed Agent tool-call 摩擦门
    "min_attempted_calls": 4,
    "max_denial_rate": 0.25,
    "max_invalid_argv_rate": 0.0,
    "max_post_failures": 0,
    "min_non_denied_terminal_rate": 0.75,
    "min_prepared_capability_hit_rate": 0.75
  },
  "budget": {"max_requests": 200}       // 可选: 请求预算上限(对照录像 .replay.json 计数, 下界)
}
```

打分维度: **detection**(期望发现的检出率)· **calibration**(命中条目 certainty 达不达下限,
防欠证/过证)· **false-positives**(陷阱被正向确认命中数; 纯负向 Refutes 条目不算)·
**budget**(录像/事件计数作已记录请求下界)· **time-to-first-evidence**(`events.jsonl` 中首个
request/action 到首个 evidence 的秒数)· **closure correctness**(recorded closure 是否有独立复审、
无正向 finding、命中 closure markers)· **collaboration**(Agent coverage、candidate/refutation→finding、
conflict resolution、missed high-value front、per-agent budget、agent first-evidence、false-positive
suppression)。声明了 `expected_collaboration` 的 fixture 会把这些 checks 纳入 clean 门；缺
`state/events.jsonl` 等必要观测数据时不会静默通过, 而是记录 `skipped` 且非 clean。

`expected_tool_friction` 只在 fixture 显式声明时启用；未声明它的旧 fixture 不读取 runtime
receipts，原有打分与退出码语义保持不变。JSON 是可加字段的输出，启用这版代码后会出现
`tool_friction: null` 或汇总元数据，因此不承诺与旧版本 byte-for-byte 相同。它只消费
hash-chain-valid 的 `AgentToolCallClaim`、完整 identity 绑定的
`PreToolUseDenied` / `PostToolUse` / `PostToolUseFailure`；只有缺 Hook terminal 时，才用 exact
child transcript 中匹配 tool-use id 的完整 `tool_result` 证明 narrow terminal。
`AgentToolCallClaim.success=false` 表示“已预留一次尝试”，
**不表示工具失败**；缺 Hook terminal 但 exact child transcript 已有结果时，只记为
`xunji_non_denied_terminal`，不读取结果语义。这里的“non-denied”只表示没有 Xunji
`PreToolUseDenied` receipt；宿主原生权限拒绝也可能生成完整 `tool_result` 并落入此 bucket。
`non_denied_terminal` 只证明存在一个未被 Xunji Hook deny 归类的完整 terminal；它包含
`PostToolUseFailure`，**不证明宿主已放行、effect 已执行、成功或形成证据**。歧义、identity
漂移、terminal 缺失或 receipt chain 问题进入
outcome `unknown`，且必须为 0 才能 clean；context/marker 归因问题单独进入
`prepared_attribution_unknown`。Prepared 归因还要求同 assignment 的 claim 共享一个
`launch_prompt_sha256`，并与 frozen row 重建的 launch prompt 完全一致；替换为另一套自洽
bundle 仍必须 unknown。只要 fixture 声明 prepared threshold，该计数就必须为 0。输出仅含
聚合计数/比率，不含 command、path、URL、session/Agent/tool-use id 或 result bytes。

Producer 输出还要通过完整 shape/invariant gate：bucket 总数必须等于 attempted calls，
invalid-argv 必须是 denial 子集，non-denied 总数必须等于三个 non-denied terminal bucket 之和，
prepared hit/offered/unknown 不得越过 attempted calls，所有 rate 必须由对应 count 精确重算，
unknown reason 总数必须与 outcome unknown 相等。字段缺失、bool 冒充整数、NaN/越界 rate 或
内部计数矛盾都会 fail closed。Producer 意外异常也会以固定的 `producer-error` reason fail
closed；异常原文不会进入公开 score，以免泄露路径、命令或导入数据。

支持的 threshold：

- count：`min_attempted_calls`、`max_denied_calls`、`max_invalid_argv_denials`、
  `max_post_failures`、`min_non_denied_terminals`、`min_prepared_capability_hits`；
- rate（0..1）：`max_denial_rate`、`max_invalid_argv_rate`、
  `min_non_denied_terminal_rate`、`min_prepared_capability_hit_rate`。

prepared-capability 命中只认 assignment instruction bundle 中 context descriptor 验证过的
精确 marker，不解析旧 heading 或命令文本：

```html
<!-- xunji.prepared-capability.v1 {"action_sha256":"...","capability_id":"...","effect":"..."} -->
```

`prepared_capability_hit_rate` 的分母不是所有 tool calls：它等于
`prepared_capability_hits / prepared_capability_offered_calls`。其中 offered calls 只统计
context descriptor 已验证、且至少含一个有效 prepared marker 的 assignment 所发起的调用；
没有被投影任何 prepared capability 的 lane 不进入该分母。

只要声明 prepared threshold，context descriptor/marker 归因必须完整，
`prepared_attribution_unknown` 也必须为 0。声明 `expected_tool_friction` 却没有任何受支持
threshold，或 threshold 名拼错/类型越界，都会 fail closed。

可选 `events.jsonl` 每行一个事件:

```json
{"ts": 0.0, "type": "request", "path": "/demo"}
{"ts": 2.0, "type": "evidence", "id": "E-001"}
```

## 用法

```bash
python tools/bench.py score runs/<dir> bench/<fixture>/truth.json   # 单个 run 打分
python tools/bench.py score-all bench/                              # 跑所有随附样例 run
python tools/bench.py score-all bench --json-out tmp/baseline.json   # 保存汇总 JSON
python tools/bench.py compare tmp/baseline.json tmp/change.json       # A/B 指标对比
python tools/bench.py --selftest                                    # 离线回归(已并入 selftest_all)
```

退出码: `score` / `score-all` 全检出 + 全校准 + 零误报 + 预算内 + 必需过程断言满足，且所有
显式 tool-friction threshold 满足、unknown=0 = 0,
否则 1。`compare` 在 detection / calibration / closure 下降, 或 false-pos / budget /
time-to-first-evidence / tool-friction 回归时返回 1；任一 tool-friction required metric 在
baseline 或 change 缺失也 fail closed。A/B 两侧必须含完全相同、非空且唯一的
tool-friction fixture ID 集；该 ID 来自 score 的 `fixture` 字段：truth 显式提供 `name` 时使用
该值，否则回退到 run 目录名。`score-all` 中最终得到的 ID 必须非空且全局唯一；单 fixture 做
A/B 时应在前后 truth 中显式复用同一个稳定 `name`，不要依赖可能变化的 run 目录名。删除或
替换难例不能改善汇总。baseline 可以不满足 threshold，
以便证明 change 的真实改善；但 change 必须绝对满足 `checks_failed=0`、outcome `unknown=0`，
声明 prepared threshold 时还必须满足 `prepared_attribution_unknown=0`，否则即使数值没有继续
恶化，`compare` 仍返回 1。

## 怎么用它 A/B 一个框架改动

1. 选一个 fixture(如本地 DVWA 某关)。
2. 改框架**前**: driver 打一次, 落 `runs/<a>/` → `bench.py score runs/<a> <truth> --json-out tmp/baseline.json`。
3. 改框架**后**: 同 fixture 再打一次, 落 `runs/<b>/` → `--json-out tmp/change.json`。
4. 跑 `bench.py compare tmp/baseline.json tmp/change.json`。
5. 比 detection / calibration / false-pos / request budget / time-to-first-evidence / closure /
   tool denial / invalid argv / non-denied terminal / prepared marker hit。**分数没变好 = 改动没证明价值**(ROADMAP
   gating principle: 度量先行, 别凭手感堆)。

## 现有 fixture

- `example-dvwa-sqli/` —— 合成的 DVWA 风格样例(SQLi + reflected XSS + 一个"登录页非漏洞"
  陷阱), 演示 schema 与打分, 也是 `bench.py` 的随附回归样本。**非真实目标**。
- 另有 17 个合成 fixture, 覆盖 auth/IDOR、injection、upload/path、path traversal、recorded
  closure、Ultra-native Agent Board collaboration、JS/API hidden routes、client-side signature
  hints、permission/state matrix、threat-hypothesis-to-evidence, and mentor-pivot canaries。
  它们只用于离线评估, 不含真实交战发现物。
- `setup-normalizer-pilot/cases.json` —— Markdown/普通 JSON setup candidate 的离线
  A/B 与安全硬门。`--ai off` 是 deterministic baseline；reference-candidate 是只在已脱敏
  request ID 上选择的 oracle，用来证明 contract 有增加召回的能力，不冒充 live provider
  质量。运行 `python3 tools/setup_normalizer_bench.py --json` 查看字段 precision/recall、
  hallucination、无来源字段、target 错选、source instruction 晋级与 model-egress leak。
