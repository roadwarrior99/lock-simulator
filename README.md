# Albatross — Lock & Dam Operator

A pygame-based lock and dam operator game. Boats with simple AI navigate a two-lane canal from both directions. Your job is to work the lock controls to get as many boats through as possible without causing an incident.

## Gameplay

Boats spawn automatically from both ends of the canal and queue at the lock gates. You control the lock — fill or drain the chamber to match water levels, then open the appropriate gate to let boats through.

**Incidents** end your run or cost you points:
- **Crash** — two boats in the same lane collide
- **Surge** — a gate is opened when the water level differential exceeds 2 m
- **Game over** — both gates are left open simultaneously for more than 3 seconds

## Controls

| Key | Action |
|-----|--------|
| `G` | Toggle upstream gate |
| `H` | Toggle downstream gate |
| `F` | Fill lock chamber (raises to upstream level) |
| `D` | Drain lock chamber (lowers to downstream level) |
| `R` | Restart (after game over) |
| `Q` | Quit (after game over) |

## Setup

Requires Python 3.10+ and pygame.

```bash
python -m venv .venv #Setup a python virtual enviornment
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt # only required once.
python game.py # Runs the game
```

## Project Structure

| File              | Description |
|-------------------|-------------|
| `game.py`         | Main game loop, rendering, and boat AI |
| `lock_and_dam.py` | Lock chamber model (gates, fill/drain) |
| `boat.py`         | Boat classes: `Kayak`, `Yacht`, `Barge`, `ContainerShip` |
| `waterway.py`     | Waterway/canal model |