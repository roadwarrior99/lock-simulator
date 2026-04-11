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

    # Print DB summary
    python asset_manager.py summary
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
    response = client.images.generate(
        model='dall-e-3',
        prompt=prompt,
        size=size,
        response_format='b64_json',
        n=1,
    )
    image_data = response.data[0].b64_json
    revised_prompt = getattr(response.data[0], 'revised_prompt', prompt)

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


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(
        description='Asset manager — generate crew dialog and images via OpenAI.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument('--db', default=db_module.DB_PATH,
                   help='Path to the assets SQLite database (default: %(default)s)')

    sub = p.add_subparsers(dest='cmd', metavar='COMMAND')

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

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd is None:
        parser.print_help()
        return

    db = db_module.GameDatabase(args.db)

    try:
        if args.cmd == 'crew-name':
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

    finally:
        db.close()


if __name__ == '__main__':
    main()