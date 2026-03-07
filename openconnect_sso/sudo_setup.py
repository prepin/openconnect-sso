import os
import shutil
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
    try:
        openconnect_path = get_openconnect_path()
    except FileNotFoundError:
        return False

    # Try to run sudo -n openconnect --version
    # If it succeeds without password prompt, it's configured
    result = subprocess.run(
        ["sudo", "-n", openconnect_path, "--version"],
        capture_output=True,
        timeout=5,
    )

    return result.returncode == 0


def setup_sudoers(openconnect_path):
    """Configure passwordless sudo for openconnect."""
    system = get_platform()
    username = os.getenv("USER") or os.getenv("USERNAME")

    if not username:
        raise ValueError("Cannot determine username")

    sudoers_content = f"{username} ALL=(ALL) NOPASSWD: {openconnect_path}\n"

    if system == "linux":
        sudoers_file = Path("/etc/sudoers.d/openconnect-sso")
        return _write_sudoers_file(sudoers_file, sudoers_content)
    elif system == "darwin":
        # macOS 10.13+ supports /etc/sudoers.d/
        sudoers_file = Path("/etc/sudoers.d/openconnect-sso")
        if sudoers_file.parent.exists():
            return _write_sudoers_file(sudoers_file, sudoers_content)
        else:
            # Fallback to main sudoers file
            return _append_to_main_sudoers(sudoers_content)
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


def _append_to_main_sudoers(content):
    """Append sudoers configuration to main sudoers file."""
    import subprocess
    import tempfile

    # Read current sudoers
    result = subprocess.run(
        ["sudo", "cat", "/etc/sudoers"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error(
            "Failed to read sudoers file",
            stderr=result.stderr,
        )
        raise RuntimeError(f"Failed to read sudoers file: {result.stderr}")

    current_sudoers = result.stdout

    # Check if already configured
    if "openconnect" in current_sudoers:
        logger.info("Sudoers already configured for openconnect")
        return True

    # Create temp file with new content
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sudoers", delete=False) as tmp:
        tmp.write(current_sudoers)
        tmp.write(f"\n# openconnect-sso passwordless sudo\n{content}")
        tmp.flush()
        tmp_path = tmp.name

    try:
        # Validate
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

        # Install using visudo
        result = subprocess.run(
            ["sudo", "cp", tmp_path, "/etc/sudoers"],
            capture_output=True,
        )

        if result.returncode != 0:
            logger.error(
                "Failed to update sudoers file",
                stderr=result.stderr,
            )
            raise RuntimeError(f"Failed to update sudoers file: {result.stderr}")

        logger.info("Sudoers file updated successfully")
        return True

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def remove_sudoers():
    """Remove passwordless sudo configuration for openconnect."""
    import subprocess

    system = get_platform()

    try:
        openconnect_path = get_openconnect_path()
    except FileNotFoundError:
        logger.warn("openconnect not found, skipping sudoers removal")
        return True

    if system == "linux":
        sudoers_file = Path("/etc/sudoers.d/openconnect-sso")
        if sudoers_file.exists():
            result = subprocess.run(
                ["sudo", "rm", str(sudoers_file)],
                capture_output=True,
            )

            if result.returncode != 0:
                logger.error(
                    "Failed to remove sudoers file",
                    stderr=result.stderr.decode("utf-8"),
                )
                return False

            logger.info("Sudoers file removed successfully")
            return True
        else:
            logger.info("Sudoers file does not exist")
            return True

    elif system == "darwin":
        sudoers_file = Path("/etc/sudoers.d/openconnect-sso")
        if sudoers_file.parent.exists() and sudoers_file.exists():
            result = subprocess.run(
                ["sudo", "rm", str(sudoers_file)],
                capture_output=True,
            )

            if result.returncode != 0:
                logger.error(
                    "Failed to remove sudoers file",
                    stderr=result.stderr.decode("utf-8"),
                )
                return False

            logger.info("Sudoers file removed successfully")
            return True
        else:
            # Need to remove from main sudoers file
            return _remove_from_main_sudoers(openconnect_path)

    return False


def _remove_from_main_sudoers(openconnect_path):
    """Remove openconnect entry from main sudoers file."""
    import subprocess
    import tempfile

    # Read current sudoers
    result = subprocess.run(
        ["sudo", "cat", "/etc/sudoers"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error(
            "Failed to read sudoers file",
            stderr=result.stderr,
        )
        return False

    current_sudoers = result.stdout

    # Remove openconnect-sso entry
    lines = []
    skip_next = False
    for line in current_sudoers.splitlines():
        if "# openconnect-sso passwordless sudo" in line:
            skip_next = True
            continue
        if skip_next:
            skip_next = False
            continue
        lines.append(line)

    new_sudoers = "\n".join(lines)

    # Check if anything changed
    if new_sudoers == current_sudoers:
        logger.info("No sudoers entry to remove")
        return True

    # Create temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sudoers", delete=False) as tmp:
        tmp.write(new_sudoers)
        tmp.flush()
        tmp_path = tmp.name

    try:
        # Validate
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
            return False

        # Install
        result = subprocess.run(
            ["sudo", "cp", tmp_path, "/etc/sudoers"],
            capture_output=True,
        )

        if result.returncode != 0:
            logger.error(
                "Failed to update sudoers file",
                stderr=result.stderr,
            )
            return False

        logger.info("Sudoers entry removed successfully")
        return True

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
