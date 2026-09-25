import json
import logging
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from requests.exceptions import Timeout

from openconnect_sso import app, cli, config
from openconnect_sso.authenticator import AuthenticationError
from openconnect_sso.browser import PageLoadError
from openconnect_sso.saml_authenticator import (
    BrowserAuthenticationTimeout,
    TokenCookieMissing,
)


def test_request_timeout_returns_network_error():
    args = SimpleNamespace(log_level=logging.WARNING, authenticate=True)
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
        (PageLoadError("Browser failed to load a page"), 7),
    ),
)
def test_browser_authentication_errors_are_reported(exception, exit_code):
    args = SimpleNamespace(log_level=logging.WARNING, authenticate=True)
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


def test_gateway_rejection_returns_authentication_error():
    args = SimpleNamespace(log_level=logging.WARNING, authenticate=True)
    loop = MagicMock()
    loop.run_until_complete.side_effect = AuthenticationError(
        "Gateway rejected authentication"
    )

    with (
        patch("openconnect_sso.app.config.load", return_value=config.Config()),
        patch("openconnect_sso.app.configure_logger"),
        patch("openconnect_sso.app.asyncio.new_event_loop", return_value=loop),
        patch("openconnect_sso.app.asyncio.set_event_loop"),
        patch("openconnect_sso.app._run", new=lambda args, cfg: object()),
        patch("openconnect_sso.app.logger.error") as error,
    ):
        assert app.run(args) == 3

    error.assert_called_once_with(
        "VPN authentication failed", error="Gateway rejected authentication"
    )


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
        patch("openconnect_sso.app.preflight_openconnect", return_value="sudo"),
        patch("openconnect_sso.app.asyncio.new_event_loop", return_value=loop),
        patch("openconnect_sso.app.asyncio.set_event_loop"),
        patch("openconnect_sso.app._run", new=lambda args, cfg: object()),
        patch("openconnect_sso.app.logger.error"),
    ):
        assert app.run(args) == 4

    configure_logger.assert_called_once_with(logging.getLogger(), expected_level)


@pytest.mark.parametrize(
    ("program", "passwordless"),
    (("sudo", True), ("sudo", False), ("doas", False)),
)
def test_preflight_checks_openconnect_without_starting_tunnel(program, passwordless):
    with (
        patch("openconnect_sso.app.get_elevation_program", return_value=program),
        patch(
            "openconnect_sso.sudo_setup.get_openconnect_path",
            return_value="/usr/bin/openconnect",
        ),
        patch(
            "openconnect_sso.sudo_setup.check_sudoers_configured",
            return_value=passwordless,
        ) as check,
        patch("openconnect_sso.app.subprocess.run") as run,
    ):
        run.return_value.returncode = 0
        assert app.preflight_openconnect() == (program, "/usr/bin/openconnect")

    if program == "sudo":
        check.assert_called_once_with()
    else:
        check.assert_not_called()
    if program == "sudo" and passwordless:
        run.assert_not_called()
    else:
        run.assert_called_once_with(
            [program, "/usr/bin/openconnect", "--version"],
            stdout=app.subprocess.DEVNULL,
        )


def test_preflight_rejects_unavailable_or_denied_elevation():
    with patch("openconnect_sso.app.get_elevation_program", return_value=None):
        with pytest.raises(PermissionError, match="Neither sudo nor doas"):
            app.preflight_openconnect()

    with (
        patch("openconnect_sso.app.get_elevation_program", return_value="sudo"),
        patch(
            "openconnect_sso.sudo_setup.get_openconnect_path",
            return_value="/usr/bin/openconnect",
        ),
        patch(
            "openconnect_sso.sudo_setup.check_sudoers_configured", return_value=False
        ),
        patch(
            "openconnect_sso.app.subprocess.run",
            return_value=SimpleNamespace(returncode=1),
        ),
    ):
        with pytest.raises(PermissionError, match="sudo cannot run OpenConnect"):
            app.preflight_openconnect()


