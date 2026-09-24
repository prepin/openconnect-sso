from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from openconnect_sso.authenticator import (
    Authenticator,
    HTTP_TIMEOUT,
    create_http_headers,
    create_http_session,
)


def test_explicit_proxy_disables_environment_proxies():
    session = create_http_session("socks5://proxy.example.com:1080", "4.7.00136")

    assert session.trust_env is False
    assert session.proxies == {
        "http": "socks5://proxy.example.com:1080",
        "https": "socks5://proxy.example.com:1080",
    }


def test_redirect_discovery_uses_session_and_timeout():
    authenticator = Authenticator.__new__(Authenticator)
    authenticator.host = SimpleNamespace(
        address="vpn.example.com/group",
        vpn_url="https://vpn.example.com/group",
    )
    authenticator.session = MagicMock()
    response = MagicMock(url="https://redirect.example.com/group")
    authenticator.session.get.return_value = response

    authenticator._detect_authentication_target_url()

    authenticator.session.get.assert_called_once_with(
        "https://vpn.example.com/group", timeout=HTTP_TIMEOUT
    )
    assert authenticator.host.address == "https://redirect.example.com/group"


def test_authentication_logs_do_not_contain_secrets():
    authenticator = Authenticator.__new__(Authenticator)
    authenticator.host = SimpleNamespace(vpn_url="https://vpn.example.com/group")
    authenticator.version = "4.7.00136"
    authenticator.session = MagicMock()
    response = SimpleNamespace(
        content=b"<session-token>vpn-token</session-token>", status_code=200
    )
    authenticator.session.post.return_value = response

    with (
        patch(
            "openconnect_sso.authenticator._create_auth_init_request",
            return_value=b"init-request",
        ),
        patch(
            "openconnect_sso.authenticator._create_auth_finish_request",
            return_value=b"<sso-token>sso-token</sso-token>",
        ),
        patch("openconnect_sso.authenticator.parse_response"),
        patch("openconnect_sso.authenticator.logger.debug") as debug,
    ):
        authenticator._start_authentication()
        authenticator._complete_authentication(MagicMock(), "sso-token")

    log_output = repr(debug.call_args_list)
    assert "vpn-token" not in log_output
    assert "sso-token" not in log_output
    assert debug.call_args_list[1].kwargs == {"status": 200}
    assert debug.call_args_list[3].kwargs == {"status": 200}
    expected = {
        "headers": create_http_headers("4.7.00136"),
        "timeout": HTTP_TIMEOUT,
    }
    assert authenticator.session.post.call_args_list[0].kwargs == expected
    assert authenticator.session.post.call_args_list[1].kwargs == expected
