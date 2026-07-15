# Core 06：DrissionPage 浏览器生命周期与 UI 动作执行 Spec

## 操作提示词（可直接复制）

```text
你是本仓库的实现代理。工作目录固定为 D:\DataAnt\.worktrees\browser-bot-demo。

只读取本 spec：D:\DataAnt\.worktrees\browser-bot-demo\docs\superpowers\tasks\core-06-drissionpage-browser.md，以及必要现有代码 pyproject.toml、app/models.py、app/sites/douban_movie.py、tests/test_douban_parser.py。不得读取总计划 docs/superpowers/plans/2026-07-15-browser-bot-core-demo.md。

严格按本 spec 的 TDD 顺序执行。只允许创建或修改 app/browser_session.py、tests/test_browser_session.py、app/sites/douban_movie.py、tests/test_douban_parser.py；不得改其他文件，不得安装依赖。必须使用 pyproject.toml 已固定的 DrissionPage>=4.1.1,<4.2、本机 Chrome/Edge、独立 browser-profile 和动态本地端口。所有 PowerShell 命令先 Set-Location 到绝对 worktree。

本任务严禁真实访问豆瓣或其他外网：自动测试只能用 fake tab；浏览器 smoke 只能打开 data: URL。适配器虽实现真实站点动作，但本任务不得调用它们访问真实站点，真实站点审计留给 Core 10。

验证成功后提交允许文件，commit message 必须为：feat: add DrissionPage browser actions

完成时回报：
DONE
- changed: <逐行列出文件>
- red: <命令与预期失败摘要>
- verify: <命令与通过摘要；注明 smoke 仅 data: URL>
- commit: <短 SHA 和 message>

无法完成时回报：
BLOCKED
- step: <阻塞步骤>
- evidence: <命令、错误原文和已检查内容>
- changed: <已经改动的文件；没有则写 none>

不得用猜测绕过失败，不得真实访问豆瓣。
```

## Base / prerequisites

- Repo root：`D:\DataAnt\.worktrees\browser-bot-demo`。
- Core 01–02 和 Core 05 已完成；纯解析器与 fixtures 已存在且测试通过。
- `pyproject.toml` 已固定 `DrissionPage>=4.1.1,<4.2`；不得执行安装或升级。
- 运行机器为 Windows，至少安装本机 Chrome 或 Edge。不得接管日常浏览器 profile。
- 本任务仅验证本地生命周期和 fake-tab 动作；真实站点 locator 审计属于 Core 10。

## Goal

用 DrissionPage 管理一个 batch 的 Chromium/Tab 生命周期：发现本机 Chrome/Edge、使用独立 profile、每次启动分配动态 localhost 端口、按 headed/headless 配置启动并可靠退出；为豆瓣适配器增加小型 locator 契约、阻断/页面变化/网络错误分类，以及搜索和详情动作。

## Files（仅允许本任务）

- Create：`app/browser_session.py`
- Create：`tests/test_browser_session.py`
- Modify：`app/sites/douban_movie.py`
- Modify：`tests/test_douban_parser.py`

不得修改 `pyproject.toml`、fixtures、runner、CLI 或其他文件。

## Fixed contracts

依赖必须保持：

```toml
dependencies = ["DrissionPage>=4.1.1,<4.2", "openpyxl>=3.1,<4"]
```

必要模型接口：

```python
@dataclass(frozen=True, slots=True)
class Task:
    task_id: str
    query: str
    query_year: str | None

@dataclass(frozen=True, slots=True)
class Candidate:
    title: str
    year: str | None
    kind: str | None
    detail_url: str

@dataclass(frozen=True, slots=True)
class MovieResult:
    task_id: str
    query: str
    query_year: str | None
    # 其余字段由 Core 05 解析器填写
```

浏览器公开契约固定为：

```python
def find_browser_executable(explicit: Path | None = None) -> Path: ...
def _free_local_port() -> int: ...

class BrowserSession(AbstractContextManager[object]):
    def __init__(
        self,
        headed: bool,
        artifacts_dir: Path,
        profile_dir: Path,
        browser_path: Path | None = None,
    ) -> None: ...

    def __enter__(self): ...  # 返回 Chromium.latest_tab
    def __exit__(self, exc_type, exc, traceback) -> None: ...
```

