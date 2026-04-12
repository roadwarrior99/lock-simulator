"""
asset_manager.py — Dev tool for generating game content via the OpenAI API.

Not part of the game runtime. Requires:
    pip install openai

Set your key before running:
    export OPENAI_API_KEY=sk-...

Usage examples
--------------
    # Generate random crew names
    python asset_manager.py crew-name --count 5
    python asset_manager.py crew-name --count 3 --gender male

    # Generate dialog for a crew member and save to DB
    python asset_manager.py crew-dialog --name "Pat Holloway" --role deckhand --context barge_connected

    # Generate profiles for all crew missing bio/notes
    python asset_manager.py crew-profile

    # Target one specific crew member (creates record if not in DB)
    python asset_manager.py crew-profile --name "Pat Holloway" --role deckhand --vessel "MV Prairie Star"

    # Generate an image and save the file + register it in the DB
    python asset_manager.py image --prompt "towboat at night on the Mississippi River" --category background

    # Generate lock radio traffic for all ships (creates captains first)
    python asset_manager.py gen-radio --all

    # Print DB summary
    python asset_manager.py summary

    # Browse and regenerate art_assets in a windowed UI
    python asset_manager.py browse
"""

import argparse
import base64
import csv
import logging
import os
import random
import sys
from pathlib import Path

# Load .env from the project root if present (no external dependency needed)
_env_path = Path(__file__).parent / '.env'
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith('#') and '=' in _line:
            _k, _, _v = _line.partition('=')
            os.environ.setdefault(_k.strip(), _v.strip())

import assets as db_module

logging.basicConfig(level=logging.INFO, format='%(levelname)s  %(message)s')
logger = logging.getLogger(__name__)

# ── OpenAI client (lazy import so the file can be read without openai installed) ──

def _openai_client():
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("openai package not found. Run: pip install openai")
    key = os.environ.get('OPENAI_API_KEY')
    if not key:
        sys.exit("OPENAI_API_KEY environment variable is not set.")
    return OpenAI(api_key=key)


# ── Name pool ─────────────────────────────────────────────────────────────────

_SOURCE_DIR      = Path(__file__).parent / 'source_data'
_FIRST_NAMES_CSV = _SOURCE_DIR / 'Popular_Baby_Names.csv'
_LAST_NAMES_CSV  = _SOURCE_DIR / 'surnames.csv'
_VESSELS_CSV     = _SOURCE_DIR / 'vessels.csv'

# Cache so CSVs are only parsed once per process
_name_pool_cache: dict = {}


def _load_name_pool():
    """Parse both CSVs and return {male: ([names], [weights]), female: ..., last: ...}."""
    if _name_pool_cache:
        return _name_pool_cache

    # ── First names ──
    male_names,   male_weights   = [], []
    female_names, female_weights = [], []

    with open(_FIRST_NAMES_CSV, newline='', encoding='utf-8') as fh:
        for row in csv.DictReader(fh):
            name   = row["Child's First Name"].strip().title()
            gender = row['Gender'].strip().upper()
            try:
                weight = int(row['Count'])
            except (ValueError, KeyError):
                weight = 1
            if not name:
                continue
            if gender == 'MALE':
                male_names.append(name);   male_weights.append(weight)
            elif gender == 'FEMALE':
                female_names.append(name); female_weights.append(weight)

    # ── Last names ──
    last_names, last_weights = [], []
    with open(_LAST_NAMES_CSV, newline='', encoding='utf-8') as fh:
        for row in csv.DictReader(fh):
            name = row['name'].strip().title()
            try:
                weight = int(row['count'])
            except (ValueError, KeyError):
                weight = 1
            if name:
                last_names.append(name)
                last_weights.append(weight)

    _name_pool_cache.update({
        'male':   (male_names,   male_weights),
        'female': (female_names, female_weights),
        'last':   (last_names,   last_weights),
    })
    return _name_pool_cache


def random_crew_name(gender: str = None) -> str:
    """
    Return a random 'Firstname Lastname' drawn weighted by real-world frequency.

    *gender* can be 'male', 'female', or None (random mix).
    """
    pool = _load_name_pool()

    if gender is None:
        gender = random.choice(['male', 'female'])
    gender = gender.lower()
    if gender not in ('male', 'female'):
        raise ValueError(f"gender must be 'male', 'female', or None — got {gender!r}")

    first_names, first_weights = pool[gender]
    last_names,  last_weights  = pool['last']

    first = random.choices(first_names, weights=first_weights, k=1)[0]
    last  = random.choices(last_names,  weights=last_weights,  k=1)[0]
    return f"{first} {last}"


# ── Vessel pool ──────────────────────────────────────────────────────────────

# Maps CSV vessel sub-types to the game's vessel_type vocabulary
_VESSEL_TYPE_MAP = {
    'Tug':                  'towboat',
    'Tug (Towing/Pushing)': 'towboat',
    'Barge':                'barge',
    'Solid Cargo':          'barge',
    'Liquid Cargo':         'barge',
    'Canoe/Kayak':          'kayak',
    'Gondolas / pedalos':   'paddleboat',
    'Rowboat':              'paddleboat',
    'Sailboat (aux. motor)':'yacht',
    'Sailboat (sail only)': 'yacht',
    'Motorboat':            'yacht',
    'Recreational craft':   'yacht',
}

# Weights so the lock sees a realistic mix: lots of barges, some towboats, occasional others
_VESSEL_TYPE_WEIGHTS = {
    'barge':      40,
    'towboat':    25,
    'yacht':      20,
    'kayak':      10,
    'paddleboat':  5,
}

# Name prefixes per game vessel type
_VESSEL_NAME_PREFIXES = {
    'towboat':    ['MV', 'MV', 'MV', 'TB'],
    'barge':      ['', '', 'B-', 'DB-'],
    'yacht':      ['SY', 'MY', ''],
    'kayak':      [''],
    'paddleboat': [''],
}

_vessel_pool_cache: dict = {}


def _load_vessel_pool() -> dict:
    """Parse vessels.csv and return pools for ports and cargo descriptions."""
    if _vessel_pool_cache:
        return _vessel_pool_cache

    ports, cargos = set(), set()
    with open(_VESSELS_CSV, newline='', encoding='utf-8') as fh:
        for row in csv.DictReader(fh, delimiter=';'):
            for col in ('Port_Of_Departure_L2', 'Port_Of_Accident_L2'):
                p = row.get(col, '').strip()
                if p and p not in ('Unknown', 'NA', ''):
                    ports.add(p)
            c = row.get('Ship_Craft_Type_L3', '').strip()
            if c and c not in ('Other', 'Unknown', 'NA', ''):
                cargos.add(c)

    _vessel_pool_cache['ports']  = sorted(ports)
    _vessel_pool_cache['cargos'] = sorted(cargos)
    return _vessel_pool_cache


