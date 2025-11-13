"""Playback backends for auto_break_player."""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from typing import List, Optional


class BasePlayer:
    """Interface definition for playback backends."""

    def load_playlist(self, files: List[str]) -> None:
        raise NotImplementedError

    def play(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def set_volume(self, volume: int) -> None:
        raise NotImplementedError

    def is_playing(self) -> bool:
        raise NotImplementedError

    def update(self) -> Optional[int]:
        """Perform housekeeping tasks. Return new index if changed."""
        raise NotImplementedError

    def current_index(self) -> int:
        raise NotImplementedError

    def skip(self) -> None:
        raise NotImplementedError


class DummyPlayer(BasePlayer):
    """A playback backend used for development and tests."""

    def __init__(self) -> None:
        self._files: List[str] = []
        self._index = -1
        self._playing = False
        self._volume = 70

    def load_playlist(self, files: List[str]) -> None:
        self._files = list(files)
        self._index = 0 if self._files else -1
        self._playing = False

    def play(self) -> None:
        if not self._files:
            return
        self._playing = True

    def stop(self) -> None:
        self._playing = False
        self._index = -1

    def set_volume(self, volume: int) -> None:
        self._volume = max(0, min(100, volume))

    def is_playing(self) -> bool:
        return self._playing

    def update(self) -> Optional[int]:
        return None

    def current_index(self) -> int:
        return self._index

    def skip(self) -> None:
        if not self._files:
            return
        if self._index + 1 < len(self._files):
            self._index += 1
        else:
            self.stop()


try:  # pragma: no cover - external dependency
    import vlc
except Exception:  # pragma: no cover - executed when VLC not installed
    vlc = None


class VLCPlayer(BasePlayer):  # pragma: no cover - requires VLC runtime
    def __init__(self) -> None:
        if vlc is None:
            raise RuntimeError("python-vlc is not available")
        self._player = vlc.MediaListPlayer()
        self._media_list = vlc.MediaList()
        self._current_index = -1
        self._player_event = self._player.event_manager()
        self._player_event.event_attach(vlc.EventType.MediaListPlayerNextItemSet, self._on_next)
        self._player_event.event_attach(vlc.EventType.MediaListPlayerStopped, self._on_stopped)

    def _on_next(self, event) -> None:
        self._current_index = self._player.get_media_player().get_media().get_index()  # type: ignore[attr-defined]

    def _on_stopped(self, event) -> None:
        self._current_index = -1

    def load_playlist(self, files: List[str]) -> None:
        self._media_list = vlc.MediaList(files)
        self._player.set_media_list(self._media_list)
        self._current_index = 0 if files else -1

    def play(self) -> None:
        if self._media_list.count() == 0:
            return
        self._player.play()

    def stop(self) -> None:
        self._player.stop()
        self._current_index = -1

    def set_volume(self, volume: int) -> None:
        player = self._player.get_media_player()
        if player:
            player.audio_set_volume(volume)

    def is_playing(self) -> bool:
        return bool(self._player.is_playing())

    def update(self) -> Optional[int]:
        return self._current_index

    def current_index(self) -> int:
        return self._current_index

    def skip(self) -> None:
        self._player.next()


class CVLCPlayer(BasePlayer):  # pragma: no cover - requires cvlc binary
    def __init__(self) -> None:
        self._files: List[str] = []
        self._index = -1
        self._process: Optional[subprocess.Popen[str]] = None
        self._commands: "queue.Queue[str]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._playing = False
        self._volume = 70
        self._binary = self._resolve_binary()

    def _resolve_binary(self) -> str:
        """Locate a VLC-compatible executable on the current platform."""

        candidates: list[str] = []

        env_candidates = [
            os.environ.get("CVLC_PATH"),
            os.environ.get("VLC_BINARY"),
        ]
        candidates.extend([value for value in env_candidates if value])

        if os.name == "nt":
            program_files = [
                os.environ.get("ProgramFiles"),
                os.environ.get("ProgramFiles(x86)"),
            ]
            for base in program_files:
                if not base:
                    continue
                win_path = Path(base) / "VideoLAN" / "VLC" / "vlc.exe"
                candidates.append(str(win_path))
            candidates.extend(["vlc.exe", "vlc", "cvlc"])
        else:
            candidates.append("cvlc")
            candidates.append("vlc")

        for candidate in candidates:
            if not candidate:
                continue
            candidate_path = Path(candidate)
            if candidate_path.exists():
                return str(candidate_path)
            resolved = shutil.which(candidate)
            if resolved:
                return resolved

        raise RuntimeError(
            "Unable to locate VLC executable. Set CVLC_PATH or install VLC in the default location."
        )

    def _ensure_thread(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._writer_thread, daemon=True)
        self._thread.start()

    def _writer_thread(self) -> None:
        while True:
            cmd = self._commands.get()
            if cmd == "__quit__":
                break
            if self._process and self._process.stdin:
                try:
                    self._process.stdin.write(cmd + "\n")
                    self._process.stdin.flush()
                except BrokenPipeError:
                    break

    def _stop_process(self) -> None:
        if self._process:
            self._commands.put("quit")
            try:
                self._process.communicate(timeout=1)
            except Exception:
                self._process.kill()
        self._process = None
        if self._thread and self._thread.is_alive():
            self._commands.put("__quit__")
            self._thread.join(timeout=0.2)
        self._thread = None

    def load_playlist(self, files: List[str]) -> None:
        self.stop()
        self._files = list(files)
        self._index = 0 if self._files else -1

    def _needs_fake_tty(self) -> bool:
        return os.name == "nt"

    def _build_args(self) -> list[str]:
        args = [
            self._binary,
            "--quiet",
            "--intf",
            "dummy",
            "--extraintf",
            "rc",
            "--no-video",
            "--rc-quiet",
        ]
        if self._needs_fake_tty():
            # When VLC is launched without a console window on Windows it does
            # not treat stdin as an interactive terminal. The RC interface
            # therefore ignores commands unless we explicitly request the fake
            # TTY bridge.
            args.append("--rc-fake-tty")
        args += self._files
        return args

    def _spawn(self) -> None:
        if not self._files:
            return
        args = self._build_args()
        self._process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self._ensure_thread()
        # make sure the first command that reaches the RC interface is the
        # volume level so the preview is not startling on launch
        self._commands.put(f"volume {int(self._volume * 2.56)}")

    def play(self) -> None:
        if self._process is None:
            self._spawn()
        if self._process:
            # Explicitly send the play command – on Windows VLC does not begin
            # playback automatically when the RC interface is enabled.
            self._commands.put("play")
            self._playing = True

    def stop(self) -> None:
        self._playing = False
        self._stop_process()
        self._index = -1

    def set_volume(self, volume: int) -> None:
        self._volume = max(0, min(100, volume))
        if self._process:
            self._commands.put(f"volume {int(self._volume * 2.56)}")

    def is_playing(self) -> bool:
        if self._process is None:
            return False
        return self._process.poll() is None and self._playing

    def update(self) -> Optional[int]:
        if self._process and self._process.poll() is not None:
            self._process = None
            self._playing = False
            self._index = -1
        return self._index

    def current_index(self) -> int:
        return self._index

    def skip(self) -> None:
        if self._process:
            self._commands.put("next")
            if self._files:
                self._index = (self._index + 1) % len(self._files)


def make_player(backend: str) -> BasePlayer:
    backend = backend.lower()
    if backend == "vlc":
        return VLCPlayer()
    if backend == "cvlc":
        return CVLCPlayer()
    if backend == "dummy":
        return DummyPlayer()
    if backend == "auto":
        try:
            return VLCPlayer()
        except Exception:
            try:
                return CVLCPlayer()
            except Exception:
                return DummyPlayer()
    raise ValueError(f"Unknown backend: {backend}")


__all__ = [
    "BasePlayer",
    "DummyPlayer",
    "VLCPlayer",
    "CVLCPlayer",
    "make_player",
]
