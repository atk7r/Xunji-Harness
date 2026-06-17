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
  "budget": {"max_requests": 200}       // 可选: 请求预算上限(对照录像 .replay.json 计数, 下界)
}
```

打分维度: **detection**(期望发现的检出率)· **calibration**(命中条目 certainty 达不达下限,
防欠证/过证)· **false-positives**(陷阱被正向确认命中数; 纯负向 Refutes 条目不算)·
**budget**(录像计数作已记录请求下界)。

## 用法

```bash
python tools/bench.py score runs/<dir> bench/<fixture>/truth.json   # 单个 run 打分
python tools/bench.py score-all bench/                              # 跑所有随附样例 run
python tools/bench.py --selftest                                    # 离线回归(已并入 selftest_all)
```

退出码: 全检出 + 全校准 + 零误报 = 0(可当回归门), 否则 1。

## 怎么用它 A/B 一个框架改动

1. 选一个 fixture(如本地 DVWA 某关)。
2. 改框架**前**: driver 打一次, 落 `runs/<a>/` → `bench.py score runs/<a> <truth>` 记分。
3. 改框架**后**: 同 fixture 再打一次, 落 `runs/<b>/` → 记分。
4. 比 detection / calibration / false-pos / budget。**分数没变好 = 改动没证明价值**(ROADMAP
   gating principle: 度量先行, 别凭手感堆)。

## 现有 fixture

- `example-dvwa-sqli/` —— 合成的 DVWA 风格样例(SQLi + reflected XSS + 一个"登录页非漏洞"
  陷阱), 演示 schema 与打分, 也是 `bench.py` 的随附回归样本。**非真实目标**。
