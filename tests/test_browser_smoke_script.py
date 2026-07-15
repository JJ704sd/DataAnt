from pathlib import Path

from scripts import browser_smoke


class FakeTab:
    url = "data:text/html,<h1>ok</h1>"

    def get(self, url: str) -> None:
        assert url.startswith("data:text/html,")

    def ele(self, locator: str):
        assert locator == "tag:h1"
        return type("Heading", (), {"text": "ok"})()


class FakeSession:
    exited = False

    def __init__(self, headed: bool, artifacts: Path, profile: Path):
        assert headed is True

    def __enter__(self):
        return FakeTab()

    def __exit__(self, exc_type, exc, traceback):
        self.exited = True


def test_run_uses_local_data_page_and_closes_session(monkeypatch) -> None:
    session = FakeSession(True, Path("artifacts"), Path("browser-profile/smoke"))
    monkeypatch.setattr(browser_smoke, "BrowserSession", lambda *args: session)
    assert browser_smoke.run() == "BROWSER_SMOKE_OK"
    assert session.exited is True