def test_preflight_failure_prevents_browser_authentication():
    args = cli.create_argparser().parse_args(["--server", "vpn.example.com"])
    with (
        patch("openconnect_sso.app.config.load", return_value=config.Config()),
        patch("openconnect_sso.app.should_prompt_sudo_setup", return_value=False),
        patch("openconnect_sso.app.configure_logger"),
        patch(
            "openconnect_sso.app.preflight_openconnect",
            side_effect=PermissionError("denied"),
        ),
        patch("openconnect_sso.app.asyncio.new_event_loop") as loop,
        patch("openconnect_sso.app._run") as authenticate,
        patch("openconnect_sso.app.logger.error"),
    ):
        assert app.run(args) == 20
    loop.assert_not_called()
    authenticate.assert_not_called()


def test_authenticate_only_skips_privilege_setup_and_preflight(capsys):
    args = cli.create_argparser().parse_args(
        ["--authenticate", "--server", "vpn.example.com"]
    )
    loop = MagicMock()
    loop.run_until_complete.return_value = (
        SimpleNamespace(session_token="test-cookie", server_cert_hash="test-hash"),
        SimpleNamespace(vpn_url="https://vpn.example.com"),
    )
    with (
        patch("openconnect_sso.app.config.load", return_value=config.Config()),
        patch("openconnect_sso.app.should_prompt_sudo_setup") as prompt,
        patch("openconnect_sso.app.configure_logger"),
        patch("openconnect_sso.app.preflight_openconnect") as preflight,
        patch("openconnect_sso.app.asyncio.new_event_loop", return_value=loop),
        patch("openconnect_sso.app.asyncio.set_event_loop"),
        patch("openconnect_sso.app._run", new=lambda args, cfg: object()),
        patch("openconnect_sso.app.config.save"),
        patch("openconnect_sso.app.logger.warn"),
        patch("openconnect_sso.app.run_openconnect") as tunnel,
    ):
        assert app.run(args) == 0
    prompt.assert_not_called()
    preflight.assert_not_called()
    tunnel.assert_not_called()
    assert "COOKIE=test-cookie" in capsys.readouterr().out


def test_legacy_tls_is_limited_to_authentication_child():
    raw_args = [
        "openconnect-sso",
        "--legacy-tls",
        "--authenticate",
        "shell",
        "--server",
        "vpn.example.com",
        "--",
        "--base-mtu=1370",
    ]
    output = json.dumps(
        {
            "host": "https://vpn.example.com/group",
            "cookie": "test-cookie",
            "fingerprint": "sha256:test",
        }
    ).encode()
    child = MagicMock()
    child.__enter__.return_value = child
    child.wait.return_value = 0
    child.stdout.fileno.return_value = 42
    with (
        patch.dict(os.environ, {"OPENSSL_CONF": "parent.conf"}),
        patch("openconnect_sso.app.sys.argv", raw_args),
        patch("openconnect_sso.app.subprocess.Popen", return_value=child) as popen,
        patch("openconnect_sso.app.os.set_blocking"),
        patch("openconnect_sso.app.os.read", side_effect=[output, BlockingIOError]),
    ):
        auth_response, profile = app.authenticate_with_legacy_tls()
        assert os.environ["OPENSSL_CONF"] == "parent.conf"

    command = popen.call_args.args[0]
    assert command[1:] == [
        "-m",
        "openconnect_sso.cli",
        "--authenticate=json",
        "--server",
        "vpn.example.com",
    ]
    assert Path(popen.call_args.kwargs["env"]["OPENSSL_CONF"]).is_file()
    assert popen.call_args.kwargs["env"]["OPENSSL_CONF"] != "parent.conf"
    assert popen.call_args.kwargs["stdout"] == subprocess.PIPE
    assert auth_response.session_token == "test-cookie"
    assert profile.vpn_url == "https://vpn.example.com/group"


def test_legacy_authentication_child_error_is_returned():
    args = cli.create_argparser().parse_args(["--legacy-tls", "--authenticate"])
    with (
        patch("openconnect_sso.app.config.load", return_value=config.Config()),
        patch("openconnect_sso.app.configure_logger"),
        patch(
            "openconnect_sso.app.authenticate_with_legacy_tls",
            side_effect=subprocess.CalledProcessError(5, ["auth-child"]),
        ),
        patch("openconnect_sso.app.preflight_openconnect") as preflight,
    ):
        assert app.run(args) == 5
    preflight.assert_not_called()