def random_ship_record() -> dict:
    """
    Return a dict ready to pass to ``db.add_ship()`` using data sampled from
    vessels.csv.  Vessel names are generated from the crew name pool so they
    read like real river boat names.
    """
    pool = _load_vessel_pool()
    name_pool = _load_name_pool()

    # Pick vessel type weighted toward realistic lock traffic
    types   = list(_VESSEL_TYPE_WEIGHTS.keys())
    weights = [_VESSEL_TYPE_WEIGHTS[t] for t in types]
    vessel_type = random.choices(types, weights=weights, k=1)[0]

    # Build the vessel name
    prefix = random.choice(_VESSEL_NAME_PREFIXES[vessel_type])
    if vessel_type in ('barge',) and prefix in ('B-', 'DB-'):
        # Numbered barges
        suffix = str(random.randint(100, 9999))
    else:
        # Named vessels — pull a last name and titlecase it
        last_names, last_weights = name_pool['last']
        suffix = random.choices(last_names, weights=last_weights, k=1)[0]
        # Occasionally add a second word for flavour (e.g. "Prairie Star")
        if random.random() < 0.35:
            adjectives = [
                'Prairie', 'River', 'Delta', 'Gulf', 'Bayou', 'Cypress',
                'Cardinal', 'Bluff', 'Timber', 'Iron', 'Steel', 'Stone',
            ]
            suffix = random.choice(adjectives) + ' ' + suffix

    if not prefix:
        name = suffix
    elif prefix.endswith('-'):
        name = prefix + suffix          # B-7471, DB-3045
    else:
        name = f"{prefix} {suffix}"     # MV Prairie Star

    direction = random.choice(['upstream', 'downstream'])
    ports     = pool['ports']
    origin, destination = random.sample(ports, 2)

    cargo = None
    if vessel_type in ('barge', 'towboat'):
        cargo = random.choice(pool['cargos']) if pool['cargos'] else None

    return {
        'name':        name,
        'vessel_type': vessel_type,
        'direction':   direction,
        'origin':      origin,
        'destination': destination,
        'cargo':       cargo,
        'notes':       None,
    }


# ── Lock radio generation ─────────────────────────────────────────────────────

LOCK_RADIO_SYSTEM_PROMPT = """\
You write realistic VHF radio exchanges between vessels and a Mississippi River lock operator.
Follow real-world lockage protocol: the vessel hails the lock on channel 14 or 16,
requests lockage, operator confirms availability and gives approach/hold instructions,
vessel acknowledges and enters, operator gives clearance, vessel thanks and departs.
Keep each transmission short and clipped — real radio talk, no pleasantries.
Use proper callsign format. The lock operator's callsign is "Lock Twelve" (or the lock name given).
Return ONLY a JSON array. Each element must be an object with exactly three keys:
  "sender_type": "ship" or "operator"
  "sender_name": the callsign used (vessel name or lock name)
  "message": the radio transmission text
No markdown fences, no explanation — raw JSON array only."""


def generate_lock_radio_exchange(
    vessel_name: str,
    direction:   str,
    vessel_type: str  = 'vessel',
    lock_name:   str  = 'Lock Twelve',
    cargo:       str  = None,
) -> list[dict]:
    """
    Generate a realistic VHF lockage exchange for *vessel_name*.

    Returns a list of dicts: [{sender_type, sender_name, message}, …]
    """
    import json as _json

    client = _openai_client()

    cargo_clause  = f' carrying {cargo}' if cargo else ''
    bound_clause  = f'{"up" if direction == "upstream" else "down"}bound'
    user_prompt   = (
        f"Generate a realistic VHF radio lockage exchange.\n"
        f"Vessel: {vessel_name}, a {vessel_type}{cargo_clause}, {bound_clause}.\n"
        f"Lock: {lock_name}.\n"
        f"Write 6–10 transmissions covering: initial hail, operator response, "
        f"approach/hold instructions, entry clearance, and departure."
    )

    logger.debug("chat prompt [lock_radio]:\n  system: %s\n  user: %s",
                 LOCK_RADIO_SYSTEM_PROMPT, user_prompt)

    response = client.chat.completions.create(
        model='gpt-4o',
        messages=[
            {'role': 'system', 'content': LOCK_RADIO_SYSTEM_PROMPT},
            {'role': 'user',   'content': user_prompt},
        ],
        temperature=0.7,
    )

    raw = response.choices[0].message.content.strip()
    logger.debug("lock_radio raw response: %s", raw)

    try:
        messages = _json.loads(raw)
    except _json.JSONDecodeError:
        # Strip accidental markdown fences and retry
        clean = raw.strip('`').lstrip('json').strip()
        messages = _json.loads(clean)

    # Normalise keys
    result = []
    for m in messages:
        result.append({
            'sender_type': str(m.get('sender_type', 'ship')).lower(),
            'sender_name': str(m.get('sender_name', vessel_name)),
            'message':     str(m.get('message', '')),
        })
    return result


def gen_lock_radio(
    db,
    *,
    vessel_name: str  = None,
    lock_name:   str  = 'Lock Twelve',
    count:       int  = 1,
) -> list[dict]:
    """
    Generate lock radio exchanges and save them to the lock_radio table.

    If *vessel_name* is given, generate one exchange for that ship.
    Otherwise pick *count* random ships from the ships table.

    Returns a list of {vessel_name, thread_id, messages} dicts.
    """
    if vessel_name:
        ship_rows = [{'name': vessel_name, 'vessel_type': 'vessel',
                      'direction': 'downstream', 'cargo': None}]
    else:
        all_ships = db.ships(limit=10_000)
        if not all_ships:
            logger.warning("No ships in DB — add some with gen-ships first.")
            return []
        ship_rows = random.sample(all_ships, min(count, len(all_ships)))

    results = []
    for ship in ship_rows:
        name   = ship.get('name') or 'Unknown Vessel'
        vtype  = ship.get('vessel_type') or 'vessel'
        dirn   = ship.get('direction') or 'downstream'
        cargo  = ship.get('cargo')

        exchanges = generate_lock_radio_exchange(
            name, dirn, vessel_type=vtype,
            lock_name=lock_name, cargo=cargo,
        )

        thread_id = db.new_radio_thread()
        for msg in exchanges:
            db.add_lock_radio_message(
                msg['sender_type'],
                msg['sender_name'],
                msg['message'],
                thread_id=thread_id,
                vessel_name=name,
                direction=dirn,
            )

        results.append({
            'vessel_name': name,
            'thread_id':   thread_id,
            'messages':    exchanges,
        })
        logger.info("Saved %d messages for %s (thread %d)",
                    len(exchanges), name, thread_id)

    return results


# ── Captain generation ───────────────────────────────────────────────────────

def gen_captains(db) -> list[dict]:
    """
    For every ship in the ships table that has no captain assigned in crew,
    generate a random name and create a crew record with role='captain'.

    Returns a list of the newly created crew dicts.
    """
    ships = db.ships(limit=10_000)
    if not ships:
        return []

    # Build a set of vessel names that already have a captain
    existing_captains = {
        c['vessel_name']
        for c in db.crew_list(role='captain')
        if c['vessel_name']
    }

    created = []
    for ship in ships:
        vessel_name = ship['name']
        if not vessel_name or vessel_name in existing_captains:
            continue

        name = random_crew_name()
        row_id = db.add_crew(name, role='captain', vessel_name=vessel_name)
        record = {'id': row_id, 'name': name, 'role': 'captain',
                  'vessel_name': vessel_name}
        created.append(record)
        existing_captains.add(vessel_name)   # guard against duplicate ship names

    return created


