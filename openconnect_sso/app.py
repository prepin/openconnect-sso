import asyncio
import getpass
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

import shlex
import shutil
import structlog
from prompt_toolkit import HTML
from prompt_toolkit.shortcuts import radiolist_dialog

from openconnect_sso import config
from openconnect_sso.authenticator import Authenticator, AuthResponseError
from openconnect_sso.browser import Terminated
from openconnect_sso.config import Credentials
from openconnect_sso.profile import get_profiles

from requests.exceptions import HTTPError

logger = structlog.get_logger()


def should_prompt_sudo_setup(cfg):
    """Check if we should prompt user to setup sudo."""
    try:
        from openconnect_sso.sudo_setup import check_sudoers_configured
    except ImportError:
        return False

    # Don't prompt if already configured or dismissed
    if cfg.sudo_configured or cfg.sudo_setup_dismissed:
        return False

    # Don't prompt on Windows
    if os.name == "nt":
        return False

    # Check if already working
    if check_sudoers_configured():
        cfg.sudo_configured = True
        config.save(cfg)
        return False

    return True


def prompt_sudo_setup(cfg):
    """Prompt user to setup passwordless sudo."""
    from prompt_toolkit.shortcuts import button_dialog

    result = button_dialog(
        title="Setup Passwordless sudo",
        text=(
            "openconnect-sso requires sudo to run openconnect.\n\n"
            "Would you like to configure passwordless sudo for openconnect?\n"
            "This will only allow openconnect to run without password.\n\n"
            "You can also run: openconnect-sso --setup-sso"
        ),
        buttons=[
            ("Setup Now", True),
            ("Never Ask Again", "dismissed"),
            ("Skip", False),
        ],
    ).run()

    if result is True:
        # Run setup
        from openconnect_sso.cli import setup_sudo_configuration

        setup_sudo_configuration()
    elif result == "dismissed":
        # Mark as dismissed
        cfg.sudo_setup_dismissed = True
        config.save(cfg)
    # If False (Skip), do nothing


def run(args):
    cfg = config.load()

    # Check if we should prompt for sudo setup (before VPN auth)
    if should_prompt_sudo_setup(cfg):
        prompt_sudo_setup(cfg)

    log_level = args.log_level if args.log_level is not None else cfg.log_level
    configure_logger(logging.getLogger(), log_level)

    try:
        if os.name == "nt":
            asyncio.set_event_loop(asyncio.ProactorEventLoop())
            loop = asyncio.get_event_loop()
        else:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        auth_response, selected_profile = loop.run_until_complete(_run(args, cfg))
    except KeyboardInterrupt:
        logger.warn("CTRL-C pressed, exiting")
        return 130
    except ValueError as e:
        msg, retval = e.args
        logger.error(msg)
        return retval
    except Terminated:
        logger.warn("Browser window terminated, exiting")
        return 2
    except AuthResponseError as exc:
        logger.error(
            f'Required attributes not found in response ("{exc}", does this endpoint do SSO?), exiting'
        )
        return 3
    except HTTPError as exc:
        logger.error(f"Request error: {exc}")
        return 4

    config.save(cfg)

    if args.authenticate:
        logger.warn("Exiting after login, as requested")
        details = {
            "host": selected_profile.vpn_url,
            "cookie": auth_response.session_token,
            "fingerprint": auth_response.server_cert_hash,
        }
        if args.authenticate == "json":
            print(json.dumps(details, indent=4))
        elif args.authenticate == "shell":
            print(
                "\n".join(f"{k.upper()}={shlex.quote(v)}" for k, v in details.items())
            )
        return 0

    try:
        return run_openconnect(
            auth_response,
            selected_profile,
            args.proxy,
            args.ac_version,
            args.openconnect_args,
            cfg.on_connect,
        )
    except KeyboardInterrupt:
        logger.warn("CTRL-C pressed, exiting")
        return 0
    finally:
        handle_disconnect(cfg.on_disconnect)


def configure_logger(logger, level):
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer()
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(level)


async def _run(args, cfg):
    credentials = None
    if cfg.credentials:
        credentials = cfg.credentials
    elif args.user:
        credentials = Credentials(args.user)

    if credentials and not credentials.password:
        credentials.password = getpass.getpass(prompt=f"Password ({args.user}): ")
        cfg.credentials = credentials

    if credentials and not credentials.totp:
        credentials.totp = getpass.getpass(
            prompt=f"TOTP secret (leave blank if not required) ({args.user}): "
        )
        cfg.credentials = credentials

    if cfg.default_profile and not (args.use_profile_selector or args.server):
        selected_profile = cfg.default_profile
    elif args.use_profile_selector or args.profile_path:
        profiles = get_profiles(Path(args.profile_path))
        if not profiles:
            raise ValueError("No profile found", 17)

        selected_profile = await select_profile(profiles)
        if not selected_profile:
            raise ValueError("No profile selected", 18)
    elif args.server:
        selected_profile = config.HostProfile(
            args.server, args.usergroup, args.authgroup
        )
    else:
        raise ValueError(
            "Cannot determine server address. Invalid arguments specified.", 19
        )

    cfg.default_profile = config.HostProfile(
        selected_profile.address, selected_profile.user_group, selected_profile.name
    )

    display_mode = config.DisplayMode[args.browser_display_mode.upper()]

    auth_response = await authenticate_to(
        selected_profile, args.proxy, credentials, display_mode, args.ac_version
    )

    if args.on_disconnect and not cfg.on_disconnect:
        cfg.on_disconnect = args.on_disconnect

    return auth_response, selected_profile


