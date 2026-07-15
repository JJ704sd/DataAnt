# 真实联网轻量门禁设计

## 目标

将真实豆瓣 demo 的“独立审批工单 + evidence 文件”硬门禁替换为操作者在 CLI 中显式确认的轻量门禁。个人本地 demo 无需提供审批人、邮件或工单引用，但仍必须限制运行规模、速率和浏览器模式，并在站点保护出现时立即停止。

## 当前问题

现有治理要求 `controlled-demo-evidence.json` 包含非空 `approval_reference`、`compliance_approved=true` 和批准查询数量。该流程适合组织级受控验收，但对仓库所有者亲自运行的本地 demo 成本过高，并把 workbook 结构校验与审批证明耦合在一起。

当前 CLI 本身没有联网前硬门禁，审批约束主要依赖文档和事后 verifier。结果是规则严格但防误操作能力有限：知道命令的人仍可直接运行，而只想合法本地试跑的人必须人工构造 evidence。

## 选择方案

在 CLI 中增加显式、可机器校验的本地授权参数，删除独立审批 evidence 的强制要求。CLI 成为联网前的真正硬门禁，workbook verifier 回归为纯输出合同校验。

未采用的方案：

- 不只改文档，因为那不会阻止误联网。
- 不彻底删除联网保护，因为批量误跑、无头运行或过快速率仍可能触发站点保护。

## CLI 契约

`python -m app.main run` 新增：

```text
--live-approved
--max-queries N
```

规则：

1. `--live-approved` 是访问真实豆瓣的显式操作者确认；缺失时在创建 `BrowserSession` 前返回退出码 2。
2. `--max-queries` 在真实运行时必须显式提供，合法范围为 1–10。
3. 加载 CSV 后，任务数不得超过 `--max-queries`；超出时在浏览器启动前返回退出码 2。
4. `--headed` 必须为真；传入 `--no-headed` 时返回退出码 2。
5. `--min-interval` 必须至少为 5 秒；更小值返回退出码 2。
6. 所有上述校验在 `BrowserSession` 构造前完成，失败时不得创建 profile、打开浏览器或访问网络。
7. 当前 CLI 只连接真实 `DoubanMovieAdapter`，因此 `run` 子命令一律视为真实联网流程。离线 pytest 和 `scripts.browser_smoke` 不经过该 CLI 门禁。

合法示例：

```powershell
python -m app.main run `
  --input inputs/queries.controlled.csv `
  --output outputs/douban_movies.xlsx `
  --live-approved `
  --max-queries 10 `
  --headed `
  --min-interval 5 `
  --profile-dir browser-profile/douban
```

## Workbook verifier 契约

`verify_controlled_workbook()` 改为只接收 workbook 路径：

```python
verify_controlled_workbook(workbook_path: Path) -> dict[str, int]
```

删除以下要求：

- evidence 文件存在；
- `approval_reference` 非空；
- `compliance_approved` 为真；
- `approved_query_count`、`run_id` 和 `completed_at` 存在于 evidence。

保留以下 workbook 合同：

- 文件存在且可读取；
- 12 列 schema 完全匹配；
- 数据行数量在 1–10 之间；
- 每个 `task_id` 唯一；
- status 属于八个合法状态；
- 每行 `collected_at` 非空。

数据行上限与 CLI 最大查询数保持一致。verifier 不要求恰好 10 行，使 1 条 smoke 和较小批次也能正式验证。

这是有意的向后不兼容 API 变更：所有调用点和测试必须同步去掉 evidence 参数，不保留表面兼容的废弃参数。

## 站点保护

保留并加强现有安全行为：

- HTTP 403、418、429 继续视为 `BLOCKED`。
- 页面出现“访问频率过高”“异常请求”或“验证码”继续视为 `BLOCKED`。
- URL 跳转到 `sec.douban.com` 或登录安全检查页时视为 `BLOCKED`，而不是 `PAGE_CHANGED`。
- Runner 写入当前任务的 `BLOCKED` 后立即停止剩余批次。
- 不自动登录、不自动识别验证码、不绕过频率限制，也不使用 `--retry-status BLOCKED`。

普通登录页可由操作者在同一隔离 profile 中手动完成；密码、验证码和 Cookie 不进入代码、命令参数、日志或 Git。

## 文档与 CI

同步修改：

- README 的运行命令、联网说明和故障矩阵；
- `docs/superpowers/tasks/core-13-release-readiness.md` 的 workbook/evidence 门禁；
- `scripts.verify_core.py` 及 `tests/test_verify_core.py`；
- CLI 测试和项目配置契约测试中对命令参数及离线 CI 的断言。

CI 继续保持纯离线：不得设置 `--live-approved`，不得调用真实 `app.main run`，不得创建或上传 profile、workbook、Cookie 或 evidence。

## 测试

实施遵循 TDD：

1. CLI 缺少 `--live-approved` 时在浏览器前退出。
2. 缺少或越界 `--max-queries` 时退出。
3. 输入任务数超过 `--max-queries` 时退出。
4. `--no-headed` 或间隔小于 5 秒时退出。
5. 合法参数保持现有 Runner/Excel 行为。
6. workbook verifier 接受 1–10 行，不需要 evidence。
7. verifier 拒绝 0 行、超过 10 行、重复 task、错误 schema、非法状态和空时间。
8. `sec.douban.com` 重定向被识别为 `BLOCKED`。
9. 全量 pytest、核心 coverage gate、pip check 和零网络 browser smoke 通过。

## 运行产物与仓库卫生

以下内容继续由 `.gitignore` 排除并禁止提交：

- `browser-profile/*`
- `outputs/*`
- `artifacts/*`
- Cookie、Local State、Sessions、HTML、截图、日志和本地工作簿

删除 evidence 强制要求不代表允许提交运行产物。

## 非目标

- 不加入自动登录、验证码处理或反爬绕过。
- 不改变查询解析、候选匹配、详情字段或 Excel 列。
- 不增加远程审批服务或账号系统。
- 不让 CI 访问真实网络。
- 不取消运行规模、速率、有头模式和站点保护限制。
