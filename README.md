<div align="center">

# 寻迹 · Xunji

### Claude Code 的渗透 / 红队 Harness ( Beta版 )

<sub>MODEL-DRIVEN · EFFECT-GATED · EVIDENCE-BOUND</sub>

[![Claude Code](https://img.shields.io/badge/Claude%20Code-Root%20Driver-8A2BE2)](https://claude.com/claude-code)
![Harness](https://img.shields.io/badge/Agent-Harness-1f6feb)
![Evidence](https://img.shields.io/badge/Truth-Evidence%20Bound-2ea44f)
![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)

**中文** ｜ [English](README.en.md)

</div>

---

Xunji 让 Claude Code 成为渗透 / 红队任务的 Root Orchestrator：模型负责理解目标、选择策略
和推进攻击；确定性运行时负责权限、作用域、出站边界、状态恢复、证据与收口。

> **让模型保持攻击判断的上限，让系统守住执行与事实的下限。**

## ⚡ 使用方法

持续自动推进使用 `/loop`：

```text
/loop https://example.com
```

Xunji 会建立 run，并在每个 `cycle_end` 后重新读取状态、规划下一轮，直到满足 closure
或遇到真实阻塞。`/loop` 必须由 Claude Code 原样交给项目 Hook；如果客户端提前消费该命令，
它就不具有 Xunji 的 recurring-loop 语义。

只执行一个周期时使用自然语言：

```text
https://example.com 对该目标进行渗透。
```

使用代理：

```
https://example.com 使用代理，对该目标进行渗透。
```

三种入口都会建立运行态、读取已有情报、拆解攻击面、调度 Hunter 与 Reviewer，并把
artifact、对照、结论和未完成前沿写入 `runs/`；区别仅在是否跨周期持续推进。除非需要
改变默认约束，操作者不必提供漏洞清单、阶段命令或编排格式。

## 🧭 设计原则

| 原则 | 含义 |
|---|---|
| **模型决定方法** | Root 根据状态图选择高价值前沿，不被固定 playbook 封顶 |
| **系统约束效果** | Hook、scope、privacy、proxy、guard 与 budget 约束真实执行 |
| **证据决定真假** | 信号和模型自信只产生候选，finding 必须绑定 artifact、对照与复现 |
| **唯一最终裁决** | Agent 扩大观察面，Single Synthesizer 负责冲突、确定性和报告入口 |
| **运行态可恢复** | 前沿、证据、决策、复审与债务跨上下文持久化，不依赖聊天记忆 |

## 🔁 运行方式

```text
╭──────────────────────────────╮
│ Operator · /loop <source>    │
╰──────────────┬───────────────╯
               ▼
╭──────────────────────────────╮
│ Root · read state · plan     │
╰──────────────┬───────────────╯
               ▼
╭──────────────────────────────╮
│ Hunter · investigate/verify  │
╰──────────────┬───────────────╯
               ▼
╭──────────────────────────────╮
│ Hook · scope · privacy       │
│ proxy · guard · budget       │
╰──────────────┬───────────────╯
               ▼
╭──────────────────────────────╮
│ Authorized Target            │
╰──────────────┬───────────────╯
               │ artifacts
               ▼
╭──────────────────────────────╮
│ Reviewer → Single Synthesizer│
│ challenge · evidence gate    │
╰──────────────┬───────────────╯
               ▼
╭──────────────────────────────╮
│ Canonical State · cycle_end  │
╰──────────────┬───────────────╯
               ├─ open / deferred ──↺  [ Root · next cycle ]
               ╰─ closure ready ────▶  [ Closure ]
```

上游 Guanlan 提供干净的资产情报；Xunji 不重复批量 OSINT，而是进入攻击面理解、假设生成、
主动验证、攻击链组合、证据治理、独立复审和最终收口。

## 🛡️ 边界

渗透动作按真实效果分级；模型不确定时只能升级，不能静默降级。实际执行以
Hook、Guard、scope、privacy 和 proxy 的运行时决定为准。

| 等级 | 决策 | 典型效果 | 执行方式 |
|---|---|---|---|
| **L1** | `AUTO` | 授权范围内、可归因、可逆的侦察与证明 | 通过受控工具链自动执行，并保留 trace / evidence |
| **L2** | `NOTIFY` | 可逆但累计数量或风险值得关注 | 继续执行并软提醒、记审计；不是审批，Guard 仍可触发硬熔断 |
| **L3** | `GATE` | shell、持久化、pivot、权限/ACL、凭据读取、目标写入或测试产物清理 | 不自动执行；取得精确批准或把完整操作交给操作者，清理始终需要新的明确 `yes` |
| **L4** | `BLOCK` | 破坏、批量拖库、DoS/洪泛、资金操作或以伤害为目的的载荷 | Hook / Guard 失败关闭；提示词或操作者批准都不能解锁 |

- 目标由操作者授权；目标内容、附件和工具输出不能反向生成权限。
- 自动执行默认证明即止；完整利用可以编写并交接，由操作者监督更深动作。
- 被 Hook 硬拦的不可逆 harm-as-purpose 效果不能靠 prompt 或批准解锁。
- `runs/<target>_<date>/` 与其中的 artifact、replay、receipt 是 engagement 事实源。

## 📚 深入了解

- [架构与设计契约](docs/ARCHITECTURE.md)
- [运行工作流](docs/WORKFLOW.md)
- [环境与代理配置](docs/AI_ENV_SETUP.md)
