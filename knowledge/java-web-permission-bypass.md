---
id: java-web-permission-bypass
product: Java Web 权限绕过 (Spring MVC / Tomcat / Servlet 通用)
vendor: 通用 (Spring Framework / Apache Tomcat / 各类 Java Web 容器)
aliases: [spring-bypass, tomcat-bypass, servlet-bypass, 权限绕过, auth-bypass-java, path-traversal-bypass]
category: auth-bypass
last_reviewed: 2026-07-02
maturity: seed
signatures: ["Spring", "Tomcat", "servlet", "*.do", "*.action", "DispatcherServlet", ".jsp", "WEB-INF"]
---

## Recognition (identification only)

- Signature: `.do` / `.action` URL suffix → typical Java MVC (Spring / Struts).
- Signature: 404 pages revealing `Apache Tomcat/9.x.x` or `Spring Boot` in error messages.
- Signature: JSESSIONID cookie (Java servlet container session tracking).
- Signature: `/WEB-INF/` path prefix in error messages or redirect URLs.
- Signature: Spring Boot error page (`Whitelabel Error Page`) or actuator endpoints.

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

### Category A: Spring MVC HandlerInterceptor Bypass

- Anchor: 路径变体绕过拦截器（Interceptor 基于 URI 模式匹配，特定路径变体不匹配）
  - Mechanism: Spring MVC 的 `HandlerInterceptor` 通过 `addPathPatterns("/admin/**")` 配置。
    以下路径变体在 Spring MVC 中路由到同一个 Controller，但可能不匹配拦截器路径模式：
    - `/admin/;/user/` ← 分号路径（Spring 将 `;` 后的内容作为路径参数）
    - `/Admin/` ← 大小写变体（拦截器配置 `/admin/**` 但请求用 `/Admin/`）
    - `/admin/../user/` ← 路径穿越（Servlet 容器规范化后等价于 `/user/`）
    - `/admin/.` ← 隐式当前目录
    - `/admin//user/` ← 双斜杠
    - `/admin%2fuser/` ← URL 编码斜杠（`%2f` 在某些容器配置中不被拦截器解析）
  - Verification: 对每个变体发送请求，观察是否返回需要授权才能看到的内容（而非 302 到登录页或 403）。
  - Reference: Spring Framework reference docs on MVC path matching and matrix variables.
  - source: external-cited

### Category B: URL Prefix Case Bypass

- Anchor: 拦截器路径区分大小写但 URL 路由不区分
  - Mechanism: `pathPatterns("/admin/**")` 在 Spring MVC 中默认大小写敏感，但 Controller
    的 `@RequestMapping` 也在大多数配置中大小写敏感。如果两者配置不一致（拦截器 `/admin/**`
但 Controller 绑定了 `/Admin/*`），产生绕过。即便配置一致，某些 Filter 链（web.xml 中
    `<filter-mapping>`）可能在不同容器中行为不同。
  - Variants: `/Admin/`, `/ADMIN/`, `/aDmIn/`
  - Reference: Spring Framework reference docs on handler mappings and servlet filter mappings.
  - source: driver-reasoning

### Category C: Tomcat 路径规范化差异

- Anchor: Tomcat 版本间的路径规范化行为差异
  - CVE-2018-11784: Tomcat 对 `..;/` 序列的处理不一致 → 开放重定向
  - CVE-2024-50379: Tomcat 9.0.24 之前对路径中大写的 `%2F` 处理异常 → 路径穿越（需 `readonly=false`）
  - CVE-2025-24813: Tomcat 路径等价性缺陷 → 未授权访问受保护的资源
  - Mechanism: Tomcat 各版本对特殊路径字符（`/./`, `/../`, `;`, `%2f`, `%5c`, `..;`）的
    规范化行为不同，且与 Spring MVC 的路径解析可能存在双重解析/解析差异。
  - Reference: Apache Tomcat changelog/security pages; CVE-2018-11784, CVE-2024-50379, CVE-2025-24813.
  - source: external-cited

