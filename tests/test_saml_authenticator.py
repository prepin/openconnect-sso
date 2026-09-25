import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from openconnect_sso.browser import PageLoadError, Terminated
from openconnect_sso.saml_authenticator import (
    BrowserAuthenticationTimeout,
    TokenCookieMissing,
    authenticate_in_browser,
    same_final_url,
)


class FakeBrowser:
    def __init__(
        self, final_url=None, cookies=None, cookie_error=None, load_error=None
    ):
        self.final_url = final_url
        self.cookies = cookies or {}
        self.cookie_error = cookie_error
        self.load_error = load_error
        self.url = None
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.closed = True

    async def authenticate_at(self, url, credentials):
        pass

    async def page_loaded(self):
        if self.load_error:
            raise self.load_error
        if self.final_url:
            self.url = self.final_url
        else:
            await asyncio.Future()

    async def wait_for_cookie(self, name, url=None):
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

    async def add_cookie(name, url):
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


@pytest.mark.parametrize(
    ("actual", "expected", "matches"),
    (
        (
            "https://VPN.EXAMPLE.COM/final/?ticket=123#done",
            "https://vpn.example.com/final",
            True,
        ),
        ("https://vpn.example.com:443/final", "https://vpn.example.com/final/", True),
        ("https://vpn.example.com/final-extra", "https://vpn.example.com/final", False),
        ("https://login.example.com/final", "https://vpn.example.com/final", False),
        ("http://vpn.example.com/final", "https://vpn.example.com/final", False),
        ("https://vpn.example.com:8443/final", "https://vpn.example.com/final", False),
        ("https://vpn.example.com:bad/final", "https://vpn.example.com/final", False),
    ),
)
def test_final_url_normalization(actual, expected, matches):
    assert same_final_url(actual, expected) is matches


@pytest.mark.asyncio
async def test_browser_load_failure_is_reported_and_browser_closes():
    browser = FakeBrowser(load_error=PageLoadError("Browser failed to load a page"))
    with (
        patch("openconnect_sso.saml_authenticator.Browser", return_value=browser),
        pytest.raises(PageLoadError, match="Browser failed"),
    ):
        await authenticate_in_browser(None, auth_info(), None, None)
    assert browser.closed is True
