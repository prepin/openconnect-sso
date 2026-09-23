from types import SimpleNamespace
from unittest.mock import patch

from openconnect_sso import app


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