def test_legacy_tunnel_runs_in_parent_without_openssl_override():
    args = cli.create_argparser().parse_args(
        ["--legacy-tls", "--server", "vpn.example.com"]
    )
    saved = config.Config(on_connect="configure DNS", on_disconnect="notify user")
    auth = SimpleNamespace(session_token="test-cookie", server_cert_hash="sha256:test")
    profile = config.HostProfile("vpn.example.com", "", "")

    with (
        patch("openconnect_sso.app.config.load", side_effect=[config.Config(), saved]),
        patch("openconnect_sso.app.should_prompt_sudo_setup", return_value=False),
        patch("openconnect_sso.app.configure_logger"),
        patch(
            "openconnect_sso.app.preflight_openconnect",
            return_value=("sudo", "/usr/bin/openconnect"),
        ),
        patch(
            "openconnect_sso.app.authenticate_with_legacy_tls",
            return_value=(auth, profile),
        ),
        patch("openconnect_sso.app.config.save"),
        patch("openconnect_sso.app.run_openconnect", return_value=0) as tunnel,
        patch("openconnect_sso.app.handle_disconnect") as disconnect,
    ):
        original_conf = os.environ.get("OPENSSL_CONF")
        assert app.run(args) == 0
        assert os.environ.get("OPENSSL_CONF") == original_conf

    tunnel.assert_called_once_with(
        auth,
        profile,
        None,
        "4.7.00136",
        [],
        "configure DNS",
        ("sudo", "/usr/bin/openconnect"),
    )
    disconnect.assert_called_once_with("notify user")


def test_preflight_precedes_authentication_and_reuses_elevation():
    args = cli.create_argparser().parse_args(["--server", "vpn.example.com"])
    loop = MagicMock()
    loop.run_until_complete.return_value = (
        SimpleNamespace(session_token="test-cookie"),
        SimpleNamespace(vpn_url="https://vpn.example.com"),
    )
    order = []
    with (
        patch("openconnect_sso.app.config.load", return_value=config.Config()),
        patch("openconnect_sso.app.should_prompt_sudo_setup", return_value=False),
        patch("openconnect_sso.app.configure_logger"),
        patch(
            "openconnect_sso.app.preflight_openconnect",
            side_effect=lambda: (
                order.append("preflight"),
                ("sudo", "/usr/bin/openconnect"),
            )[1],
        ),
        patch("openconnect_sso.app.asyncio.new_event_loop", return_value=loop),
        patch("openconnect_sso.app.asyncio.set_event_loop"),
        patch(
            "openconnect_sso.app._run",
            new=lambda args, cfg: (order.append("authenticate"), object())[1],
        ),
        patch("openconnect_sso.app.config.save"),
        patch("openconnect_sso.app.run_openconnect", return_value=0) as tunnel,
        patch("openconnect_sso.app.handle_disconnect"),
    ):
        assert app.run(args) == 0
    assert order == ["preflight", "authenticate"]
    assert tunnel.call_args.args[-1] == ("sudo", "/usr/bin/openconnect")
    tunnel.assert_called_once()


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


def test_tunnel_uses_preflight_binary():
    auth_info = SimpleNamespace(
        session_token="test-cookie", server_cert_hash="test-hash"
    )
    host = SimpleNamespace(vpn_url="https://vpn.example.com")
    with (
        patch("openconnect_sso.app.get_elevation_program") as select_elevation,
        patch("openconnect_sso.app.subprocess.run") as run,
    ):
        app.run_openconnect(
            auth_info,
            host,
            None,
            "4.7.00136",
            [],
            elevation=("sudo", "/opt/homebrew/bin/openconnect"),
        )

    select_elevation.assert_not_called()
    assert run.call_args.args[0][:2] == ["sudo", "/opt/homebrew/bin/openconnect"]


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


def test_sudo_setup_does_not_claim_success_if_rule_is_inactive(capsys):
    with (
        patch("openconnect_sso.cli.shutil.which", return_value="/usr/bin/sudo"),
        patch(
            "openconnect_sso.sudo_setup.check_sudoers_configured",
            side_effect=[False, False],
        ) as check,
        patch(
            "openconnect_sso.sudo_setup.get_openconnect_path",
            return_value="/usr/bin/openconnect",
        ),
        patch("openconnect_sso.sudo_setup.setup_sudoers", return_value=True),
        patch("openconnect_sso.cli.config.save") as save,
    ):
        assert cli.setup_sudo_configuration() == 1

    assert check.call_count == 2
    save.assert_not_called()
    assert "passwordless OpenConnect is not active" in capsys.readouterr().out
