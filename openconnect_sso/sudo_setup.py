import os
import pwd
import shutil
import stat
import subprocess
import structlog
import platform
from pathlib import Path

logger = structlog.get_logger()


def get_openconnect_path():
    """Find the openconnect binary in PATH."""
    openconnect_path = shutil.which("openconnect")
    if not openconnect_path:
        raise FileNotFoundError("openconnect not found in PATH")

    # Return absolute path
    return str(Path(openconnect_path).resolve())


def get_platform():
    """Detect the current platform."""
    system = platform.system().lower()

    if system == "linux":
        return "linux"
    elif system == "darwin":
        return "darwin"
    else:
        raise ValueError(f"Unsupported platform: {system}")


def check_sudoers_configured():
    """Check if passwordless sudo is already configured for openconnect."""
    if not shutil.which("sudo"):
        return False

    try:
        openconnect_path = get_openconnect_path()
    except FileNotFoundError:
        return False

    # Ignore cached credentials so a previous sudo login cannot mask a missing rule.
    result = subprocess.run(
        ["sudo", "-n", "-k", openconnect_path, "--version"],
        capture_output=True,
        timeout=5,
    )

    return result.returncode == 0


def validate_openconnect_binary(openconnect_path, system):
    """Validate the executable before granting it passwordless sudo."""
    binary = Path(openconnect_path).resolve(strict=True)
    metadata = binary.stat()
    if not stat.S_ISREG(metadata.st_mode) or not metadata.st_mode & 0o111:
        raise ValueError(f"OpenConnect is not an executable file: {binary}")
    if metadata.st_mode & 0o022:
        raise ValueError(f"OpenConnect is writable by group or others: {binary}")
    if metadata.st_uid not in ({0} if system == "linux" else {0, os.getuid()}):
        raise ValueError(f"OpenConnect has an unexpected owner: {binary}")
    return str(binary)


def setup_sudoers(openconnect_path):
    """Configure passwordless sudo for openconnect."""
    system = get_platform()
    openconnect_path = validate_openconnect_binary(openconnect_path, system)
    username = pwd.getpwuid(os.getuid()).pw_name
    if not username:
        raise ValueError("Cannot determine username")

    sudoers_content = f"{username} ALL=(ALL) NOPASSWD: {openconnect_path}\n"

    if system == "linux":
        sudoers_file = Path("/etc/sudoers.d/openconnect-sso")
        return _write_sudoers_file(sudoers_file, sudoers_content)
    elif system == "darwin":
        sudoers_file = Path("/etc/sudoers.d/openconnect-sso")
        if sudoers_file.parent.is_dir():
            return _write_sudoers_file(sudoers_file, sudoers_content)
        raise RuntimeError("/etc/sudoers.d is missing; configure sudoers with visudo")
    else:
        raise ValueError(f"Unsupported platform: {system}")


def _write_sudoers_file(sudoers_file, content):
    """Write sudoers configuration to a file."""
    import subprocess
    import tempfile

    # Validate content using visudo
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sudoers", delete=False) as tmp:
        tmp.write(content)
        tmp.flush()
        tmp_path = tmp.name

    try:
        # Validate sudoers syntax
        result = subprocess.run(
            ["visudo", "-c", "-f", tmp_path],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logger.error(
                "Sudoers validation failed",
                output=result.stdout,
                errors=result.stderr,
            )
            raise RuntimeError(f"Sudoers validation failed: {result.stderr}")

        # Use visudo to safely edit sudoers file
        # This requires the file to exist and be proper format
        result = subprocess.run(
            [
                "sudo",
                "tee",
                str(sudoers_file),
            ],
            input=content.encode("utf-8"),
            capture_output=True,
        )

        if result.returncode != 0:
            logger.error(
                "Failed to write sudoers file",
                stderr=result.stderr.decode("utf-8"),
            )
            raise RuntimeError(
                f"Failed to write sudoers file: {result.stderr.decode('utf-8')}"
            )

        # Set correct permissions (0440)
        result = subprocess.run(
            ["sudo", "chmod", "0440", str(sudoers_file)],
            capture_output=True,
        )

        if result.returncode != 0:
            logger.error(
                "Failed to set sudoers file permissions",
                stderr=result.stderr.decode("utf-8"),
            )
            raise RuntimeError(
                f"Failed to set permissions: {result.stderr.decode('utf-8')}"
            )

        logger.info(
            "Sudoers file created successfully",
            file=str(sudoers_file),
        )
        return True

    finally:
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def remove_sudoers():
    """Remove passwordless sudo configuration for openconnect."""
    system = get_platform()
    sudoers_file = Path("/etc/sudoers.d/openconnect-sso")
    if not sudoers_file.exists():
        if system == "darwin" and not sudoers_file.parent.is_dir():
            logger.error(
                "Remove any legacy openconnect-sso rule from /etc/sudoers with visudo"
            )
            return False
        return True

    result = subprocess.run(["sudo", "rm", str(sudoers_file)], capture_output=True)
    if result.returncode != 0:
        logger.error("Failed to remove sudoers file", stderr=result.stderr.decode())
        return False
    logger.info("Sudoers file removed successfully")
    return True
