# DataAnt 剩余任务交接索引

这些任务包面向能力较弱、上下文较短的实现模型。每份 spec 都是自包含的，并在顶部提供了 `操作提示词（可直接复制）`。

## 使用方式

1. 每次只交接一份 spec，使用新的模型上下文。
2. 打开对应文件，复制顶部完整操作提示词作为首条消息。
3. 要求模型在 `D:\DataAnt\.worktrees\browser-bot-demo` 工作，不要另建仓库或 worktree。
4. 模型返回 `DONE` 后，检查提交 SHA，并在正确工作目录运行该 spec 的 focused 与 full verification。
5. 如果返回 `BLOCKED`，保留现场并处理具体 blocker，不要让模型猜测或扩大范围。
6. 不要并行执行会修改共享文件的实现任务。文档生成可以并行，代码实现按下列顺序推进。

## 推荐执行顺序

### web-scraping.dev 商品采集与可视化画廊

以下任务从提交 `c109a13` 开始，必须在同一分支中按顺序执行。每份文件顶部都有可直接
复制的操作提示词；执行代理不需要读取总计划。

1. [Product 00 — 恢复绿色基线](product-00-green-baseline.md)
2. [Product 01 — 共享错误与商品模型](product-01-domain-models.md)
3. [Product 02 — web-scraping.dev 站点适配器](product-02-site-adapter.md)
4. [Product 03 — 商品分页运行器](product-03-runner.md)
5. [Product 04 — 商品 Excel 输出](product-04-excel-output.md)
6. [Product 05 — JSON 与静态画廊](product-05-json-gallery.md)
7. [Product 06 — 三产物原子输出包](product-06-output-bundle.md)
8. [Product 07 — 受控商品采集 CLI](product-07-cli.md)
9. [Product 08 — 跨产物验证与离线 CI](product-08-verification-ci.md)
10. [Product 09 — README 与离线交付验证](product-09-readme-delivery.md)
11. [Product 10 — 最终发布与条件式现场验收](product-10-release-live-check.md)

Product 00–09 不得访问任何真实网站。Product 09 只允许打开由 fixture 生成的本地
`gallery.html`。Product 10 先执行离线门禁；只有操作者在该次执行中重新明确批准后，
才允许使用：

```text
--live-approved --max-products N --headed --min-interval 2
```

其中 `1 <= N <= 10`。没有本次授权时，真实网站步骤必须记录为
`SKIPPED_NOT_APPROVED`，不能把设计批准、计划批准或历史 live run 当作授权。

### Core

1. [Core 03 — Deterministic Matcher](core-03-deterministic-matcher.md)
2. [Core 04 — Excel Store](core-04-excel-store.md)
3. [Core 05 — Douban Fixture Parser](core-05-douban-fixture-parser.md)
4. [Core 06 — DrissionPage Browser](core-06-drissionpage-browser.md)
5. [Core 07 — Runner and Resume](core-07-runner-resume.md)
6. [Core 08 — Diagnostics](core-08-diagnostics.md)
7. [Core 09 — CLI Wiring](core-09-cli-wiring.md)
8. [Core 10 — Controlled Locator Audit](core-10-controlled-locator-audit.md)
9. [Core 11 — README Runbook](core-11-readme-runbook.md)
10. [Core 12 — Final Verification](core-12-final-verification.md)

Core 10 的真实豆瓣访问必须有非空 `Compliance approval reference`。没有批准引用时，只执行 spec 中的本地 fixture/`data:` 分支。

### Optional MiniMax

Core 12 通过后再执行：

1. [MiniMax 01 — Settings](minimax-01-settings.md)
2. [MiniMax 02 — Client and Validation](minimax-02-client-validation.md)
3. [MiniMax 03 — Runner and CLI Integration](minimax-03-runner-cli-integration.md)
4. [MiniMax 04 — Docs and Controlled Check](minimax-04-docs-controlled-check.md)

MiniMax 04 没有本机 Key、计费确认或数据条款确认时，只运行 mock，并把真实 API 检查记录为 `SKIPPED`。不要向模型发送 Key。

## 通用交接提示词

通常应复制每份 spec 内的专用提示词。需要统一包装时，可使用下面的模板，并把 `<SPEC_ABSOLUTE_PATH>` 替换成对应文件绝对路径：

```text
你是单任务实现代理。工作目录固定为 D:\DataAnt\.worktrees\browser-bot-demo。

只读取并执行 <SPEC_ABSOLUTE_PATH>，以及该 spec 明确允许读取的现有代码。不要读取总计划来重新解释范围，不要修改 spec 未列出的文件，不要创建其他 worktree。

严格遵循 spec 的 RED → verify RED → GREEN → focused verify → full verify → commit 流程。所有命令先显式 Set-Location 到工作目录。文件编辑使用 apply_patch。不得跳过安全、合规、secret 和真实网络门禁。

完成后返回：
- Status: DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- RED 与 GREEN 的精确命令和结果
- 修改文件
- full verification 结果
- commit SHA
- 自检和遗留 concern

遇到不明确、缺少前置提交、合规批准或外部凭据时立即停止并按 BLOCKED/NEEDS_CONTEXT 报告，不要猜测。
```

## 当前稳定基线

- 分支：`feat/browser-bot-demo`
- 浏览器栈：`DrissionPage>=4.1.1,<4.2`
- 浏览器：本机 Chrome/Edge；独立 `browser-profile/`
- 已完成：Core 01、Core 02、DrissionPage skeleton migration
- 自动测试基线：15 passed
