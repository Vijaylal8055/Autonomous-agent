"""Open the deployed Streamlit app in a headless browser.

Why a browser: plain HTTP requests don't count as app traffic and can't click the
"wake this app up" button that Streamlit Community Cloud shows on hibernated apps.
"""
import os
import sys

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

URL = os.environ.get("APP_URL", "").strip()
WAKE_BUTTON = "Yes, get this app back up!"
APP_IFRAME = 'iframe[title="streamlitApp"]'   # Community Cloud embeds the app in this iframe


def main() -> int:
    if not URL:
        print("APP_URL is not set. Add it under Settings -> Secrets and variables -> Actions -> Variables.")
        return 1

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=90_000)

        try:
            page.get_by_role("button", name=WAKE_BUTTON).click(timeout=15_000)
            print("App was hibernating: clicked the wake-up button.")
        except PWTimeout:
            print("No wake-up button: app was already awake.")

        try:
            page.wait_for_selector(APP_IFRAME, timeout=180_000)
            page.frame_locator(APP_IFRAME).locator('[data-testid="stApp"]').wait_for(timeout=180_000)
            print("App is up and rendering.")
            browser.close()
            return 0
        except PWTimeout:
            print("App did not finish loading within 3 minutes.")
            browser.close()
            return 1


if __name__ == "__main__":
    sys.exit(main())
