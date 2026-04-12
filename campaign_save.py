"""
campaign_save.py — serialise / restore GameEngine campaign state.

No pygame dependency; safe to import in unit tests.
"""

import json
import os

STAGE_IDS = ('operator', 'deckhand', 'engineer', 'captain')

STARTING_DEBT = 10000.0


def default_progressions():
    """Return a fresh per-stage progression dict (no debt — debt is global)."""
    def _fresh():
        return {
            'phase':          'nights',
            'clean_shifts':   0,
            'shift_num':      1,
            'story_seen':     False,
            'total_earnings': 0.0,
        }
    progs = {sid: _fresh() for sid in STAGE_IDS}
    # Operator tracks which ships have been seen and in which direction this week.
    # 'week' increments every 7 shifts; 'ships' maps name → {'last_dir': +1 or -1}.
    progs['operator']['ship_log'] = {'week': 0, 'ships': {}}
    return progs


def save_campaign(path, active_stage_id, progressions, debt):
    """
    Write campaign state to *path* as JSON.
    Parent directories are created automatically.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    payload = {
        'version':         2,
        'active_stage_id': active_stage_id,
        'debt':            debt,
        'progressions':    progressions,
    }
    with open(path, 'w') as fh:
        json.dump(payload, fh, indent=2)


def load_campaign(path):
    """
    Read a campaign save from *path*.

    Raises FileNotFoundError if the file does not exist.

    Missing stages and missing keys within stages are back-filled with
    defaults so that old saves remain compatible after new stages are added.

    Returns:
        {
            'active_stage_id': str,
            'debt':            float,
            'progressions':    dict   (all STAGE_IDS guaranteed present)
        }
    """
    with open(path, 'r') as fh:
        data = json.load(fh)

    defaults = default_progressions()
    saved_progs = data.get('progressions', {})

    merged = {}
    for sid in STAGE_IDS:
        base = dict(defaults[sid])
        saved = dict(saved_progs.get(sid, {}))
        saved.pop('debt', None)   # strip legacy per-stage debt if present
        base.update(saved)
        merged[sid] = base

    # v1 saves stored debt inside operator progression — migrate if needed
    legacy_debt = saved_progs.get('operator', {}).get('debt', None)
    debt = data.get('debt', legacy_debt if legacy_debt is not None else STARTING_DEBT)

    return {
        'active_stage_id': data.get('active_stage_id', 'operator'),
        'debt':            float(debt),
        'progressions':    merged,
    }