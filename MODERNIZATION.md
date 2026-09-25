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

## Authentication Decision

The affected gateway did not offer native external-browser SSO to OpenConnect 9.21 with the saved profile. On Linux, `openconnect --authenticate --external-browser=xdg-open` completed TLS and sent an XML POST. Then it exited with a "no SSO" diagnostic before the browser opened or a cookie appeared.

The existing `openconnect-sso --authenticate` flow succeeded against the same gateway after the stale tunnel processes stopped. Keep the embedded browser, password autofill, and TOTP path. Do not add a second native authentication path for this gateway.

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

### 5. Browser Completion and Load Failures

The browser wait has a deadline. It now compares the final URL by scheme, host, port, and path. Query strings, fragments, and trailing slashes do not block completion.

The browser reports failed main-page loads as authentication errors. Stopped navigations can continue to a later page.

Cookie selection uses the cookie name, domain, and path for the gateway URL.

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

The documentation must not describe the rule as a secure VPN-only permission. Linux setup requires a root-owned binary. macOS setup permits the current administrator's Homebrew binary. Neither accepts group- or world-writable executables.

### 9. Sudo and Doas Behavior

The connection code now prefers `sudo` when it is available. It uses `doas` on a doas-only system. The setup code only offers passwordless sudo when `sudo` is available.

The probe uses `sudo -n -k` with OpenConnect's version command. This command ignores cached sudo credentials and does not update them.

Tunnel connections now check elevation before VPN authentication. Authentication-only runs skip the preflight. The connection code starts the tunnel once.

### 10. Expected Authentication Errors

The application now catches `AuthenticationError` and reports a stable exit status without logging the gateway response.

The parser now uses explicit protocol errors instead of `assert`. It reports malformed XML, unexpected response types, missing attributes, and invalid authentication IDs.

Other browser and network errors keep their existing exit codes.

### 11. Legacy TLS Launcher

`launcher/vpn-connect` now invokes `openconnect-sso --legacy-tls`. The package includes the OpenSSL configuration that enables `UnsafeLegacyRenegotiation`.

Only the authentication child receives `OPENSSL_CONF`. The parent and privileged OpenConnect tunnel do not inherit the override from the launcher.

The installed OpenConnect uses GnuTLS. Therefore, `OPENSSL_CONF` does not change its TLS behavior.

The native authentication test reached the affected gateway but did not receive an external-browser SSO flow. The existing authentication path still needs its legacy TLS configuration.

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
4. Run disconnect hooks as the desktop user with explicit shell arguments.
5. Correct the passwordless sudo documentation.
6. Add regression tests for the process commands and exit status 1.

This phase is small because the native authentication work can remove much of the affected code.

### Phase 1: Test Native OpenConnect Authentication (Complete for This Gateway)

The Linux test used OpenConnect 9.21, the saved profile, the AnyConnect user agent, and `--external-browser=xdg-open`. The gateway was reachable, but native authentication stopped before browser handoff. The saved profile has no authgroup or usergroup. This test did not exercise proxy behavior or macOS.

No cookie was returned. The experiment did not start a privileged tunnel or write a cookie to disk.

### Phase 2: Retain the Working Authentication Path

Keep the custom protocol flow and PyQt browser for this gateway. HTTP timeouts, explicit protocol errors, the browser deadline, domain-aware cookies, fresh TOTP, and secret-free logs are in place.

The browser now normalizes final URLs and reports page-load failures. It does not log browser state objects that contain session cookies.

### Phase 3: Preserve Automatic Browser Entry

Keep password and TOTP autofill in the current Qt browser. Do not replace the default workflow with a system browser that requires manual entry.

### Phase 4: Correct Privilege and Hook Behavior

Run authentication as the desktop user. Elevate only the tunnel process.

Use a non-destructive elevation preflight. Then invoke OpenConnect exactly once.

Run `on_connect` from the vpnc script because the saved command changes system DNS configuration. Quote the command before a root shell evaluates it.

Run `on_disconnect` from the desktop-user process through `/bin/sh -c`. This preserves shell syntax and does not elevate the hook.

Keep passwordless setup only for users who already have administrator access. Apply these restrictions:

- Resolve the absolute OpenConnect path.
- Require a root-owned binary on Linux. Permit the current user's Homebrew binary on macOS.
- Reject group- or world-writable executables on both platforms.
- Use the same elevation program for setup and connection.
- Use `visudo` for syntax validation.
- Do not rewrite the main macOS sudoers file. Ask for manual setup if `/etc/sudoers.d` is missing.
- Describe the rule as convenience, not restricted privilege.

### Phase 5: Preserve Legacy Gateway Access

Native OpenConnect did not complete authentication on the affected gateway. The existing flow succeeded with the legacy OpenSSL configuration.

The `--legacy-tls` option runs authentication in a child process with the bundled OpenSSL configuration. The launcher forwards to this option.

The README warns that legacy renegotiation lowers TLS security for that child process.

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

Retain dependencies used by the working custom protocol and Qt autofill. Remove only packages that have no callers. Keep the default installation capable of automatic password and TOTP entry.

### Phase 8: Add Focused Tests and CI

Add tests for these behaviors:

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
- A recorded native OpenConnect incompatibility for the affected gateway
- uv project management and a valid lock
- Linux and macOS CI for current Python versions
- Correct fork documentation

The gateway test requires the existing authentication path. Keep the changes focused on that path and its remaining error handling.

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
