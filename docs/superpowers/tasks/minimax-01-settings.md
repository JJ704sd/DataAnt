# MiniMax 01：可选依赖与安全配置

## 操作提示词（可直接复制）

```text
你是本任务的实现工程师。唯一工作目录是绝对路径 D:\DataAnt\.worktrees\browser-bot-demo；所有命令都必须以该目录为工作目录。唯一任务说明是 D:\DataAnt\.worktrees\browser-bot-demo\docs\superpowers\tasks\minimax-01-settings.md。只读取本 spec 和完成本任务必需的现有代码/测试；不得读取 docs/superpowers/plans/2026-07-15-minimax-candidate-matcher.md 或其他总计划。

严格按本 spec 的 RED → RED verify → GREEN → focused verify → full verify → commit 顺序执行。只修改“精确文件边界”列出的文件；不得调用 MiniMax、不得打开或自动化浏览器、不得调用 DrissionPage、不得写 Excel；不得引入 Playwright、trace、storage_state。不得在代码、测试、日志或提交中写入真实 Key。先检查 Base/前置条件，不满足就停止。

完成后仅以如下格式回复：
DONE
- changed: <文件列表>
- red: <命令及预期失败摘要>
- green: <命令及通过摘要>
- full_verify: <命令及通过摘要>
- commit: <hash> feat: add optional MiniMax settings
或：
BLOCKED
- gate: <未满足的门禁>
- evidence: <命令与输出摘要>
- changed: <如有；不得为绕过门禁扩大范围>
```

## Base / 前置条件

- 仓库根目录：`D:\DataAnt\.worktrees\browser-bot-demo`。
- 浏览器核心 Demo 已完成且测试全绿；至少存在 `app/models.py`、`app/matcher.py`、`app/runner.py`、`app/main.py`。
- 工作树在开始时必须干净。运行 `git status --short`；如有输出，回复 `BLOCKED`，不要覆盖他人修改。
- 本任务不依赖 OpenAI SDK 已安装；RED 与设置测试必须在没有 `llm` extra 时也能收集。
- 本任务只建立配置边界，不发送任何网络请求。LLM 永远只是确定性规则产生歧义后的可选 fallback；Key 的存在不代表可以调用模型。

## Goal

增加可选的 OpenAI Python SDK 依赖和经验证的 MiniMax 环境配置。默认核心安装与 `import app.llm_matcher` 不导入 `openai`；启用端稍后使用固定 10 秒超时、一次调用、SDK 自动重试关闭。缺少 Key 或模型时给出不含秘密值的配置错误。

## 精确文件边界

- Modify: `pyproject.toml`
- Modify: `.env.example`
- Create: `app/llm_matcher.py`
- Create: `tests/test_llm_matcher.py`
- 不得修改 README、Runner、CLI、浏览器、Excel 或任何其他文件。

## 必须保持的接口与安全契约

后续任务会从 `app.llm_matcher` 导入：

```python
class LlmConfigurationError(ValueError): ...

@dataclass(frozen=True, slots=True)
class MiniMaxSettings:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 10.0
    min_confidence: float = 0.85

    @classmethod
    def from_env(cls) -> "MiniMaxSettings": ...
```

环境变量契约：

- `MINIMAX_API_KEY`：启用 `--llm-match` 时必填；只存内存，不输出值。
- `MINIMAX_MODEL`：启用时必填；模型名不可在实现中硬编码。
- `MINIMAX_BASE_URL`：可选，缺省 `https://api.minimax.io/v1`，移除末尾 `/`。
- `.env.example` 只能包含变量名、空 Key 与非秘密默认值。禁止真实 Key。
- 错误文本只允许指出缺少哪个变量，不得拼接环境、HTML、cookies、browser-profile 或异常请求对象。

未来客户端构造契约在此锁定：`OpenAI(api_key=..., base_url=..., timeout=10.0, max_retries=0)`。最多一次匹配请求，不自动重试。当前任务不得实际构造客户端或调用 API。

后续实现必须保持的端到端不变量也在本任务锁定：LLM 仅是确定性规则歧义时的 fallback；最小 payload 每次只发送 query、可选 year 与最多 5 个候选的 title/year/kind；本地严格校验 JSON、`chosen_index` 类型与 bounds、`confidence >= 0.85` 以及标题关系。非法响应或 10 秒超时必须返回无决策，并由 Runner 写 `REVIEW_REQUIRED`，不得自动重试。不得发送或泄漏 Key、HTML、cookies、browser-profile，也不得让 LLM 调用 DrissionPage 或写 Excel。

## 严格 TDD 实施步骤

### 1. RED：先创建失败测试

创建 `tests/test_llm_matcher.py`，完整内容如下：

