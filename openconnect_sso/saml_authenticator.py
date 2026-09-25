import asyncio
from urllib.parse import urlsplit

import structlog

from openconnect_sso.browser import Browser

log = structlog.get_logger()
BROWSER_AUTH_TIMEOUT = 600
COOKIE_WAIT_TIMEOUT = 5


async def authenticate_in_browser(
    proxy,
    auth_info,
    credentials,
    display_mode,
    timeout=BROWSER_AUTH_TIMEOUT,
    cookie_timeout=COOKIE_WAIT_TIMEOUT,
):
    async with Browser(proxy, display_mode) as browser:
        await browser.authenticate_at(auth_info.login_url, credentials)
        deadline = asyncio.get_running_loop().time() + timeout

        try:
            await asyncio.wait_for(
                _wait_for_final_url(browser, auth_info.login_final_url), timeout
            )
        except asyncio.TimeoutError as exc:
            raise BrowserAuthenticationTimeout(timeout) from exc

        try:
            remaining = max(0, deadline - asyncio.get_running_loop().time())
            return await asyncio.wait_for(
                browser.wait_for_cookie(
                    auth_info.token_cookie_name, auth_info.login_final_url
                ),
                min(cookie_timeout, remaining),
            )
        except asyncio.TimeoutError as exc:
            raise TokenCookieMissing(auth_info.token_cookie_name) from exc


async def _wait_for_final_url(browser, final_url):
    while not same_final_url(browser.url, final_url):
        await browser.page_loaded()
        log.debug("Browser loaded page")


def same_final_url(actual, expected):
    if not actual:
        return False
    try:
        actual_url, expected_url = urlsplit(actual), urlsplit(expected)
        return (
            actual_url.scheme.lower() == expected_url.scheme.lower()
            and actual_url.hostname is not None
            and actual_url.hostname == expected_url.hostname
            and (actual_url.port or default_port(actual_url.scheme))
            == (expected_url.port or default_port(expected_url.scheme))
            and actual_url.path.rstrip("/") == expected_url.path.rstrip("/")
        )
    except ValueError:
        return False


def default_port(scheme):
    return {"https": 443, "http": 80}.get(scheme.lower())


class BrowserAuthenticationTimeout(Exception):
    def __init__(self, timeout):
        super().__init__(f"Browser authentication timed out after {timeout} seconds")


class TokenCookieMissing(Exception):
    def __init__(self, cookie_name):
        super().__init__(
            f"Browser authentication finished without expected cookie {cookie_name!r}"
        )