async def select_profile(profile_list):
    selection = await radiolist_dialog(
        title="Select AnyConnect profile",
        text=HTML(
            "The following AnyConnect profiles are detected.\n"
            "The selection will be <b>saved</b> and not asked again unless the <pre>--profile-selector</pre> command line option is used"
        ),
        values=[(p, p.name) for i, p in enumerate(profile_list)],
    ).run_async()
    # Somehow prompt_toolkit sets up a bogus signal handler upon exit
    # TODO: Report this issue upstream
    if hasattr(signal, "SIGWINCH"):
        asyncio.get_event_loop().remove_signal_handler(signal.SIGWINCH)
    if not selection:
        return selection
    logger.info("Selected profile", profile=selection.name)
    return selection


def authenticate_to(host, proxy, credentials, display_mode, version):
    logger.info("Authenticating to VPN endpoint", name=host.name, address=host.address)
    return Authenticator(host, proxy, credentials, version).authenticate(display_mode)


def create_vpnc_wrapper(on_connect_command):
    import tempfile

    wrapper_script = f"""#!/bin/sh
/etc/vpnc/vpnc-script "$@"
if [ "$reason" = "connect" ]; then
    {on_connect_command} &
fi
"""
    wrapper_file = tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False)
    wrapper_file.write(wrapper_script)
    wrapper_file.close()
    os.chmod(wrapper_file.name, 0o755)
    return wrapper_file.name


def run_openconnect(auth_info, host, proxy, version, args, on_connect=""):
    as_root = next(([prog] for prog in ("doas", "sudo") if shutil.which(prog)), [])
    try:
        if not as_root:
            if os.name == "nt":
                import ctypes

                if not ctypes.windll.shell32.IsUserAnAdmin():
                    raise PermissionError
            else:
                raise PermissionError
    except PermissionError:
        logger.error(
            "Cannot find suitable program to execute as superuser (doas/sudo), exiting"
        )
        return 20

    command_line = [
        "openconnect",
        "--useragent",
        f"AnyConnect Linux_64 {version}",
        "--version-string",
        version,
        "--cookie-on-stdin",
        "--servercert",
        auth_info.server_cert_hash,
        *args,
        host.vpn_url,
    ]

    wrapper_script = None
    if on_connect and sys.platform.startswith("linux"):
        wrapper_script = create_vpnc_wrapper(on_connect)
        command_line.extend(["--script", wrapper_script])
        logger.info("Created vpnc wrapper for on_connect", script=wrapper_script)

    if proxy:
        command_line.extend(["--proxy", proxy])

    try:
        # Try to use sudo -n for passwordless execution
        if as_root == ["sudo"]:
            # First try with -n flag (passwordless)
            passwordless_command = ["sudo", "-n"] + command_line
            session_token = auth_info.session_token.encode("utf-8")
            logger.debug(
                "Starting OpenConnect (passwordless)", command_line=passwordless_command
            )
            result = subprocess.run(passwordless_command, input=session_token)

            # If passwordless succeeded, return
            if result.returncode == 0 or result.returncode != 1:
                return result.returncode

            # If -n flag not supported or password required, fall back to regular sudo
            logger.debug("Passwordless sudo failed, trying regular sudo")
        elif as_root == ["doas"]:
            # doas also supports -n flag
            passwordless_command = ["doas", "-n"] + command_line
            session_token = auth_info.session_token.encode("utf-8")
            logger.debug(
                "Starting OpenConnect (passwordless doas)",
                command_line=passwordless_command,
            )
            result = subprocess.run(passwordless_command, input=session_token)

            # If passwordless succeeded, return
            if result.returncode == 0 or result.returncode != 1:
                return result.returncode

            logger.debug("Passwordless doas failed, trying regular doas")

        # Fall back to regular sudo/doas (will prompt for password)
        full_command = as_root + command_line
        session_token = auth_info.session_token.encode("utf-8")
        logger.debug("Starting OpenConnect", command_line=full_command)
        return subprocess.run(full_command, input=session_token).returncode
    finally:
        if wrapper_script:
            os.unlink(wrapper_script)
            logger.debug("Cleaned up vpnc wrapper", script=wrapper_script)


def handle_disconnect(command):
    if command:
        logger.info("Running command on disconnect", command_line=command)
        return subprocess.run(command, timeout=5, shell=True).returncode
