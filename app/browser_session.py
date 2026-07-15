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
