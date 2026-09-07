# CODEX_CONTEXT.md

## Purpose

This file is the handoff context for continuing development of this repository in Codex/Desktop without having to replay the full ChatGPT conversation.

Read this file **before modifying anything**.

> **Update (2026-09-07):** T1-T5 from `IMPLEMENTACION_MEJORAS.md` are implemented on this
> branch. Notably: Battle target matching now uses `cv2.matchTemplate` (with a bruteforce
> fallback if OpenCV is unavailable) instead of a pixel-by-pixel scan; the Battle detection
> loop now runs in a backend thread (`battle_monitor_thread.py`) instead of the browser;
> routine checkpoints are validated during execution; and Battle can optionally execute a
> real click via `battle_action_executor.py`, gated by the transient
> `battle_auto_action_enabled` flag (off by default) plus a foreground check — this is a
> deliberate, user-confirmed exception to "AI Advisor is advisory/read-only" below, which
> still applies to `ai_advisor.py` itself.
>
> Also: the actual git remote configured for this checkout is
> `https://github.com/escuelaalz1-debug/titian-mapper`, not `tibia-mapper` as named below —
> flagging the discrepancy rather than silently correcting it.
>
> **T6-T14 also implemented (2026-09-07):** notably T13 — `app_ai.py` no longer exists.
> Its two responsibilities (registering `/api/ai/*` and `/api/map/*` via `register_ai_routes`
> / `register_map_routes`, and the `ai_ui.js` injection `after_request` hook) were merged
> directly into `app.py`, since `launcher.py` (used by `tibia-mapper.spec` to build the EXE)
> only ever imported `app.py` — the packaged EXE never had the AI/map routes. Run `python
> app.py` for everything now; there is no separate AI entry point anymore.
>
> **T15 also implemented (2026-09-07):** `screen_event_monitor.analyze_event_region()` now
> has a real detector (`detect_text` via `bestiary_reader.read_bestiary()` reused as a
> generic OCR text reader; `battle_reference` via `battle_monitor._best_match()`), and the
> 5 handlers in `mouse_helpers.py` execute real input, gated by a new transient
> `events_auto_action_enabled` flag (off by default) plus a foreground check — same pattern
> as `battle_auto_action_enabled`. B8 was also fixed: `capture_event_region()` now uses
> `get_live_frame()` (DXGI-local coordinates) instead of `ImageGrab.grab(all_screens=True)`
> (virtual-desktop coordinates).
>
> **CRITICAL, READ BEFORE TRUSTING ANY "verified with real Tibia" CLAIM ABOVE OR IN
> `IMPLEMENTACION_MEJORAS.md`:** on 2026-09-07, screen capture of Tibia on the user's
> machine was found to return **pure black** via *both* DXGI Desktop Duplication (`dxcam`,
> what `get_live_frame()` uses) *and* Windows Game Bar (`Win+Alt+PrtScn`) — two independent
> capture mechanisms. The NVIDIA Alt+F1 fallback (`request_nvidia_capture()`) doesn't fire
> either (confirmed by the user; NVIDIA App installed but Alt+F1 does nothing). Likely
> cause: Tibia's client actively excludes its window from capture (similar to
> `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`, common in anti-cheat), though a
> hybrid-GPU (Intel UHD 770 + NVIDIA RTX 3070) capture-adapter mismatch was also considered
> and not fully ruled out. **This means the entire visual pipeline (Battle, Loot, Health
> OCR, checkpoints) could not see real Tibia content in that session** — a Battle
> "reference" recaptured live turned out to be solid black (see the `_best_match_cv2` flat-
> template bug fix, same session), and every "confirmed working with real Tibia" claim made
> earlier in that session for T1/T2/T4 is almost certainly invalid (black compared against
> black). Before trusting *any* live-Tibia test result on this machine, first confirm a
> fresh `get_live_frame()` capture actually shows real game content, not black.
>
> **RESOLVED, same session:** the root cause was confirmed — Tibia actively blocks
> conventional screen capture, but the user confirmed OBS's "Game Capture" source *can* see
> it once the "Use anti-cheat compatibility hook" checkbox is enabled on that source. Added
> a second capture backend (`settings.capture_backend = "obs_camera"`, see `capture_utils.
> _get_obs_camera_frame()` and `obs_bridge.py`) that reads OBS's Virtual Camera via
> `cv2.VideoCapture` instead of DXGI. **This is now the working backend on the user's
> machine** (`settings.json` has `capture_backend: "obs_camera"`, `obs_camera_index: 1`).
> Genuinely re-verified afterward with real Tibia content (not black): Battle template
> matching correctly located and discriminated between two different real Battle List rows.
> `battle_event_region` / `battle_reference_region` were also recalibrated to the OBS-view
> coordinates (1920x1080 canvas) — the old DXGI-era coordinates (2560x1440-based) no longer
> apply while this backend is active. If `capture_backend` is ever switched back to `"dxgi"`,
> expect the black-screen problem to return unless Tibia's protection has changed.

## Repository

