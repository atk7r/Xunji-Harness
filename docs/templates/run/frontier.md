# Frontier

## Open Fronts

### F-xxx

- Front:
- Assets:
- Why it matters:
- Current depth: shallow / moderate / deep
- Status: open / probing / blocked_type_a / blocked_type_b / deferred / closed
- Barrier class: none / app-layer / auth-layer / WAF-layer / routing-layer / network-layer / scope-credential-layer
- Failure budget:
  - Same barrier failures:
  - Same bypass family attempts:
  - Same tech-stack assets tried:
- Vectors tried:
- Untried classes:
- Best current evidence:
- Next autonomous move:
- Stop condition:
- Unruled out:
- Linked hypotheses:

## Deferred Fronts

## Closed Fronts

<!-- 每个 Closed Front (### F-id) 字段:
     Front / Assets / Current depth: shallow|moderate|deep / Why closed /
     Assets: 单行填写, 多资产用逗号/分号分隔; 使用 host[:port] 或 URL, 不要用 HTTP Host 头语义。
     Vectors tried: 尝试过的向量类别 (depth=shallow 关高价值前沿时必填, 防浅尝即弃) /
     Evidence: E-xxx / Type A/B reason / Residual risk
     —— "我够不着"(WAF/超时/登录门控)记 Deferred 而非 Closed; Closed 须有正面证据。 -->

<!-- Unruled out: Type B / deferred / closed 时条件必填。列出"针对这个front我还没排除的攻击面"——
     不填意味着你声称穷举了，但在安全测试中穷举几乎不可能。
     写具体: 不是"可能还有其它注入点"，而是"POST body SSTI 未测试 / nginx静态文件路径穿越未测试"。
     这条是反早闭钩子——写出来，你自己就会去补。 -->
