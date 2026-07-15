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
