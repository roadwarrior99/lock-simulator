"""
campaign_save.py — serialise / restore GameEngine campaign state.

No pygame dependency; safe to import in unit tests.
"""

import json
import os

STAGE_IDS = ('operator', 'deckhand', 'engineer', 'captain')


def default_progressions():
    """Return a fresh per-stage progression dict."""
    def _fresh(debt=0.0):
        return {
            'phase':          'nights',
            'clean_shifts':   0,
            'shift_num':      1,
            'story_seen':     False,
            'total_earnings': 0.0,
            'debt':           debt,
        }
    return {
        'operator': _fresh(debt=10000.0),
        'deckhand': _fresh(),
        'engineer': _fresh(),
        'captain':  _fresh(),
    }


def save_campaign(path, active_stage_id, progressions):
    """
    Write campaign state to *path* as JSON.
    Parent directories are created automatically.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    payload = {
        'version':         1,
        'active_stage_id': active_stage_id,
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
            'progressions':    dict   (all STAGE_IDS guaranteed present)
        }
    """
    with open(path, 'r') as fh:
        data = json.load(fh)

    defaults = default_progressions()
    saved_progs = data.get('progressions', {})

    merged = {}
    for sid in STAGE_IDS:
        base = dict(defaults[sid])          # start from defaults
        base.update(saved_progs.get(sid, {}))  # overlay saved values
        merged[sid] = base

    return {
        'active_stage_id': data.get('active_stage_id', 'operator'),
        'progressions':    merged,
    }