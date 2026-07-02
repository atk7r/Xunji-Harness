# Constraints Ledger

> 每条约束记录一个被尝试但受阻的 mechanism class + input shape 组合。
> Mechanism class 必须使用 `knowledge/_lexicon.md` 的 canonical name。
> Evidence 必须指向一个存在的 E-xxx（check_run 硬门强制检查）。
> 条件文件 —— 只在有负向结果积累时创建。

## C-001

- Front: F-001
- Mechanism class: SQLi-login
- Input shape: POST /authService/authUser/v2/login/phone (JSON: phone, smsCode)
- Why blocked: WAF-signature
- Evidence: E-005
- Ruled out: Boolean/union SQLi on phone param — WAF consistently blocks SQL keywords; no encoding bypass found at app layer