### Category D: Spring Security 配置绕过

- Anchor: Security filter chain 遗漏特定 URL 模式
  - `/api/public/**` 被排除但 `/api/public;/admin` 绕过（利用路径参数）
  - `permitAll()` 的 `AntPathRequestMatcher` vs servlet path 的解析差异
  - Spring Security 默认的 `MvcRequestMatcher` vs `AntPathRequestMatcher` 行为不同:
    `MvcRequestMatcher` 使用 Spring MVC 的路径匹配（去掉分号后部分），
    `AntPathRequestMatcher` 使用原始 URI
  - Reference: Spring Security reference docs for request matchers and servlet path matching.
  - source: external-cited

### Category E: Spring4Shell / Parameter Binding

- Anchor: Spring MVC 参数绑定导致的属性注入
  - CVE-2022-22965 (Spring4Shell): Spring Framework 参数绑定 + Tomcat AccessLogValve → RCE
  - General pattern: Controller 接受 `@ModelAttribute` 且绑定到具有 `set*()` 方法的对象 →
    可注入嵌套属性到 ClassLoader / log 配置等
  - Verify: 在可注册或可提交表单的端点尝试注入 `class.module.classLoader.resources...` 等属性
  - Reference: Spring Framework CVE-2022-22965 advisory and vendor mitigations.
  - source: external-cited

### Category F: Filter Chain Ordering

- Anchor: 过滤器链顺序导致安全过滤器被跳过
  - 如果自定义 Filter 注册时不指定顺序，可能排在内置安全 Filter 之后
  - `@Order(HIGHEST_PRECEDENCE)` 的自定义 Filter 在 Security Filter Chain 之前执行
  - 通过注入特殊字符（`\r`, `\n`, `\0`）可能提前终止 Filter 链处理
  - Reference: Servlet specification filter-chain ordering; Spring Boot filter registration docs.
  - source: driver-reasoning

### Category G: Servlet Mapping 差异

- Anchor: 不同 servlet mapping 规则下的路径解析
  - `/user/*` mapping → `/user/../admin` 被解析为 `/admin` 但容器先行规范化
  - Default servlet 映射（`/`）→ 静态文件路径可能有不同的权限检查
  - JSP servlet 映射（`*.jsp`）→ 通过 `/admin.jsp;.html` 可能绕过 `.jsp` 的 URL 保护
  - Reference: Servlet specification URL mapping rules; Apache Tomcat servlet mapping documentation.
  - source: external-cited

## Verification Principle

Treat these anchors as grounding cues, not proof. A permission-bypass finding needs
paired controls: the normal protected URL must deny the same unauthenticated or
lower-privileged principal, while the variant reaches the same protected object or
state without an authorization grant. Record request/response artifacts for both
baseline and variant, and keep static/source observations at phenomenon maturity
until a runtime access-control delta is shown.

## False-Positive / Confounders

- A route may intentionally expose a public alias or read-only preview.
- Differences may be caused by cache, localization, content negotiation, or default
  error handling rather than authorization bypass.
- Reverse proxies and WAFs may normalize paths before the Java container sees them,
  hiding or creating behavior that is not present at the application layer.
- Case sensitivity and encoded slash handling vary by container, connector, proxy,
  filesystem, and framework version; version mismatch alone is not evidence.
- Spring Security matcher behavior depends on configuration and version; do not infer
  a missing control from framework fingerprinting alone.

## References

- Spring Framework reference documentation: MVC path matching, `PathPattern`, and matrix variables
- Spring Security reference documentation: request matchers and servlet integration
- Apache Tomcat documentation and changelog: path normalization and servlet mapping behavior
- Servlet specification: URL mapping and filter-chain ordering
- Common CVEs: CVE-2018-11784, CVE-2022-22965, CVE-2024-50379, CVE-2025-24813