适配器新增契约固定为：

```python
class BlockedError(RuntimeError): ...
class PageChangedError(RuntimeError): ...
class NetworkError(RuntimeError): ...

class DoubanMovieAdapter:
    SEARCH_INPUTS = ("@role=searchbox", "css:input[name='search_text']")
    def search(self, tab, task: Task) -> list[Candidate]: ...
    def fetch_detail(self, tab, task: Task, candidate: Candidate) -> MovieResult: ...
```

固定行为：默认有头由调用方传 `headed=True`；自动发现 Chrome/Edge，不伪造 User-Agent；独立 `profile_dir`；动态回环端口；一个 session 只创建一个 Chromium 并返回 latest tab；退出总是 `quit()`。导航 `tab.get(...)` 返回 false 时抛自定义 `NetworkError`；阻断抛 `BlockedError`；关键 locator/结果标记缺失抛 `PageChangedError`；同步等待不用 `time.sleep()`。

## TDD implementation

- [ ] **Step 1 — RED：追加 locator 与网络分类测试**

在 `tests/test_douban_parser.py` 文件末尾追加：

```python
from app.models import Candidate
from app.sites.douban_movie import NetworkError


def test_adapter_exposes_a_small_locator_contract() -> None:
    assert DoubanMovieAdapter.SEARCH_INPUTS == (
        "@role=searchbox",
        "css:input[name='search_text']",
    )


class NavigationFailureTab:
    html = ""
    url = "data:text/html,offline"

    def get(self, url: str, retry: int, timeout: int) -> bool:
        return False


def test_search_navigation_failure_is_a_network_error() -> None:
    with pytest.raises(NetworkError, match="navigation failed"):
        DoubanMovieAdapter().search(NavigationFailureTab(), Task("a", "电影", None))


def test_detail_navigation_failure_is_a_network_error() -> None:
    candidate = Candidate("电影", "1994", "电影", "https://movie.douban.com/subject/1/")
    with pytest.raises(NetworkError, match="detail navigation failed"):
        DoubanMovieAdapter().fetch_detail(
            NavigationFailureTab(), Task("a", "电影", None), candidate
        )
```

运行单个 locator 测试：

```powershell
Set-Location 'D:\DataAnt\.worktrees\browser-bot-demo'
python -m pytest tests/test_douban_parser.py::test_adapter_exposes_a_small_locator_contract -v
```

预期：FAIL，因为 `SEARCH_INPUTS` 尚未定义。

- [ ] **Step 2 — RED：创建浏览器 session 测试**

创建 `tests/test_browser_session.py`：

```python
from pathlib import Path
import socket

import pytest

from app.browser_session import _free_local_port, find_browser_executable


def test_explicit_browser_path_is_used(tmp_path: Path) -> None:
    executable = tmp_path / "chrome.exe"
    executable.touch()
    assert find_browser_executable(executable) == executable


def test_missing_explicit_browser_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Chrome or Edge"):
        find_browser_executable(tmp_path / "missing.exe")


def test_free_local_port_returns_bindable_loopback_port() -> None:
    port = _free_local_port()
    assert 0 < port < 65536
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
```

```powershell
Set-Location 'D:\DataAnt\.worktrees\browser-bot-demo'
python -m pytest tests/test_browser_session.py -v
```

预期：非零退出，collection 因 `app.browser_session` 不存在而失败。

- [ ] **Step 3 — GREEN：创建完整浏览器生命周期实现**

创建 `app/browser_session.py`：

