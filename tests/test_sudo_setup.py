import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from openconnect_sso import sudo_setup


@pytest.fixture
def mock_openconnect_path():
    """Provide a fake openconnect path for testing."""
    return "/usr/bin/openconnect"


@pytest.fixture
def mock_username():
    """Provide a fake username for testing."""
    return "testuser"


@pytest.fixture
def mock_linux_platform():
    """Mock Linux platform."""
    with patch("openconnect_sso.sudo_setup.platform.system", return_value="Linux"):
        yield


@pytest.fixture
def mock_macos_platform():
    """Mock macOS platform."""
    with patch("openconnect_sso.sudo_setup.platform.system", return_value="Darwin"):
        yield


class TestGetOpenconnectPath:
    """Test get_openconnect_path function."""

    def test_found_in_path(self):
        """Test finding openconnect in PATH."""
        with patch("shutil.which", return_value="/usr/bin/openconnect"):
            path = sudo_setup.get_openconnect_path()
            assert path == "/usr/bin/openconnect"

    def test_resolves_symlink(self):
        """Test that path is resolved to absolute path."""
        with (
            patch("shutil.which", return_value="/usr/bin/openconnect"),
            patch("pathlib.Path.resolve", return_value=Path("/real/path/openconnect")),
        ):
            path = sudo_setup.get_openconnect_path()
            assert path == "/real/path/openconnect"

    def test_not_found(self):
        """Test when openconnect is not found."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(FileNotFoundError, match="openconnect not found"):
                sudo_setup.get_openconnect_path()


class TestGetPlatform:
    """Test get_platform function."""

    def test_linux(self):
        """Test Linux platform detection."""
        with patch("openconnect_sso.sudo_setup.platform.system", return_value="Linux"):
            platform = sudo_setup.get_platform()
            assert platform == "linux"

    def test_macos(self):
        """Test macOS platform detection."""
        with patch("openconnect_sso.sudo_setup.platform.system", return_value="Darwin"):
            platform = sudo_setup.get_platform()
            assert platform == "darwin"

    def test_unsupported(self):
        """Test unsupported platform."""
        with patch(
            "openconnect_sso.sudo_setup.platform.system", return_value="Windows"
        ):
            with pytest.raises(ValueError, match="Unsupported platform: windows"):
                sudo_setup.get_platform()


class TestCheckSudoersConfigured:
    """Test check_sudoers_configured function."""

    def test_configured(self, mock_openconnect_path):
        """Test when sudoers is configured."""
        with (
            patch("shutil.which", return_value=mock_openconnect_path),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
        ):
            result = sudo_setup.check_sudoers_configured()
            assert result is True

    def test_not_configured(self, mock_openconnect_path):
        """Test when sudoers is not configured."""
        with (
            patch("shutil.which", return_value=mock_openconnect_path),
            patch("subprocess.run", return_value=MagicMock(returncode=1)),
        ):
            result = sudo_setup.check_sudoers_configured()
            assert result is False

    def test_openconnect_not_found(self):
        """Test when openconnect is not found."""
        with patch("shutil.which", return_value=None):
            result = sudo_setup.check_sudoers_configured()
            assert result is False


class TestSetupSudoers:
    """Test setup_sudoers function."""

    @patch.dict(os.environ, {"USER": "testuser"})
    def test_linux_success(self, mock_openconnect_path, mock_linux_platform):
        """Test successful Linux setup."""
        with patch("openconnect_sso.sudo_setup._write_sudoers_file", return_value=True):
            result = sudo_setup.setup_sudoers(mock_openconnect_path)
            assert result is True

    @patch.dict(os.environ, {"USER": "testuser"})
    def test_linux_failure(self, mock_openconnect_path, mock_linux_platform):
        """Test failed Linux setup."""
        with patch(
            "openconnect_sso.sudo_setup._write_sudoers_file",
            side_effect=RuntimeError("Failed"),
        ):
            with pytest.raises(RuntimeError, match="Failed"):
                sudo_setup.setup_sudoers(mock_openconnect_path)

    @patch.dict(os.environ, {"USER": "testuser"})
    def test_macos_with_sudoers_d(self, mock_openconnect_path, mock_macos_platform):
        """Test macOS setup with sudoers.d support."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("openconnect_sso.sudo_setup._write_sudoers_file", return_value=True),
        ):
            result = sudo_setup.setup_sudoers(mock_openconnect_path)
            assert result is True

    @patch.dict(os.environ, {"USER": "testuser"})
    def test_macos_without_sudoers_d(self, mock_openconnect_path, mock_macos_platform):
        """Test macOS setup without sudoers.d support."""
        with (
            patch("pathlib.Path.exists", return_value=False),
            patch(
                "openconnect_sso.sudo_setup._append_to_main_sudoers", return_value=True
            ),
        ):
            result = sudo_setup.setup_sudoers(mock_openconnect_path)
            assert result is True

    @patch.dict(os.environ, {}, clear=True)
    def test_no_username(self, mock_openconnect_path, mock_linux_platform):
        """Test when username cannot be determined."""
        with pytest.raises(ValueError, match="Cannot determine username"):
            sudo_setup.setup_sudoers(mock_openconnect_path)


