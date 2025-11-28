# InkyPi Codebase Guide

Comprehensive notes for running, configuring, and extending the InkyPi codebase.

## Overview
- Flask app (`src/inkypi.py`) serves the web UI and drives a background refresh loop that renders plugins to an e-ink display (or mock display in development).
- Plugins produce Pillow images; the display pipeline resizes, re-orients, and enhances them before handing off to hardware drivers.
- A playlist system schedules which plugin instance renders next, using interval or scheduled refresh rules per instance.
- Images and configuration are persisted under `src/static` and `src/config` so the service can survive restarts.

## Architecture Walkthrough
- **Entry point**: `src/inkypi.py` wires Flask + Waitress, registers blueprints, starts the background `RefreshTask`, and optionally shows a startup image.
- **Configuration**: `src/config.py::Config` loads `config/device.json` (production) or `config/device_dev.json` when `--dev` is passed, plus plugin metadata (`plugins/*/plugin-info.json`). It also tracks playlist state (`PlaylistManager`) and last refresh metadata (`RefreshInfo`).
- **Display layer**: `display/display_manager.py` selects a concrete display based on `display_type` (`mock`, `inky`, or `epd*` waveshare). It saves the raw image, rotates/resizes for the target resolution, applies optional enhancements, and delegates to the hardware driver.
- **Refresh loop**: `refresh_task.py` runs in a daemon thread. It waits `plugin_cycle_interval_seconds`, picks the active playlist for the current time window, advances to the next plugin instance, and renders it if the schedule/interval allows. A SHA-256 hash is used to skip redundant updates.
- **Plugins**: Registered via `plugins/plugin_registry.py` using each plugin’s `plugin-info.json`. Implementations subclass `BasePlugin`, expose `generate_image`, and can render from Pillow or headless Chromium HTML snapshots (`utils/image_utils.py`).
- **Static/UI**: HTML templates live under `src/templates` and `src/plugins/*/settings.html`. Assets are under `src/static`.

## Repository Layout
- `src/inkypi.py` – application bootstrap and server.
- `src/config.py` – config model + persistence; `src/config/device_dev.json` is the dev default.
- `src/display/*` – abstract + concrete display drivers (Inky, Waveshare, mock).
- `src/refresh_task.py` – background scheduler.
- `src/plugins/` – built-in plugins, registry, and plugin base class.
- `src/utils/` – helpers for images, fonts, networking, and startup rendering.
- `install/` – production installer scripts, dependencies, and systemd unit.
- `tests/` – pytest suite (playlist behavior tests).

## Running Locally (Development)
1. **Prerequisites**: Python 3.11+, `chromium-headless-shell` (for HTML-rendered plugins), and system headers for Pillow. On Debian/Raspberry Pi OS: `sudo apt-get install chromium-browser chromium-driver libopenjp2-7`.
2. **Create a venv & install deps**:
   ```bash
   cd /home/thanhkt/WeaAQI
   python -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   pip install -r install/requirements.txt
   ```
3. **Config file**: Dev mode uses `src/config/device_dev.json` (mock display, 800x480). To run without `--dev`, copy `install/config_base/device.json` into `src/config/device.json` and adjust fields (`display_type`, `resolution`, `playlist_config`, etc.).
4. **Run the server**:
   ```bash
   python src/inkypi.py --dev
   ```
   - Serves on port 8080 with the mock display. Prod mode (no flag) expects hardware and port 80.
5. **Tests**:
   ```bash
   pytest
   ```

## Production Install
- Run `sudo bash install/install.sh [-W <waveshare_model>]`.
- The script:
  - Enables SPI/I2C overlays, installs Debian and Python dependencies, and optionally fetches the Waveshare driver into `src/display/waveshare_epd`.
  - Creates a venv under `/usr/local/inkypi/venv_inkypi`, symlinks `src`, installs requirements, and copies base config to `src/config/device.json`.
  - Installs the `inkypi.service` systemd unit and starts it after setup.
- Use `sudo systemctl restart inkypi` after config changes.

## Configuration Basics
- **Device config** (`src/config/device*.json`): contains `display_type`, `resolution`, `orientation`, `inverted_image`, `plugin_cycle_interval_seconds`, and nested `playlist_config` plus `refresh_info`.
- **Playlists**: time windows (`start_time`/`end_time` strings, 24h format) with ordered plugin instances. Active playlist selection prefers the shortest active window.
- **Plugin instances**: stored in `playlist_config.playlists[].plugins[]` with `plugin_settings`, `refresh` (either `interval` seconds or `scheduled` `"HH:MM"`), and `latest_refresh_time`.
- **Images**: current output at `src/static/images/current_image.png`; per-plugin cached renders in `src/static/images/plugins/`.

## Plugin & Playlist Flow
1. Plugin code implements `generate_image(settings, device_config)` and raises `RuntimeError` on user-facing errors.
2. Each plugin has `plugin-info.json` (id, display_name, class) and optional `settings.html` for the web form.
3. When the scheduler picks a plugin instance, it checks:
   - Interval elapsed since `latest_refresh_time`, or
   - Scheduled time reached (per instance) for the current day.
4. If refresh is required, it renders, caches the image, hashes it, and updates config. If the hash matches the last displayed frame, the physical display is skipped to reduce wear.

## Operations & Tips
- Set `SRC_DIR` to the repo root if plugins need absolute paths for assets (otherwise defaults to `src` relative paths).
- `inverted_image` rotates the rendered frame 180° after resizing (useful for flipped displays).
- `log_system_stats` in config enables periodic CPU/memory/disk logging during refresh cycles.
- `utils/app_utils.generate_startup_image` shows the hostname/IP at boot when `startup` is true in config.

