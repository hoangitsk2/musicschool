# auto_break_player

An automated break-time music player designed for Raspberry Pi deployments with a modern web UI, Tkinter desktop controller, and background playback daemon.

## Features

- Flask backend with REST API and Tailwind + DaisyUI dashboard (dark theme).
- Playback daemon coordinating schedules, session timeout, and GPIO relay control.
- Multiple playback backends: python-vlc, cvlc subprocess, or dummy player for development.
- SQLite database via SQLAlchemy with tables for tracks, playlists, schedules, commands, state, and logs.
- Secure audio uploads with extension whitelist and unique filenames.
- Tkinter (ttkbootstrap) desktop controller for quick control over the REST API.
- GitHub Pages-ready remote dashboard for controlling the Pi from anywhere.
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
├─ requirements-win.txt       # Windows development dependencies
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

1. Copy `config.yaml.example` to `config.yaml` and adjust settings (set `cors_origins` to the domains that will host your dashboard).
2. Ensure `music_dir` and `logs_dir` exist or will be created by the app.
3. On Windows development, set `vlc_backend: dummy` and `gpio.enabled: false`.

## Setup (Windows / development)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-win.txt
copy config.yaml.example config.yaml
python scripts\migrate_db.py
python app.py  # terminal 1
python playback_daemon.py  # terminal 2
# optional GUI controller
python gui_spotify.py
```

Open the dashboard at <http://127.0.0.1:8000>.

### Deploying the remote dashboard

1. Update `config.yaml` on the Raspberry Pi so `cors_origins` includes the GitHub Pages origin (for example `https://your-username.github.io`).
2. Upload the contents of `remote_site/` to a GitHub repository and enable GitHub Pages (or serve the folder from any static host).
3. Visit the published site, set the Raspberry Pi API URL in the connection card, and control schedules and playback remotely.

The remote dashboard talks directly to the Flask API, so no proxy or server-side rendering is required.

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

## Testing

```bash
pip install -r requirements-win.txt  # contains pytest for convenience
pytest
```

## Security notes

- Audio uploads are limited to `.mp3` and `.wav` by default and saved with unique filenames.
- GPIO access gracefully falls back to a mock when hardware is unavailable.
- Playback falls back to cvlc or a dummy implementation when VLC is not available.

## License

MIT
