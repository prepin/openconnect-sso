# Modernization Findings and Plan

## Scope

This repository is a semi-public fork for a small group of users. It does not target a broad public audience.

The supported platforms are Linux and macOS. Users install the tool with `uv` and already have administrator access.

The fork must preserve these capabilities:

- Browser autofill and TOTP support
- Passwordless startup for existing administrators
- A privileged connect hook for route and DNS changes
- A disconnect hook that runs as the desktop user
- Access to a gateway that requires legacy TLS behavior

## Recommended Direction

The fork can become a thin convenience layer around modern OpenConnect. It does not need to maintain a second AnyConnect protocol implementation.

The target flow is:

```text
CLI, profiles, and configuration
    |
    v
unprivileged openconnect --authenticate --external-browser=...
    |
    v
OpenConnect returns the cookie and connection data
    |
    v
one privileged OpenConnect tunnel process
```

OpenConnect supports AnyConnect external-browser SSO from version 9.0. OpenConnect 9.21 is installed on the current development system.

The browser can use one of these modes:

- The system browser is the default mode.
- A small PyQt helper provides autofill and TOTP support.

OpenConnect will own the XML protocol, SAML callback, token encryption, redirects, proxy behavior, and cookie transfer. The helper will only open the supplied URL and fill browser fields.

This direction depends on a real gateway test. Some gateways offer only the older embedded SSO method.

## Repository State

- The fork is 11 commits ahead of upstream commit `9412807`.
- The worktree was clean during this review.
- Runtime code and tests contain approximately 2,233 lines.
- The package supports Python 3.11 through 3.14.
- Test CI covers Linux and macOS with Python 3.11 through 3.14.
- The current development system uses Python 3.13.15.
- The current development system uses OpenConnect 9.21.
- Most tests cover the new sudo code.
- Authentication and process orchestration have little direct test coverage.

`uv.lock` now matches the standard project metadata. The old Poetry lock and Nix files were removed.

The package version is still the upstream version 0.8.1. The repository links, installation guide, support statement, and security notes now identify this fork.

## Findings

### 1. OpenConnect Can Start Twice

`openconnect_sso/app.py:306-343` starts OpenConnect with `sudo -n` or `doas -n`.

The code treats exit status 1 as an elevation error. OpenConnect also uses exit status 1 for connection and authentication errors.

As a result, the code can start OpenConnect a second time. This action can reuse a token and repeat hook effects.

### 2. The Connect Hook Runs Through a Privileged Script

`openconnect_sso/app.py:251-264` inserts `on_connect` text into a temporary shell script. Privileged OpenConnect uses this file as its vpnc script.

The command comes from a user-writable configuration file. The temporary file also remains user-writable while a root process consumes it.

The connect hook needs root access for route and DNS changes. This fork accepts that behavior for existing administrators.

The documentation must identify `on_connect` as an unrestricted root command. The disconnect hook runs as the desktop user.

### 3. Debug Logs Can Contain the VPN Token

`openconnect_sso/authenticator.py:75-82` logs complete authentication responses at debug level.

The final response contains the VPN session token. A debug log can therefore contain a reusable secret.

Authentication request and response bodies must not enter logs.

### 4. Redirect Discovery Bypasses the HTTP Session

`openconnect_sso/authenticator.py:55-61` uses `requests.get()` instead of the configured session.

This request does not use the explicit proxy or session cookies. No authentication HTTP request has a timeout.

A direct request can bypass the required proxy. A stalled request can also block the process without a time limit.

### 5. Browser Completion Can Wait Forever

`openconnect_sso/saml_authenticator.py:12-16` requires exact equality with the final URL. The wait has no timeout.

Fragments, query parameters, trailing slashes, failed page loads, and provider changes can prevent completion.

The browser stores cookies only by name. It discards the cookie domain, path, expiry, and security attributes.

### 6. TOTP Can Expire Before Use

`openconnect_sso/browser/webengine_process.py:272-358` generates credential values when it creates the injected JavaScript.

The browser can reach the TOTP page after the code expires. The helper must generate a fresh code when the TOTP field appears.

### 7. CLI and Configuration Precedence Is Inconsistent

`openconnect_sso/app.py:175-190` gives saved credentials priority over `--user`. A user cannot use the option to change accounts.

The password prompt uses `args.user` instead of the selected credential name. It can show `Password (None)`.

The saved `log_level` value is also ineffective. The argument parser always supplies a default value before the application reads the configuration.

### 8. Passwordless Sudo Is Not a Security Boundary

