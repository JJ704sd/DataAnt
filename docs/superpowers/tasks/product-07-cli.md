# 任务 7：接入独立 `collect-products` CLI

## 操作提示词（可直接复制）

```text
你是 DataAnt 的单任务实现代理。唯一工作目录是 D:\DataAnt；所有 PowerShell 命令先执行 Set-Location -LiteralPath 'D:\DataAnt'。

只读取并执行本任务文件：D:\DataAnt\docs\superpowers\tasks\product-07-cli.md。可读取批准的设计文档 docs/superpowers/specs/2026-07-16-web-scraping-dev-product-gallery-design.md，以及本任务文件小节明确列出的现有源码和测试。不得读取总计划 docs/superpowers/plans/2026-07-16-web-scraping-dev-product-gallery.md 来重新解释或扩大范围。

开始前运行 git status --short 和 git log --oneline -12。历史中必须包含前置提交：feat: commit product outputs as one bundle。如果缺失，返回 BLOCKED。保留并忽略开始前已经存在的未跟踪 .codex-tmp/、.planning/、browser_bot_demo.egg-info/；不得删除、移动、暂存或修改它们。若存在其他不属于本任务的 tracked 修改，返回 BLOCKED，不得覆盖用户工作。

严格执行本文件中的 RED → verify RED → GREEN → focused verify → full verify → commit 顺序。文件编辑使用 apply_patch。只允许修改文件小节列出的文件；不得安装或升级依赖，不得 amend、reset、force push，不得修改或提交 outputs/、artifacts/、browser-profile/、.superpowers/ 中的运行时内容。

本任务严格离线：不得启动浏览器，不得访问 web-scraping.dev、豆瓣或其他外网，不得传入 --live-approved。

提交前运行 git diff --check，并确认 git diff --name-only 只含本任务允许文件。除非本任务明确说明不需要提交，commit message 必须精确为：feat: add controlled product collection command

完成时按以下格式回复：
Status: DONE | DONE_WITH_CONCERNS | BLOCKED | NOT_READY
- task: product-07-cli
- preflight: <前置提交与初始状态>
- red: <精确命令、退出码、预期失败>
- green: <focused 命令与结果>
- full_verify: <全量命令与结果>
- changed: <逐行文件列表>
- commit: <短 SHA + message；无提交时写 none>
- live: NOT_RUN | SKIPPED_NOT_APPROVED | APPROVED_AND_RUN | STOPPED_ON_PROTECTION
- concerns: <无则写 none>

任何门禁失败都保留现场并报告，不得猜测、伪造绿色结果或扩大范围。
```

## Base / 前置条件

- 仓库根目录：`D:\DataAnt`。
- 批准设计：`docs/superpowers/specs/2026-07-16-web-scraping-dev-product-gallery-design.md`。
- 前置提交：`feat: commit product outputs as one bundle`。
- 本任务提交：`feat: add controlled product collection command`。
- 不要触碰开始前已存在的未跟踪 `.codex-tmp/`、`.planning/`、`browser_bot_demo.egg-info/`。


**文件：**

- 修改：`app/main.py:23-128`
- 修改：`tests/test_main.py`
- 修改：`AGENTS.md`

- [x] **步骤 1：写 CLI 参数失败测试**

在 `tests/test_main.py` 增加：

```python
def test_collect_products_parser_has_safe_defaults() -> None:
    args = build_parser().parse_args(
        [
            "collect-products",
            "--site", "web-scraping.dev",
            "--output-dir", "outputs/demo",
        ]
    )
    assert args.site == "web-scraping.dev"
    assert args.output_dir == "outputs/demo"
    assert args.headed is True
    assert args.min_interval == 2.0
    assert args.profile_dir == "browser-profile/web-scraping-dev"
    assert args.live_approved is False
    assert args.max_products is None
```

- [x] **步骤 2：写浏览器创建前门禁测试**

