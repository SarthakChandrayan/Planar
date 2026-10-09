from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_BACKEND_DIR / ".env", _PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ollama_base_url: str = Field(default="http://localhost:11434", min_length=1)
    ollama_model: str = Field(default="qwen3:4b", min_length=1)
    ollama_think: bool = False
    # Longest wait for the next streamed token (covers prompt processing).
    ollama_timeout_seconds: float = Field(default=1200.0, gt=0)
    ollama_num_ctx: int = Field(default=16384, ge=2048)
    # How long Ollama keeps the model in RAM after a request.
    ollama_keep_alive: str = "30m"

    # Deterministic decoding so repeated runs and evaluations are comparable.
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    llm_seed: int = 42
    # Hard cap per model call; stops a small model looping forever on CPU.
    llm_max_output_tokens: int = Field(default=2048, ge=128)

    # Transcript tokens per chunk. Longer meetings are split with overlap.
    chunk_max_tokens: int = Field(default=8000, ge=500)
    # After the decisions and requirements passes, ask the model only for
    # what it missed (raises recall; about a minute more per meeting).
    analysis_second_look: bool = True
    max_transcript_chars: int = Field(default=300_000, gt=0)

    runs_dir: Path = _BACKEND_DIR / "data" / "runs"
    # Example transcripts offered in the UI ("Try a sample").
    samples_dir: Path = _PROJECT_ROOT / "samples"

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["text", "json"] = "text"
    # Comma-separated origins. Empty means same-origin only (the Vite proxy).
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    enable_dev_endpoints: bool = False

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value