# ── Crew dialog ───────────────────────────────────────────────────────────────

DIALOG_SYSTEM_PROMPT = """\
You are a writer for a narrative simulation game set on the Upper Mississippi River.
Players manage a lock and dam, working alongside a small towboat crew.
Write short, grounded, in-character dialog lines — the kind a real riverman would say.
Keep each line under two sentences. No fluff, no emojis. River slang is welcome."""

DIALOG_CONTEXT_HINTS = {
    'barge_connected':   'the crew just finished connecting a barge',
    'barge_disconnected':'the crew just disconnected a barge',
    'lock_entering':     'a vessel is entering the lock chamber',
    'lock_exiting':      'a vessel is exiting the lock chamber',
    'gate_open':         'a lock gate has been opened',
    'gate_close':        'a lock gate has been closed',
    'engine_trouble':    'the engine is running hot or having issues',
    'bilge_alarm':       'the bilge alarm has triggered',
    'shift_start':       'the crew member is starting their shift',
    'shift_end':         'the crew member is ending their shift',
    'idle':              'things are quiet, nothing urgent happening',
}


def generate_crew_dialog(
    name: str,
    role: str,
    context: str,
    stage_id: str = None,
    count: int = 4,
) -> list[str]:
    """Return *count* dialog lines for a crew member in the given context."""
    client = _openai_client()
    hint = DIALOG_CONTEXT_HINTS.get(context, context)
    user_prompt = (
        f"Character: {name}, {role} on a Mississippi River towboat.\n"
        f"Situation: {hint}.\n"
        f"Write {count} distinct one-or-two-sentence lines this character might say. "
        f"Return only the lines, one per row, no numbering."
    )
    logger.debug("chat prompt [dialog]:\n  system: %s\n  user: %s",
                 DIALOG_SYSTEM_PROMPT, user_prompt)
    response = client.chat.completions.create(
        model='gpt-4o',
        messages=[
            {'role': 'system', 'content': DIALOG_SYSTEM_PROMPT},
            {'role': 'user',   'content': user_prompt},
        ],
        temperature=0.85,
    )
    raw = response.choices[0].message.content.strip()
    lines = [ln.strip().strip('"') for ln in raw.splitlines() if ln.strip()]
    return lines[:count]


def save_crew_dialog(db, name: str, role: str, context: str, stage_id: str, lines: list[str]):
    """Look up (or create) the crew member, then insert each line as a crew_message."""
    matches = [c for c in db.crew_list() if c['name'].lower() == name.lower()]
    crew_id = matches[0]['id'] if matches else None

    ids = []
    for line in lines:
        row_id = db.add_crew_message(
            name,
            crew_id=crew_id,
            role=role,
            context=context,
            stage_id=stage_id,
        )
        ids.append(row_id)
        logger.info("  [crew_message %d] %s", row_id, line)
    return ids


# ── Crew profile ──────────────────────────────────────────────────────────────

PROFILE_SYSTEM_PROMPT = """\
You are writing short crew bios for a narrative river simulation game.
Each bio should be 2-3 sentences: where they're from, how long they've worked the river,
and one defining personality trait. Plain prose, no bullet points."""


def generate_crew_profile(name: str, role: str, vessel: str = None) -> dict:
    """Return a dict with 'bio' and 'notes' keys for the crew member."""
    client = _openai_client()
    vessel_clause = f" aboard {vessel}" if vessel else ""
    user_prompt = (
        f"Write a short bio for {name}, a {role}{vessel_clause} "
        f"on the Upper Mississippi River. Then add one sentence of GM notes "
        f"(personality quirk or secret the player might uncover). "
        f"Format as two paragraphs: first the bio, then 'GM: ' followed by the note."
    )
    logger.debug("chat prompt [profile]:\n  system: %s\n  user: %s",
                 PROFILE_SYSTEM_PROMPT, user_prompt)
    response = client.chat.completions.create(
        model='gpt-4o',
        messages=[
            {'role': 'system', 'content': PROFILE_SYSTEM_PROMPT},
            {'role': 'user',   'content': user_prompt},
        ],
        temperature=0.75,
    )
    raw = response.choices[0].message.content.strip()
    bio, _, gm_note = raw.partition('\nGM:')
    return {
        'bio':   bio.strip(),
        'notes': gm_note.strip() if gm_note else None,
    }


# ── Image generation ──────────────────────────────────────────────────────────

IMAGE_OUTPUT_DIR = os.path.join('assets', 'generated')


def generate_image(
    prompt: str,
    category: str = None,
    campaign_id: str = None,
    size: str = '1024x1024',
    out_dir: str = IMAGE_OUTPUT_DIR,
) -> str:
    """
    Generate an image via DALL-E 3, save it as a PNG, and return the file path.
    The file is named from a slug of the prompt.
    """
    client = _openai_client()
    logger.debug("image prompt [generate_image]  size=%s:\n%s", size, prompt)
    response = client.images.generate(
        model='dall-e-3',
        prompt=prompt,
        size=size,
        response_format='b64_json',
        n=1,
    )
    image_data = response.data[0].b64_json
    revised_prompt = getattr(response.data[0], 'revised_prompt', prompt)
    logger.debug("revised prompt: %s", revised_prompt)

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    slug = ''.join(c if c.isalnum() else '_' for c in prompt.lower())[:60]
    filename = f"{slug}.png"
    filepath = os.path.join(out_dir, filename)

    with open(filepath, 'wb') as fh:
        fh.write(base64.b64decode(image_data))

    logger.info("Image saved: %s", filepath)
    logger.info("Revised prompt: %s", revised_prompt)
    return filepath, filename


def register_generated_image(db, filepath: str, filename: str, prompt: str,
                              category: str, campaign_id: str):
    """Register the generated PNG in the art_assets table."""
    try:
        from PIL import Image
        with Image.open(filepath) as im:
            width, height = im.size
    except ImportError:
        width = height = None

    row_id = db.register_asset(
        filename,
        category=category,
        description=prompt[:200],
        campaign_id=campaign_id,
        width=width,
        height=height,
    )
    logger.info("Registered art_asset id=%d  filename=%s", row_id, filename)
    return row_id


# ── Crew portraits ───────────────────────────────────────────────────────────

PORTRAIT_OUTPUT_DIR = os.path.join('assets', 'generated', 'portraits')
PORTRAIT_SIZE_PX    = 288   # 3 inches at 96 dpi


def _infer_gender(first_name: str) -> str:
    """
    Return 'male' or 'female' by comparing the name's frequency in each gender
    pool.  Falls back to 'male' if the name isn't found.
    """
    pool = _load_name_pool()
    name = first_name.strip().title()

    male_names,   male_weights   = pool['male']
    female_names, female_weights = pool['female']

    male_count   = sum(w for n, w in zip(male_names,   male_weights)   if n == name)
    female_count = sum(w for n, w in zip(female_names, female_weights) if n == name)

    if female_count > male_count:
        return 'female'
    return 'male'


