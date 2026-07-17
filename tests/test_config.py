from tmhi_watchdog.config import Settings
from tmhi_watchdog.credentials import ManagedEnvFile


def test_saved_gateway_password_is_loaded_when_env_password_is_missing(
    monkeypatch,
    tmp_path,
) -> None:
    env_path = tmp_path / "watchdog.env"
    env_path.write_text("GATEWAY_PASSWORD=saved-password\n", encoding="utf-8")
    monkeypatch.setenv("WATCHDOG_ENV_PATH", str(env_path))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "watchdog.db"))
    monkeypatch.delenv("GATEWAY_PASSWORD", raising=False)
    monkeypatch.delenv("GATEWAY_PASSWORD_FILE", raising=False)

    settings = Settings.from_env()

    assert settings.gateway_password == "saved-password"
    assert settings.gateway_password_source == "saved"
    assert settings.safe_summary()["gateway_login_saved"] is True


def test_saved_gateway_password_overrides_env_password(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / "watchdog.env"
    env_path.write_text("GATEWAY_PASSWORD=saved-password\n", encoding="utf-8")
    monkeypatch.setenv("WATCHDOG_ENV_PATH", str(env_path))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "watchdog.db"))
    monkeypatch.setenv("GATEWAY_PASSWORD", "env-password")
    monkeypatch.delenv("GATEWAY_PASSWORD_FILE", raising=False)

    settings = Settings.from_env()

    assert settings.gateway_password == "saved-password"
    assert settings.gateway_password_source == "saved"


def test_managed_settings_are_created_on_first_start(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / "watchdog.env"
    monkeypatch.setenv("WATCHDOG_ENV_PATH", str(env_path))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "watchdog.db"))
    monkeypatch.delenv("GATEWAY_PASSWORD", raising=False)
    monkeypatch.delenv("GATEWAY_PASSWORD_FILE", raising=False)

    settings = Settings.from_env()

    assert env_path.exists()
    assert "GATEWAY_PASSWORD=" in env_path.read_text(encoding="utf-8")
    assert settings.managed_env_path == str(env_path)


def test_managed_settings_round_trip_quoted_password(tmp_path) -> None:
    env_path = tmp_path / "watchdog.env"
    managed_env = ManagedEnvFile(str(env_path))

    managed_env.set_value("GATEWAY_PASSWORD", 'space # and "quote"')

    assert managed_env.load()["GATEWAY_PASSWORD"] == 'space # and "quote"'
