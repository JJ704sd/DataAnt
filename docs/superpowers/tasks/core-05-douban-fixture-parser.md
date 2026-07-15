# Core 05：豆瓣离线 Fixture Parser 执行 Spec

## 操作提示词（可直接复制）

```text
你是本仓库的实现代理。工作目录固定为 D:\DataAnt\.worktrees\browser-bot-demo。

只读取本 spec：D:\DataAnt\.worktrees\browser-bot-demo\docs\superpowers\tasks\core-05-douban-fixture-parser.md，以及必要现有代码 app/models.py、app/sites/__init__.py。不得读取总计划 docs/superpowers/plans/2026-07-15-browser-bot-core-demo.md。

严格按本 spec 的 TDD 顺序执行。只允许创建或修改 app/sites/douban_movie.py、tests/test_douban_parser.py、tests/fixtures/search_results.html、tests/fixtures/search_empty.html、tests/fixtures/detail_movie.html、tests/fixtures/blocked.html。不得安装依赖，不得改其他文件。所有 PowerShell 命令先 Set-Location 到绝对 worktree。全部解析必须离线；不得启动浏览器，不得发起任何真实豆瓣或其他外网流量。

验证成功后提交允许文件，commit message 必须为：feat: add fixture-backed Douban parsing

完成时回报：
DONE
- changed: <逐行列出文件>
- red: <命令与预期失败摘要>
- verify: <命令与通过摘要>
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
- Core 01–02 已完成，`app.models` 可导入下述类型；`app/sites/__init__.py` 已存在。
- 本任务仅使用 Python 标准库和本地脱敏 HTML；不需要 DrissionPage 进程。

## Goal

从本地脱敏搜索页和详情页 HTML 中纯解析最多 5 个候选及电影核心字段，并离线识别阻断信号。标题或规范详情 URL 缺失必须产生 `PAGE_CHANGED`；年份、导演、评分可缺失。

## Files（仅允许本任务）

- Create：`app/sites/douban_movie.py`
- Create：`tests/test_douban_parser.py`
- Create：`tests/fixtures/search_results.html`
- Create：`tests/fixtures/search_empty.html`
- Create：`tests/fixtures/detail_movie.html`
- Create：`tests/fixtures/blocked.html`

## Fixed contracts

必要模型契约：

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

class MatchMethod(StrEnum):
    NONE = "NONE"

class Status(StrEnum):
    SUCCESS = "SUCCESS"
    PAGE_CHANGED = "PAGE_CHANGED"

@dataclass(frozen=True, slots=True)
class MovieResult:
    task_id: str
    query: str
    query_year: str | None
    matched_title: str = ""
    matched_year: str | None = None
    director: str = ""
    rating: float | None = None
    detail_url: str = ""
    match_method: MatchMethod = MatchMethod.NONE
    status: Status = Status.UNEXPECTED_ERROR
    error_message: str = ""
    collected_at: str = ""

    @classmethod
    def from_task(cls, task: Task) -> "MovieResult": ...
    def stamped(self) -> "MovieResult": ...
```

`DoubanMovieAdapter` 固定公开纯函数：

```python
@staticmethod
def is_blocked(html: str, status_code: int | None) -> bool: ...

@staticmethod
def parse_search_html(html: str) -> list[Candidate]: ...

@staticmethod
def parse_detail_html(html: str, task: Task, url: str) -> MovieResult: ...
```

固定解析行为：候选 URL 仅接受 `https://movie.douban.com/subject/<数字>/`，最多前 5 项；详情核心字段为标题和规范 URL；导演多个用 ` / ` 连接；年份去括号；评分空白为 `None`，不写 0；HTTP 403/418/429 或文本“访问频率过高”“异常请求”“验证码”均判阻断。

## TDD implementation

- [ ] **Step 1 — 创建脱敏 fixtures（测试输入，不访问网络）**

`tests/fixtures/search_results.html`：

```html
<html><body><div id="content"><div class="result-list">
  <div class="result"><a href="https://movie.douban.com/subject/1292052/">肖申克的救赎</a><span>1994 / 电影</span></div>
  <div class="result"><a href="https://movie.douban.com/subject/9999999/">肖申克</a><span>2010 / 短片</span></div>
</div></div></body></html>
```

`tests/fixtures/search_empty.html`：

```html
<html><body><div id="content"><div class="result-list"></div><p>没有找到相关内容</p></div></body></html>
```

`tests/fixtures/detail_movie.html`：

```html
<html><body><h1><span property="v:itemreviewed">肖申克的救赎</span><span class="year">(1994)</span></h1>
<div id="info"><a rel="v:directedBy">弗兰克·德拉邦特</a><a rel="v:directedBy">第二导演</a></div>
<strong property="v:average">9.7</strong></body></html>
```

`tests/fixtures/blocked.html`：

```html
<html><body><h1>检测到有异常请求</h1><p>你的 IP 访问频率过高</p></body></html>
```

- [ ] **Step 2 — RED：创建完整测试**

创建 `tests/test_douban_parser.py`：

