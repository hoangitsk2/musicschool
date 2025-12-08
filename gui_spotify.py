"""Desktop controller for auto_break_player using ttkbootstrap."""
from __future__ import annotations

import argparse
import contextlib
import mimetypes
import os
import threading
import time
from tkinter import END, filedialog, messagebox

import requests
import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH, E, EW, HORIZONTAL, LEFT, NW, RIGHT, TOP, W, X, Y

DEFAULT_API_BASE = os.environ.get("AUTO_BREAK_PLAYER_API", "http://127.0.0.1:8000/api")


class SpotifyStyleGUI(ttk.Window):
    def __init__(self, api_base: str = DEFAULT_API_BASE) -> None:
        super().__init__(themename="minty")
        self.title("Campus Break DJ")
        self.geometry("860x760")
        self.playlists: list[dict[str, object]] = []
        self.tracks: list[dict[str, object]] = []
        self.playlist_entries: dict[int, list[dict[str, object]]] = {}
        self.schedules: list[dict[str, object]] = []
        self.power_auto = ttk.BooleanVar(value=True)
        self.schedule_enabled = ttk.BooleanVar(value=True)
        self.api_base = api_base.rstrip("/")
        self.selected_playlist_id: int | None = None
        self.selected_schedule_id: int | None = None

        self._build_layout()
        self.after(100, self.refresh_playlists)
        self.after(200, self.refresh_tracks)
        self.after(1000, self.refresh_status)
        self.after(1500, self.refresh_schedules)

    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        padding = 15
        style = ttk.Style()
        style.configure("Card.TFrame", padding=padding)
        container = ttk.Frame(self, padding=padding)
        container.pack(fill=BOTH, expand=True)

        title = ttk.Label(
            container,
            text="Break Session Studio",
            font=("Inter", 26, "bold"),
            bootstyle="inverse",
        )
        title.pack(pady=(0, 4))
        subtitle = ttk.Label(
            container,
            text="Âm nhạc giờ ra chơi cho học sinh vui vẻ và đúng lịch",
            font=("Inter", 12),
            bootstyle="info",
        )
        subtitle.pack(pady=(0, 12))

        self.notebook = ttk.Notebook(container, bootstyle="dark")
        self.notebook.pack(fill=BOTH, expand=True)

        dashboard = ttk.Frame(self.notebook, padding=padding, style="Card.TFrame")
        playlists_tab = ttk.Frame(self.notebook, padding=padding, style="Card.TFrame")
        tracks_tab = ttk.Frame(self.notebook, padding=padding, style="Card.TFrame")
        schedules_tab = ttk.Frame(self.notebook, padding=padding, style="Card.TFrame")

        self._build_dashboard_tab(dashboard)
        self._build_playlists_tab(playlists_tab)
        self._build_tracks_tab(tracks_tab)
        self._build_schedules_tab(schedules_tab)

        self.notebook.add(dashboard, text="Dashboard")
        self.notebook.add(playlists_tab, text="Playlists")
        self.notebook.add(tracks_tab, text="Tracks")
        self.notebook.add(schedules_tab, text="Schedules")

    def _build_dashboard_tab(self, parent: ttk.Frame) -> None:
        self.playlist_combo = ttk.Combobox(parent, bootstyle="dark", state="readonly")
        self.playlist_combo.pack(fill=X, pady=5)

        minutes_frame = ttk.Frame(parent)
        minutes_frame.pack(fill=X, pady=5)
        ttk.Label(minutes_frame, text="Session minutes", font=("Inter", 11, "bold")).pack(side=LEFT)
        self.minutes_entry = ttk.Entry(minutes_frame)
        self.minutes_entry.insert(0, "15")
        self.minutes_entry.pack(side=RIGHT, fill=X, expand=True)

        self.auto_power_check = ttk.Checkbutton(
            parent,
            text="Auto power ON before play",
            variable=self.power_auto,
            bootstyle="success-toolbutton",
        )
        self.auto_power_check.pack(anchor=W, pady=5)

        preview_frame = ttk.Labelframe(parent, text="Track preview", padding=12, bootstyle="secondary")
        preview_frame.pack(fill=X, pady=5)
        self.preview_combo = ttk.Combobox(preview_frame, bootstyle="dark", state="readonly")
        self.preview_combo.pack(fill=X, pady=(0, 8))
        ttk.Button(
            preview_frame,
            text="Play preview on system",
            command=self.on_preview,
            bootstyle="secondary",
        ).pack(fill=X)

        button_frame = ttk.Frame(parent, padding=(0, 10))
        button_frame.pack(fill=X, pady=10)
        ttk.Button(button_frame, text="Play", command=self.on_play, bootstyle="success").pack(
            side=LEFT, expand=True, padx=5
        )
        ttk.Button(button_frame, text="Stop", command=self.on_stop, bootstyle="danger").pack(
            side=LEFT, expand=True, padx=5
        )
        ttk.Button(button_frame, text="Skip", command=self.on_skip, bootstyle="secondary").pack(
            side=LEFT, expand=True, padx=5
        )

        volume_label = ttk.Label(parent, text="Volume", font=("Inter", 12, "bold"))
        volume_label.pack(anchor=W, pady=(20, 5))
        self.volume_var = ttk.IntVar(value=70)
        self.volume_slider = ttk.Scale(
            parent,
            from_=0,
            to=100,
            orient=HORIZONTAL,
            variable=self.volume_var,
            command=self.on_volume_change,
        )
        self.volume_slider.pack(fill=X)

        delay_frame = ttk.Labelframe(parent, text="Timed session", padding=12, bootstyle="info")
        delay_frame.pack(fill=X, pady=20)
        ttk.Label(delay_frame, text="Delay start (minutes)").pack(anchor=W)
        self.delay_entry = ttk.Entry(delay_frame)
        self.delay_entry.insert(0, "5")
        self.delay_entry.pack(fill=X, pady=5)
        ttk.Button(
            delay_frame, text="Start timed session", command=self.on_timed_session, bootstyle="info"
        ).pack(fill=X)

        status_frame = ttk.Labelframe(parent, text="Status", padding=12, bootstyle="primary")
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

    def _build_playlists_tab(self, parent: ttk.Frame) -> None:
        create_frame = ttk.Frame(parent)
        create_frame.pack(fill=X, pady=(0, 10))
        ttk.Label(create_frame, text="New playlist", font=("Inter", 11, "bold")).pack(anchor=W)
        entry_row = ttk.Frame(create_frame)
        entry_row.pack(fill=X, pady=4)
        self.new_playlist_entry = ttk.Entry(entry_row)
        self.new_playlist_entry.pack(side=LEFT, fill=X, expand=True, padx=(0, 8))
        ttk.Button(entry_row, text="Create", bootstyle="success", command=self.on_create_playlist).pack(side=LEFT)

        lists_frame = ttk.Frame(parent)
        lists_frame.pack(fill=BOTH, expand=True)

        left_panel = ttk.Frame(lists_frame)
        left_panel.pack(side=LEFT, fill=Y, expand=True, padx=(0, 12))

        ttk.Label(left_panel, text="Playlists", font=("Inter", 12, "bold")).pack(anchor=W, pady=(0, 6))
        self.playlist_tree = ttk.Treeview(left_panel, columns=("name",), show="headings", height=8, bootstyle="info")
        self.playlist_tree.heading("name", text="Name")
        self.playlist_tree.pack(fill=BOTH, expand=True)
        self.playlist_tree.bind("<<TreeviewSelect>>", self.on_playlist_selected)

        right_panel = ttk.Frame(lists_frame)
        right_panel.pack(side=LEFT, fill=BOTH, expand=True)

        ttk.Label(right_panel, text="Playlist entries", font=("Inter", 12, "bold")).pack(anchor=W, pady=(0, 6))
        self.playlist_entries_tree = ttk.Treeview(
            right_panel,
            columns=("position", "track"),
            show="headings",
            height=8,
            bootstyle="secondary",
        )
        self.playlist_entries_tree.heading("position", text="Pos")
        self.playlist_entries_tree.heading("track", text="Track")
        self.playlist_entries_tree.column("position", width=60, anchor=W)
        self.playlist_entries_tree.pack(fill=BOTH, expand=True)

        control_frame = ttk.Frame(right_panel)
        control_frame.pack(fill=X, pady=8)
        self.playlist_track_combo = ttk.Combobox(control_frame, bootstyle="dark", state="readonly")
        self.playlist_track_combo.pack(side=LEFT, fill=X, expand=True, padx=(0, 8))
        self.playlist_position_spin = ttk.Spinbox(control_frame, from_=0, to=999, width=5)
        self.playlist_position_spin.set("0")
        self.playlist_position_spin.pack(side=LEFT, padx=(0, 8))
        ttk.Button(
            control_frame,
            text="Add to playlist",
            bootstyle="primary",
            command=self.on_add_track_to_playlist,
        ).pack(side=LEFT)

        ttk.Button(
            right_panel,
            text="Remove selected entry",
            bootstyle="danger-outline",
            command=self.on_remove_playlist_entry,
        ).pack(anchor=E, pady=4)

    def _build_tracks_tab(self, parent: ttk.Frame) -> None:
        action_frame = ttk.Frame(parent)
        action_frame.pack(fill=X, pady=(0, 10))
        ttk.Button(action_frame, text="Upload tracks", bootstyle="success", command=self.on_upload_tracks).pack(
            side=LEFT
        )
        ttk.Button(
            action_frame,
            text="Delete selected",
            bootstyle="danger-outline",
            command=self.on_delete_track,
        ).pack(side=LEFT, padx=(10, 0))

        self.track_tree = ttk.Treeview(
            parent,
            columns=("id", "name", "duration"),
            show="headings",
            height=12,
            bootstyle="info",
        )
        self.track_tree.heading("id", text="ID")
        self.track_tree.column("id", width=60, anchor=W)
        self.track_tree.heading("name", text="Name")
        self.track_tree.column("name", anchor=W)
        self.track_tree.heading("duration", text="Duration (s)")
        self.track_tree.column("duration", width=120, anchor=W)
        self.track_tree.pack(fill=BOTH, expand=True)

    def _build_schedules_tab(self, parent: ttk.Frame) -> None:
        form = ttk.Frame(parent)
        form.pack(fill=X, pady=(0, 10))

        ttk.Label(form, text="Schedule name", font=("Inter", 11, "bold")).grid(row=0, column=0, sticky=W)
        self.schedule_name_entry = ttk.Entry(form)
        self.schedule_name_entry.grid(row=0, column=1, sticky=EW, padx=(8, 0))

        ttk.Label(form, text="Playlist", font=("Inter", 11, "bold")).grid(row=1, column=0, sticky=W, pady=(6, 0))
        self.schedule_playlist_combo = ttk.Combobox(form, bootstyle="dark", state="readonly")
        self.schedule_playlist_combo.grid(row=1, column=1, sticky=EW, padx=(8, 0), pady=(6, 0))

        ttk.Label(form, text="Days", font=("Inter", 11, "bold")).grid(row=2, column=0, sticky=NW, pady=(6, 0))
        days_frame = ttk.Frame(form)
        days_frame.grid(row=2, column=1, sticky=W, padx=(8, 0), pady=(6, 0))
        self.schedule_day_vars: dict[str, ttk.BooleanVar] = {}
        day_labels = [
            ("0", "Sun"),
            ("1", "Mon"),
            ("2", "Tue"),
            ("3", "Wed"),
            ("4", "Thu"),
            ("5", "Fri"),
            ("6", "Sat"),
        ]
        for value, label in day_labels:
            var = ttk.BooleanVar(value=value in {"1", "2", "3", "4", "5"})
            self.schedule_day_vars[value] = var
            ttk.Checkbutton(days_frame, text=label, variable=var, bootstyle="secondary-toolbutton").pack(
                side=LEFT, padx=2
            )

        ttk.Label(form, text="Start HH:MM", font=("Inter", 11, "bold")).grid(row=3, column=0, sticky=W, pady=(6, 0))
        self.schedule_time_entry = ttk.Entry(form)
        self.schedule_time_entry.insert(0, "09:30")
        self.schedule_time_entry.grid(row=3, column=1, sticky=EW, padx=(8, 0), pady=(6, 0))

        ttk.Label(form, text="Minutes", font=("Inter", 11, "bold")).grid(row=4, column=0, sticky=W, pady=(6, 0))
        self.schedule_minutes_entry = ttk.Entry(form)
        self.schedule_minutes_entry.insert(0, "15")
        self.schedule_minutes_entry.grid(row=4, column=1, sticky=EW, padx=(8, 0), pady=(6, 0))

        ttk.Checkbutton(form, text="Enabled", variable=self.schedule_enabled, bootstyle="success").grid(
            row=5, column=1, sticky=W, pady=(6, 0)
        )

        ttk.Button(
            form,
            text="Create schedule",
            bootstyle="info",
            command=self.on_create_schedule,
        ).grid(row=6, column=1, sticky=E, pady=(10, 0))

        self.schedule_tree = ttk.Treeview(
            parent,
            columns=("name", "playlist", "days", "start", "minutes", "enabled"),
            show="headings",
            height=10,
            bootstyle="primary",
        )
        for column, heading in zip(
            ("name", "playlist", "days", "start", "minutes", "enabled"),
            ("Name", "Playlist", "Days", "Start", "Minutes", "Enabled"),
        ):
            self.schedule_tree.heading(column, text=heading)
            self.schedule_tree.column(column, anchor=W)
        self.schedule_tree.column("minutes", width=90)
        self.schedule_tree.column("enabled", width=80)
        self.schedule_tree.pack(fill=BOTH, expand=True, pady=(10, 0))
        self.schedule_tree.bind("<<TreeviewSelect>>", self.on_schedule_selected)

        ttk.Button(
            parent,
            text="Toggle selected",
            bootstyle="secondary",
            command=self.on_toggle_schedule,
        ).pack(anchor=E, pady=6)

        planner = ttk.Labelframe(parent, text="School break planner", padding=12, bootstyle="success")
        planner.pack(fill=X, pady=(4, 0))
        planner.columnconfigure(1, weight=1)

        ttk.Label(planner, text="Tên nhóm lịch", font=("Inter", 11, "bold")).grid(row=0, column=0, sticky=W)
        self.break_prefix_entry = ttk.Entry(planner)
        self.break_prefix_entry.insert(0, "Giờ ra chơi")
        self.break_prefix_entry.grid(row=0, column=1, sticky=EW, padx=(8, 0))

        ttk.Label(planner, text="Thời gian bắt đầu (HH:MM)", font=("Inter", 11, "bold")).grid(
            row=1, column=0, sticky=NW, pady=(8, 0)
        )
        self.break_times_entry = ttk.Entry(planner)
        self.break_times_entry.insert(0, "09:30, 15:30")
        self.break_times_entry.grid(row=1, column=1, sticky=EW, padx=(8, 0), pady=(8, 0))

        ttk.Label(planner, text="Số phút mỗi phiên", font=("Inter", 11, "bold")).grid(row=2, column=0, sticky=W, pady=(8, 0))
        self.break_minutes_spin = ttk.Spinbox(planner, from_=5, to=60, width=6)
        self.break_minutes_spin.set("15")
        self.break_minutes_spin.grid(row=2, column=1, sticky=W, padx=(8, 0), pady=(8, 0))

        self.break_replace_var = ttk.BooleanVar(value=True)
        ttk.Checkbutton(
            planner,
            text="Vô hiệu hoá lịch cũ cùng nhóm",
            variable=self.break_replace_var,
            bootstyle="warning",
        ).grid(row=3, column=1, sticky=W, padx=(8, 0), pady=(4, 0))

        ttk.Button(
            planner,
            text="Tạo kế hoạch giờ ra chơi",
            bootstyle="success-outline",
            command=self.on_create_break_plan,
        ).grid(row=4, column=1, sticky=E, pady=(10, 0))

    # ------------------------------------------------------------------
    def refresh_playlists(self) -> None:
        self._load_playlists()
        self.after(30000, self.refresh_playlists)

    def refresh_tracks(self) -> None:
        self._load_tracks()
        self.after(45000, self.refresh_tracks)

    def refresh_schedules(self) -> None:
        self._load_schedules()
        self.after(60000, self.refresh_schedules)

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
    def _load_playlists(self) -> None:
        try:
            response = requests.get(f"{self.api_base}/playlists", timeout=5)
            response.raise_for_status()
            self.playlists = response.json()
            names = [str(item.get("name", "")) for item in self.playlists]
            self.playlist_combo["values"] = names
            if names and not self.playlist_combo.get():
                self.playlist_combo.set(names[0])
            if hasattr(self, "schedule_playlist_combo"):
                self.schedule_playlist_combo["values"] = names
                if names and self.schedule_playlist_combo.get() not in names:
                    self.schedule_playlist_combo.set(names[0])
            self._populate_playlist_tree()
            if self.selected_playlist_id and not any(
                int(item.get("id", -1)) == self.selected_playlist_id for item in self.playlists
            ):
                self.selected_playlist_id = None
            self._refresh_selected_playlist_entries()
        except Exception as exc:  # pragma: no cover - UI feedback
            messagebox.showerror("Error", f"Failed to load playlists: {exc}")

    def _load_tracks(self) -> None:
        try:
            response = requests.get(f"{self.api_base}/tracks", timeout=5)
            response.raise_for_status()
            self.tracks = response.json()
            names = [str(item.get("name", "")) for item in self.tracks]
            self.preview_combo["values"] = names
            if names and not self.preview_combo.get():
                self.preview_combo.set(names[0])
            if hasattr(self, "playlist_track_combo"):
                self.playlist_track_combo["values"] = names
                if names and not self.playlist_track_combo.get():
                    self.playlist_track_combo.set(names[0])
            self._populate_track_tree()
            self._refresh_selected_playlist_entries()
        except Exception as exc:  # pragma: no cover - UI feedback
            messagebox.showerror("Error", f"Failed to load tracks: {exc}")

    def _load_schedules(self) -> None:
        try:
            response = requests.get(f"{self.api_base}/schedules", timeout=5)
            response.raise_for_status()
            self.schedules = response.json()
            self._populate_schedule_tree()
        except Exception as exc:  # pragma: no cover - UI feedback
            messagebox.showerror("Error", f"Failed to load schedules: {exc}")

    def _refresh_selected_playlist_entries(self) -> None:
        if self.selected_playlist_id is not None:
            self._load_playlist_entries(self.selected_playlist_id)

    def _clear_tree(self, tree: ttk.Treeview) -> None:
        for item in tree.get_children():
            tree.delete(item)

    def _populate_playlist_tree(self) -> None:
        if not hasattr(self, "playlist_tree"):
            return
        self._clear_tree(self.playlist_tree)
        for item in self.playlists:
            playlist_id = int(item.get("id", -1))
            name = str(item.get("name", ""))
            self.playlist_tree.insert("", "end", iid=str(playlist_id), values=(name,))
        if self.selected_playlist_id is not None:
            iid = str(self.selected_playlist_id)
            if iid in self.playlist_tree.get_children():
                self.playlist_tree.selection_set(iid)
                self.playlist_tree.focus(iid)

    def _populate_playlist_entries_tree(self, playlist_id: int) -> None:
        if not hasattr(self, "playlist_entries_tree"):
            return
        self._clear_tree(self.playlist_entries_tree)
        for entry in self.playlist_entries.get(playlist_id, []):
            entry_id = entry.get("entry_id")
            position = entry.get("position")
            track_name = entry.get("track_name") or "—"
            self.playlist_entries_tree.insert(
                "", "end", iid=str(entry_id), values=(position, track_name)
            )

    def _populate_track_tree(self) -> None:
        if not hasattr(self, "track_tree"):
            return
        self._clear_tree(self.track_tree)
        for track in self.tracks:
            track_id = track.get("id")
            duration = track.get("duration")
            duration_text = "—" if duration in (None, "") else str(duration)
            self.track_tree.insert(
                "",
                "end",
                iid=str(track_id),
                values=(track_id, track.get("name"), duration_text),
            )

    def _populate_schedule_tree(self) -> None:
        if not hasattr(self, "schedule_tree"):
            return
        self._clear_tree(self.schedule_tree)
        for schedule in self.schedules:
            schedule_id = schedule.get("id")
            playlist_name = self._lookup_playlist_name(schedule.get("playlist_id"))
            enabled_text = "Yes" if schedule.get("enabled") else "No"
            self.schedule_tree.insert(
                "",
                "end",
                iid=str(schedule_id),
                values=(
                    schedule.get("name"),
                    playlist_name,
                    schedule.get("days"),
                    schedule.get("start_time"),
                    schedule.get("session_minutes"),
                    enabled_text,
                ),
            )
        if self.selected_schedule_id is not None:
            iid = str(self.selected_schedule_id)
            if iid in self.schedule_tree.get_children():
                self.schedule_tree.selection_set(iid)
                self.schedule_tree.focus(iid)

    def _load_playlist_entries(self, playlist_id: int) -> None:
        try:
            response = requests.get(f"{self.api_base}/playlists/{playlist_id}", timeout=5)
            response.raise_for_status()
            data = response.json()
            self.playlist_entries[playlist_id] = data.get("tracks", [])
            self._populate_playlist_entries_tree(playlist_id)
        except Exception as exc:  # pragma: no cover - UI feedback
            messagebox.showerror("Error", f"Failed to load playlist entries: {exc}")

    def _selected_playlist_id(self) -> int | None:
        playlist_id = self._playlist_id_from_name(self.playlist_combo.get())
        if playlist_id is not None:
            return playlist_id
        return self.selected_playlist_id

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

    def _playlist_id_from_name(self, name: str | None) -> int | None:
        if not name:
            return None
        for item in self.playlists:
            if item.get("name") == name:
                return int(item.get("id"))
        return None

    def _track_id_from_name(self, name: str | None) -> int | None:
        if not name:
            return None
        for item in self.tracks:
            if item.get("name") == name:
                return int(item.get("id"))
        return None

    # ------------------------------------------------------------------
    def on_playlist_selected(self, _event=None) -> None:
        selection = self.playlist_tree.selection() if hasattr(self, "playlist_tree") else []
        if not selection:
            return
        playlist_id = int(selection[0])
        self.selected_playlist_id = playlist_id
        name = self._lookup_playlist_name(playlist_id)
        if name != "—":
            self.playlist_combo.set(name)
            if hasattr(self, "schedule_playlist_combo") and name in self.schedule_playlist_combo["values"]:
                self.schedule_playlist_combo.set(name)
        self._load_playlist_entries(playlist_id)

    def on_create_playlist(self) -> None:
        name = self.new_playlist_entry.get().strip()
        if not name:
            messagebox.showwarning("Playlist", "Enter a playlist name")
            return
        try:
            self._api_request("POST", "playlists", json={"name": name})
            self.new_playlist_entry.delete(0, END)
            self._load_playlists()
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def on_add_track_to_playlist(self) -> None:
        if self.selected_playlist_id is None:
            messagebox.showwarning("Playlist", "Select a playlist from the list")
            return
        track_id = self._track_id_from_name(self.playlist_track_combo.get())
        if track_id is None:
            messagebox.showwarning("Playlist", "Select a track to add")
            return
        position = self._parse_int(self.playlist_position_spin.get(), 0)
        try:
            self._api_request(
                "POST",
                f"playlists/{self.selected_playlist_id}/tracks",
                json={"track_id": track_id, "position": position},
            )
            self._load_playlist_entries(self.selected_playlist_id)
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def on_remove_playlist_entry(self) -> None:
        if self.selected_playlist_id is None:
            messagebox.showwarning("Playlist", "Select a playlist first")
            return
        selection = self.playlist_entries_tree.selection() if hasattr(self, "playlist_entries_tree") else []
        if not selection:
            messagebox.showwarning("Playlist", "Choose an entry to remove")
            return
        entry_id = int(selection[0])
        try:
            self._api_request("DELETE", f"playlists/{self.selected_playlist_id}/tracks/{entry_id}")
            self._load_playlist_entries(self.selected_playlist_id)
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def on_upload_tracks(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select audio files",
            filetypes=[("Audio", "*.mp3 *.wav"), ("All", "*.*")],
        )
        if not paths:
            return
        try:
            with contextlib.ExitStack() as stack:
                files = []
                for path in paths:
                    fh = stack.enter_context(open(path, "rb"))
                    mime = mimetypes.guess_type(path)[0] or "audio/mpeg"
                    files.append(("files", (os.path.basename(path), fh, mime)))
                response = self._api_request("POST", "tracks", files=files, timeout=30)
                data = response.json()
                uploaded = data.get("uploaded", [])
                errors = data.get("errors", [])
            if uploaded:
                messagebox.showinfo("Tracks", f"Uploaded {len(uploaded)} track(s)")
            if errors:
                messagebox.showwarning("Tracks", "\n".join(errors))
            self._load_tracks()
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def on_delete_track(self) -> None:
        selection = self.track_tree.selection() if hasattr(self, "track_tree") else []
        if not selection:
            messagebox.showwarning("Tracks", "Select track(s) to delete")
            return
        for item in selection:
            track_id = int(item)
            try:
                self._api_request("DELETE", f"tracks/{track_id}")
            except Exception as exc:
                messagebox.showerror("Error", str(exc))
                break
        self._load_tracks()

    def on_schedule_selected(self, _event=None) -> None:
        selection = self.schedule_tree.selection() if hasattr(self, "schedule_tree") else []
        if not selection:
            self.selected_schedule_id = None
            return
        self.selected_schedule_id = int(selection[0])

    def on_toggle_schedule(self) -> None:
        if self.selected_schedule_id is None:
            messagebox.showwarning("Schedules", "Select a schedule to toggle")
            return
        try:
            self._api_request("POST", f"schedules/{self.selected_schedule_id}/toggle")
            self._load_schedules()
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def on_create_schedule(self) -> None:
        playlist_id = self._playlist_id_from_name(self.schedule_playlist_combo.get()) if hasattr(
            self, "schedule_playlist_combo"
        ) else None
        if playlist_id is None:
            messagebox.showwarning("Schedules", "Select a playlist for the schedule")
            return
        name = self.schedule_name_entry.get().strip() or "Session"
        start_time = self.schedule_time_entry.get().strip() or "00:00"
        minutes = self._parse_int(self.schedule_minutes_entry.get(), 15)
        days = [day for day, var in getattr(self, "schedule_day_vars", {}).items() if var.get()]
        payload = {
            "name": name,
            "playlist_id": playlist_id,
            "start_time": start_time,
            "session_minutes": minutes,
            "days": days,
            "enabled": self.schedule_enabled.get(),
        }
        try:
            self._api_request("POST", "schedules", json=payload)
            self._load_schedules()
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def on_create_break_plan(self) -> None:
        playlist_id = self._playlist_id_from_name(self.schedule_playlist_combo.get()) if hasattr(
            self, "schedule_playlist_combo"
        ) else None
        if playlist_id is None:
            messagebox.showwarning("School break", "Chọn playlist để phát trong giờ ra chơi")
            return
        raw_times = (self.break_times_entry.get() if hasattr(self, "break_times_entry") else "").replace("\n", ",")
        try:
            times = self._parse_times(raw_times)
        except ValueError as exc:
            messagebox.showerror("School break", str(exc))
            return
        prefix = self.break_prefix_entry.get().strip() if hasattr(self, "break_prefix_entry") else ""
        payload = {
            "playlist_id": playlist_id,
            "start_times": times,
            "session_minutes": self._parse_int(self.break_minutes_spin.get(), 15)
            if hasattr(self, "break_minutes_spin")
            else 15,
            "days": [day for day, var in getattr(self, "schedule_day_vars", {}).items() if var.get()],
            "name_prefix": prefix or "Giờ ra chơi",
            "replace": bool(self.break_replace_var.get()) if hasattr(self, "break_replace_var") else False,
        }
        try:
            self._api_request("POST", "schedules/break-plan", json=payload)
            self._load_schedules()
            messagebox.showinfo("School break", "Đã cập nhật kế hoạch giờ ra chơi 15 phút cho học sinh.")
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

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
    def _api_request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        timeout = kwargs.pop("timeout", 10)
        response = requests.request(method, f"{self.api_base}/{endpoint}", timeout=timeout, **kwargs)
        if response.status_code >= 400:
            data = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else {}
            raise RuntimeError(data.get("error") or response.text)
        return response

    def _post(self, endpoint: str, payload: dict) -> None:
        self._api_request("POST", endpoint, json=payload, timeout=5)

    @staticmethod
    def _parse_int(value: str, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_times(value: str) -> list[str]:
        parts = []
        for chunk in value.replace(";", ",").split(","):
            token = chunk.strip()
            if not token:
                continue
            try:
                time.strptime(token, "%H:%M")
            except ValueError as exc:
                raise ValueError(f"Thời gian không hợp lệ: {token}") from exc
            if token not in parts:
                parts.append(token)
        if not parts:
            raise ValueError("Nhập ít nhất một thời gian bắt đầu ở định dạng HH:MM")
        return parts


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
