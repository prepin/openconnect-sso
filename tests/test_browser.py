import asyncio
import sys

import attr
import pytest

from openconnect_sso.browser import Browser, DisplayMode, PageLoadError


@pytest.mark.asyncio
async def test_browser_selects_cookie_for_final_url():
    browser = Browser()
    browser.cookies = {
        ("sso-token", "login.example.com", "/"): "identity-provider-token",
        ("sso-token", ".vpn.example.com", "/auth"): "vpn-token",
    }

    token = await browser.wait_for_cookie(
        "sso-token", "https://vpn.example.com/auth/final"
    )

    assert token == "vpn-token"


@pytest.mark.asyncio
async def test_browser_context_manager_should_work_in_empty_context_manager():
    async with Browser() as _:
        pass


@pytest.mark.xfail(
    sys.platform in ["darwin", "win32"],
    reason="https://github.com/vlaci/openconnect-sso/issues/23",
)
@pytest.mark.asyncio
async def test_browser_reports_loaded_url(httpserver):
    async with Browser(display_mode=DisplayMode.HIDDEN) as browser:
        auth_url = httpserver.url_for("/authenticate")
        httpserver.expect_request("/authenticate").respond_with_data("<html>OK</html>")

        await browser.authenticate_at(auth_url, credentials=None)

        assert browser.url is None
        await browser.page_loaded()
        assert browser.url == auth_url


@pytest.mark.xfail(
    sys.platform in ["darwin", "win32"],
    reason="https://github.com/vlaci/openconnect-sso/issues/23",
)
@pytest.mark.asyncio
async def test_browser_cookies_accessible(httpserver):
    async with Browser(display_mode=DisplayMode.HIDDEN) as browser:
        httpserver.expect_request("/authenticate").respond_with_data(
            "<html><body>Hello</body></html>",
            headers={"Set-Cookie": "cookie-name=cookie-value"},
        )
        auth_url = httpserver.url_for("/authenticate")
        cred = Credentials("username", "password")

        await browser.authenticate_at(auth_url, cred)
        await browser.page_loaded()
        assert await browser.wait_for_cookie("cookie-name", auth_url) == "cookie-value"


@pytest.mark.xfail(
    sys.platform in ["darwin", "win32"],
    reason="https://github.com/vlaci/openconnect-sso/issues/23",
)
@pytest.mark.asyncio
async def test_browser_reports_failed_page_load(httpserver):
    url = httpserver.url_for("/unavailable")
    httpserver.stop()

    async with Browser(display_mode=DisplayMode.HIDDEN) as browser:
        await browser.authenticate_at(url, credentials=None)
        with pytest.raises(PageLoadError, match="Browser failed"):
            await asyncio.wait_for(browser.page_loaded(), timeout=5)


@attr.s
class Credentials:
    username = attr.ib()
    password = attr.ib()