```python
from pathlib import Path

import pytest

from app.models import MatchMethod, Status, Task
from app.sites.douban_movie import DoubanMovieAdapter


FIXTURES = Path(__file__).parent / "fixtures"
DETAIL_URL = "https://movie.douban.com/subject/1292052/"


def html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_search_candidates_in_source_order() -> None:
    candidates = DoubanMovieAdapter.parse_search_html(html("search_results.html"))
    assert [(c.title, c.year, c.kind, c.detail_url) for c in candidates] == [
        ("肖申克的救赎", "1994", "电影", DETAIL_URL),
        ("肖申克", "2010", "短片", "https://movie.douban.com/subject/9999999/"),
    ]


def test_parse_search_empty_returns_empty_list() -> None:
    assert DoubanMovieAdapter.parse_search_html(html("search_empty.html")) == []


def test_parse_search_limits_candidates_to_five() -> None:
    item = '<a href="https://movie.douban.com/subject/{}/">电影</a><span>1994 / 电影</span>'
    assert len(DoubanMovieAdapter.parse_search_html("".join(item.format(i) for i in range(1, 7)))) == 5


def test_parse_detail_extracts_fields_and_multiple_directors() -> None:
    task = Task("a", "肖申克的救赎", "1994")
    result = DoubanMovieAdapter.parse_detail_html(html("detail_movie.html"), task, DETAIL_URL)
    assert result.status == Status.SUCCESS
    assert result.matched_title == "肖申克的救赎"
    assert result.matched_year == "1994"
    assert result.director == "弗兰克·德拉邦特 / 第二导演"
    assert result.rating == 9.7
    assert result.detail_url == DETAIL_URL
    assert result.match_method == MatchMethod.NONE
    assert result.collected_at


def test_detail_allows_missing_non_core_fields() -> None:
    task = Task("a", "电影", None)
    body = '<span property="v:itemreviewed">电影</span><strong property="v:average"></strong>'
    result = DoubanMovieAdapter.parse_detail_html(body, task, DETAIL_URL)
    assert result.status == Status.SUCCESS
    assert result.matched_year is None
    assert result.director == ""
    assert result.rating is None


@pytest.mark.parametrize("url", ["", "http://movie.douban.com/subject/1/", "https://example.com/subject/1/"])
def test_invalid_detail_url_returns_page_changed(url: str) -> None:
    task = Task("a", "电影", None)
    body = '<span property="v:itemreviewed">电影</span>'
    result = DoubanMovieAdapter.parse_detail_html(body, task, url)
    assert result.status == Status.PAGE_CHANGED
    assert result.error_message == "Missing title or canonical detail URL"


def test_missing_title_returns_page_changed() -> None:
    result = DoubanMovieAdapter.parse_detail_html("<html></html>", Task("a", "电影", None), DETAIL_URL)
    assert result.status == Status.PAGE_CHANGED


@pytest.mark.parametrize("status_code", [403, 418, 429])
def test_blocked_status_is_detected(status_code: int) -> None:
    assert DoubanMovieAdapter.is_blocked("", status_code)


def test_blocked_text_is_detected() -> None:
    assert DoubanMovieAdapter.is_blocked(html("blocked.html"), 200)
    assert not DoubanMovieAdapter.is_blocked("<html>普通页面</html>", 200)
```

- [ ] **Step 3 — verify RED**

```powershell
Set-Location 'D:\DataAnt\.worktrees\browser-bot-demo'
python -m pytest tests/test_douban_parser.py -v
```

预期：非零退出，因 `DoubanMovieAdapter` 尚不存在而 collection 失败。

- [ ] **Step 4 — GREEN：创建完整纯解析实现**

创建 `app/sites/douban_movie.py`：

```python
from __future__ import annotations

import re
from dataclasses import replace

from app.models import Candidate, MatchMethod, MovieResult, Status, Task


DETAIL_URL = re.compile(r"^https://movie\.douban\.com/subject/\d+/$")
BLOCK_TEXT = ("访问频率过高", "异常请求", "验证码")


class DoubanMovieAdapter:
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
```

- [ ] **Step 5 — focused verify 与 full verify**

```powershell
Set-Location 'D:\DataAnt\.worktrees\browser-bot-demo'
python -m pytest tests/test_douban_parser.py -v
python -m pytest -q
```

预期：parser tests 全部 PASS；完整套件退出 0。命令不启动浏览器且不访问网络。

- [ ] **Step 6 — commit**

```powershell
Set-Location 'D:\DataAnt\.worktrees\browser-bot-demo'
git status --short
git add -- app/sites/douban_movie.py tests/test_douban_parser.py tests/fixtures/search_results.html tests/fixtures/search_empty.html tests/fixtures/detail_movie.html tests/fixtures/blocked.html
git diff --cached --check
git commit -m "feat: add fixture-backed Douban parsing"
```

## Acceptance checklist

- [ ] 仅允许列表中的 6 个文件被创建或修改。
- [ ] 全部测试只读取脱敏本地 fixture；没有浏览器和网络流量。
- [ ] 候选保持源码顺序、URL 规范且最多 5 个。
- [ ] 标题与规范 URL 为核心字段；缺失时 `PAGE_CHANGED`。
- [ ] 年份、导演、评分缺失仍可 `SUCCESS`，空评分为 `None`。
- [ ] 多导演用 ` / ` 连接。
- [ ] 403/418/429 和三类阻断文本均可识别。
- [ ] focused tests 与 full suite 均退出 0。
- [ ] commit message 精确为 `feat: add fixture-backed Douban parsing`。
