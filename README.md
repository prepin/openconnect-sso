# openconnect-sso

Maintained fork of openconnect-sso for Cisco SSL-VPN authentication through
Azure AD (SAMLv2), with automatic password and TOTP entry.

[![Tests](https://github.com/prepin/openconnect-sso/actions/workflows/test.yml/badge.svg)](https://github.com/prepin/openconnect-sso/actions/workflows/test.yml)

## Support

This fork supports Linux and macOS. It requires:

- OpenConnect
- A desktop keyring
- [uv](https://docs.astral.sh/uv/) for installation

The Python package includes the Qt browser dependencies.

## Installation

Install the current fork from Git:

```shell
uv tool install git+https://github.com/prepin/openconnect-sso
```

Upgrade or remove the tool with these commands:

```shell
uv tool upgrade openconnect-sso
uv tool uninstall openconnect-sso
```

The upstream PyPI, AUR, and Nix packages do not contain this fork's changes.

## Usage

Provide the VPN server and your user name on the first connection:

```shell
openconnect-sso --server vpn.example.com/group --user user@example.com
```

The application saves the selected server in its configuration file. It saves
the password and TOTP seed in the desktop keyring.

Later connections can use the saved configuration:

```shell
openconnect-sso
```

The configuration file is at
`$XDG_CONFIG_HOME/openconnect-sso/config.toml`. The usual Linux path is
`$HOME/.config/openconnect-sso/config.toml`.

### TOTP Autofill

The default rules support common Azure AD password and TOTP fields. Add a rule
to `config.toml` if your provider uses a different TOTP field:

```toml
[[auto_fill_rules."https://*"]]
selector = "input[type=tel]"
fill = "totp"
```

The browser generates the TOTP value when the field appears. It does not put
the TOTP seed in JavaScript.

### Legacy TLS Gateway

If the gateway requires legacy OpenSSL renegotiation, use this option:

```shell
openconnect-sso --legacy-tls
```

The installed package includes the OpenSSL configuration. This option applies
it only to the authentication child process. It lowers TLS security for that
process. OpenConnect uses GnuTLS for the tunnel.

### Authentication Only

Use `--authenticate` to print connection data without starting the tunnel:

```shell
openconnect-sso --authenticate
```

**WARNING:** The output contains a reusable VPN session cookie. Do not write it
to a persistent log.

### OpenConnect Arguments

Put OpenConnect arguments after the `--` separator:

```shell
openconnect-sso -- --base-mtu=1370
```

## Passwordless sudo

OpenConnect needs administrator privileges to create the tunnel and configure
network routes. This fork can create a passwordless sudo rule:

```shell
openconnect-sso --setup-sudo
```

**WARNING:** Use this feature only for an account that already has
administrator access. OpenConnect accepts arbitrary arguments. Its `--script`
option can execute commands as root. This sudo rule does not grant VPN-only
access.

On Linux, automatic setup requires a root-owned OpenConnect executable. On
macOS, it also accepts an executable owned by the current user for Homebrew
installations. It rejects executables that a group or any other user can edit.
Automatic setup on macOS requires `/etc/sudoers.d`. If this directory is
missing, configure the rule manually with `sudo visudo`.

Remove the rule with this command:

```shell
openconnect-sso --remove-sudo-setup
```

If passwordless setup does not work, inspect the active policy and test the
exact OpenConnect binary:

```shell
sudo -l
sudo -n /usr/bin/openconnect --version
```

## Connection Hooks

You can set connection hooks in `config.toml`:

```toml
on_connect = 'resolvectl domain "$TUNDEV" corp.example.com'
on_disconnect = 'notify-send "VPN disconnected"'
```

**WARNING:** `on_connect` runs as root from the vpnc script. Treat it as
privileged command configuration. `on_disconnect` runs as the desktop user.

## Development

Install the locked development dependencies, run the tests, and build the
packages:

```shell
uv sync --locked
uv run --locked pytest
uv build
```

See [MODERNIZATION.md](MODERNIZATION.md) for the current maintenance plan,
completed safety work, and remaining changes.