- Repository: `escuelaalz1-debug/tibia-mapper`
- Working branch for the current AI/map work: `feature/ai-advisor`
- Do not modify `main` unless explicitly requested.
- Prefer reading the real files in the repo before assuming function names, module names, routes, settings, or data structures.

## Project overview

The application is a local Python/Flask Windows desktop-support tool that currently includes:

- routine creation/editing/execution
- mouse-coordinate recording
- OBS/DXGI-based image capture
- Battle visual detection
- Loot-change tracking
- passive Health Monitor OCR
- logs and diagnostics
- an AI Advisor layer
- offline TibiaMaps data integration

The project is primarily developed and run on Windows.

## Current application entrypoints

### Normal app

```powershell
python app.py
```

### AI-enabled app

```powershell
python app_ai.py
```

`app_ai.py` imports the existing Flask app and registers the AI/map routes and AI UI additions.

## Routine recording

Key behavior in `recorder.py`:

- `F12`: append one manual mouse coordinate to the active routine.
- `F11`: capture a checkpoint from OBS/DXGI for the last step.
- `F9`: toggle timed mouse sampling.
- Timed sampling records the current mouse position every 2 seconds.
- It does not move or click the mouse.
- Timed coordinates use the same normal routine step format.

Typical step:

```json
{
  "type": "coordinate",
  "x": 2030,
  "y": 417
}
```

Recording status also exposes timed-mode fields such as:

```text
timed_active
timed_interval_seconds
timed_sample_count
```

`static/execution_ui.js` was patched so routine polling does not unnecessarily re-render/re-download the same checkpoint every second.

## OBS / DXGI architecture

Important rule:

```text
READING / ANALYSIS -> OBS / DXGI / screen-1-local coordinates
INTERACTION        -> real Windows/game screen coordinates
```

Do not mix OBS scene coordinates with Windows input coordinates.

Routine checkpoints were changed to use OBS/DXGI instead of physical-screen/NVIDIA capture.

## Battle / Loot state

Current Battle logic uses visual matching and then Loot visual change as the completion signal.

Bestiary is no longer the preferred Battle-completion signal. Loot is considered more reliable.

While Battle is waiting for Loot change, the scanner focuses on Loot tracking rather than searching new Battle targets.

Relevant current settings include approximately:

```jsonz
{
  "loot_similarity_threshold": 0.975,
  "loot_change_confirmations": 1,
  "battle_poll_seconds": 1.0,
  "battle_similarity_threshold": 0.90,
  "battle_scan_step": 2,
  "battle_action_timeout_seconds": 5.0
}
```

The 5-second Battle timeout is a fallback. Loot change should normally release the state earlier.

Useful log patterns:

```text
BATTLE LOOT CHANGE
BATTLE STATE
BATTLE TRANSITION
loot_similarity
```

If diagnosing Battle timeout, inspect actual `loot_similarity` values around the expected Loot update instead of guessing.

## Health Monitor

Main file: `health_monitor.py`

It is passive/read-only.

It:

- captures from OBS/DXGI
- crops `health_value_region`
- runs numeric OCR
- stores last HP value
- logs when HP crosses the configured threshold
- logs recovery
- records OCR/provider errors

Current conceptual settings:

```json
{
  "health_value_region": {
    "x": 800,
    "y": 300,
    "width": 180,
    "height": 80
  },
  "health_monitor_enabled": true,
  "health_poll_seconds": 5.0,
  "health_log_threshold": 60
}
```

The threshold is currently a raw HP number, not a percentage.

Health OCR was strengthened to use a larger OCR scale for this numeric region and better diagnostics.

Useful log patterns:

```text
HEALTH MONITOR iniciado
HEALTH ALERT
HEALTH RECOVERY
HEALTH MONITOR ERROR
```

If Health Monitor fails, inspect the exact error and raw OCR token diagnostics before changing coordinates.

## AI Advisor

Branch `feature/ai-advisor` adds a local AI analysis layer.

Main files:

```text
ai_advisor.py
ai_routes.py
static/ai_ui.js
app_ai.py
```

The AI Advisor is advisory/read-only. It receives structured application state and returns analysis/recommendations.

### Local provider

The chosen free provider is:

```text
Ollama
model: qwen2.5:3b
base URL: http://127.0.0.1:11434
```

Environment overrides:

```text
OLLAMA_BASE_URL
OLLAMA_MODEL
```

The advisor calls Ollama `/api/chat` with JSON-format output requested.

If Ollama is unavailable, the app falls back to a local heuristic analyzer instead of crashing.

### AI API

```text
POST /api/ai/analyze
GET  /api/ai/status
```

`POST /api/ai/analyze` can include a routine id and optional map coordinates/context.

The response shape is intended to look like:

```json
{
  "provider": "ollama",
  "model": "qwen2.5:3b",
  "status": "warning",
  "summary": "...",
  "findings": ["..."],
  "recommendation": "...",
  "confidence": 0.88
}
```

The AI should explain state/errors and recommend what to inspect. It should not execute mouse/keyboard actions.

## Ollama setup

There is a PowerShell setup script:

```powershell
.\scripts\setup_ollama_ai.ps1
```

It is intended to:

