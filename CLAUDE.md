# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the game

```bash
source .venv/bin/activate
python game.py
```

There are no tests or linting setup. The only dependency is `pygame` (plus `matplotlib` and `numpy` in `requirements.txt`, though these are not used by the game).

## Architecture

The simulation uses a **1D coordinate system** — boats have a single `position` (left edge, in sim units) and a `length`. Sim space runs 0–1000; the lock occupies `lock_start=350` to `lock_end=650`. Screen x is mapped via `_sx_offset=50` and `_sx_scale=(width-100)/1000`.

**Two-lane model**: boats travel in opposite directions on separate visual lanes. `direction=+1` is downstream (left→right, upper lane), `direction=-1` is upstream (right→left, lower lane). Lanes are purely visual offsets (`_LANE_OFF = {1: 28, -1: 82}` px below the water surface). Collision/blocking logic is direction-based only — opposite-direction boats never interact; same-direction boats queue and can rear-end.

**Key classes:**
- `Agent` (in `game.py`) — wraps a `Boat` with AI state (`active`/`crashed`/`done`), direction, speed, `is_moving`, `tied_down`, and TTL for crash removal.
- `LockDamVisualizer` — owns the game loop, all rendering, spawn logic, and incident detection. `__init__()` is used as the restart mechanism (called directly on `K_r`).
- `LockAndDam` (`lock_and_dam.py`) — model with gradual fill/drain via `update(dt)` at `fill_rate=0.4 m/s`. `fill_chamber()` is blocked if the downstream gate is open; `drain_chamber()` is blocked if the upstream gate is open.
- `Boat` / subclasses (`boat.py`) — `Kayak` (4 m), `Yacht` (15 m), `Barge` (60 m), `PaddleBoat` (35 m). `check_collision()` is 1D overlap only.

**Gate blocking in `_step_agent`**: boats stop at the outer wall face when approaching from outside, or the inner wall face (`_wall_t_sim`) when stopped inside the lock. Tied boats (`ag.tied_down = True`) are completely stationary — `_step_agent` returns immediately.

**Operator AI**: `_update_operator(dt)` controls a visible figure on the lock wall. It autonomously walks to boats that are stopped and fully inside the lock to tie them, and unties them when their exit gate opens. The operator can cross to the opposite wall by walking to a closed gate. The operator's position is tracked in sim-space (`op['x']`); its visual y-position depends on `op['side']` (0 = top wall, 1 = bottom wall).

**Day/night cycle**: `game_time` (24-hour float) advances at `time_scale=5.0` hours per real minute. `_get_ambient_mult()` returns a 0.3–1.0 brightness multiplier used to dim all colours at night. `_get_sky_colors()` transitions through dawn/day/dusk/sunset/night palettes. Boat spawning is restricted at night (no Kayaks; weighted toward Barges). Boats show navigation lights when `is_dark` (before 6:30 or after 18:30).

**Weather system**: Moving clouds always present. Rain toggles on a random timer (`_update_weather`), darkening the ambient multiplier by 0.75×. Rain includes animated falling drops and occasional lightning bolts.

**Nature**: Trees at fixed sim-space positions along both banks. Birds fly during the day and home to trees at dusk to sleep (`_update_nature`).

**Incident types:**
- Crash — same-direction boats overlap
- Surge — gate opened with >2.0 m differential; crashes all boats currently in the chamber
- Game over — both gates open simultaneously for >1 s (60 frames)

**Views**: `view_mode` toggles between `"shore"` (default top-down side view) and `"operator"` (first-person POV from the lock wall). Toggle with `V`.

**Rendering clip regions**: `_draw_boat_shore` uses `pygame.set_clip` to constrain each boat's hull drawing to its region (upstream channel, lock interior, or downstream channel), preventing boats from painting over lock walls. Region is chosen by the sim-space centre of the boat (`cx = position + length/2`), not screen left edge.