```python
import sys

import pytest

from app.llm_matcher import LlmConfigurationError, MiniMaxSettings


def test_settings_require_key_when_llm_is_enabled(monkeypatch) -> None:
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.setenv("MINIMAX_MODEL", "test-model")
    with pytest.raises(LlmConfigurationError, match="MINIMAX_API_KEY is required"):
        MiniMaxSettings.from_env()


def test_settings_require_model_when_llm_is_enabled(monkeypatch) -> None:
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.delenv("MINIMAX_MODEL", raising=False)
    with pytest.raises(LlmConfigurationError, match="MINIMAX_MODEL is required"):
        MiniMaxSettings.from_env()


def test_settings_use_safe_defaults_and_trim_values(monkeypatch) -> None:
    monkeypatch.setenv("MINIMAX_API_KEY", " test-key ")
    monkeypatch.setenv("MINIMAX_MODEL", " test-model ")
    monkeypatch.delenv("MINIMAX_BASE_URL", raising=False)
    settings = MiniMaxSettings.from_env()
    assert settings.api_key == "test-key"
    assert settings.base_url == "https://api.minimax.io/v1"
    assert settings.model == "test-model"
    assert settings.timeout_seconds == 10.0
    assert settings.min_confidence == 0.85


def test_custom_base_url_has_no_trailing_slash(monkeypatch) -> None:
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.setenv("MINIMAX_MODEL", "test-model")
    monkeypatch.setenv("MINIMAX_BASE_URL", "https://example.invalid/v1/")
    assert MiniMaxSettings.from_env().base_url == "https://example.invalid/v1"


def test_import_does_not_load_openai() -> None:
    assert "openai" not in sys.modules
```

### 2. RED verify

```powershell
python -m pytest tests/test_llm_matcher.py -v
```

预期：收集失败，原因是 `app.llm_matcher` 不存在。若因其他原因失败，先修正测试环境，不得直接写实现。

### 3. GREEN：最小实现

在 `pyproject.toml` 的现有 `[project.optional-dependencies]` 中保留 `dev`，新增：

```toml
llm = ["openai>=1,<3"]
```

将 `.env.example` 设为以下三行；Key 必须为空：

```dotenv
MINIMAX_API_KEY=
MINIMAX_BASE_URL=https://api.minimax.io/v1
MINIMAX_MODEL=MiniMax-M2.7
```

创建 `app/llm_matcher.py`：

```python
from __future__ import annotations

import os
from dataclasses import dataclass


class LlmConfigurationError(ValueError):
    """Raised for local opt-in LLM configuration errors."""


@dataclass(frozen=True, slots=True)
class MiniMaxSettings:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 10.0
    min_confidence: float = 0.85

    @classmethod
    def from_env(cls) -> "MiniMaxSettings":
        key = os.environ.get("MINIMAX_API_KEY", "").strip()
        model = os.environ.get("MINIMAX_MODEL", "").strip()
        if not key:
            raise LlmConfigurationError(
                "MINIMAX_API_KEY is required when --llm-match is enabled"
            )
        if not model:
            raise LlmConfigurationError(
                "MINIMAX_MODEL is required when --llm-match is enabled"
            )
        base_url = os.environ.get(
            "MINIMAX_BASE_URL", "https://api.minimax.io/v1"
        ).strip().rstrip("/")
        return cls(api_key=key, base_url=base_url, model=model)
```

不得在模块顶层或 `from_env()` 中导入 `openai`。

### 4. Focused verify

```powershell
python -m pytest tests/test_llm_matcher.py -v
python -c "import sys; import app.llm_matcher; assert 'openai' not in sys.modules; print('llm settings import is SDK-free')"
```

预期：5 个测试通过，并打印 `llm settings import is SDK-free`。

### 5. Full verify

```powershell
python -m pytest -q
git diff --check
git diff --name-only
```

预期：全套测试 0 failures；`git diff --check` 无输出；文件列表只含本 spec 的四个精确文件。不得安装 `llm` extra、不得发网络请求。

### 6. Commit

```powershell
git add pyproject.toml .env.example app/llm_matcher.py tests/test_llm_matcher.py
git commit -m "feat: add optional MiniMax settings"
```

## Acceptance checklist

- [ ] `llm` 是 optional extra，核心依赖不包含 OpenAI SDK。
- [ ] 缺 Key、缺模型均 fail fast，错误不包含任何秘密值。
- [ ] 默认 base URL、10 秒、0.85 均由测试锁定。
- [ ] 模块导入不加载 `openai`。
- [ ] `.env.example` 中 Key 为空。
- [ ] 没有 MiniMax 调用、DrissionPage 调用、Excel 写入。
- [ ] 没有 Key、HTML、cookies、browser-profile 泄漏。
- [ ] 没有 Playwright、trace、storage_state 残留。
- [ ] focused/full verify 通过并使用指定 commit message。
