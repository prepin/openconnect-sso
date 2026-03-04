#!/usr/bin/env python3
"""
Script to explore SSO page structure and identify correct CSS selectors
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import openconnect_sso modules
sys.path.insert(0, str(Path(__file__).parent))

from openconnect_sso.browser import Browser
from openconnect_sso.config import Credentials, DisplayMode
import keyring

APP_NAME = "openconnect-sso"


async def explore_sso_page():
    print("=== SSO Page Explorer ===\n")

    username = "pavrepin"
    vpn_url = "https://mvpn.mvideo.ru"

    # Check if credentials exist in keychain
    print("Checking keychain for credentials...")
    password = keyring.get_password(APP_NAME, username)
    totp_secret = keyring.get_password(APP_NAME, f"totp/{username}")

    if password:
        print(f"✓ Password found for {username}")
    else:
        print(f"✗ No password found in keychain for {username}")

    if totp_secret:
        print(f"✓ TOTP secret found for {username}")
    else:
        print(f"✗ No TOTP secret found in keychain for {username}")

    print("\nStarting browser to explore SSO flow...")
    print("Please manually navigate through the 3 steps:")
    print("  1. Enter username")
    print("  2. Enter password")
    print("  3. Enter TOTP")
    print("\nI'll analyze the page structure at each step.\n")

    credentials = Credentials(username) if password else None

    async with Browser(proxy=None, display_mode=DisplayMode.SHOWN) as browser:
        # Start at VPN URL which should redirect to SSO
        await browser.authenticate_at(vpn_url, credentials)

        step = 1
        while True:
            try:
                await browser.page_loaded()
                url = browser.url
                print(f"\n{'=' * 60}")
                print(f"Step {step}: {url}")
                print(f"{'=' * 60}")

                # Inject JavaScript to analyze page structure
                if "2fa.mvideo.ru" in url or "mvideo.ru" in url:
                    print("\nAnalyzing page elements...")
                    print(
                        "Please check the browser console for detailed element information"
                    )
                    print("Look for elements with these attributes:")
                    print("  - Input fields: type, name, id, placeholder")
                    print("  - Buttons: text content, type, class, id")

                step += 1

                if "mvpn.mvideo.ru" in url and "2fa" not in url:
                    print("\n✓ Successfully authenticated! Redirected to VPN endpoint.")
                    break

            except Exception as e:
                print(f"\nError or browser closed: {e}")
                break

    print("\n=== Exploration Complete ===")
    print(
        "\nBased on the pages you visited, update config.toml with correct selectors."
    )
    print("Example format:")
    print("""
[[auto_fill_rules."https://2fa.mvideo.ru/*"]]
selector = "input[name='Login']"
fill = "username"

[[auto_fill_rules."https://2fa.mvideo.ru/*"]]
selector = "button[type='submit']"
action = "click"
""")


if __name__ == "__main__":
    try:
        asyncio.run(explore_sso_page())
    except KeyboardInterrupt:
        print("\n\nExploration cancelled by user.")
        sys.exit(0)
