"""Headless screenshot of the running app for the README."""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8765/"
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshot.png"


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": 1600, "height": 1000},
            device_scale_factor=2,
            color_scheme="dark",
        )
        page = ctx.new_page()
        page.goto(URL, wait_until="networkidle")
        # Wait until the header stat shows a non-zero node count
        page.wait_for_function(
            "() => parseInt(document.querySelector('#stat-nodes').textContent || '0') > 5",
            timeout=15000,
        )
        # Let fcose layout animation settle
        page.wait_for_timeout(4500)
        page.screenshot(path=str(OUT), full_page=False)
        browser.close()
    print(f"saved {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
