"""Desktop controller for auto_break_player using ttkbootstrap."""
from __future__ import annotations

import argparse
import os
import threading
import time
from tkinter import messagebox

import requests
import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH, HORIZONTAL, LEFT, RIGHT, W, X

DEFAULT_API_BASE = os.environ.get("AUTO_BREAK_PLAYER_API", "http://127.0.0.1:8000/api")


class SpotifyStyleGUI(ttk.Window):
    def __init__(self, api_base: str = DEFAULT_API_BASE) -> None:
        super().__init__(themename="darkly")
        self.title("auto_break_player controller")
        self.geometry("480x620")
        self.playlists: list[dict[str, object]] = []
        self.tracks: list[dict[str, object]] = []
        self.power_auto = ttk.BooleanVar(value=True)
        self.api_base = api_base.rstrip("/")

        self._build_layout()
        self.after(100, self.refresh_playlists)
        self.after(200, self.refresh_tracks)
        self.after(1000, self.refresh_status)

    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        padding = 15
        container = ttk.Frame(self, padding=padding)
        container.pack(fill=BOTH, expand=True)

        title = ttk.Label(
            container,
            text="Break Session Control",
            font=("Inter", 20, "bold"),
            bootstyle="inverse",
        )
        title.pack(pady=(0, 10))

        self.playlist_combo = ttk.Combobox(container, bootstyle="dark", state="readonly")
        self.playlist_combo.pack(fill=X, pady=5)

        minutes_frame = ttk.Frame(container)
        minutes_frame.pack(fill=X, pady=5)
        ttk.Label(minutes_frame, text="Session minutes").pack(side=LEFT)
        self.minutes_entry = ttk.Entry(minutes_frame)
        self.minutes_entry.insert(0, "15")
        self.minutes_entry.pack(side=RIGHT, fill=X, expand=True)

        self.auto_power_check = ttk.Checkbutton(
            container,
            text="Auto power ON before play",
            variable=self.power_auto,
            bootstyle="success-toolbutton",
        )
        self.auto_power_check.pack(anchor=W, pady=5)

        preview_frame = ttk.Labelframe(container, text="Track preview", padding=padding, bootstyle="secondary")
        preview_frame.pack(fill=X, pady=5)
        self.preview_combo = ttk.Combobox(preview_frame, bootstyle="dark", state="readonly")
        self.preview_combo.pack(fill=X, pady=(0, 8))
        ttk.Button(
            preview_frame,
            text="Play preview on system",
            command=self.on_preview,
            bootstyle="secondary",
        ).pack(fill=X)

        button_frame = ttk.Frame(container, padding=(0, 5))
        button_frame.pack(fill=X, pady=10)
        ttk.Button(button_frame, text="Play", command=self.on_play, bootstyle="success").pack(side=LEFT, expand=True, padx=5)
        ttk.Button(button_frame, text="Stop", command=self.on_stop, bootstyle="danger").pack(side=LEFT, expand=True, padx=5)
        ttk.Button(button_frame, text="Skip", command=self.on_skip, bootstyle="secondary").pack(side=LEFT, expand=True, padx=5)

        volume_label = ttk.Label(container, text="Volume", font=("Inter", 12, "bold"))
        volume_label.pack(anchor=W, pady=(20, 5))
        self.volume_var = ttk.IntVar(value=70)
        self.volume_slider = ttk.Scale(
            container,
            from_=0,
            to=100,
            orient=HORIZONTAL,
            variable=self.volume_var,
            command=self.on_volume_change,
        )
        self.volume_slider.pack(fill=X)

        delay_frame = ttk.Labelframe(container, text="Timed session", padding=padding, bootstyle="info")
        delay_frame.pack(fill=X, pady=20)
        ttk.Label(delay_frame, text="Delay start (minutes)").pack(anchor=W)
        self.delay_entry = ttk.Entry(delay_frame)
        self.delay_entry.insert(0, "5")
        self.delay_entry.pack(fill=X, pady=5)
        ttk.Button(delay_frame, text="Start timed session", command=self.on_timed_session, bootstyle="info").pack(fill=X)

        status_frame = ttk.Labelframe(container, text="Status", padding=padding, bootstyle="primary")
        status_frame.pack(fill=X)
        self.status_label = ttk.Label(status_frame, text="Idle", font=("Inter", 16, "bold"))
        self.status_label.pack(anchor=W)
        self.eta_label = ttk.Label(status_frame, text="Session ends: —")
        self.eta_label.pack(anchor=W, pady=2)
        self.power_label = ttk.Label(status_frame, text="Power: OFF")
        self.power_label.pack(anchor=W, pady=2)
        self.playing_playlist_label = ttk.Label(status_frame, text="Playlist: —")
        self.playing_playlist_label.pack(anchor=W, pady=2)
        self.playing_track_label = ttk.Label(status_frame, text="Track: —")
        self.playing_track_label.pack(anchor=W, pady=2)

    # ------------------------------------------------------------------
    def refresh_playlists(self) -> None:
        try:
            response = requests.get(f"{self.api_base}/playlists", timeout=5)
            response.raise_for_status()
            self.playlists = response.json()
            names = [item["name"] for item in self.playlists]
            self.playlist_combo["values"] = names
            if names and not self.playlist_combo.get():
                self.playlist_combo.current(0)
        except Exception as exc:  # pragma: no cover - UI feedback
            messagebox.showerror("Error", f"Failed to load playlists: {exc}")
        finally:
            self.after(30000, self.refresh_playlists)

    def refresh_tracks(self) -> None:
        try:
            response = requests.get(f"{self.api_base}/tracks", timeout=5)
            response.raise_for_status()
            self.tracks = response.json()
            names = [item["name"] for item in self.tracks]
            self.preview_combo["values"] = names
            if names and not self.preview_combo.get():
                self.preview_combo.current(0)
        except Exception as exc:  # pragma: no cover - UI feedback
            messagebox.showerror("Error", f"Failed to load tracks: {exc}")
        finally:
            self.after(45000, self.refresh_tracks)

    def refresh_status(self) -> None:
        try:
            response = requests.get(f"{self.api_base}/status", timeout=5)
            response.raise_for_status()
            data = response.json()
            self.status_label.configure(text=data.get("status", "idle").title())
            eta = data.get("session_end_at") or "—"
            self.eta_label.configure(text=f"Session ends: {eta}")
            self.power_label.configure(text=f"Power: {'ON' if data.get('power_on') else 'OFF'}")
            volume = data.get("volume")
            if isinstance(volume, int):
                self.volume_var.set(volume)
            playlist_name = self._lookup_playlist_name(data.get("playlist_id"))
            track_name = self._lookup_track_name(data.get("current_track_id"))
            self.playing_playlist_label.configure(text=f"Playlist: {playlist_name}")
            self.playing_track_label.configure(text=f"Track: {track_name}")
        except Exception:
            pass
        finally:
            self.after(2000, self.refresh_status)

    # ------------------------------------------------------------------
    def _selected_playlist_id(self) -> int | None:
        if not self.playlists:
            return None
        name = self.playlist_combo.get()
        for item in self.playlists:
            if item.get("name") == name:
                return int(item.get("id"))
        return None

    def _selected_preview_track_id(self) -> int | None:
        if not self.tracks:
            return None
        name = self.preview_combo.get()
        for item in self.tracks:
            if item.get("name") == name:
                return int(item.get("id"))
        return None

    def _lookup_playlist_name(self, playlist_id: int | None) -> str:
        if playlist_id is None:
            return "—"
        for item in self.playlists:
            if int(item.get("id", -1)) == int(playlist_id):
                return str(item.get("name"))
        return "—"

    def _lookup_track_name(self, track_id: int | None) -> str:
        if track_id is None:
            return "—"
        for item in self.tracks:
            if int(item.get("id", -1)) == int(track_id):
                return str(item.get("name"))
        return "—"

    def on_play(self) -> None:
        playlist_id = self._selected_playlist_id()
        if playlist_id is None:
            messagebox.showwarning("Playlist", "Select a playlist first")
            return
        minutes = self._parse_int(self.minutes_entry.get(), 15)
        try:
            if self.power_auto.get():
                self._post("power", {"on": True})
            self._post("play", {"playlist_id": playlist_id, "minutes": minutes})
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def on_preview(self) -> None:
        track_id = self._selected_preview_track_id()
        if track_id is None:
            messagebox.showwarning("Track preview", "Select a track to preview")
            return
        try:
            if self.power_auto.get():
                self._post("power", {"on": True})
            self._post("preview", {"track_id": track_id})
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def on_stop(self) -> None:
        try:
            self._post("stop", {})
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def on_skip(self) -> None:
        try:
            self._post("skip", {})
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def on_volume_change(self, _value: str) -> None:
        value = int(float(self.volume_slider.get()))
        self.after_cancel(getattr(self, "_volume_job", None)) if hasattr(self, "_volume_job") else None

        def send_volume() -> None:
            try:
                self._post("volume", {"volume": value})
            except Exception as exc:
                messagebox.showerror("Error", str(exc))

        self._volume_job = self.after(400, send_volume)

    def on_timed_session(self) -> None:
        delay = self._parse_int(self.delay_entry.get(), 5)
        playlist_id = self._selected_playlist_id()
        if playlist_id is None:
            messagebox.showwarning("Playlist", "Select a playlist first")
            return
        minutes = self._parse_int(self.minutes_entry.get(), 15)

        def worker() -> None:
            for remaining in range(delay, 0, -1):
                self.status_label.after(0, lambda r=remaining: self.status_label.configure(text=f"Starting in {r} min"))
                time.sleep(60)
            try:
                if self.power_auto.get():
                    self._post("power", {"on": True})
                self._post("play", {"playlist_id": playlist_id, "minutes": minutes})
            except Exception as exc:
                messagebox.showerror("Error", str(exc))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    def _post(self, endpoint: str, payload: dict) -> None:
        response = requests.post(f"{self.api_base}/{endpoint}", json=payload, timeout=5)
        if response.status_code >= 400:
            data = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else {}
            raise RuntimeError(data.get("error") or response.text)

    @staticmethod
    def _parse_int(value: str, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Desktop controller for auto_break_player")
    parser.add_argument(
        "--api-base",
        dest="api_base",
        default=DEFAULT_API_BASE,
        help="Base URL for the auto_break_player API (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    app = SpotifyStyleGUI(api_base=args.api_base)
    app.mainloop()


if __name__ == "__main__":
    main()