```python
from __future__ import annotations

from contextlib import AbstractContextManager
import os
from pathlib import Path
import socket

from DrissionPage import Chromium, ChromiumOptions


PROGRAM_FILES = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
PROGRAM_FILES_X86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
LOCAL_APP_DATA = Path(os.environ.get("LOCALAPPDATA", ""))
WINDOWS_BROWSER_PATHS = (
    PROGRAM_FILES / "Google/Chrome/Application/chrome.exe",
    PROGRAM_FILES_X86 / "Google/Chrome/Application/chrome.exe",
    LOCAL_APP_DATA / "Google/Chrome/Application/chrome.exe",
    PROGRAM_FILES / "Microsoft/Edge/Application/msedge.exe",
    PROGRAM_FILES_X86 / "Microsoft/Edge/Application/msedge.exe",
)


def find_browser_executable(explicit: Path | None = None) -> Path:
    candidates = (explicit,) if explicit is not None else WINDOWS_BROWSER_PATHS
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    raise FileNotFoundError("Chrome or Edge executable was not found")


def _free_local_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class BrowserSession(AbstractContextManager[object]):
    def __init__(
        self,
        headed: bool,
        artifacts_dir: Path,
        profile_dir: Path,
        browser_path: Path | None = None,
    ) -> None:
        self.headed = headed
        self.artifacts_dir = artifacts_dir
        self.profile_dir = profile_dir
        self.browser_path = browser_path
        self._browser: Chromium | None = None

    def __enter__(self):
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        options = (
            ChromiumOptions()
            .set_browser_path(find_browser_executable(self.browser_path))
            .set_local_port(_free_local_port())
            .set_user_data_path(self.profile_dir)
        )
        if not self.headed:
            options.headless()
        self._browser = Chromium(addr_or_opts=options)
        return self._browser.latest_tab

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._browser is not None:
            self._browser.quit()
```

- [ ] **Step 4 — GREEN：用以下完整内容替换 adapter**

将 `app/sites/douban_movie.py` 替换为：

```python
from __future__ import annotations

import re
from dataclasses import replace

from DrissionPage.common import wait_until

from app.models import Candidate, MatchMethod, MovieResult, Status, Task


DETAIL_URL = re.compile(r"^https://movie\.douban\.com/subject/\d+/$")
BLOCK_TEXT = ("访问频率过高", "异常请求", "验证码")


class BlockedError(RuntimeError):
    pass


class PageChangedError(RuntimeError):
    pass


class NetworkError(RuntimeError):
    pass


class DoubanMovieAdapter:
    SEARCH_INPUTS = (
        "@role=searchbox",
        "css:input[name='search_text']",
    )

    @staticmethod
    def is_blocked(html: str, status_code: int | None) -> bool:
        return status_code in {403, 418, 429} or any(marker in html for marker in BLOCK_TEXT)

    @staticmethod
    def parse_search_html(html: str) -> list[Candidate]:
        links = re.findall(
            r'<a[^>]+href="(https://movie\.douban\.com/subject/\d+/)"[^>]*>([^<]+)</a>\s*<span>(\d{4})\s*/\s*([^<]+)</span>',
            html,
        )
        return [
            Candidate(title.strip(), year, kind.strip(), url)
            for url, title, year, kind in links[:5]
        ]

    @staticmethod
    def parse_detail_html(html: str, task: Task, url: str) -> MovieResult:
        title = re.search(r'property="v:itemreviewed"[^>]*>([^<]+)', html)
        year = re.search(r'class="year"[^>]*>\((\d{4})\)', html)
        directors = re.findall(r'rel="v:directedBy"[^>]*>([^<]+)', html)
        rating = re.search(r'property="v:average"[^>]*>([^<]*)', html)
        if title is None or DETAIL_URL.fullmatch(url) is None:
            return replace(
                MovieResult.from_task(task),
                status=Status.PAGE_CHANGED,
                error_message="Missing title or canonical detail URL",
            ).stamped()
        rating_value = float(rating.group(1)) if rating and rating.group(1).strip() else None
        return replace(
            MovieResult.from_task(task),
            matched_title=title.group(1).strip(),
            matched_year=year.group(1) if year else None,
            director=" / ".join(name.strip() for name in directors),
            rating=rating_value,
            detail_url=url,
            match_method=MatchMethod.NONE,
            status=Status.SUCCESS,
        ).stamped()

    def _search_input(self, tab):
        for locator in self.SEARCH_INPUTS:
            element = tab.ele(locator, timeout=1)
            if element:
                return element
        raise PageChangedError("Search input was not found")

    def search(self, tab, task: Task) -> list[Candidate]:
        if not tab.get("https://movie.douban.com/", retry=0, timeout=20):
            raise NetworkError("Douban navigation failed")
        if self.is_blocked(tab.html, None):
            raise BlockedError("Douban blocked the batch")
        self._search_input(tab).input(f"{task.query}\n", clear=True)
        try:
            wait_until(
                lambda: bool(tab.ele("css:.result-list", timeout=0))
                or "没有找到" in tab.html,
                timeout=10,
            )
        except TimeoutError as exc:
            raise PageChangedError("Search result marker was not found") from exc
        page_html = tab.html
        if self.is_blocked(page_html, None):
            raise BlockedError("Douban blocked the batch")
        return self.parse_search_html(page_html)

    def fetch_detail(self, tab, task: Task, candidate: Candidate) -> MovieResult:
        if not tab.get(candidate.detail_url, retry=0, timeout=20):
            raise NetworkError("Douban detail navigation failed")
        page_html = tab.html
        if self.is_blocked(page_html, None):
            raise BlockedError("Douban blocked the batch")
        return self.parse_detail_html(page_html, task, tab.url)
```