class TestWriteSudoersFile:
    """Test _write_sudoers_file function."""

    @pytest.fixture
    def sudoers_file(self):
        """Provide a temporary sudoers file path."""
        with tempfile.NamedTemporaryFile(suffix=".sudoers", delete=False) as f:
            yield Path(f.name)
            if os.path.exists(f.name):
                os.unlink(f.name)

    def test_success(self, sudoers_file):
        """Test successful sudoers file creation."""
        content = "testuser ALL=(ALL) NOPASSWD: /usr/bin/openconnect\n"

        with (
            patch("subprocess.run") as mock_run,
            patch("os.unlink"),
        ):  # Prevent temp file deletion
            # Mock visudo validation success
            mock_run.side_effect = [
                MagicMock(returncode=0),  # visudo -c
                MagicMock(returncode=0),  # tee
                MagicMock(returncode=0),  # chmod
            ]

            result = sudo_setup._write_sudoers_file(sudoers_file, content)
            assert result is True

    def test_validation_failure(self, sudoers_file):
        """Test when visudo validation fails."""
        content = "invalid content"

        with (
            patch("subprocess.run") as mock_run,
            patch("os.unlink"),
        ):  # Prevent temp file deletion
            # Mock visudo validation failure
            mock_run.return_value = MagicMock(returncode=1, stderr="syntax error")

            with pytest.raises(RuntimeError, match="Sudoers validation failed"):
                sudo_setup._write_sudoers_file(sudoers_file, content)


class TestRemoveSudoers:
    """Test remove_sudoers function."""

    def test_linux_success(self, mock_openconnect_path, mock_linux_platform):
        """Test successful removal on Linux."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
        ):
            result = sudo_setup.remove_sudoers()
            assert result is True

    def test_linux_file_not_exists(self, mock_openconnect_path, mock_linux_platform):
        """Test when sudoers file doesn't exist on Linux."""
        with patch("pathlib.Path.exists", return_value=False):
            result = sudo_setup.remove_sudoers()
            assert result is True

    def test_openconnect_not_found(self, mock_linux_platform):
        """Test when openconnect is not found."""
        with patch("shutil.which", return_value=None):
            result = sudo_setup.remove_sudoers()
            assert result is True

    def test_macos_with_sudoers_d(self, mock_openconnect_path, mock_macos_platform):
        """Test removal on macOS with sudoers.d support."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
        ):
            result = sudo_setup.remove_sudoers()
            assert result is True

    def test_macos_without_sudoers_d(self, mock_openconnect_path, mock_macos_platform):
        """Test removal on macOS without sudoers.d support."""
        with (
            patch("pathlib.Path.exists", return_value=False),
            patch(
                "openconnect_sso.sudo_setup._remove_from_main_sudoers",
                return_value=True,
            ),
        ):
            result = sudo_setup.remove_sudoers()
            assert result is True
