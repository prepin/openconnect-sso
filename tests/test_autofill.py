from types import SimpleNamespace
from unittest.mock import MagicMock

from openconnect_sso.browser.webengine_process import (
    fill_totp,
    get_selectors,
    get_totp_check_script,
)


class Credentials:
    username = "user@example.com"
    password = "password"

    def __init__(self):
        self.current_totp = "expired-code"
        self.totp_reads = 0

    @property
    def totp(self):
        self.totp_reads += 1
        return self.current_totp


def test_totp_is_generated_only_after_field_appears():
    credentials = Credentials()
    rules = [
        SimpleNamespace(selector="input[name=otp]", fill="totp", action=None),
        SimpleNamespace(selector="button[type=submit]", fill=None, action="click"),
    ]

    autofill_script = get_selectors(rules, credentials)

    assert credentials.totp_reads == 0
    assert "pendingTotp" in autofill_script
    assert "input[name=otp]" in autofill_script

    credentials.current_totp = "current-code"
    page = MagicMock()
    fill_totp(page, "input[name=otp]", credentials)

    assert credentials.totp_reads == 1
    fill_script = page.runJavaScript.call_args.args[0]
    assert "current-code" in fill_script
    assert "expired-code" not in fill_script


def test_totp_field_check_uses_configured_selectors():
    script = get_totp_check_script(["input[name=otp]"])

    assert "input[name=otp]" in script
    assert "elem.value" in script
