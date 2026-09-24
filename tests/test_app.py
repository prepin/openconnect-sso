import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from requests.exceptions import Timeout

from openconnect_sso import app
from openconnect_sso.saml_authenticator import (
    BrowserAuthenticationTimeout,
    TokenCookieMissing,
)


def test_request_timeout_returns_network_error():
    args = SimpleNamespace(log_level=logging.WARNING)
    loop = MagicMock()
    loop.run_until_complete.side_effect = Timeout("gateway timed out")

    with (
        patch("openconnect_sso.app.config.load", return_value=MagicMock()),
        patch("openconnect_sso.app.should_prompt_sudo_setup", return_value=False),
        patch("openconnect_sso.app.configure_logger"),
        patch("openconnect_sso.app.asyncio.new_event_loop", return_value=loop),
        patch("openconnect_sso.app.asyncio.set_event_loop"),
        patch("openconnect_sso.app._run", new=lambda args, cfg: object()),
        patch("openconnect_sso.app.logger.error") as error,
    ):
        result = app.run(args)

    assert result == 4
    error.assert_called_once_with("Request error: gateway timed out")


@pytest.mark.parametrize(
    ("exception", "exit_code"),
    (
        (BrowserAuthenticationTimeout(600), 5),
        (TokenCookieMissing("sso-token"), 6),
    ),
)
def test_browser_authentication_errors_are_reported(exception, exit_code):
    args = SimpleNamespace(log_level=logging.WARNING)
    loop = MagicMock()
    loop.run_until_complete.side_effect = exception

    with (
        patch("openconnect_sso.app.config.load", return_value=MagicMock()),
        patch("openconnect_sso.app.should_prompt_sudo_setup", return_value=False),
        patch("openconnect_sso.app.configure_logger"),
        patch("openconnect_sso.app.asyncio.new_event_loop", return_value=loop),
        patch("openconnect_sso.app.asyncio.set_event_loop"),
        patch("openconnect_sso.app._run", new=lambda args, cfg: object()),
        patch("openconnect_sso.app.logger.error") as error,
    ):
        result = app.run(args)

    assert result == exit_code
    error.assert_called_once_with(str(exception))


def test_connect_hook_runs_after_vpnc_script():
    with (
        patch("openconnect_sso.app.get_vpnc_script_path", return_value="/vpnc-script"),
    ):
        path = app.create_vpnc_wrapper(
            'resolvectl domain "$TUNDEV" corp && notify-send "VPN connected"'
        )

    try:
        wrapper = Path(path).read_text()
    finally:
        Path(path).unlink()

    assert '/vpnc-script "$@"' in wrapper
    assert 'if [ "$reason" = "connect" ]; then' in wrapper
    assert (
        "/bin/sh -c "
        '\'resolvectl domain "$TUNDEV" corp && notify-send "VPN connected"\' &'
    ) in wrapper


def test_openconnect_exit_one_does_not_retry():
    auth_info = SimpleNamespace(
        session_token="vpn-token", server_cert_hash="sha256:fingerprint"
    )
    host = SimpleNamespace(vpn_url="https://vpn.example.com/group")

    with (
        patch(
            "openconnect_sso.app.shutil.which",
            side_effect=lambda program: "/usr/bin/sudo" if program == "sudo" else None,
        ),
        patch("openconnect_sso.app.subprocess.run") as run,
    ):
        run.return_value.returncode = 1

        result = app.run_openconnect(auth_info, host, None, "4.7.00136", [])

    assert result == 1
    run.assert_called_once_with(
        [
            "sudo",
            "openconnect",
            "--useragent",
            "AnyConnect Linux_64 4.7.00136",
            "--version-string",
            "4.7.00136",
            "--cookie-on-stdin",
            "--servercert",
            "sha256:fingerprint",
            "https://vpn.example.com/group",
        ],
        input=b"vpn-token",
    )
