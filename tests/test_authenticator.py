from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from openconnect_sso.authenticator import (
    AuthenticationError,
    Authenticator,
    AuthCompleteResponse,
    AuthRequestResponse,
    AuthResponseError,
    HTTP_TIMEOUT,
    create_http_headers,
    create_http_session,
    parse_response,
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


@pytest.mark.parametrize(
    ("xml", "error"),
    (
        (b"<broken", "Invalid XML"),
        (b'<config-auth type="other"/>', "Unexpected authentication response type"),
        (
            b'<config-auth type="auth-request"><auth id="other"/></config-auth>',
            "Unexpected authentication request ID",
        ),
        (
            b'<config-auth type="complete"><auth id="other"/></config-auth>',
            "Unexpected authentication completion ID",
        ),
        (
            b'<config-auth type="auth-request"><auth id="main"/></config-auth>',
            "Missing authentication request attributes",
        ),
        (
            b'<config-auth type="complete"><auth id="success"/></config-auth>',
            "Missing authentication completion attributes",
        ),
    ),
)
def test_invalid_gateway_response_reports_protocol_error(xml, error):
    response = SimpleNamespace(content=xml, raise_for_status=lambda: None)
    with pytest.raises(AuthResponseError, match=error):
        parse_response(response)


def test_valid_gateway_responses_still_parse():
    request = SimpleNamespace(
        content=(
            b'<config-auth type="auth-request"><auth id="main">'
            b"<message>Sign in</message>"
            b"<sso-v2-login>https://login.example.com</sso-v2-login>"
            b"<sso-v2-login-final>https://vpn.example.com/final</sso-v2-login-final>"
            b"<sso-v2-token-cookie-name>sso-token</sso-v2-token-cookie-name>"
            b"</auth><opaque>opaque-data</opaque></config-auth>"
        ),
        raise_for_status=lambda: None,
    )
    complete = SimpleNamespace(
        content=(
            b'<config-auth type="complete"><auth id="success">'
            b"<message>Connected</message></auth><session-token>vpn-token</session-token>"
            b"<config><vpn-base-config><server-cert-hash>sha256:hash</server-cert-hash>"
            b"</vpn-base-config></config></config-auth>"
        ),
        raise_for_status=lambda: None,
    )

    assert parse_response(request).login_url == "https://login.example.com"
    result = parse_response(complete)
    assert isinstance(result, AuthCompleteResponse)
    assert result.session_token == "vpn-token"


@pytest.mark.asyncio
async def test_rejected_authentication_does_not_log_gateway_response():
    response = AuthRequestResponse(
        "main", "", "", "rejected with vpn-token", "", "", "", None
    )
    authenticator = Authenticator.__new__(Authenticator)
    with (
        patch.object(authenticator, "_detect_authentication_target_url"),
        patch.object(authenticator, "_start_authentication", return_value=response),
        patch("openconnect_sso.authenticator.logger.error") as error,
        pytest.raises(AuthenticationError) as exc,
    ):
        await authenticator.authenticate(None)

    assert "vpn-token" not in str(exc.value)
    error.assert_not_called()