`openconnect_sso/sudo_setup.py:51-63` permits unrestricted execution of the selected OpenConnect binary.

OpenConnect accepts `--script`. Therefore, this rule can provide arbitrary root command execution.

The users of this fork already have administrator access. The feature can remain as a convenience for those users.

The documentation must not describe the rule as a secure VPN-only permission. The setup code must also reject a user-writable OpenConnect binary.

### 9. Sudo and Doas Behavior

The connection code now prefers `sudo` when it is available. It uses `doas` on a doas-only system. The setup code only offers passwordless sudo when `sudo` is available.

The probe uses `sudo -n -k` with OpenConnect's version command. This command ignores cached sudo credentials and does not update them.

Tunnel connections now check elevation before VPN authentication. Authentication-only runs skip the preflight. The connection code starts the tunnel once.

### 10. Expected Authentication Errors Can Produce Tracebacks

The application catches `AuthResponseError`, but it does not catch the base `AuthenticationError`.

The parser also uses `assert` for protocol validation. Python removes these statements in optimized mode.

Expected protocol errors must use explicit exceptions and stable exit codes.

### 11. The Legacy TLS Launcher Is Incomplete

`launcher/vpn-connect` references `~/.config/openconnect-sso/ssl.conf`. The repository contains `launcher/.ssl_conf` instead.

Nothing installs the OpenSSL configuration file. The configuration enables `UnsafeLegacyRenegotiation` for the full Python process.

The installed OpenConnect uses GnuTLS. Therefore, `OPENSSL_CONF` does not change its TLS behavior.

The native authentication test must include the affected gateway. Native OpenConnect can remove the need for the unsafe OpenSSL override.

### 12. Packaging and CI Migration

The package now uses standard project metadata and a uv lock. The build backend is still `poetry-core`.

Test CI uses uv and covers the supported Python versions on Linux and macOS. The separate coding-style workflow still uses older actions.

The old Nix files depended on the invalid Poetry lock. They were removed with that lock.

The supported installation method is `uv`.

### 13. The Package Version Still Describes Upstream

The README and repository links now identify this fork. The stale PyPI, AUR, Nix, and Windows installation instructions were removed.

The installation guide now uses `uv`. It also describes the passwordless sudo and privileged hook risks.

The fork still needs its own version before its first release.

## Implementation Plan

### Phase 0: Correct Active Safety Problems

1. Remove authentication request and response bodies from logs.
2. Replace the two OpenConnect attempts with one elevation preflight and one connection attempt.
3. Quote the privileged `on_connect` command and document its root access.
4. Run disconnect hooks without `shell=True`.
5. Correct the passwordless sudo documentation.
6. Add regression tests for the process commands and exit status 1.

This phase is small because the native authentication work can remove much of the affected code.

### Phase 1: Prove Native OpenConnect Authentication

Create a narrow experimental path that invokes `openconnect --authenticate` as the desktop user.

Use `xdg-open` on Linux and `open` on macOS for the first test. Parse these output fields without shell evaluation:

- `COOKIE`
- `CONNECT_URL`
- `FINGERPRINT`
- `RESOLVE`

Pass the cookie to the privileged connection process through standard input. Do not store it in a file or command-line argument.

The gateway test must cover these cases:

- SSO and MFA complete successfully.
- The external-browser callback reaches OpenConnect.
- The authgroup and usergroup values work.
- Proxy behavior works.
- The returned cookie starts a tunnel.
- Linux and macOS open the browser correctly.
- The legacy TLS gateway still connects.

### Phase 2: Apply the Authentication Decision

If native authentication works, remove these components:

- `openconnect_sso/authenticator.py`
- `openconnect_sso/saml_authenticator.py`
- Custom HTTP authentication requests
- Custom SAML cookie coordination
- Exact final-URL matching
- Most browser multiprocessing coordination

If native authentication does not work, retain the current path as a fallback. Then add these controls:

- HTTP connection and read timeouts
- Explicit protocol exceptions
- URL normalization
- A browser authentication timeout
- Page-load error propagation
- Domain-aware cookie selection
- Fresh TOTP generation
- Secret-free logs

Do not maintain both authentication paths after the gateway test proves that one path is sufficient.

### Phase 3: Preserve Autofill as a Browser Helper

Adapt the PyQt browser into a small executable for `--external-browser`.

The helper will receive a URL from OpenConnect. It will open the URL and apply the existing autofill rules.

