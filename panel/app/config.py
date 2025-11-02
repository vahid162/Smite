"""Application configuration"""
from pydantic_settings import BaseSettings
from typing import Literal


class Settings(BaseSettings):
    # Panel
    panel_port: int = 8000
    panel_host: str = "0.0.0.0"
    https_enabled: bool = False
    https_cert_path: str = "./certs/server.crt"
    https_key_path: str = "./certs/server.key"
    docs_enabled: bool = True
    
    # Database
    db_type: Literal["sqlite", "mysql"] = "sqlite"
    db_path: str = "./data/smite.db"
    db_host: str = "localhost"
    db_port: int = 3306
    db_name: str = "smite"
    db_user: str = "smite"
    db_password: str = "changeme"
    
    # Hysteria2
    hysteria2_port: int = 4443
    hysteria2_cert_path: str = "./certs/ca.crt"
    hysteria2_key_path: str = "./certs/ca.key"
    
    # Security
    secret_key: str = "changeme-secret-key-change-in-production"
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()