def _portrait_prompt(member: dict) -> str:
    """Build a DALL-E portrait prompt from a crew record."""
    name        = member.get('name', 'unknown')
    role        = member.get('role') or 'river worker'
    vessel      = member.get('vessel_name')
    bio         = member.get('bio') or ''
    first_name  = name.split()[0]
    gender      = _infer_gender(first_name)

    # Pull the first ~120 characters of the bio to add visual flavour
    bio_hint = ''
    if bio:
        clip = bio[:120].strip()
        if len(bio) > 120 and ' ' in clip:
            clip = clip[:clip.rfind(' ')]
        bio_hint = f' {clip}…' if len(bio) > len(clip) else f' {clip}'

    vessel_clause = f' aboard {vessel}' if vessel else ' on the Mississippi River'

    if gender == 'male':
        style = (
            "Painted in 90s style video game graphics."
            "Muted river-town color palette. Neutral dark background."

        )
    else:
        style = (
            "Painted in 90s style video game graphics."
            "Strong jaw, calm unflinching eyes, stoic expression. "
            "Weathered but commanding. Hard-earned confidence. "
            "Muted river-town color palette. Neutral dark background. "
            "The kind of person who has seen everything and is not afraid."
        )

    return (
        f"Close-up portrait of {name}, a {role}{vessel_clause}.{bio_hint} "
        f"{style} "
        f"No text, no watermarks."
    )


