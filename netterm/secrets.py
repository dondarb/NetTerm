"""Bóveda de contraseñas con contraseña maestra.

Equivalente a la "Passwords management" de MobaXterm: las contraseñas de las
sesiones se cifran con una clave derivada de una contraseña maestra mediante
PBKDF2-HMAC-SHA256, y cada secreto se guarda cifrado con Fernet (AES-128-CBC
+ HMAC-SHA256) en ``vault.json``.

Si no se define contraseña maestra, los secretos se guardan en texto plano en
el propio almacén de sesiones (con aviso en la interfaz).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from .config import config_dir

_ITERATIONS = 480_000
_SALT_FILE = config_dir() / "vault.salt"
_VAULT_FILE = config_dir() / "vault.json"


class VaultError(Exception):
    """Error genérico de la bóveda."""


class WrongMasterPassword(VaultError):
    """La contraseña maestra indicada no es la correcta."""


class Vault:
    """Gestor de secretos cifrados."""

    def __init__(self) -> None:
        self._fernet: Fernet | None = None
        self._salt: bytes = b""
        self._master: str | None = None
        self._secrets: dict[str, str] = {}
        self._load()

    # ------------------------------------------------------------------
    @property
    def salt(self) -> bytes:
        if not self._salt or not self._salt_path().exists():
            self._salt = secrets.token_bytes(16)
            try:
                self._salt_path().write_bytes(self._salt)
                os.chmod(self._salt_path(), 0o600)
            except OSError:
                pass
        return self._salt

    def _salt_path(self) -> Path:
        return _SALT_FILE

    def _load(self) -> None:
        try:
            data = json.loads(_VAULT_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        self._secrets = data.get("secrets", {}) if isinstance(data, dict) else {}
        self._salt = b""
        try:
            self._salt = self._salt_path().read_bytes()
        except OSError:
            pass

    def _save(self) -> None:
        payload = {"version": 1, "secrets": self._secrets}
        _VAULT_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            os.chmod(_VAULT_FILE, 0o600)
        except OSError:
            pass

    # ------------------------------------------------------------------
    def _derive(self, master: str) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self.salt,
            iterations=_ITERATIONS,
        )
        return kdf.derive(master.encode("utf-8"))

    def unlock(self, master: str) -> None:
        """Comprueba la contraseña maestra y deja la bóveda abierta."""
        key = base64.urlsafe_b64encode(self._derive(master))
        try:
            fernet = Fernet(key)
        except Exception as exc:  # pragma: no cover
            raise VaultError(str(exc)) from exc
        probe = self._secrets.get("__probe__")
        if probe:
            try:
                fernet.decrypt(probe.encode("ascii"))
            except (InvalidToken, ValueError) as exc:
                raise WrongMasterPassword(
                    "La contraseña maestra no es correcta.") from exc
        else:
            token = fernet.encrypt(b"netterm-vault-probe").decode("ascii")
            self._secrets["__probe__"] = token
            self._save()
        self._fernet = fernet
        self._master = master

    @property
    def unlocked(self) -> bool:
        return self._fernet is not None

    @property
    def has_master(self) -> bool:
        """Existe una contraseña maestra configurada (bóveda cifrada)."""
        if "__probe__" in self._secrets:
            return True
        try:
            data = json.loads(_VAULT_FILE.read_text(encoding="utf-8"))
            return bool(data.get("secrets"))
        except (OSError, ValueError):
            return False

    def lock(self) -> None:
        self._fernet = None
        self._master = None

    # ------------------------------------------------------------------
    def set_secret(self, key: str, value: str) -> None:
        if not self._fernet:
            raise VaultError("La bóveda está bloqueada.")
        token = self._fernet.encrypt(value.encode("utf-8")).decode("ascii")
        self._secrets[key] = token
        self._save()

    def get_secret(self, key: str) -> str | None:
        if not self._fernet:
            return None
        token = self._secrets.get(key)
        if not token:
            return None
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            return None

    def delete_secret(self, key: str) -> None:
        self._secrets.pop(key, None)
        self._save()

    def has_secret(self, key: str) -> bool:
        return key in self._secrets

    def list_keys(self) -> list[str]:
        return [k for k in self._secrets if k != "__probe__"]

    def change_master(self, old: str, new: str) -> None:
        if self.has_master:
            self.unlock(old)
            secrets_map = {k: self.get_secret(k) for k in self.list_keys()}
        else:
            secrets_map = {}
        self._fernet = None
        self._secrets = {}
        self.unlock(new)
        for k, v in secrets_map.items():
            if v is not None:
                self.set_secret(k, v)
        self._master = new


VAULT = Vault()
