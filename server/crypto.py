from __future__ import annotations

from cryptography.fernet import Fernet

from .settings import data_dir


def _fernet() -> Fernet:
    path = data_dir() / "secret.key"
    if not path.exists():
        path.write_bytes(Fernet.generate_key())
        path.chmod(0o600)
    return Fernet(path.read_bytes())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "••••"
    return f"{value[:3]}••••{value[-2:]}"