使用独立 `_FakeProductRunner` 和 `_FakeProductOutputBundle`，验证：

- 缺 `--live-approved` 返回 2，浏览器未创建。
- `--max-products` 为 0、11 或缺失返回 2。
- `--no-headed` 返回 2。
- `--min-interval 1.99` 返回 2。
- `--site other.example` 返回 2。
- 输出目录在仓库 `outputs/` 外返回 2。
- profile 在仓库 `browser-profile/` 外返回 2。
- 合法参数只创建一次浏览器和一次运行器。
- 汇总 blocked 返回 3。
- 输出锁定返回 4。
- 浏览器或运行器未分类异常返回 5。

- [x] **步骤 3：运行新增 CLI 测试确认失败**

```powershell
python -m pytest tests/test_main.py -q
```

预期：`collect-products` 子命令不存在。

- [x] **步骤 4：重构命令分派并实现商品门禁**

在 `app/main.py`：

- 保留 `run` 参数和执行顺序不变。
- `execute()` 根据 `args.command` 分派：

```python
if args.command == "run":
    return _execute_douban(args, logger)
if args.command == "collect-products":
    return _execute_products(args, logger)
raise AssertionError(f"unsupported command: {args.command}")
```

- 新增常量：

```python
_PRODUCT_PROFILE_DEFAULT = "browser-profile/web-scraping-dev"
_PRODUCT_MIN_INTERVAL_DEFAULT = 2.0
_PRODUCT_LIVE_MIN_INTERVAL = 2.0
_PRODUCT_LIVE_MAX = 10
```

- 新增参数：

```python
products_parser.add_argument("--site", required=True)
products_parser.add_argument("--output-dir", required=True)
products_parser.add_argument(
    "--headed", action=argparse.BooleanOptionalAction, default=True
)
products_parser.add_argument("--min-interval", type=float, default=2.0)
products_parser.add_argument("--browser-path", default=None)
products_parser.add_argument(
    "--profile-dir", default="browser-profile/web-scraping-dev"
)
products_parser.add_argument("--live-approved", action="store_true")
products_parser.add_argument("--max-products", type=int, default=None)
```

- `_validate_product_live_run()` 在任何 `BrowserSession`、adapter、runner
  或输出器构造前完成验证。
- 路径边界使用 `Path.resolve()` 和 `is_relative_to()`：
  输出必须位于 `<repo>/outputs/`，
  profile 必须位于 `<repo>/browser-profile/`。
- `_execute_products()`：
  创建 `BrowserSession`；
  创建 `WebScrapingDevAdapter`；
  运行 `ProductRunner`；
  用 `ProductOutputBundle.write()` 提交产物。
- blocked 汇总返回 3；`OutputLockedError` 返回 4；
  未分类异常返回 5；验证失败返回 2；成功返回 0。

- [x] **步骤 5：在 AGENTS.md 固化第二站点规则**

增加：

```markdown
## web-scraping.dev live runs

- Real access requires explicit `--live-approved`.
- Every command must include `--max-products N`, where `1 <= N <= 10`.
- Runs must use `--headed` and `--min-interval 2` or greater.
- Only `/products`, valid product pagination, and `/product/<digits>` may be accessed.
- Never access `/robots-disallowed`, login, cart, reviews, GraphQL, CSRF,
  downloads, or challenge endpoints.
- Stop immediately on 429, blocking, login/security checks, challenge pages,
  or redirects outside `web-scraping.dev`.
- Never automate protection bypasses.
```

- [x] **步骤 6：运行 CLI 和现有豆瓣测试**

```powershell
python -m pytest tests/test_main.py tests/test_runner.py tests/test_douban_parser.py -q
```

预期：全部通过，现有 `run` 参数和退出码保持不变。

- [x] **步骤 7：提交 CLI 接线**

```powershell
git add app/main.py tests/test_main.py AGENTS.md
git commit -m "feat: add controlled product collection command"
```
