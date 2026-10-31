"""Central Exasol configuration, authentication, and connection creation."""

import getpass
import os
from pathlib import Path
import sys

import pyexasol
from pyexasol.exceptions import ExaAuthError, ExaCommunicationError, ExaConnectionError


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPOSITORY_ROOT / "config" / "exasol.env"
EXAMPLE_CONFIG_PATH = REPOSITORY_ROOT / "config" / "exasol.env.example"


class ExasolConfigurationError(RuntimeError):
    """Exasol configuration is missing or invalid."""


class ExasolAuthenticationError(RuntimeError):
    """Exasol authentication could not be completed securely."""


class ExasolConnectionError(RuntimeError):
    """An Exasol connection could not be established or maintained."""


def load_exasol_config(config_path=None):
    """Load simple KEY=VALUE settings from the repository-local config file."""
    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    if not path.is_file():
        raise ExasolConfigurationError(
            f"Exasol configuration not found at {path}. Copy "
            f"{EXAMPLE_CONFIG_PATH} to {DEFAULT_CONFIG_PATH}, then configure it locally."
        )

    values = {}
    try:
        for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ExasolConfigurationError(
                    f"Invalid Exasol configuration entry on line {line_number}."
                )
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            if key not in {"EXASOL_HOST", "EXASOL_PORT", "EXASOL_USER", "EXASOL_PASSWORD"}:
                raise ExasolConfigurationError(
                    f"Unknown Exasol configuration setting on line {line_number}."
                )
            if key in values:
                raise ExasolConfigurationError(
                    f"Duplicate Exasol configuration setting on line {line_number}."
                )
            values[key] = value
    except OSError:
        raise ExasolConfigurationError(
            f"Unable to read Exasol configuration at {path}."
        ) from None

    missing = [key for key in ("EXASOL_HOST", "EXASOL_PORT", "EXASOL_USER") if not values.get(key)]
    if missing:
        raise ExasolConfigurationError(
            "Missing required Exasol setting(s): " + ", ".join(missing)
        )
    try:
        port = int(values["EXASOL_PORT"])
    except ValueError:
        raise ExasolConfigurationError("EXASOL_PORT must be an integer from 1 to 65535.") from None
    if not 1 <= port <= 65535:
        raise ExasolConfigurationError("EXASOL_PORT must be an integer from 1 to 65535.")

    return {
        "host": values["EXASOL_HOST"],
        "port": port,
        "user": values["EXASOL_USER"],
        "password": values.get("EXASOL_PASSWORD", ""),
    }


def _has_interactive_terminal():
    """Return whether getpass can prompt through a controlling terminal."""
    try:
        tty_fd = os.open(os.ctermid(), os.O_RDWR | os.O_NOCTTY)
    except OSError:
        return bool(getattr(sys.stdin, "isatty", lambda: False)())
    try:
        return os.isatty(tty_fd)
    finally:
        os.close(tty_fd)


def _get_password(config):
    password = config["password"]
    if password:
        return password
    if not _has_interactive_terminal():
        raise ExasolAuthenticationError(
            "EXASOL_PASSWORD is empty and no interactive terminal is available. "
            "Run the command from a terminal to enter it securely, or set it in "
            "the ignored config/exasol.env file and restrict that file with chmod 600."
        )
    try:
        password = getpass.getpass("Enter Exasol password: ")
    except (EOFError, OSError):
        raise ExasolAuthenticationError(
            "Could not read the Exasol password. Run the command from an interactive "
            "terminal or configure it in the ignored config/exasol.env file."
        ) from None
    if not password:
        raise ExasolAuthenticationError("No Exasol password was provided.")
    return password


def get_analytics_connection(autocommit=True):
    """Create the repository's single supported kind of Exasol connection."""
    config = load_exasol_config()
    password = _get_password(config)
    dsn = f"{config['host']}:{config['port']}"
    try:
        return pyexasol.connect(
            dsn=dsn,
            user=config["user"],
            password=password,
            autocommit=autocommit,
            websocket_sslopt={"cert_reqs": 0},
        )
    except ExaAuthError:
        raise ExasolAuthenticationError(
            "Exasol authentication failed. Verify EXASOL_USER and EXASOL_PASSWORD "
            "in the local configuration."
        ) from None
    except (ExaConnectionError, ExaCommunicationError):
        raise ExasolConnectionError(
            f"Could not connect to Exasol at {config['host']}:{config['port']}. "
            "Check that the database is running and reachable."
        ) from None
    except Exception:
        raise ExasolConnectionError(
            f"Exasol connection attempt to {config['host']}:{config['port']} failed."
        ) from None
