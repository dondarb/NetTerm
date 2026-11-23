"""Almacén de configuración y sesiones de NetTerm.

Todo se guarda en JSON dentro de ``$XDG_CONFIG_HOME/netterm`` para que la
aplicación sea portable (funciona igual en Fedora, en un Flatpak o en un
AppImage) sin depender de GSettings.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

from .session import Session, SessionType

APP_ID = "io.github.netterm.NetTerm"
APP_NAME = "NetTerm"


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    d = Path(base) / "netterm"
    d.mkdir(parents=True, exist_ok=True)
    return d


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    d = Path(base) / "netterm"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    d = Path(base) / "netterm"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        shutil.move(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


DEFAULT_SETTINGS: dict[str, Any] = {
    "font": "Monospace 11",
    "font_size": 11,
    "cursor_blink": True,
    "scrollback": 10000,
    "theme": "dark",
    "bell": False,
    "copy_on_select": False,
    "word_wrap": False,
    "new_tab_position": "end",
    "default_shell": "",
    "confirm_close": True,
    "x11_forward": True,
    "ssh_options": "",
    "terminal_color_scheme": "default",
    "banner": "",
    "logo": "",
    "bookmarks": [],
    "highlight_patterns": [],
    "sidebar_width": 280,
    "sftp_follow_terminal": True,
    "ssh_config_path": "",
    "auto_scan_interfaces": True,
    "recent_menu": True,
}


class Config:
    """Punto único de acceso a ajustes y sesiones."""

    def __init__(self) -> None:
        self._settings_path = config_dir() / "settings.json"
        self._sessions_path = config_dir() / "sessions.json"
        self.settings: dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.sessions: list[Session] = []
        self.load()

    # ------------------------------------------------------------------
    def load(self) -> None:
        self.settings = dict(DEFAULT_SETTINGS)
        try:
            data = json.loads(self._settings_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.settings.update(data)
        except (OSError, ValueError):
            pass

        self.sessions = []
        try:
            raw = json.loads(self._sessions_path.read_text(encoding="utf-8"))
            for item in raw.get("sessions", []):
                try:
                    self.sessions.append(Session.from_dict(item))
                except Exception:
                    continue
        except (OSError, ValueError):
            pass

    def save_settings(self) -> None:
        _atomic_write(self._settings_path,
                      json.dumps(self.settings, indent=2, ensure_ascii=False))

    def save_sessions(self) -> None:
        payload = {
            "version": 1,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "sessions": [s.to_dict() for s in self.sessions],
        }
        _atomic_write(self._sessions_path,
                      json.dumps(payload, indent=2, ensure_ascii=False))

    # ------------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, DEFAULT_SETTINGS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self.settings[key] = value

    # ------------------------------------------------------------------
    def upsert_session(self, session: Session) -> Session:
        for i, s in enumerate(self.sessions):
            if s.id == session.id:
                session.created_at = session.created_at or s.created_at
                self.sessions[i] = session
                break
        else:
            self.sessions.append(session)
        self.save_sessions()
        return session

    def delete_session(self, session_id: str) -> None:
        self.sessions = [s for s in self.sessions if s.id != session_id]
        self.save_sessions()

    def session(self, session_id: str) -> Session | None:
        for s in self.sessions:
            if s.id == session_id:
                return s
        return None

    def groups(self) -> list[str]:
        seen: list[str] = []
        for s in self.sessions:
            if s.group not in seen:
                seen.append(s.group)
        return seen or ["Mis sesiones"]

    def sessions_in(self, group: str) -> list[Session]:
        return [s for s in self.sessions if s.group == group]

    def recent(self, limit: int = 12) -> list[Session]:
        used = [s for s in self.sessions if s.last_used]
        used.sort(key=lambda s: s.last_used, reverse=True)
        return used[:limit]

    def favorites(self) -> list[Session]:
        return [s for s in self.sessions if s.favorite]

    def touch(self, session: Session) -> None:
        session.last_used = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.save_sessions()

    # ------------------------------------------------------------------
    def add_recent_host(self, host: str, username: str = "", port: int = 22) -> None:
        """Guarda un host usado para la lista de conexiones rápidas."""
        path = config_dir() / "recent.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                data = []
        except (OSError, ValueError):
            data = []
        entry = {"host": host, "username": username, "port": port}
        data = [d for d in data if not (d.get("host") == host and d.get("port") == port)]
        data.insert(0, entry)
        _atomic_write(path, json.dumps(data[:30], indent=2))

    def recent_hosts(self) -> list[dict[str, Any]]:
        path = config_dir() / "recent.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []


CONFIG = Config()
