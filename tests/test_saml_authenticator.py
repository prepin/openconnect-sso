import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from openconnect_sso.browser import Terminated
from openconnect_sso.saml_authenticator import (
    BrowserAuthenticationTimeout,
    TokenCookieMissing,
    authenticate_in_browser,
)


class FakeBrowser:
    def __init__(self, final_url=None, cookies=None, cookie_error=None):
        self.final_url = final_url
        self.cookies = cookies or {}
        self.cookie_error = cookie_error
        self.url = None
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.closed = True

    async def authenticate_at(self, url, credentials):
        pass

    async def page_loaded(self):
        if self.final_url:
            self.url = self.final_url
        else:
            await asyncio.Future()

    async def wait_for_cookie(self, name):
        if self.cookie_error:
            raise self.cookie_error
        if name in self.cookies:
            return self.cookies[name]
        await asyncio.Future()


def auth_info():
    return SimpleNamespace(
        login_url="https://login.example.com",
        login_final_url="https://vpn.example.com/final",
        token_cookie_name="sso-token",
    )


@pytest.mark.asyncio
async def test_browser_authentication_times_out_and_closes_browser():
    browser = FakeBrowser()

    with (
        patch("openconnect_sso.saml_authenticator.Browser", return_value=browser),
        pytest.raises(BrowserAuthenticationTimeout),
    ):
        await authenticate_in_browser(None, auth_info(), None, None, timeout=0.01)

    assert browser.closed is True


@pytest.mark.asyncio
async def test_browser_authentication_reports_missing_cookie_and_closes_browser():
    browser = FakeBrowser(final_url=auth_info().login_final_url)

    with (
        patch("openconnect_sso.saml_authenticator.Browser", return_value=browser),
        pytest.raises(TokenCookieMissing, match="sso-token"),
    ):
        await authenticate_in_browser(
            None, auth_info(), None, None, cookie_timeout=0.01
        )

    assert browser.closed is True


@pytest.mark.asyncio
async def test_browser_authentication_waits_for_cookie_after_final_url():
    browser = FakeBrowser(final_url=auth_info().login_final_url)

    async def add_cookie(name):
        await asyncio.sleep(0)
        browser.cookies[name] = "token"
        return "token"

    browser.wait_for_cookie = add_cookie

    with patch("openconnect_sso.saml_authenticator.Browser", return_value=browser):
        token = await authenticate_in_browser(None, auth_info(), None, None)

    assert token == "token"
    assert browser.closed is True


@pytest.mark.asyncio
async def test_browser_closure_while_waiting_for_cookie_is_reported():
    browser = FakeBrowser(
        final_url=auth_info().login_final_url, cookie_error=Terminated()
    )

    with (
        patch("openconnect_sso.saml_authenticator.Browser", return_value=browser),
        pytest.raises(Terminated),
    ):
        await authenticate_in_browser(None, auth_info(), None, None)

    assert browser.closed is True
