import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from requests.exceptions import Timeout

from openconnect_sso import app, cli, config
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


@pytest.mark.parametrize(
    ("options", "expected_level"),
    (([], logging.DEBUG), (["--log-level", "INFO"], logging.INFO)),
)
def test_log_level_prefers_cli_over_saved_config(options, expected_level):
    args = cli.create_argparser().parse_args(options)
    cfg = config.Config(log_level=logging.DEBUG)
    loop = MagicMock()
    loop.run_until_complete.side_effect = Timeout("gateway timed out")

    with (
        patch("openconnect_sso.app.config.load", return_value=cfg),
        patch("openconnect_sso.app.should_prompt_sudo_setup", return_value=False),
        patch("openconnect_sso.app.configure_logger") as configure_logger,
        patch("openconnect_sso.app.asyncio.new_event_loop", return_value=loop),
        patch("openconnect_sso.app.asyncio.set_event_loop"),
        patch("openconnect_sso.app._run", new=lambda args, cfg: object()),
        patch("openconnect_sso.app.logger.error"),
    ):
        assert app.run(args) == 4

    configure_logger.assert_called_once_with(logging.getLogger(), expected_level)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("options", "secrets", "expected_user", "expected_prompts"),
    (
        (
            ["--user", "new-user"],
            {"old-user": "old-password"},
            "new-user",
            [
                "Password (new-user): ",
                "TOTP secret (leave blank if not required) (new-user): ",
            ],
        ),
        (
            ["--user", "new-user"],
            {"new-user": "new-password", "totp/new-user": "JBSWY3DPEHPK3PXP"},
            "new-user",
            [],
        ),
        (
            [],
            {},
            "old-user",
            [
                "Password (old-user): ",
                "TOTP secret (leave blank if not required) (old-user): ",
            ],
        ),
        (
            [],
            {"old-user": "old-password", "totp/old-user": "JBSWY3DPEHPK3PXP"},
            "old-user",
            [],
        ),
    ),
)
async def test_account_selection_uses_matching_keyring_and_prompts(
    options, secrets, expected_user, expected_prompts
):
    args = cli.create_argparser().parse_args(options)
    cfg = config.Config(
        default_profile={"address": "vpn.example.com", "user_group": "", "name": ""},
        credentials={"username": "old-user"},
    )

    with (
        patch(
            "openconnect_sso.config.keyring.get_password",
            side_effect=lambda _, key: secrets.get(key),
        ),
        patch("openconnect_sso.config.keyring.set_password"),
        patch(
            "openconnect_sso.app.getpass.getpass", side_effect=["password", ""]
        ) as prompt,
        patch(
            "openconnect_sso.app.authenticate_to", new_callable=AsyncMock
        ) as authenticate,
    ):
        await app._run(args, cfg)

    assert cfg.credentials.username == expected_user
    assert authenticate.await_args.args[2].username == expected_user
    assert [call.kwargs["prompt"] for call in prompt.call_args_list] == expected_prompts


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


@pytest.mark.parametrize(
    ("available", "elevator"),
    (
        (("sudo", "doas"), "sudo"),
        (("sudo",), "sudo"),
        (("doas",), "doas"),
    ),
)
def test_openconnect_exit_one_does_not_retry(available, elevator):
    auth_info = SimpleNamespace(
        session_token="vpn-token", server_cert_hash="sha256:fingerprint"
    )
    host = SimpleNamespace(vpn_url="https://vpn.example.com/group")

    with (
        patch(
            "openconnect_sso.app.shutil.which",
            side_effect=lambda program: (
                f"/usr/bin/{program}" if program in available else None
            ),
        ),
        patch("openconnect_sso.app.subprocess.run") as run,
    ):
        run.return_value.returncode = 1

        result = app.run_openconnect(auth_info, host, None, "4.7.00136", [])

    assert result == 1
    run.assert_called_once_with(
        [
            elevator,
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


def test_sudo_setup_prompt_skipped_when_only_doas_is_available():
    cfg = config.Config()
    with (
        patch(
            "openconnect_sso.app.shutil.which",
            side_effect=lambda program: "/usr/bin/doas" if program == "doas" else None,
        ),
        patch("openconnect_sso.sudo_setup.check_sudoers_configured") as check,
    ):
        assert app.should_prompt_sudo_setup(cfg) is False
    check.assert_not_called()


def test_sudo_setup_command_requires_sudo(capsys):
    with (
        patch("openconnect_sso.cli.shutil.which", return_value=None),
        patch("openconnect_sso.sudo_setup.check_sudoers_configured") as check,
    ):
        assert cli.setup_sudo_configuration() == 1
    check.assert_not_called()
    assert "sudo not found in PATH" in capsys.readouterr().out
