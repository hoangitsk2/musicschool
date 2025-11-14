# auto_break_player

An automated break-time music player designed for Raspberry Pi deployments with a modern web UI, Tkinter desktop controller, and background playback daemon.

## Features

- Flask backend with REST API and Tailwind + DaisyUI dashboard (dark theme).
- Playback daemon coordinating schedules, session timeout, and GPIO relay control.
- Multiple playback backends: python-vlc, cvlc subprocess, or dummy player for development.
- SQLite database via SQLAlchemy with tables for tracks, playlists, schedules, commands, state, and logs.
- Secure audio uploads with extension whitelist and unique filenames.
- Tkinter (ttkbootstrap) desktop controller for quick control over the REST API.
- Systemd service definitions for Raspberry Pi autostart.
- Acceptance tests powered by pytest.

## Project layout

```
auto_break_player/
├─ app.py                     # Flask app & routes
├─ playback_daemon.py         # Background loop handling schedules & commands
├─ player.py                  # Playback backends (VLC, cvlc, dummy)
├─ gpio_control.py            # Relay controller with safe fallback
├─ models.py                  # SQLAlchemy models & helpers
├─ config.py                  # Default settings and YAML loader
├─ config.yaml.example        # Sample configuration
├─ requirements.txt           # Linux/Raspberry Pi dependencies
├─ gui_spotify.py             # Tkinter desktop controller (dark style)
├─ scripts/
│  └─ migrate_db.py           # Create database & ensure state row
├─ systemd/
│  ├─ auto_break_player.service
│  └─ auto_break_player-daemon.service
├─ templates/                 # Tailwind/DaisyUI templates
├─ static/app.js              # Dashboard interactions
├─ music/                     # Uploaded audio files
└─ logs/                      # Log output (database-backed)
```

## Configuration

1. Copy `config.yaml.example` to `config.yaml` and adjust settings.
2. Ensure `music_dir` and `logs_dir` exist or will be created by the app.
3. (Optional) Define `bootstrap_schedules` in `config.yaml` to auto-create recurring playback slots when the daemon starts.

## Setup (Raspberry Pi / Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.yaml.example config.yaml
python scripts/migrate_db.py
python app.py  # terminal 1
python playback_daemon.py  # terminal 2
```

### Systemd

Update the service files to point to your project path, copy to `/etc/systemd/system/`, then enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now auto_break_player.service
sudo systemctl enable --now auto_break_player-daemon.service
```

### Command-line schedule helper

For headless deployments you can manage schedules without opening the web UI
by using the helper script:

```bash
python scripts/schedule_cli.py list
python scripts/schedule_cli.py add --name "Morning" --playlist "Morning Mix" --time 08:00 --minutes 15 --days Mon-Fri
python scripts/schedule_cli.py disable 2
```

The script accepts playlist identifiers or exact playlist names, supports day
aliases such as `Mon-Fri`, `Weekend`, or `Fri-Mon`, and defaults to scheduling
every day when `--days` is omitted.

### Automatic schedules from configuration

Define `bootstrap_schedules` in `config.yaml` to have the playback daemon create or update schedules automatically whenever it boots.
Each entry accepts a schedule `name`, the target `playlist` (id or exact name), the start `time`, optional `minutes`, `days`, and `enabled` flag.

```yaml
bootstrap_schedules:
  - name: Morning Bell
    playlist: Morning Playlist
    time: "08:00"
    days: Mon-Fri
    minutes: 20
```

`days` uses the same syntax as the CLI helper, so aliases like `Weekend` or `Fri-Mon` are supported.

## Testing

```bash
pip install -r requirements.txt
pip install pytest
pytest
```

## Security notes

- Audio uploads are limited to `.mp3` and `.wav` by default and saved with unique filenames.
- GPIO access gracefully falls back to a mock when hardware is unavailable.
- Playback falls back to cvlc or a dummy implementation when VLC is not available.

## License

MIT
