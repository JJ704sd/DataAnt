from pathlib import Path

from app.browser_session import BrowserSession


def run() -> str:
    with BrowserSession(True, Path("artifacts"), Path("browser-profile/smoke")) as tab:
        tab.get("data:text/html,<title>browser-smoke</title><h1>ok</h1>")
        assert tab.url.startswith("data:")
        assert tab.ele("tag:h1").text == "ok"
    return "BROWSER_SMOKE_OK"


if __name__ == "__main__":
    print(run())
