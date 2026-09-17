from app.config import Settings


def test_default_ollama_settings(monkeypatch) -> None:
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_THINK", raising=False)
    monkeypatch.delenv("OLLAMA_TIMEOUT_SECONDS", raising=False)

    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)

    settings = Settings(_env_file=None)

    assert settings.ollama_base_url == "http://localhost:11434"
    assert settings.ollama_model == "qwen3:8b"
    assert settings.ollama_think is False
    assert settings.ollama_timeout_seconds == 1200.0
    assert settings.ollama_num_ctx == 16384


def test_settings_read_environment_variables(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "custom:model")
    monkeypatch.setenv("OLLAMA_THINK", "true")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("OLLAMA_NUM_CTX", "8192")

    settings = Settings(_env_file=None)

    assert settings.ollama_base_url == "http://127.0.0.1:11434"
    assert settings.ollama_model == "custom:model"
    assert settings.ollama_think is True
    assert settings.ollama_timeout_seconds == 120.0
    assert settings.ollama_num_ctx == 8192
