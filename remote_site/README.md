# Remote Dashboard

This folder contains a static dashboard designed for GitHub Pages. It talks directly to the `auto_break_player` Flask API so you can power the Raspberry Pi relay, start playlists, and manage break schedules from any browser.

## Deploy

1. Ensure the Raspberry Pi's `config.yaml` lists your GitHub Pages domain under `cors_origins` (for example `https://your-username.github.io`).
2. Copy `remote_site/` into a GitHub repository and enable GitHub Pages for the `main` branch or `docs/` folder.
3. Visit the published page, enter the public API URL of your Raspberry Pi, and click **Save & Refresh**.

## Features

- Live power and playback status with 20 second polling.
- One-click power, play, stop, skip, and volume controls.
- Break-plan form that mirrors the Flask API helper for recurring school breaks.
- Schedule list with enable/disable toggles.
- Message log so you can confirm commands were queued.

All logic stays in the browser—no extra backend is needed.
