from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    graph_backend: Literal["neo4j", "memory"] = "neo4j"
    model_provider: Literal["ollama", "demo"] = "ollama"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "local-development-only"
    neo4j_database: str = "neo4j"
    ollama_url: str = "http://localhost:11434"
    chat_model: str = "llama3.2:3b"
    embedding_model: str = "nomic-embed-text"
    embedding_dimensions: int = Field(default=768, ge=16, le=4096)
    data_dir: Path = Path("data")
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_upload_mb: int = Field(default=15, ge=1, le=100)

    @property
    def embedding_key(self) -> str:
        return f"{self.model_provider}:{self.embedding_model}:{self.embedding_dimensions}"
