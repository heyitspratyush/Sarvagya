from pathlib import Path

import pytest

from scripts import analytics_connection


def _write_config(path, password=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "EXASOL_HOST=localhost\n"
        "EXASOL_PORT=8563\n"
        "EXASOL_USER=test_user\n"
        f"EXASOL_PASSWORD={password}\n",
        encoding="utf-8",
    )
    return path


def test_loads_required_settings_from_explicit_config(tmp_path):
    config = _write_config(tmp_path / "exasol.env", "local-test-value")

    loaded = analytics_connection.load_exasol_config(config)

    assert loaded == {
        "host": "localhost",
        "port": 8563,
        "user": "test_user",
        "password": "local-test-value",
    }


def test_missing_config_file_has_actionable_error(tmp_path):
    with pytest.raises(analytics_connection.ExasolConfigurationError, match="Copy"):
        analytics_connection.load_exasol_config(tmp_path / "missing.env")


def test_missing_required_setting_is_rejected(tmp_path):
    config = tmp_path / "exasol.env"
    config.write_text("EXASOL_HOST=localhost\nEXASOL_PORT=8563\n", encoding="utf-8")

    with pytest.raises(analytics_connection.ExasolConfigurationError, match="EXASOL_USER"):
        analytics_connection.load_exasol_config(config)


def test_default_config_path_is_repository_relative_after_chdir(tmp_path, monkeypatch):
    expected_repo_config = (
        Path(analytics_connection.__file__).resolve().parent.parent
        / "config" / "exasol.env"
    )
    assert analytics_connection.DEFAULT_CONFIG_PATH == expected_repo_config
    repo_config = _write_config(tmp_path / "repo" / "config" / "exasol.env")
    monkeypatch.setattr(analytics_connection, "DEFAULT_CONFIG_PATH", repo_config)
    monkeypatch.chdir(tmp_path)

    loaded = analytics_connection.load_exasol_config()

    assert loaded["host"] == "localhost"
    assert loaded["port"] == 8563
    assert loaded["user"] == "test_user"
    assert analytics_connection.DEFAULT_CONFIG_PATH.is_absolute()


def test_missing_password_uses_interactive_getpass_fallback(tmp_path, monkeypatch):
    config = _write_config(tmp_path / "exasol.env")
    monkeypatch.setattr(analytics_connection, "DEFAULT_CONFIG_PATH", config)
    monkeypatch.setattr(analytics_connection, "_has_interactive_terminal", lambda: True)
    prompts = []
    calls = {}

    def prompt(message):
        prompts.append(message)
        return "typed-locally"

    monkeypatch.setattr(analytics_connection.getpass, "getpass", prompt)
    monkeypatch.setattr(
        analytics_connection.pyexasol,
        "connect",
        lambda **kwargs: calls.update(kwargs) or object(),
    )

    analytics_connection.get_analytics_connection(autocommit=False)

    assert prompts == ["Enter Exasol password: "]
    assert calls["password"] == "typed-locally"
    assert calls["dsn"] == "localhost:8563"
    assert calls["autocommit"] is False


def test_noninteractive_missing_password_returns_actionable_error(tmp_path, monkeypatch):
    config = _write_config(tmp_path / "exasol.env")
    monkeypatch.setattr(analytics_connection, "DEFAULT_CONFIG_PATH", config)
    monkeypatch.setattr(analytics_connection, "_has_interactive_terminal", lambda: False)
    monkeypatch.setattr(
        analytics_connection.pyexasol,
        "connect",
        lambda **kwargs: pytest.fail("connect must not receive an empty password"),
    )

    with pytest.raises(analytics_connection.ExasolAuthenticationError) as raised:
        analytics_connection.get_analytics_connection()

    assert "interactive terminal" in str(raised.value)
    assert "config/exasol.env" in str(raised.value)


def test_existing_password_does_not_prompt_and_config_is_not_overwritten(tmp_path, monkeypatch):
    config = _write_config(tmp_path / "exasol.env", "local-test-value")
    original = config.read_bytes()
    monkeypatch.setattr(analytics_connection, "DEFAULT_CONFIG_PATH", config)
    monkeypatch.setattr(
        analytics_connection.getpass,
        "getpass",
        lambda *_: pytest.fail("stored password should not prompt"),
    )
    calls = {}
    monkeypatch.setattr(
        analytics_connection.pyexasol,
        "connect",
        lambda **kwargs: calls.update(kwargs) or object(),
    )

    analytics_connection.get_analytics_connection()

    assert calls["password"] == "local-test-value"
    assert config.read_bytes() == original


def test_authentication_error_does_not_expose_password(tmp_path, monkeypatch, capsys):
    secret = "test-secret-that-must-not-leak"
    config = _write_config(tmp_path / "exasol.env", secret)
    monkeypatch.setattr(analytics_connection, "DEFAULT_CONFIG_PATH", config)

    def fail_authentication(**kwargs):
        assert kwargs["password"] == secret
        fake_connection = type("FakeExaConnection", (), {
            "options": {"verbose_error": False},
        })()
        raise analytics_connection.ExaAuthError(fake_connection, 401, f"rejected {secret}")

    monkeypatch.setattr(analytics_connection.pyexasol, "connect", fail_authentication)

    with pytest.raises(analytics_connection.ExasolAuthenticationError) as raised:
        analytics_connection.get_analytics_connection()

    assert secret not in str(raised.value)
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err


def test_connection_error_does_not_expose_credentials(tmp_path, monkeypatch):
    secret = "connection-secret-must-not-leak"
    config = _write_config(tmp_path / "exasol.env", secret)
    monkeypatch.setattr(analytics_connection, "DEFAULT_CONFIG_PATH", config)

    def fail_connection(**kwargs):
        fake_connection = type("FakeExaConnection", (), {})()
        raise analytics_connection.ExaConnectionError(fake_connection, secret)

    monkeypatch.setattr(analytics_connection.pyexasol, "connect", fail_connection)

    with pytest.raises(analytics_connection.ExasolConnectionError) as raised:
        analytics_connection.get_analytics_connection()

    assert secret not in str(raised.value)


def test_config_reader_does_not_change_existing_file(tmp_path):
    config = _write_config(tmp_path / "exasol.env", "local-test-value")
    original = config.read_bytes()

    analytics_connection.load_exasol_config(config)

    assert config.read_bytes() == original