不得增加 `time.sleep()`；本任务不得执行 `search()` 或 `fetch_detail()` 的真实站点导航。

- [ ] **Step 5 — focused offline verify**

```powershell
Set-Location 'D:\DataAnt\.worktrees\browser-bot-demo'
python -m pytest tests/test_browser_session.py tests/test_douban_parser.py -v
```

预期：全部 PASS，测试仅使用临时文件、fixture 和 fake tab，没有网络流量。

- [ ] **Step 6 — 本地浏览器 smoke，仅 data URL**

以下命令允许启动本机浏览器，但只能打开 `data:` 页面；不得把 URL 改为豆瓣或任何 `http(s)` 地址：

```powershell
Set-Location 'D:\DataAnt\.worktrees\browser-bot-demo'
python -c "from pathlib import Path; from app.browser_session import BrowserSession; s=BrowserSession(True, Path('artifacts'), Path('browser-profile/core06-smoke')); t=s.__enter__(); ok=t.get('data:text/html,<title>core06-offline-smoke</title><h1>offline</h1>'); print(ok, t.title); s.__exit__(None,None,None)"
```

预期：本机 Chrome/Edge 有头启动，标题输出包含 `core06-offline-smoke`，随后浏览器退出且命令为 0。`browser-profile/core06-smoke/` 是本地运行产物，不得暂存或提交。若本机浏览器不可用，按 `BLOCKED` 回报，不得改用外网验证。

- [ ] **Step 7 — full verify**

```powershell
Set-Location 'D:\DataAnt\.worktrees\browser-bot-demo'
python -m pytest -q
```

预期：完整测试套件退出码 0；不得运行任何真实站点 CLI 或端到端命令。

- [ ] **Step 8 — commit**

```powershell
Set-Location 'D:\DataAnt\.worktrees\browser-bot-demo'
git status --short
git add -- app/browser_session.py app/sites/douban_movie.py tests/test_browser_session.py tests/test_douban_parser.py
git diff --cached --check
git commit -m "feat: add DrissionPage browser actions"
```

暂存区必须只有上述四个文件，不能包含 profile、artifacts 或 fixture 运行产物。

## Acceptance checklist

- [ ] 仅允许列表中的四个代码/测试文件被创建或修改。
- [ ] 依赖仍为 `DrissionPage>=4.1.1,<4.2`，没有安装或依赖改动。
- [ ] 自动发现本机 Chrome/Edge，也支持显式浏览器路径。
- [ ] 使用独立 `profile_dir` 和动态 `127.0.0.1` 端口，不接管日常 profile。
- [ ] headed/headless 由参数控制；退出调用 Chromium `quit()`。
- [ ] `BlockedError`、`PageChangedError`、自定义 `NetworkError` 分类明确。
- [ ] locator 契约只有 role 与短 CSS fallback；不用固定 sleep。
- [ ] 自动测试全部离线，浏览器 smoke 只打开 `data:` URL。
- [ ] 本任务没有真实豆瓣或其他外网流量；真实站点验证留给 Core 10。
- [ ] focused tests、data-URL smoke 与 full suite 均退出 0。
- [ ] commit message 精确为 `feat: add DrissionPage browser actions`。