def gen_crew_portraits(db, *, crew_id: int = None) -> list[dict]:
    """
    Generate a portrait for every crew member that doesn't already have one.

    Images are downloaded at 1024x1024 then resized to PORTRAIT_SIZE_PX × PORTRAIT_SIZE_PX
    (3 × 3 inches at 96 dpi) before saving.  Requires Pillow (pip install Pillow).

    Each portrait is registered in art_assets with category='character' and
    tags containing 'crew_id:<n>' for later lookup.

    Pass *crew_id* to process one member instead of the whole table.
    Returns a list of dicts: {crew_id, name, filename, filepath}.
    """
    try:
        from PIL import Image as _PILImage
    except ImportError:
        sys.exit("Pillow is required for portrait generation.  Run: pip install Pillow")

    if crew_id is not None:
        member = db.get_crew(crew_id)
        if not member:
            logger.warning("No crew record found for id=%d", crew_id)
            return []
        candidates = [member]
    else:
        candidates = db.crew_list()

    # Build the set of crew_ids that already have a portrait
    existing_ids = {
        tag.strip().split(':')[1]
        for asset in db.art_assets(category='character')
        for tag in (asset.get('tags') or '').split(',')
        if tag.strip().startswith('crew_id:')
    }

    results = []
    client  = _openai_client()
    Path(PORTRAIT_OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    for member in candidates:
        cid = str(member['id'])
        if cid in existing_ids:
            logger.info("Skipping %s — portrait already exists", member['name'])
            continue

        prompt   = _portrait_prompt(member)
        filename = f"crew_{cid}_{member['name'].lower().replace(' ', '_')}.png"
        filepath = os.path.join(PORTRAIT_OUTPUT_DIR, filename)

        logger.info("Generating portrait for %s (crew %s)…", member['name'], cid)
        logger.debug("image prompt [portrait  crew %s]:\n%s", cid, prompt)

        response = client.images.generate(
            model='dall-e-3',
            prompt=prompt,
            size='1024x1024',
            response_format='b64_json',
            n=1,
        )
        image_data = response.data[0].b64_json

        # Decode, resize to 3×3 in, save
        import io
        raw = _PILImage.open(io.BytesIO(base64.b64decode(image_data)))
        resized = raw.resize((PORTRAIT_SIZE_PX, PORTRAIT_SIZE_PX), _PILImage.LANCZOS)
        resized.save(filepath)

        db.register_asset(
            filename,
            category='character',
            description=f"Portrait of {member['name']}, {member.get('role') or 'crew'}",
            tags=f"portrait,crew_id:{cid}",
            width=PORTRAIT_SIZE_PX,
            height=PORTRAIT_SIZE_PX,
        )

        logger.info("  Saved %dx%d px → %s", PORTRAIT_SIZE_PX, PORTRAIT_SIZE_PX, filepath)
        results.append({'crew_id': member['id'], 'name': member['name'],
                        'filename': filename, 'filepath': filepath})

    return results


# ── Asset browser UI ─────────────────────────────────────────────────────────

WIN_W, WIN_H   = 900, 620
PANEL_W        = 320          # left info panel width
PREVIEW_X      = PANEL_W + 10
PREVIEW_Y      = 10
PREVIEW_SIZE   = WIN_H - 20   # square preview area
BG_COLOR       = (18,  18,  22)
PANEL_BG       = (28,  28,  34)
ACCENT         = (80, 160, 220)
TEXT_COLOR     = (210, 210, 215)
DIM_COLOR      = (110, 110, 120)
REGEN_COLOR    = (200,  80,  80)
REGEN_ACTIVE   = (255, 130,  60)


def browse_assets_ui(db):
    """
    Pygame window for browsing and regenerating art_assets.

    Controls
    --------
    ←  /  →   previous / next asset
    ↑  /  ↓   jump 10 back / forward
    R         regenerate current image via DALL-E (saves & updates DB)
    F         filter: cycle through categories  (all → background → character → …)
    ESC / Q   quit
    """
    try:
        import pygame
    except ImportError:
        sys.exit("pygame is required for the asset browser.  Run: pip install pygame")

    try:
        from PIL import Image as _PIL
        _HAS_PIL = True
    except ImportError:
        _HAS_PIL = False

    pygame.init()
    screen = pygame.display.set_mode((WIN_W, WIN_H))
    pygame.display.set_caption("Asset Browser — Albatross")
    clock  = pygame.time.Clock()

    font_lg  = pygame.font.SysFont('monospace', 15, bold=True)
    font_sm  = pygame.font.SysFont('monospace', 12)
    font_xs  = pygame.font.SysFont('monospace', 11)

    # ── state ─────────────────────────────────────────────────────────────────
    def _crew_id_from_asset(asset):
        for tag in (asset.get('tags') or '').split(','):
            tag = tag.strip()
            if tag.startswith('crew_id:'):
                try:
                    return int(tag.split(':')[1])
                except (ValueError, IndexError):
                    pass
        return None

    raw_assets = db.art_assets()
    # Sort: portraits first (by crew_id numerically), then others (category/filename)
    raw_assets.sort(key=lambda a: (
        (0, _crew_id_from_asset(a) or 0, '')
        if _crew_id_from_asset(a) is not None
        else (1, 0, f"{a.get('category','')}/{a.get('filename','')}")
    ))
    all_assets   = raw_assets
    categories   = ['all'] + sorted({a['category'] for a in all_assets if a['category']})
    cat_idx      = 0
    assets       = all_assets[:]
    idx          = 0
    cached_surf  = None   # the currently displayed pygame.Surface
    regen_state  = None   # None | 'working' | 'done' | 'error'
    status_msg   = ''

    # Crew-ID jump input state
    jump_mode    = False   # True while user is typing a crew id
    jump_buf     = ''      # digits typed so far

    def filtered():
        cat = categories[cat_idx]
        return all_assets if cat == 'all' else [a for a in all_assets if a['category'] == cat]

    def jump_to_crew(crew_id_str):
        """Move idx to the first asset whose crew_id tag matches."""
        try:
            target = int(crew_id_str)
        except ValueError:
            return f'invalid id: {crew_id_str!r}'
        for i, a in enumerate(assets):
            if _crew_id_from_asset(a) == target:
                return i
        return f'crew id {target} not found'

    def load_surface(asset):
        """Return a pygame.Surface for *asset*, or None if file not found."""
        # Try several candidate paths
        candidates = [
            asset['filename'],
            os.path.join(IMAGE_OUTPUT_DIR, asset['filename']),
            os.path.join(PORTRAIT_OUTPUT_DIR, asset['filename']),
        ]
        for path in candidates:
            if os.path.isfile(path):
                try:
                    return pygame.image.load(path).convert_alpha()
                except Exception:
                    return None
        return None

    def wrap_text(text, font, max_w):
        """Split *text* into lines that fit within *max_w* pixels."""
        words, lines, line = text.split(), [], ''
        for word in words:
            test = f'{line} {word}'.strip()
            if font.size(test)[0] <= max_w:
                line = test
            else:
                if line:
                    lines.append(line)
                line = word
        if line:
            lines.append(line)
        return lines

    def draw_panel(asset, regen_state, status_msg):
        panel = pygame.Rect(0, 0, PANEL_W, WIN_H)
        pygame.draw.rect(screen, PANEL_BG, panel)
        pygame.draw.line(screen, ACCENT, (PANEL_W, 0), (PANEL_W, WIN_H), 1)

        y  = 12
        mx = PANEL_W - 12

        def row(label, value, vc=TEXT_COLOR):
            nonlocal y
            lbl = font_sm.render(label, True, DIM_COLOR)
            screen.blit(lbl, (10, y))
            y += 16
            if value:
                for ln in wrap_text(str(value), font_xs, mx):
                    surf = font_xs.render(ln, True, vc)
                    screen.blit(surf, (14, y))
                    y += 14
            y += 4

        # index badge
        badge = font_lg.render(f"{idx + 1} / {len(assets)}", True, ACCENT)
        screen.blit(badge, (10, y));  y += 22

        row('filename',    asset['filename'])
        row('category',    asset['category'])
        row('description', asset['description'])
        row('tags',        asset['tags'])
        cid = _crew_id_from_asset(asset)
        row('crew id',     str(cid) if cid is not None else '—')
        row('size',
            f"{asset['width']}×{asset['height']}" if asset['width'] else '—')

        # filter indicator
        y = WIN_H - 130
        cat_txt = font_sm.render(
            f"filter: {categories[cat_idx]}  [F]", True, ACCENT)
        screen.blit(cat_txt, (10, y));  y += 20

        # crew-id jump box
        if jump_mode:
            box_col = (255, 220, 80)
            prompt  = f'crew id: {jump_buf}_'
            pygame.draw.rect(screen, (40, 40, 20), (8, y, PANEL_W - 16, 18))
            pygame.draw.rect(screen, box_col,      (8, y, PANEL_W - 16, 18), 1)
            screen.blit(font_sm.render(prompt, True, box_col), (12, y + 2))
        else:
            screen.blit(font_sm.render('[G] go to crew id', True, DIM_COLOR), (10, y))
        y += 22

        # regen button hint
        rcolor = REGEN_ACTIVE if regen_state == 'working' else REGEN_COLOR
        label  = 'regenerating…' if regen_state == 'working' else '[R] regenerate'
        screen.blit(font_sm.render(label, True, rcolor), (10, y));  y += 20

        # status
        if status_msg:
            for ln in wrap_text(status_msg, font_xs, mx):
                screen.blit(font_xs.render(ln, True, DIM_COLOR), (10, y))
                y += 14

        # nav hint
        screen.blit(font_xs.render('← →  navigate   ESC quit', True, DIM_COLOR),
                    (10, WIN_H - 18))

    def draw_preview(surf):
        preview_rect = pygame.Rect(PREVIEW_X, PREVIEW_Y,
                                   WIN_W - PREVIEW_X - 10, WIN_H - 20)
        pygame.draw.rect(screen, PANEL_BG, preview_rect)
        if surf is None:
            msg = font_sm.render('no image on disk', True, DIM_COLOR)
            screen.blit(msg, msg.get_rect(center=preview_rect.center))
        else:
            # Scale to fit while keeping aspect ratio
            sw, sh  = surf.get_size()
            pw, ph  = preview_rect.size
            scale   = min(pw / sw, ph / sh)
            nw, nh  = int(sw * scale), int(sh * scale)
            scaled  = pygame.transform.smoothscale(surf, (nw, nh))
            cx = preview_rect.x + (pw - nw) // 2
            cy = preview_rect.y + (ph - nh) // 2
            screen.blit(scaled, (cx, cy))

    # ── initial load ──────────────────────────────────────────────────────────
    assets      = filtered()
    cached_surf = load_surface(assets[idx]) if assets else None

    running = True
    while running:
        clock.tick(30)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                # ── Crew-ID jump input mode ────────────────────────────────────
                if jump_mode:
                    if event.key == pygame.K_ESCAPE:
                        jump_mode = False
                        jump_buf  = ''
                        status_msg = ''
                    elif event.key == pygame.K_RETURN and jump_buf:
                        result = jump_to_crew(jump_buf)
                        jump_mode = False
                        jump_buf  = ''
                        if isinstance(result, int):
                            idx = result
                            cached_surf = load_surface(assets[idx])
                            regen_state = None
                            status_msg  = ''
                        else:
                            status_msg = result
                    elif event.key == pygame.K_BACKSPACE:
                        jump_buf = jump_buf[:-1]
                    elif event.unicode.isdigit():
                        jump_buf += event.unicode
                    continue   # swallow all other keys while in jump mode

                # ── Normal navigation ─────────────────────────────────────────
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False

                elif event.key == pygame.K_g:
                    jump_mode  = True
                    jump_buf   = ''
                    status_msg = ''

                elif event.key == pygame.K_RIGHT and assets:
                    idx = (idx + 1) % len(assets)
                    cached_surf = load_surface(assets[idx])
                    regen_state = status_msg = None

                elif event.key == pygame.K_LEFT and assets:
                    idx = (idx - 1) % len(assets)
                    cached_surf = load_surface(assets[idx])
                    regen_state = status_msg = None

                elif event.key == pygame.K_DOWN and assets:
                    idx = min(idx + 10, len(assets) - 1)
                    cached_surf = load_surface(assets[idx])
                    regen_state = status_msg = None

                elif event.key == pygame.K_UP and assets:
                    idx = max(idx - 10, 0)
                    cached_surf = load_surface(assets[idx])
                    regen_state = status_msg = None

                elif event.key == pygame.K_f:
                    cat_idx = (cat_idx + 1) % len(categories)
                    assets  = filtered()
                    idx     = 0
                    cached_surf = load_surface(assets[idx]) if assets else None
                    regen_state = status_msg = None

                elif event.key == pygame.K_r and assets and regen_state != 'working':
                    asset = assets[idx]
                    is_portrait = (asset.get('category') == 'character' or
                                   'portrait' in (asset.get('tags') or ''))

                    # For crew portraits use the same prompt builder as gen-portraits
                    prompt = None
                    if is_portrait:
                        crew_id_tag = next(
                            (t for t in (asset.get('tags') or '').split(',')
                             if t.strip().startswith('crew_id:')),
                            None,
                        )
                        if crew_id_tag:
                            try:
                                cid = int(crew_id_tag.strip().split(':')[1])
                                member = db.get_crew(cid)
                                if member:
                                    prompt = _portrait_prompt(member)
                            except (ValueError, IndexError):
                                pass
                    if not prompt:
                        prompt = asset.get('description') or asset['filename']

                    regen_state = 'working'
                    status_msg  = 'Calling DALL-E…'
                    screen.fill(BG_COLOR)
                    draw_panel(asset, regen_state, status_msg)
                    draw_preview(cached_surf)
                    pygame.display.flip()

                    try:
                        # Determine output dir from existing path
                        out_dir = PORTRAIT_OUTPUT_DIR if is_portrait else IMAGE_OUTPUT_DIR
                        for candidate in (asset['filename'],
                                          os.path.join(IMAGE_OUTPUT_DIR, asset['filename']),
                                          os.path.join(PORTRAIT_OUTPUT_DIR, asset['filename'])):
                            if os.path.isfile(candidate):
                                out_dir = os.path.dirname(os.path.abspath(candidate))
                                break

                        client = _openai_client()
                        logger.debug("image prompt [browser regen]:\n%s", prompt)
                        response = client.images.generate(
                            model='dall-e-3',
                            prompt=prompt,
                            size='1024x1024',
                            response_format='b64_json',
                            n=1,
                        )
                        raw_bytes = base64.b64decode(response.data[0].b64_json)

                        filepath = os.path.join(out_dir, asset['filename'])
                        if is_portrait and _HAS_PIL:
                            import io
                            from PIL import Image as _PILB
                            img = _PILB.open(io.BytesIO(raw_bytes))
                            img.resize((PORTRAIT_SIZE_PX, PORTRAIT_SIZE_PX),
                                       _PILB.LANCZOS).save(filepath)
                        else:
                            Path(out_dir).mkdir(parents=True, exist_ok=True)
                            with open(filepath, 'wb') as fh:
                                fh.write(raw_bytes)

                        # Update DB dimensions
                        if _HAS_PIL:
                            from PIL import Image as _PILC
                            with _PILC.open(filepath) as im:
                                w, h = im.size
                            db.register_asset(asset['filename'],
                                              category=asset.get('category'),
                                              description=asset.get('description'),
                                              tags=asset.get('tags'),
                                              campaign_id=asset.get('campaign_id'),
                                              width=w, height=h)

                        cached_surf = load_surface(asset)
                        regen_state = 'done'
                        status_msg  = 'Regenerated.'
                    except Exception as exc:
                        regen_state = 'error'
                        status_msg  = f'Error: {exc}'

        screen.fill(BG_COLOR)
        if assets:
            draw_panel(assets[idx], regen_state, status_msg)
            draw_preview(cached_surf)
        else:
            msg = font_lg.render('No assets found.', True, DIM_COLOR)
            screen.blit(msg, msg.get_rect(center=screen.get_rect().center))

        pygame.display.flip()

    pygame.quit()


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(
        description='Asset manager — generate crew dialog and images via OpenAI.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument('--db', default=db_module.DB_PATH,
                   help='Path to the assets SQLite database (default: %(default)s)')
    p.add_argument('--debug', action='store_true',
                   help='Enable DEBUG logging (prints all prompts sent to OpenAI)')

    sub = p.add_subparsers(dest='cmd', metavar='COMMAND')

    # -- gen-radio
    gr = sub.add_parser('gen-radio',
                        help='Generate VHF lock radio exchanges and store in lock_radio')
    gr.add_argument('--vessel',    default=None,
                    help='Generate for this specific vessel name (skips DB lookup)')
    gr.add_argument('--lock-name', default='Lock Twelve',
                    help='Lock callsign used by the operator (default: %(default)s)')
    gr.add_argument('--count',     type=int, default=1,
                    help='Number of random ships to generate exchanges for (default: 1)')
    gr.add_argument('--all',       action='store_true',
                    help='Create captains for all ships then generate radio traffic for '
                         'every ship that does not already have an exchange')
    gr.add_argument('--dry-run',   action='store_true',
                    help='Print the exchange without saving to DB')

    # -- crew-name
    cn = sub.add_parser('crew-name', help='Generate random crew names from census data')
    cn.add_argument('--count',  type=int, default=1, help='How many names to generate')
    cn.add_argument('--gender', choices=['male', 'female'], default=None,
                    help='Restrict first names to one gender (default: random mix)')
    cn.add_argument('--save',   action='store_true',
                    help='Add each generated name to the crew table with no role')

    # -- crew-dialog
    cd = sub.add_parser('crew-dialog', help='Generate dialog lines for a crew member')
    cd.add_argument('--name',     required=True, help='Crew member name')
    cd.add_argument('--role',     required=True, help='Role (deckhand, engineer, captain…)')
    cd.add_argument('--context',  required=True,
                    help='Trigger context. Known: ' + ', '.join(DIALOG_CONTEXT_HINTS))
    cd.add_argument('--stage-id', default=None,
                    help='Game stage (operator/deckhand/engineer/captain)')
    cd.add_argument('--count',    type=int, default=4, help='Number of lines to generate')
    cd.add_argument('--dry-run',  action='store_true', help='Print lines, do not save to DB')

    # -- crew-profile
    cp = sub.add_parser(
        'crew-profile',
        help='Generate bio/notes for crew members that are missing them. '
             'Pass --name to target one specific member, otherwise all incomplete crew are processed.',
    )
    cp.add_argument('--name',    default=None, help='Target a specific crew member by name')
    cp.add_argument('--role',    default=None, help='Role override (used when creating a new record)')
    cp.add_argument('--vessel',  default=None, help='Vessel name override')
    cp.add_argument('--dry-run', action='store_true', help='Print results without saving')

    # -- image
    img = sub.add_parser('image', help='Generate an image with DALL-E 3')
    img.add_argument('--prompt',      required=True)
    img.add_argument('--category',    default=None,
                     help='Art category (background/character/ui/boat/environment)')
    img.add_argument('--campaign-id', default=None)
    img.add_argument('--size',        default='1024x1024',
                     choices=['1024x1024', '1792x1024', '1024x1792'])
    img.add_argument('--out-dir',     default=IMAGE_OUTPUT_DIR)
    img.add_argument('--dry-run',     action='store_true',
                     help='Print the prompt, do not call the API')

    # -- browse
    sub.add_parser('browse', help='Open the art_assets browser UI')

    # -- gen-portraits
    gp = sub.add_parser('gen-portraits',
                        help='Generate a portrait image for every crew member without one')
    gp.add_argument('--crew-id', type=int, default=None,
                    help='Only generate a portrait for this crew id')
    gp.add_argument('--dry-run', action='store_true',
                    help='Print prompts without calling the API')

    # -- gen-captains
    sub.add_parser('gen-captains',
                   help='Create a captain crew record for every ship that lacks one')

    # -- gen-ships
    gs = sub.add_parser('gen-ships', help='Generate random ship records from vessels.csv')
    gs.add_argument('--count',  type=int, default=5, help='How many ships to generate')
    gs.add_argument('--type',   dest='vessel_type', default=None,
                    choices=['towboat', 'barge', 'yacht', 'kayak', 'paddleboat'],
                    help='Force a specific vessel type')
    gs.add_argument('--save',   action='store_true', help='Insert records into the ships table')

    # -- summary
    sub.add_parser('summary', help='Print row counts for each DB table')

    # -- audit
    sub.add_parser('audit',
                   help='Report content gaps: ships without crew, crew without '
                        'portraits, captains without radio, crew without messages')

    return p


def audit_gaps(db) -> dict:
    """
    Scan the database for common content gaps and return a report dict.

    Checks:
      ships_no_crew       — ships with no crew member assigned to them
      crew_no_portrait    — crew with no art_asset tagged crew_id:<n>, or whose
                            portrait file is missing from disk
      crew_no_radio       — crew (captains) whose vessel has no lock_radio messages
      crew_no_messages    — crew with no crew_messages rows at all

    Each key maps to a list of dicts describing the affected records.
    """
    portrait_dir = PORTRAIT_OUTPUT_DIR
    all_ships  = db.ships(limit=10_000)
    all_crew   = db.crew_list()
    all_assets = db.art_assets(category='character')

    # Index crew by vessel_name for fast lookup
    crew_by_vessel: dict[str, list[dict]] = {}
    for c in all_crew:
        vn = c.get('vessel_name')
        if vn:
            crew_by_vessel.setdefault(vn, []).append(c)

    # Index art_assets by the crew_id tag they carry
    asset_by_crew_id: dict[int, dict] = {}
    for a in all_assets:
        for tag in (a.get('tags') or '').split(','):
            tag = tag.strip()
            if tag.startswith('crew_id:'):
                try:
                    cid = int(tag.split(':')[1])
                    asset_by_crew_id[cid] = a
                except ValueError:
                    pass

    # Vessels that have at least one lock_radio message
    radio_vessels: set[str] = {
        m['vessel_name']
        for m in db.lock_radio_messages(limit=100_000)
        if m.get('vessel_name')
    }

    # crew_ids that have at least one crew_message
    crew_ids_with_messages: set[int] = {
        m['crew_id']
        for m in db._rows(
            "SELECT DISTINCT crew_id FROM crew_messages WHERE crew_id IS NOT NULL"
        )
    }

    # ── 1. Ships with no crew ─────────────────────────────────────────────────
    ships_no_crew = [
        {'id': s['id'], 'name': s['name'],
         'vessel_type': s.get('vessel_type'), 'direction': s.get('direction')}
        for s in all_ships
        if s.get('name') and s['name'] not in crew_by_vessel
    ]

    # ── 2. Crew with no portrait (asset missing or file absent) ───────────────
    crew_no_portrait = []
    for c in all_crew:
        cid = c['id']
        asset = asset_by_crew_id.get(cid)
        if asset is None:
            crew_no_portrait.append({
                'crew_id': cid, 'name': c['name'], 'role': c.get('role'),
                'vessel_name': c.get('vessel_name'),
                'reason': 'no art_asset tagged crew_id:{}'.format(cid),
            })
        else:
            filepath = os.path.join(portrait_dir, asset['filename'])
            if not os.path.exists(filepath):
                crew_no_portrait.append({
                    'crew_id': cid, 'name': c['name'], 'role': c.get('role'),
                    'vessel_name': c.get('vessel_name'),
                    'reason': 'asset registered ({}) but file missing'.format(asset['filename']),
                })

    # ── 3. Captains whose vessel has no lock_radio messages ───────────────────
    crew_no_radio = [
        {'crew_id': c['id'], 'name': c['name'],
         'vessel_name': c.get('vessel_name')}
        for c in all_crew
        if c.get('role') == 'captain'
        and c.get('vessel_name')
        and c['vessel_name'] not in radio_vessels
    ]

    # ── 4. Crew with no crew_messages at all ──────────────────────────────────
    crew_no_messages = [
        {'crew_id': c['id'], 'name': c['name'], 'role': c.get('role'),
         'vessel_name': c.get('vessel_name')}
        for c in all_crew
        if c['id'] not in crew_ids_with_messages
    ]

    return {
        'ships_no_crew':    ships_no_crew,
        'crew_no_portrait': crew_no_portrait,
        'crew_no_radio':    crew_no_radio,
        'crew_no_messages': crew_no_messages,
    }


def _print_audit(report: dict):
    """Pretty-print an audit_gaps() report to stdout."""
    sections = [
        ('ships_no_crew',
         'Ships with no crew assigned',
         lambda r: f"  ship {r['id']:>4}  {r['name']:<30}  {r['vessel_type'] or '?':<12}  {r['direction'] or '?'}"),
        ('crew_no_portrait',
         'Crew with no portrait (asset missing or file absent)',
         lambda r: f"  crew {r['crew_id']:>4}  {r['name']:<28}  {r['role'] or '?':<10}  vessel={r['vessel_name'] or '—'}  [{r['reason']}]"),
        ('crew_no_radio',
         'Captains whose vessel has no lock_radio messages',
         lambda r: f"  crew {r['crew_id']:>4}  {r['name']:<28}  vessel={r['vessel_name'] or '—'}"),
        ('crew_no_messages',
         'Crew with no crew_messages at all',
         lambda r: f"  crew {r['crew_id']:>4}  {r['name']:<28}  {r['role'] or '?':<10}  vessel={r['vessel_name'] or '—'}"),
    ]
    any_gap = False
    for key, title, fmt in sections:
        rows = report[key]
        status = f"({len(rows)} gap{'s' if len(rows) != 1 else ''})" if rows else "(OK)"
        print(f"\n── {title} {status} ──")
        for r in rows:
            print(fmt(r))
        if rows:
            any_gap = True
    if not any_gap:
        print("\nAll checks passed — no gaps found.")


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.cmd is None:
        parser.print_help()
        return

    db = db_module.GameDatabase(args.db)

    try:
        if args.cmd == 'gen-radio':
            if args.dry_run:
                vessel   = args.vessel or 'MV Example'
                print("Dry run — would send:\n")
                print(f"  system: {LOCK_RADIO_SYSTEM_PROMPT}\n")
                print(
                    f"  user: Generate a realistic VHF radio lockage exchange.\n"
                    f"  Vessel: {vessel}, a vessel, downbound.\n"
                    f"  Lock: {args.lock_name}.\n"
                    f"  Write 6–10 transmissions covering: initial hail, operator "
                    f"response, approach/hold instructions, entry clearance, and departure."
                )
            elif getattr(args, 'all', False):
                # ── Step 1: ensure every ship has a captain ───────────────────
                new_caps = gen_captains(db)
                if new_caps:
                    print(f"Created {len(new_caps)} captain(s).")
                else:
                    print("All ships already have a captain.")

                # ── Step 2: generate radio for ships with no existing exchange ─
                all_ships = db.ships(limit=10_000)
                covered   = {
                    m['vessel_name']
                    for m in db.lock_radio_messages(limit=10_000)
                    if m.get('vessel_name')
                }
                pending = [s for s in all_ships
                           if s.get('name') and s['name'] not in covered]
                skipped = len(all_ships) - len(pending)

                if skipped:
                    print(f"Skipping {skipped} ship(s) that already have radio traffic.")
                if not pending:
                    print("Nothing to generate.")
                else:
                    print(f"Generating radio exchanges for {len(pending)} ship(s)…\n")
                    total_msgs = 0
                    for ship in pending:
                        name  = ship['name']
                        vtype = ship.get('vessel_type') or 'vessel'
                        dirn  = ship.get('direction')   or 'downstream'
                        cargo = ship.get('cargo')
                        try:
                            exchanges = generate_lock_radio_exchange(
                                name, dirn,
                                vessel_type=vtype,
                                lock_name=args.lock_name,
                                cargo=cargo,
                            )
                            thread_id = db.new_radio_thread()
                            for msg in exchanges:
                                db.add_lock_radio_message(
                                    msg['sender_type'],
                                    msg['sender_name'],
                                    msg['message'],
                                    thread_id=thread_id,
                                    vessel_name=name,
                                    direction=dirn,
                                )
                            total_msgs += len(exchanges)
                            print(f"  [{thread_id}] {name}  ({len(exchanges)} msgs)")
                        except Exception as exc:
                            print(f"  ERROR {name}: {exc}")

                    print(f"\nDone. {total_msgs} message(s) across {len(pending)} thread(s).")
            else:
                results = gen_lock_radio(
                    db,
                    vessel_name=args.vessel,
                    lock_name=args.lock_name,
                    count=args.count,
                )
                for r in results:
                    print(f"\n── {r['vessel_name']}  (thread {r['thread_id']}) ──")
                    for msg in r['messages']:
                        tag = '→' if msg['sender_type'] == 'ship' else '←'
                        print(f"  {tag}  [{msg['sender_name']}]  {msg['message']}")
                print(f"\n{sum(len(r['messages']) for r in results)} message(s) saved "
                      f"across {len(results)} thread(s).")

        elif args.cmd == 'crew-name':
            names = [random_crew_name(args.gender) for _ in range(args.count)]
            for name in names:
                print(name)
            if args.save:
                for name in names:
                    row_id = db.add_crew(name)
                    logger.info("  [crew %d] %s", row_id, name)
                print(f"Saved {len(names)} crew member(s) to DB.")

        elif args.cmd == 'crew-dialog':
            lines = generate_crew_dialog(
                args.name, args.role, args.context,
                stage_id=args.stage_id,
                count=args.count,
            )
            print(f"\nGenerated {len(lines)} lines for {args.name} [{args.context}]:")
            for ln in lines:
                print(f"  • {ln}")
            if not args.dry_run:
                save_crew_dialog(db, args.name, args.role, args.context,
                                 args.stage_id, lines)
                print("Saved to DB.")

        elif args.cmd == 'crew-profile':
            # Build the list of crew to process
            if args.name:
                matches = [c for c in db.crew_list()
                           if c['name'].lower() == args.name.lower()]
                if not matches:
                    # Not in DB yet — treat as a one-off with supplied flags
                    targets = [{'id': None, 'name': args.name,
                                'role': args.role, 'vessel_name': args.vessel,
                                'bio': None, 'notes': None}]
                else:
                    targets = matches
            else:
                # All crew missing bio OR notes
                targets = [c for c in db.crew_list()
                           if not c.get('bio') or not c.get('notes')]
                if not targets:
                    print("All crew already have bio and notes.")
                    return

            for member in targets:
                name        = member['name']
                role        = args.role or member.get('role')
                vessel_name = args.vessel or member.get('vessel_name')

                print(f"\n── {name} ({role or 'no role'}) ──")
                profile = generate_crew_profile(name, role or 'crew member', vessel_name)
                print(f"Bio:\n{profile['bio']}")
                if profile['notes']:
                    print(f"GM notes:\n{profile['notes']}")

                if not args.dry_run:
                    if member['id'] is not None:
                        db.update_crew(member['id'], **profile)
                        print(f"Updated crew id={member['id']}.")
                    else:
                        row_id = db.add_crew(name, role=role,
                                             vessel_name=vessel_name, **profile)
                        print(f"Created crew id={row_id}.")

        elif args.cmd == 'image':
            if args.dry_run:
                print(f"Dry run — would send prompt: {args.prompt}")
                return
            filepath, filename = generate_image(
                args.prompt,
                category=args.category,
                campaign_id=args.campaign_id,
                size=args.size,
                out_dir=args.out_dir,
            )
            register_generated_image(
                db, filepath, filename, args.prompt,
                args.category, args.campaign_id,
            )
            print(f"Done: {filepath}")

        elif args.cmd == 'browse':
            browse_assets_ui(db)

        elif args.cmd == 'gen-portraits':
            if args.dry_run:
                crew = ([db.get_crew(args.crew_id)] if args.crew_id
                        else db.crew_list())
                crew = [c for c in crew if c]
                if not crew:
                    print("No crew found.")
                else:
                    for member in crew:
                        print(f"\n── crew {member['id']}  {member['name']} ──")
                        print(_portrait_prompt(member))
            else:
                results = gen_crew_portraits(db, crew_id=args.crew_id)
                if not results:
                    print("No new portraits generated.")
                else:
                    for r in results:
                        print(f"  [crew {r['crew_id']}]  {r['name']}  →  {r['filepath']}")
                    print(f"\n{len(results)} portrait(s) generated.")

        elif args.cmd == 'gen-captains':
            created = gen_captains(db)
            if not created:
                print("Every ship already has a captain, or there are no ships in the DB.")
            else:
                col = max(len(c['name']) for c in created)
                for c in created:
                    print(f"  [crew {c['id']}]  {c['name']:<{col}}  captain  {c['vessel_name']}")
                print(f"\n{len(created)} captain(s) created.")

        elif args.cmd == 'gen-ships':
            records = []
            while len(records) < args.count:
                ship = random_ship_record()
                if args.vessel_type:
                    ship['vessel_type'] = args.vessel_type
                records.append(ship)

            col = max(len(r['name']) for r in records)
            for ship in records:
                print(
                    f"  {ship['name']:<{col}}  {ship['vessel_type']:<12}"
                    f"  {ship['direction']:<12}  {ship['origin']} → {ship['destination']}"
                    + (f"  [{ship['cargo']}]" if ship['cargo'] else '')
                )

            if args.save:
                for ship in records:
                    row_id = db.add_ship(**ship)
                    logger.info("  [ship %d] %s", row_id, ship['name'])
                print(f"\nSaved {len(records)} ship(s) to DB.")

        elif args.cmd == 'summary':
            s = db.summary()
            col = max(len(k) for k in s)
            for k, v in s.items():
                print(f"  {k:<{col}}  {v}")

        elif args.cmd == 'audit':
            report = audit_gaps(db)
            _print_audit(report)

    finally:
        db.close()


if __name__ == '__main__':
    main()