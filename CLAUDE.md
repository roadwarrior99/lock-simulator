# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the game

```bash
source .venv/bin/activate
python game.py
```

There are no tests or linting setup. The only dependency is `pygame` (plus `matplotlib` and `numpy` in `requirements.txt`, though these are not used by the game).

## Architecture

The simulation uses a **1D coordinate system** — boats have a single `position` (left edge, in sim units) and a `length`. Sim space runs 0–1000; the lock occupies `lock_start=500` to `lock_end=700`. Screen x is mapped via `_sx_offset=50` and `_sx_scale=(width-100)/1000`.

**Two-lane model**: boats travel in opposite directions on separate visual lanes. `direction=+1` is downstream (left→right, upper lane), `direction=-1` is upstream (right→left, lower lane). Lanes are purely visual offsets (`_LANE_OFF = {1: 28, -1: 82}` px below the water surface). Collision/blocking logic is direction-based only — opposite-direction boats never interact; same-direction boats queue and can rear-end.

**Key classes:**
- `Agent` (in `game.py`) — wraps a `Boat` with AI state (`active`/`crashed`/`done`), direction, speed, and TTL for crash removal.
- `LockDamVisualizer` — owns the game loop, all rendering, spawn logic, and incident detection. `__init__()` is used as the restart mechanism (called directly on `K_r`).
- `LockAndDam` (`lock_and_dam.py`) — pure model: upstream/downstream/chamber water levels, gate open flags, `fill_chamber()`/`drain_chamber()`.
- `Boat` / subclasses (`boat.py`) — `Kayak` (4 m), `Yacht` (15 m), `Barge` (60 m). `check_collision()` is 1D overlap only.

**Gate blocking in `_step_agent`**: boats stop at the outer wall face when approaching from outside, or the inner wall face (`_wall_t_sim`) when stopped inside the lock. `_wall_t_sim` is derived from the pixel wall thickness so stops align with the drawn walls.

**Incident types:**
- Crash — same-direction boats overlap
- Surge — gate opened with >2.0 m differential; crashes all boats currently in the chamber
- Game over — both gates open simultaneously for >3 s (180 frames)

**Rendering clip regions**: `_draw_boat_shore` uses `pygame.set_clip` to constrain each boat's hull drawing to its region (upstream channel, lock interior, or downstream channel), preventing boats from painting over lock walls. Region is chosen by the sim-space centre of the boat (`cx = position + length/2`), not screen left edge.