- verify/install Ollama
- start Ollama if needed
- pull `qwen2.5:3b`
- test `/api/chat`
- prepare/update local TibiaMaps data

After setup:

```powershell
python app_ai.py
```

Then open:

```text
http://127.0.0.1:5000
```

## TibiaMaps offline integration

The project now uses a local clone of:

```text
https://github.com/tibiamaps/tibia-map-data.git
```

Local destination:

```text
data/tibia-map-data
```

This directory is ignored by Git and should remain local/cache data.

Update/download script:

```powershell
.\scripts\update_tibiamaps.ps1
```

The script should:

- clone the repo if missing
- otherwise run `git pull --ff-only`

Main local map service:

```text
tibia_map_service.py
```

Expected local source files include:

```text
data/tibia-map-data/data/bounds.json
data/tibia-map-data/data/markers.json
data/tibia-map-data/data/floor-XX-map.png
data/tibia-map-data/data/floor-XX-pathfinding.png
```

### Map API

```text
GET /api/map/status
GET /api/map/position?x=31946&y=31900&z=7
```

The map service should return structured information such as:

- requested Tibia position
- pixel coordinate in local floor image
- map RGB/color
- pathfinding state
- walkability
- friction/cost when available
- nearby markers
- viewer URL
- local-cache source metadata

Example target coordinate used during development:

```text
x=31946
y=31900
z=7
```

### Pathfinding interpretation

Current intended interpretation from TibiaMaps data:

```text
#FFFF00 -> non-walkable
#FF00FF -> unexplored
other grayscale values -> walkable/friction value
```

Do not assume every non-yellow/non-magenta RGB value is automatically valid without checking the actual dataset if results look strange.

## AI + map integration

The AI panel was extended to optionally include local TibiaMaps context.

The UI allows map coordinates and can request map context alongside Battle/Health/log/routine context.

The AI should receive a structured `map` object rather than scraping the website during each request.

The design goal is:

```text
first download/update map repo
-> work from local files
-> no repeated tibiamaps.io requests
-> send compact structured map context to Ollama
```

## Routine-path analysis in AI Advisor

The advisor includes a small geometry analyzer for recorded routine coordinates.

It currently computes concepts like:

- coordinate count
- total pixel distance
- near-duplicate consecutive points
- large jumps
- quiet vs movement segments

This is useful for cleaning/understanding F9 timed recordings.

Do not automatically rewrite or execute a routine based only on AI output. Present suggested cleanup/analysis first.

## Key files to inspect before changes

Before modifying functionality, read the relevant real files. Common files include:

```text
app.py
app_ai.py
app_paths.py
settings_store.py
settings.json
recorder.py
routine_store.py
routine_executor.py
mouse_helpers.py
checkpoint_store.py
capture_utils.py
battle_monitor.py
battle_store.py
health_monitor.py
bestiary_reader.py
ai_advisor.py
ai_routes.py
tibia_map_service.py
static/execution_ui.js
static/ai_ui.js
scripts/setup_ollama_ai.ps1
scripts/update_tibiamaps.ps1
.gitignore
requirements.txt
```

Do not assume current SHAs or code from this document are authoritative. The repo files are authoritative.

## Current commands for local development

Switch to the AI branch:

```powershell
git fetch
git checkout feature/ai-advisor
git pull
```

Install Python dependencies if needed:

```powershell
python -m pip install -r requirements.txt
```

Download/update map data:

```powershell
.\scripts\update_tibiamaps.ps1
```

Prepare Ollama + model:

```powershell
.\scripts\setup_ollama_ai.ps1
```

Run AI-enabled app:

```powershell
python app_ai.py
```

Useful URLs:

```text
http://127.0.0.1:5000
http://127.0.0.1:5000/api/ai/status
http://127.0.0.1:5000/api/map/status
http://127.0.0.1:5000/api/map/position?x=31946&y=31900&z=7
```

## How Codex should start a session

When opening this repo in Codex, first do this:

1. Read `CODEX_CONTEXT.md`.
2. Run `git status` and `git branch --show-current`.
3. Confirm branch is `feature/ai-advisor` before writing files.
4. Inspect the actual files related to the requested task.
5. Run the smallest relevant tests/checks before and after changes.
6. Do not claim a test passed unless it was actually executed.
7. Keep `main` untouched unless explicitly requested.
8. Prefer small, reviewable commits.

## Suggested first Codex task

A good first local task is:

```text
Read CODEX_CONTEXT.md and inspect the current feature/ai-advisor branch.
Verify Ollama, qwen2.5:3b, the local tibia-map-data clone, /api/ai/status,
/api/map/status, and /api/map/position?x=31946&y=31900&z=7.
Run the app locally, capture any errors, and fix only the AI/map integration issues you can reproduce.
Do not modify main.
```

## Notes for continuity

- The user prefers direct, practical fixes and copy-pasteable PowerShell commands.
- If a problem is uncertain, inspect logs/code rather than inventing names or causes.
- For Battle completion, prefer Loot-based evidence over reintroducing Bestiary logic.
- For map data, prefer local cached `tibia-map-data` over repeated remote requests.
- For AI, prefer local Ollama and preserve a fallback path when Ollama is unavailable.