The helper will retrieve secrets from the keyring as the desktop user. It will generate a new TOTP code when the matching field appears.

The system browser will remain the default. The embedded helper will be an explicit autofill mode.

### Phase 4: Correct Privilege and Hook Behavior

Run authentication as the desktop user. Elevate only the tunnel process.

Use a non-destructive elevation preflight. Then invoke OpenConnect exactly once.

Run `on_connect` from the vpnc script because the saved command changes system DNS configuration. Quote the command before a root shell evaluates it.

Run `on_disconnect` from the desktop-user process. Preserve its current user identity.

Users who need shell syntax can configure an explicit command such as `sh -c '...'`.

Keep passwordless setup only for users who already have administrator access. Apply these restrictions:

- Resolve the absolute OpenConnect path.
- Require a root-owned binary.
- Reject a group-writable or user-writable binary.
- Use the same elevation program for setup and connection.
- Use `visudo` for syntax validation.
- Do not rewrite the main macOS sudoers file.
- Describe the rule as convenience, not restricted privilege.

### Phase 5: Preserve Legacy Gateway Access

Test the affected gateway through native OpenConnect before changing the launcher.

If native OpenConnect works, remove the unsafe OpenSSL override. GnuTLS then provides the required compatibility.

If the fallback still requires OpenSSL, add an explicit legacy TLS option. Apply the override only to the authentication helper process.

Fix the configuration filename and installation path. Add a warning that the option lowers TLS security.

### Phase 6: Move Project Management to uv (Complete)

Package metadata uses standard `[project]` fields. The build backend remains `poetry-core`.

The checked-in `uv.lock` replaces `poetry.lock`. It supports Linux, macOS, and Python 3.11 through 3.14.

The supported Python range is 3.11 through 3.14. The package and command names remain the same.

Document installation from Git:

```console
uv tool install git+https://github.com/prepin/openconnect-sso
```

The README documents installation, upgrade, and removal commands.

### Phase 7: Reduce Dependencies

If native authentication replaces the custom protocol, remove dependencies that no longer have callers.

Likely removal candidates are:

- `requests`
- `lxml`
- `attrs`
- `structlog`
- `prompt-toolkit`
- `pyxdg`
- `PySocks`
- `colorama`
- Runtime `setuptools`

Keep `keyring`, `pyotp`, and `toml` while the current configuration format remains. Make PyQt6 and PyQt6-WebEngine optional dependencies for autofill mode.

Use the standard library before adding replacement dependencies.

### Phase 8: Add Focused Tests and CI

Add tests for these behaviors:

- Parse OpenConnect authentication output.
- Build the exact privileged command.
- Do not restart OpenConnect after exit status 1.
- Send the cookie only through standard input.
- Run the connect hook as root and the disconnect hook as the desktop user.
- Apply CLI and configuration precedence.
- Remove secrets from logs.
- Generate a fresh TOTP code.
- Load the existing configuration after metadata changes.

Run core tests on Linux and macOS with Python 3.11 through 3.14. Run the PyQt browser test in a separate Linux Xvfb job.

Build the wheel and source archive in CI. Use a frozen uv synchronization to detect lock changes.

### Phase 9: Correct Project Identity and Documentation

Release the first maintained fork version as `0.9.0`.

Update these items:

- Repository and homepage URLs
- Workflow badges
- Python and operating-system support
- uv installation steps
- Keyring and browser storage behavior
- Passwordless sudo risk
- Legacy TLS risk
- Hook execution identity
- Fork changes since upstream 0.8.1

The stale Nix and Niv files were removed because uv is the supported installation path.

## First Milestone

Version `0.9.0` will contain these changes:

- Safety corrections for logging, hooks, and duplicate OpenConnect execution
- A native OpenConnect authentication experiment behind an explicit option
- uv project management and a valid lock
- Linux and macOS CI for current Python versions
- Correct fork documentation

Do not do a large refactor before the real gateway test. The gateway result determines which authentication code the project can remove.

## Deliberate Non-Goals

The modernization does not include these items:

- Windows support
- A plugin system
- A general VPN provider abstraction
- A custom privilege service
- Parallel support for Poetry, uv, and Nix
- Long-term support for two authentication implementations

These features add maintenance cost without a current requirement.

## References

- [OpenConnect manual](https://www.infradead.org/openconnect/manual.html)
- [OpenConnect external-browser SSO change](https://gitlab.com/openconnect/openconnect/-/merge_requests/354)
- [uv tool documentation](https://docs.astral.sh/uv/guides/tools/)
