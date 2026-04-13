import logging
import pygame
import math
import os
import random
from lock_and_dam import LockAndDam
from boat import Yacht, Barge, Kayak, PaddleBoat
from waterway import Canal
from assets import GameDatabase

logger = logging.getLogger(__name__)


# ── Boat agent ────────────────────────────────────────────────────────────────

class Agent:
    """A boat with autonomous AI movement."""
    _counter = 0

    def __init__(self, boat, direction):
        Agent._counter += 1
        self.boat      = boat
        self.direction = direction   # +1 = downstream (L→R), -1 = upstream (R→L)
        self.state     = "active"    # "active" | "crashed" | "done"
        self.speed     = random.uniform(0.9, 1.6)
        self.is_moving = False
        self.tied_down = False
        self.tied_side = None        # 0=top, 1=bottom
        self.ttl       = None        # frames until removal after crash


# ── Visualizer ────────────────────────────────────────────────────────────────

class LockDamVisualizer:

    SURGE_THRESHOLD = 2.0   # metres; opening gate above this differential → incident
    HOURLY_WAGE     = 7.25  # $/hour
    BOAT_BONUS      = 15.0 # $ per boat passed; An incentive to keep it moving.

    def __init__(self, shift_duration=None, shift_start_time=8.0, cfg_time_scale=5.0, dev_mode=False, ship_log=None):
        pygame.init()
        self.width  = 1200
        self.height = 800
        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption("Lock & Dam Operator")
        self.clock  = pygame.time.Clock()
        self.time   = 0.0
        self.game_time  = shift_start_time
        self.time_scale = cfg_time_scale

        # Shift config — preserved so K_r restart uses same parameters
        self._cfg_shift_duration   = shift_duration
        self._cfg_shift_start_time = shift_start_time
        self.dev_mode = dev_mode
        self._cfg_time_scale       = cfg_time_scale

        # Ship sighting log — persisted in campaign, passed in from main.py.
        # Structure: {'week': int, 'ships': {name: {'last_dir': +1 or -1}}}
        # A ship cannot travel the same direction twice in the same week unless
        # it has been seen returning in the opposite direction first.
        if ship_log is None:
            self.ship_log = {'week': 0, 'ships': {}}
        else:
            import copy
            self.ship_log = copy.deepcopy(ship_log)

        # Shift tracking
        self.shift_hours_elapsed = 0.0
        self.shift_complete      = False
        self.incident_count      = 0    # total incidents this run

        # ── Palette ───────────────────────────────────────────────────────────
        self.SKY_TOP        = ( 85, 140, 220)
        self.SKY_BOTTOM     = (170, 205, 245)
        self.WATER_TOP      = ( 55, 135, 205)
        self.WATER_BOT      = ( 20,  70, 150)
        self.WATER_SHIMMER  = (100, 175, 230)
        self.LOCK_WATER_TOP = ( 45, 120, 195)
        self.CONCRETE       = (175, 165, 148)
        self.CONCRETE_DARK  = (130, 122, 108)
        self.GRASS          = ( 72, 155,  68)
        self.GRASS_DARK     = ( 50, 115,  48)
        self.DIRT           = (130, 102,  72)
        self.DARK_GRAY      = ( 70,  70,  70)
        self.WHITE          = (255, 255, 255)
        self.BLACK          = ( 20,  20,  20)
        self.RED            = (215,  55,  55)
        self.GREEN          = ( 50, 200,  80)
        self.ORANGE         = (255, 140,  30)

        self._boat_colors = {
            "Yacht": (230, 230, 230),
            "Barge": (175, 135,  75),
            "Kayak": (235,  95,  35),
            "PaddleBoat": (180, 60, 60),
        }

        # ── Simulation ────────────────────────────────────────────────────────
        self.lock_dam  = LockAndDam("Main Lock", 10, 0)
        self.canal     = Canal("Main Canal")
        self.agents    = []

        self.lock_start = 350    # upstream gate (sim coords)
        self.lock_end   = 650    # downstream gate

        # ── Shore-view layout constants ───────────────────────────────────────
        # sim x ∈ [0, 1000]  →  screen x ∈ [50, 1150]
        self._sx_offset   = 50
        self._sx_scale    = (self.width - 100) / 1000.0
        self._wl_base     = 430   # screen-y at water level 0 m
        self._wl_scale    = 5     # px per metre (higher water = lower y)
        self._water_bot_y = 540
        _wall_t_px        = 20    # lock wall thickness in pixels (must match draw_shore_view)
        self._wall_t_sim  = _wall_t_px / self._sx_scale  # wall thickness in sim units

        # ── Gameplay ──────────────────────────────────────────────────────────
        self.score             = 0
        self.incidents         = []    # list of message strings
        self.flash_timer       = 0     # incident flash countdown (frames)
        self.flash_color       = self.RED
        self.game_over         = False
        self.both_gates_timer  = 0     # frames both gates have been open simultaneously
        self.BOTH_GATES_LIMIT  = 60   # 3 seconds at 60 fps

        # ── Spawning ──────────────────────────────────────────────────────────
        self.spawn_timer     = 0
        self.spawn_interval  = 300   # frames (~5 s at 60 fps)
        self._boat_counter   = 0
        self._next_direction = 1     # alternates each spawn

        # ── Weather ───────────────────────────────────────────────────────────
        self.clouds = []
        for _ in range(12):
            self.clouds.append({
                'x': random.uniform(-100, 1100),
                'y': random.uniform(10, 140),
                'w': random.uniform(80, 180),
                'h': random.uniform(40, 70),
                'speed': random.uniform(0.05, 0.15)
            })
        self.rain_active = False
        self.weather_timer = random.randint(1000, 3000)
        self.rain_drops = []
        for _ in range(160):
            self.rain_drops.append({
                'x': random.randint(0, self.width),
                'y': random.randint(0, self.height),
                's': random.randint(5, 12)
            })
        self.lightning_timer = 0
        self.lightning_bolt = None

        # ── Nature ────────────────────────────────────────────────────────────
        self.trees = []
        # Pre-calculate tree positions in sim-space
        for x in range(40, 310, 80): # Upstream
            self.trees.append({'x': x, 'type': 'up'})
        for x in range(690, 960, 80): # Downstream
            self.trees.append({'x': x, 'type': 'down'})

        self.birds = []
        for _ in range(6):
            self.birds.append({
                'x': random.uniform(0, self.width),
                'y': random.uniform(50, 150),
                'vx': random.uniform(0.5, 1.5),
                'vy': random.uniform(-0.2, 0.2),
                'state': 'flying', # 'flying', 'homing', 'sleeping'
                'target_tree': None,
                'wing_phase': random.uniform(0, math.pi * 2)
            })

        # ── Operator & Views ──────────────────────────────────────────────────
        self.view_mode = "shore" # "shore" or "operator"
        self.operator = {
            'x': self.lock_start + 10,
            'target_x': self.lock_start + 10,
            'state': 'idle', # 'idle', 'walking', 'tying', 'untying', 'crossing'
            'side': 0, # 0 = top, 1 = bottom
            'target_side': 0,
            'cross_progress': 0.0,  # 0.0→1.0 while crossing between walls
            'rope_progress': 0.0, # 0.0 to 1.0 (thrown)
            'target_boat': None, # agent being tied/untied
            'task': None # 'tie', 'untie', or None
        }

        # Fonts
        self.fnt_lg = pygame.font.Font(None, 42)
        self.fnt_md = pygame.font.Font(None, 28)
        self.fnt_sm = pygame.font.Font(None, 22)

        # ── Asset DB ──────────────────────────────────────────────────────────
        # Map vessel_type strings → game class
        _VT_TO_CLS = {
            'barge': Barge, 'towboat': Barge,
            'yacht': Yacht, 'kayak': Kayak, 'paddleboat': PaddleBoat,
        }
        self._db_ships_by_cls: dict[type, list[dict]] = {
            Barge: [], Yacht: [], Kayak: [], PaddleBoat: []}
        # vessel_name → {direction_str: [{'id': int, 'message': str}, ...]}
        # direction_str is 'downstream', 'upstream', or None (direction not set)
        self._db_radio: dict[str, dict] = {}
        self._captain_portraits: dict[str, pygame.Surface] = {}
        # vessel_name → {'crew_id': int, 'filename': str} — for debug logging
        self._captain_meta: dict[str, dict] = {}
        self._agent_ship_map: dict[int, dict] = {}   # id(ag) → ship record
        self._radio_triggered: set[int] = set()      # id(ag) already triggered (tie event)
        self._radio_approach: set[int]  = set()      # id(ag) already triggered (lock entry)
        self._radio_depart:   set[int]  = set()      # id(ag) already triggered (lines cleared)
        self._radio_bubbles: list[dict] = []         # active speech bubbles
        self._roster_buttons: list      = []         # [(pygame.Rect, Agent), ...] refreshed each frame
        self._op_screen_pos: tuple      = (600, 390) # updated each frame in draw_shore_view
        self._gate_anim_up: float       = 0.0        # 0.0=closed → 1.0=open
        self._gate_anim_dn: float       = 0.0
        self._db_operator_radio: dict[str, list[dict]] = {}  # vessel_name → [{id, message}]
        self._radio_popup: dict | None  = None       # active radio popup state

        try:
            _db = GameDatabase()
            for s in _db.ships():
                cls = _VT_TO_CLS.get((s.get('vessel_type') or '').lower())
                if cls and s.get('name'):
                    self._db_ships_by_cls[cls].append(s)

            # Pre-load ship radio messages (ship→operator transmissions only).
            # Bucket by direction so a downstream boat gets downstream messages.
            # Store full records {id, message} so debug logging can reference the DB row.
            for msg in _db.lock_radio_messages(sender_type='ship', limit=5000):
                vn = msg.get('vessel_name') or msg.get('sender_name')
                if vn:
                    dir_str = msg.get('direction') or None  # 'downstream'/'upstream'/None
                    record = {'id': msg['id'], 'message': msg['message']}
                    self._db_radio.setdefault(vn, {}).setdefault(dir_str, []).append(record)

            # Pre-load operator→ship radio messages (options the player can choose).
            for msg in _db.lock_radio_messages(sender_type='operator', limit=5000):
                vn = msg.get('vessel_name') or msg.get('sender_name')
                if vn:
                    record = {'id': msg['id'], 'message': msg['message']}
                    self._db_operator_radio.setdefault(vn, []).append(record)

            # Pre-load captain portraits
            self._captain_portraits = self._load_captain_portraits(_db)

            # Cross-reference: log every vessel with radio messages that is missing
            # a captain record or a captain portrait so gaps are easy to find.
            vessels_with_radio = set(self._db_radio.keys())
            vessels_with_portrait = set(self._captain_portraits.keys())
            captain_vessels = {
                c['vessel_name']
                for c in _db.crew_list(role='captain')
                if c.get('vessel_name')
            }
            no_captain = vessels_with_radio - captain_vessels
            captain_no_portrait = (vessels_with_radio & captain_vessels) - vessels_with_portrait
            if no_captain:
                logger.debug("asset gap — vessels with radio messages but NO captain in crew table (%d): %s",
                             len(no_captain), sorted(no_captain))
            if captain_no_portrait:
                logger.debug("asset gap — vessels with a captain but NO portrait loaded (%d): %s",
                             len(captain_no_portrait), sorted(captain_no_portrait))
            if not no_captain and not captain_no_portrait:
                logger.debug("asset check OK — all %d radio vessels have a captain and portrait",
                             len(vessels_with_radio))

            _db.close()
        except Exception:
            pass   # DB unavailable — game runs without it

        # Seed two initial boats
        self._spawn_boat( 1,  100)
        self._spawn_boat(-1, 900)

    # ── Coordinate helpers ────────────────────────────────────────────────────

    def _sx(self, sim_x):
        """Simulation x → screen x."""
        return int(self._sx_offset + sim_x * self._sx_scale)

    def _wy(self, level):
        """Water level (m) → screen y (surface)."""
        return int(self._wl_base - level * self._wl_scale)

    def _get_speed_mult(self):
        h = self.game_time
        if 8.0 <= h < 18.0: return 1.0
        if 18.0 <= h < 22.0: return 1.0 - (h - 18.0) / 4.0 * 0.4  # Dims to 0.6
        if 22.0 <= h or h < 4.0: return 0.6
        if 4.0 <= h < 8.0: return 0.6 + (h - 4.0) / 4.0 * 0.4  # Brightens to 1.0
        return 1.0

    def _interp_col(self, c1, c2, t):
        t = max(0.0, min(1.0, t))
        return (
            int(c1[0] + (c2[0] - c1[0]) * t),
            int(c1[1] + (c2[1] - c1[1]) * t),
            int(c1[2] + (c2[2] - c1[2]) * t)
        )

    def _dim(self, color, mult):
        return (int(color[0] * mult), int(color[1] * mult), int(color[2] * mult))

    def _get_ambient_mult(self):
        h = self.game_time
        if 8.0 <= h < 16.0: 
            mult = 1.0
        elif 16.0 <= h < 20.0: 
            mult = 1.0 - (h - 16.0) / 4.0 * 0.7  # Dims to 0.3
        elif 20.0 <= h or h < 5.0: 
            mult = 0.3
        elif 5.0 <= h < 8.0: 
            mult = 0.3 + (h - 5.0) / 3.0 * 0.7  # Brightens to 1.0
        else:
            mult = 1.0
        
        if self.rain_active:
            mult *= 0.75  # Darker when raining
        return mult

    def _get_sky_colors(self):
        h = self.game_time
        night_top, night_bot = (5, 5, 20), (10, 10, 40)
        day_top,   day_bot   = self.SKY_TOP, self.SKY_BOTTOM
        sunset_top, sunset_bot = (50, 40, 100), (180, 80, 60)
        if 5.0 <= h < 8.0: # Dawn
            t = (h - 5.0) / 3.0
            return self._interp_col(night_top, day_top, t), self._interp_col(night_bot, day_bot, t)
        if 8.0 <= h < 16.0: # Day
            return day_top, day_bot
        if 16.0 <= h < 20.0: # Dusk
            t = (h - 16.0) / 4.0
            return self._interp_col(day_top, sunset_top, t), self._interp_col(day_bot, sunset_bot, t)
        if 20.0 <= h < 22.0: # Evening
            t = (h - 20.0) / 2.0
            return self._interp_col(sunset_top, night_top, t), self._interp_col(sunset_bot, night_bot, t)
        return night_top, night_bot

    # ── Drawing primitives ────────────────────────────────────────────────────

    def _gradient_rect(self, c1, c2, rect):
        x, y, w, h = rect
        if h <= 0 or w <= 0:
            return
        for i in range(h):
            t = i / (h - 1) if h > 1 else 0
            r = int(c1[0] + (c2[0] - c1[0]) * t)
            g = int(c1[1] + (c2[1] - c1[1]) * t)
            b = int(c1[2] + (c2[2] - c1[2]) * t)
            pygame.draw.line(self.screen, (r, g, b), (x, y + i), (x + w - 1, y + i))

    # Lane offsets from water surface (px).  d=+1 upper lane, d=-1 lower lane.
    # Separation must exceed the tallest boat's full hull height to avoid visual overlap.
    _LANE_OFF    = {1: 28, -1: 82}
    _DIVIDER_OFF = 55   # midpoint between the two lanes
    _WALL_T_PX   = 18   # lock wall thickness in pixels (must match draw_shore_view)

    def _in_lock(self, boat):
        return boat.position < self.lock_end and boat.position + boat.length > self.lock_start

    def _fully_in_lock(self, boat):
        return boat.position >= self.lock_start and (boat.position + boat.length) <= self.lock_end

    def _lane_y(self, ag, surf_y):
        """Vertical centre for the boat hull — always direction-based, no lane merging."""
        return surf_y + self._LANE_OFF[ag.direction]

    def _lane_divider(self, x, w, surf_y):
        """Draw a dashed centre-line dividing the two traffic lanes."""
        dy = surf_y + self._DIVIDER_OFF
        dash_col = (38, 95, 172)
        for dx in range(x, x + w - 8, 20):
            pygame.draw.line(self.screen, dash_col, (dx, dy), (dx + 12, dy), 1)

    def _draw_sky(self, bottom_y):
        top, bot = self._get_sky_colors()
        self._gradient_rect(top, bot, (0, 0, self.width, bottom_y))
        self._draw_clouds(bottom_y)

    def _draw_clouds(self, sky_h):
        mult = self._get_ambient_mult()
        cloud_v = 240 if not self.rain_active else 150
        cloud_col = self._dim((cloud_v, cloud_v, cloud_v), mult)
        
        for c in self.clouds:
            cx, cy = int(c['x']), int(c['y'])
            cw, ch = int(c['w']), int(c['h'])
            # Only draw if cloud is within sky area
            if cy > sky_h: continue
            
            # Simple puffy cloud using 3 ellipses
            pygame.draw.ellipse(self.screen, cloud_col, (cx, cy, cw, ch))
            pygame.draw.ellipse(self.screen, cloud_col, (cx + cw//4, cy - ch//2, cw//2, ch))
            pygame.draw.ellipse(self.screen, cloud_col, (cx + cw//2, cy, cw//2, ch))

    def _draw_birds(self):
        mult = self._get_ambient_mult()
        bird_col = self._dim((20, 20, 20), mult)
        for b in self.birds:
            if b['state'] == 'sleeping':
                continue
            
            bx, by = b['x'], b['y']
            # Wing flap
            wing = math.sin(self.time * 15 + b['wing_phase']) * 4
            pygame.draw.line(self.screen, bird_col, (bx, by), (bx - 4, by - 2 + wing), 1)
            pygame.draw.line(self.screen, bird_col, (bx, by), (bx + 4, by - 2 + wing), 1)

    def _draw_tree(self, sx, sy):
        mult = self._get_ambient_mult()
        trunk_col = self._dim((101, 67, 33), mult)
        leaf_col = self._dim((34, 139, 34), mult)
        
        # Trunk
        pygame.draw.rect(self.screen, trunk_col, (sx - 3, sy - 15, 6, 15))
        # Canopy
        pygame.draw.circle(self.screen, leaf_col, (sx, sy - 22), 12)
        pygame.draw.circle(self.screen, leaf_col, (sx - 8, sy - 18), 9)
        pygame.draw.circle(self.screen, leaf_col, (sx + 8, sy - 18), 9)

    def _draw_rain(self):
        if not self.rain_active:
            return
        mult = self._get_ambient_mult()
        # Rain is less visible at night
        alpha = int(180 * mult)
        rain_col = (180, 200, 255, alpha)
        
        rain_surf = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        for d in self.rain_drops:
            pygame.draw.line(rain_surf, rain_col, (d['x'], d['y']), (d['x'] - 2, d['y'] + 8), 1)
        self.screen.blit(rain_surf, (0, 0))

    def _draw_lightning(self):
        if self.lightning_timer > 0 and self.lightning_bolt:
            # Flash effect
            flash_alpha = min(150, self.lightning_timer * 30)
            flash_surf = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            flash_surf.fill((255, 255, 255, flash_alpha))
            self.screen.blit(flash_surf, (0, 0))
            
            # Bolt
            pygame.draw.lines(self.screen, (255, 255, 255), False, self.lightning_bolt, 2)

    def _draw_water_band(self, x, y, w):
        h = self._water_bot_y - y
        if h <= 0 or w <= 0:
            return
        mult = self._get_ambient_mult()
        self._gradient_rect(self._dim(self.WATER_TOP, mult), self._dim(self.WATER_BOT, mult), (x, y, w, h))
        pygame.draw.line(self.screen, self._dim(self.WATER_SHIMMER, mult), (x, y), (x + w, y), 2)

    def _draw_bank_strip(self, x, top_y, w):
        mult = self._get_ambient_mult()
        pygame.draw.rect(self.screen, self._dim(self.DIRT, mult),       (x, top_y - 12, w, 12))
        pygame.draw.rect(self.screen, self._dim(self.GRASS, mult),      (x, top_y - 26, w, 14))
        pygame.draw.rect(self.screen, self._dim(self.GRASS_DARK, mult), (x, top_y - 38, w, 12))

    def _draw_ground_strip(self, lk_sx, lk_ex):
        """Fill the full ground area below _water_bot_y with layered earth and grass."""
        mult  = self._get_ambient_mult()
        gy    = self._water_bot_y
        gh    = self.height - gy

        for gx, gw in ((0, lk_sx), (lk_ex, self.width - lk_ex)):
            if gw <= 0:
                continue
            # Earth gradient: medium soil at top → dark earth at bottom
            self._gradient_rect(
                self._dim((112, 86, 56), mult),
                self._dim((70,  52, 32), mult),
                (gx, gy, gw, gh),
            )
            # Grass cap
            pygame.draw.rect(self.screen, self._dim(self.GRASS,      mult), (gx, gy,      gw, 14))
            pygame.draw.rect(self.screen, self._dim(self.GRASS_DARK, mult), (gx, gy + 12, gw,  6))
            pygame.draw.rect(self.screen, self._dim(self.DIRT,       mult), (gx, gy + 16, gw, 10))

            # Grass tufts (deterministic using x position as seed)
            for tx in range(gx + 6, gx + gw, 16):
                th = 4 + (tx * 17 + 3) % 5
                pygame.draw.line(self.screen, self._dim((48, 118, 44), mult),
                                 (tx,     gy + 2), (tx - 2, gy + 2 - th), 1)
                pygame.draw.line(self.screen, self._dim((68, 148, 58), mult),
                                 (tx + 3, gy + 2), (tx + 5, gy + 2 - th + 1), 1)

            # Ground-level trees at the same sim-space positions as the sky trees
            for tree in self.trees:
                sx = self._sx(tree['x'])
                if gx <= sx < gx + gw:
                    self._draw_ground_tree(sx, gy)

    def _draw_ground_tree(self, sx, ground_y):
        """Draw a larger ground-level tree on the embankment."""
        mult  = self._get_ambient_mult()
        trunk = self._dim(( 82, 53, 26), mult)
        leaf1 = self._dim(( 26, 112, 26), mult)
        leaf2 = self._dim(( 44, 138, 38), mult)
        # Trunk planted in the soil
        pygame.draw.rect(self.screen, trunk, (sx - 4, ground_y + 8, 8, 30))
        # Canopy — three overlapping circles for a fuller look
        pygame.draw.circle(self.screen, leaf1, (sx,       ground_y + 2),  20)
        pygame.draw.circle(self.screen, leaf2, (sx - 13,  ground_y + 10), 14)
        pygame.draw.circle(self.screen, leaf2, (sx + 13,  ground_y + 10), 14)
        pygame.draw.circle(self.screen, leaf1, (sx,       ground_y + 16), 15)

    # ── Shore view ────────────────────────────────────────────────────────────

    def draw_shore_view(self):
        up_y  = self._wy(self.lock_dam.upstream_level)
        dn_y  = self._wy(self.lock_dam.downstream_level)
        lk_y  = self._wy(self.lock_dam.lock_chamber_level)
        lk_sx = self._sx(self.lock_start)
        lk_ex = self._sx(self.lock_end)
        lk_w  = lk_ex - lk_sx
        wall_t   = 18
        wall_top = up_y - 35

        self._draw_sky(min(up_y, dn_y) - 40)

        # Gate faces in screen x — water extends all the way to the gate face so
        # no grey concrete gap is visible between the channel water and the gate.
        mult    = self._get_ambient_mult()
        inner_x = lk_sx + wall_t
        inner_w = lk_w - 2 * wall_t

        # Ground strip (full width below water_bot_y — covers both channel floors)
        self._draw_ground_strip(lk_sx, lk_ex)

        # Upstream channel — water reaches the upstream gate face (inner_x)
        shimmer_col = self._dim(self.WATER_SHIMMER, mult)
        self._draw_water_band(0, up_y, inner_x)
        self._lane_divider(0, inner_x, up_y)
        self._draw_bank_strip(0, up_y, inner_x)
        t = self.time * 1.8
        for wx in range(0, inner_x - 10, 35):
            oy = int(3 * math.sin(t + wx * 0.06))
            pygame.draw.line(self.screen, shimmer_col,
                             (wx + 5, up_y + oy), (wx + 25, up_y + oy), 1)

        # Downstream channel — water starts at the downstream gate face
        dn_gate_x = inner_x + inner_w   # = lk_ex - wall_t
        self._draw_water_band(dn_gate_x, dn_y, self.width - dn_gate_x)
        self._lane_divider(dn_gate_x, self.width - dn_gate_x, dn_y)
        self._draw_bank_strip(dn_gate_x, dn_y, self.width - dn_gate_x)
        for wx in range(dn_gate_x + 5, self.width - 10, 35):
            oy = int(2 * math.sin(t + wx * 0.06))
            pygame.draw.line(self.screen, shimmer_col,
                             (wx, dn_y + oy), (wx + 20, dn_y + oy), 1)

        # Lock chamber — water fill
        self._gradient_rect(self._dim(self.LOCK_WATER_TOP, mult), self._dim(self.WATER_BOT, mult),
                            (inner_x, lk_y, inner_w, self._water_bot_y - lk_y))
        pygame.draw.line(self.screen, self._dim(self.WATER_SHIMMER, mult),
                         (inner_x, lk_y), (inner_x + inner_w, lk_y), 2)
        self._lane_divider(inner_x, inner_w, lk_y)

        # Turbulent water effects when filling or draining
        if self.lock_dam.is_filling or self.lock_dam.is_draining:
            t2 = self.time * 2
            bubble_col = self._interp_col((220, 245, 255), (50, 60, 80), 1.0 - mult)
            streak_col = self._interp_col((240, 250, 255), (70, 80, 100), 1.0 - mult)
            for i in range(20):
                rx = (math.sin(i * 1.5 + t2) * 0.5 + 0.5) * inner_w
                ry = (math.cos(i * 2.3 + t2 * 0.7) * 0.5 + 0.5) * 35
                bx = inner_x + int(rx)
                by = lk_y + int(ry)
                if by < self._water_bot_y:
                    size = 1 + int(2 * (math.sin(t2 * 2 + i) * 0.5 + 0.5))
                    pygame.draw.circle(self.screen, bubble_col, (bx, by), size)
                sx2 = inner_x + int((i * 17 + t2 * 40) % inner_w)
                sw  = 10 + 5 * math.sin(i + t2)
                if lk_y < self._water_bot_y:
                    pygame.draw.line(self.screen, streak_col,
                                     (sx2, lk_y + 1), (int(sx2 + sw), lk_y + 1), 2)

        # Concrete headwall — top cap only (no side piers below waterline;
        # the channel water now fills flush to the gate faces).
        conc_col  = self._dim(self.CONCRETE, mult)
        conc_dark = self._dim(self.CONCRETE_DARK, mult)
        pygame.draw.rect(self.screen, conc_col,
                         (lk_sx, wall_top, lk_w, lk_y - wall_top))
        for cy in range(wall_top + 10, lk_y, 14):
            pygame.draw.line(self.screen, conc_dark,
                             (lk_sx, cy), (lk_sx + lk_w, cy), 1)
        # Bottom chamber floor cap
        pygame.draw.rect(self.screen, conc_col,
                         (lk_sx, self._water_bot_y, lk_w, 20))
        pygame.draw.rect(self.screen, conc_dark,
                         (inner_x, self._water_bot_y, inner_w, 10))

        # Both gates must handle the full upstream head.
        # Upstream gate: top at up_y, bottom at floor sill.
        # Downstream gate: same total height, but its leaves sit 3/4 leaf-height higher
        # so they land in the water column rather than in the ground.
        gate_h    = self._water_bot_y - up_y             # total gate height (px)
        leaf_h    = gate_h // 2                          # one leaf arm length
        dn_shift  = (leaf_h * 3) // 4                    # shift downstream gate upward
        dn_top    = dn_y - dn_shift + 5                  # +5 px down
        dn_floor  = dn_top + gate_h + 10                 # +10 px so lower leaf meets shore

        # Trees (drawn before gates so gates appear in front)
        for tree in self.trees:
            sx = self._sx(tree['x'])
            if tree['type'] == 'up': sy = up_y - 38
            else: sy = dn_y - 38
            self._draw_tree(sx, sy)

        self._draw_miter_gate(inner_x   - 10, up_y,   self._water_bot_y,
                              self._gate_anim_up, faces_right=True)
        self._draw_miter_gate(dn_gate_x + 10, dn_top, dn_floor,
                              self._gate_anim_dn, faces_right=False,
                              top_face_scale=2.0, top_shrink=100)

        # Boats
        for ag in self.agents:
            if ag.state != "done":
                self._draw_boat_shore(ag, up_y, dn_y, lk_y, lk_sx, lk_ex)

        # Water level labels
        self._wl_label((self._sx_offset + lk_sx) // 2, up_y, "Upstream", self.lock_dam.upstream_level)
        self._wl_label((lk_ex + self._sx(1000)) // 2, dn_y,
                       "Downstream", self.lock_dam.downstream_level)
        self._wl_label((lk_sx + lk_ex) // 2, lk_y,
                       "Chamber", self.lock_dam.lock_chamber_level)

        # ── Ropes and Operator (Shore View) ───────────────────────────────────
        # Draw permanent ropes for all tied boats
        rope_col = self._dim((200, 190, 150), mult)
        for ag in self.agents:
            if ag.state == "active" and ag.tied_down and self._in_lock(ag.boat):
                bx = self._sx(ag.boat.position + ag.boat.length / 2)
                by = self._lane_y(ag, lk_y)
                if ag.tied_side == 0:
                    ry = wall_top - 2
                else:
                    ry = self._water_bot_y + 2
                pygame.draw.line(self.screen, rope_col, (bx, ry), (bx, by), 2)

        op = self.operator
        ox = self._sx(op['x'])
        top_y    = wall_top - 5
        bottom_y = self._water_bot_y + 10
        if op['state'] == 'crossing':
            # Nudge operator 2 px inward so he appears to walk on the gate leaf
            # rather than the outer wall edge.
            if op['x'] <= (self.lock_start + self.lock_end) / 2:
                ox += 8   # upstream gate: toward lock interior (right)
            else:
                ox -= 8   # downstream gate: toward lock interior (left)
            t  = op['cross_progress']
            # Ease in-out so the walk looks natural
            t  = t * t * (3 - 2 * t)
            if op['target_side'] == 1:   # crossing top → bottom
                oy = int(top_y    + (bottom_y - top_y) * t)
            else:                         # crossing bottom → top
                oy = int(bottom_y + (top_y - bottom_y) * t)
        else:
            oy = top_y if op['side'] == 0 else bottom_y
        self._op_screen_pos = (ox, oy)   # cached for speech-bubble anchoring

        body_col = self._dim((60, 80, 200), mult) # blue uniform
        pygame.draw.circle(self.screen, body_col, (ox, oy), 5) # body
        pygame.draw.circle(self.screen, self._dim((240, 200, 180), mult), (ox, oy - 8), 4) # head
        
        # Active task rope (throwing/pulling)
        if op['state'] in ('tying', 'untying') and op['target_boat']:
            target_ag = op['target_boat']
            boat_bx = self._sx(target_ag.boat.position + target_ag.boat.length / 2)
            boat_by = self._lane_y(target_ag, lk_y)
            curr_bx = ox + (boat_bx - ox) * op['rope_progress']
            curr_by = oy + (boat_by - oy) * op['rope_progress']
            pygame.draw.line(self.screen, rope_col, (ox, oy), (int(curr_bx), int(curr_by)), 2)

    def draw_operator_view(self):
        """A pseudo-first-person POV looking down from the lock wall."""
        mult = self._get_ambient_mult()
        # Sky background (above opposite wall)
        self._draw_sky(200)
        self._draw_clouds(200)

        # Opposite concrete wall (horizon-ish)
        conc_col = self._dim(self.CONCRETE, mult)
        conc_dark = self._dim(self.CONCRETE_DARK, mult)
        pygame.draw.rect(self.screen, conc_col, (0, 200, self.width, 100))
        for cy in range(210, 300, 20):
            pygame.draw.line(self.screen, conc_dark, (0, cy), (self.width, cy), 2)

        # Water in the chamber
        # Level relative to "full" (10m)
        lvl = self.lock_dam.lock_chamber_level
        # Water takes up middle space. 
        # As it drains, it moves lower on screen, revealing more opposite wall?
        # Let's keep it simple: static water area, but boat moves within it.
        water_y = 300
        water_h = 400
        self._gradient_rect(self._dim(self.LOCK_WATER_TOP, mult), 
                            self._dim(self.WATER_BOT, mult), 
                            (0, water_y, self.width, water_h))

        # Turbulent water if filling/draining
        if self.lock_dam.is_filling or self.lock_dam.is_draining:
            t = self.time * 3
            bubble_col = self._interp_col((220, 245, 255), (50, 60, 80), 1.0 - mult)
            for i in range(30):
                bx = (math.sin(i * 0.7 + t) * 0.5 + 0.5) * self.width
                by = water_y + (math.cos(i * 1.1 + t * 0.5) * 0.5 + 0.5) * water_h
                pygame.draw.circle(self.screen, bubble_col, (int(bx), int(by)), random.randint(2, 5))

        # Boats and ropes in POV
        op = self.operator
        pov_scale = 15
        
        for ag in self.agents:
            if ag.state != "done" and self._in_lock(ag.boat):
                boat = ag.boat
                boat_col = self._dim(self._boat_color(boat), mult)
                
                # Horizontal position relative to operator
                rel_x = (boat.position + boat.length / 2) - op['x']
                screen_cx = self.width // 2 + rel_x * pov_scale
                boat_w = boat.length * pov_scale
                screen_lx = screen_cx - boat_w // 2
                
                # Vertical position (depends on water level and lane)
                # lane_y_off: closer to our wall (higher y) or opposite wall (lower y)
                side_of_boat = 1 if ag.direction == -1 else 0
                lane_y_off = 120 if side_of_boat == op['side'] else 20
                boat_y = water_y + (10 - lvl) * 25 + lane_y_off
                boat_h = int(boat.beam * pov_scale)
                
                if screen_lx + boat_w > 0 and screen_lx < self.width:
                    lx  = int(screen_lx)
                    rx  = int(screen_lx + boat_w)
                    bw  = rx - lx
                    ty  = int(boat_y)
                    by  = int(boat_y + boat_h)
                    bh  = by - ty
                    is_dark = self.game_time < 6.5 or self.game_time > 18.5
                    outline = self._dim(self.DARK_GRAY, mult)
                    vtype = boat.vessel_type

                    # deck_y: line separating hull (below) from superstructure (above)
                    deck_y = ty + bh * 2 // 5

                    if vtype == "kayak":
                        # Slim double-ended hull — tapers to points at both ends
                        mid_y = (ty + by) // 2
                        pts = [(lx, mid_y),
                               (lx + bw // 5, ty), (rx - bw // 5, ty),
                               (rx, mid_y),
                               (rx - bw // 5, by), (lx + bw // 5, by)]
                        pygame.draw.polygon(self.screen, boat_col, pts)
                        pygame.draw.polygon(self.screen, outline, pts, 1)
                        # cockpit
                        ck = bw // 8
                        pygame.draw.ellipse(self.screen, self._dim((40, 25, 15), mult),
                                            (lx + bw // 2 - ck, mid_y - ck // 2, ck * 2, ck))

                    elif vtype == "yacht":
                        bow_cut = max(8, bw // 4)
                        # Hull — pointed bow, flat stern
                        if ag.direction == 1:
                            hull_pts = [(lx, deck_y), (lx, by),
                                        (rx - bow_cut, by), (rx, deck_y + bh // 4),
                                        (rx - bow_cut // 2, deck_y)]
                        else:
                            hull_pts = [(rx, deck_y), (rx, by),
                                        (lx + bow_cut, by), (lx, deck_y + bh // 4),
                                        (lx + bow_cut // 2, deck_y)]
                        pygame.draw.polygon(self.screen, boat_col, hull_pts)
                        pygame.draw.polygon(self.screen, outline, hull_pts, 2)
                        # boot stripe
                        boot_col = self._dim((180, 30, 30), mult)
                        pygame.draw.line(self.screen, boot_col, (lx, by - 3), (rx, by - 3), 2)
                        # cabin
                        cab_w = bw * 2 // 5
                        cab_h = bh * 2 // 5
                        cab_x = lx + bw // 4 if ag.direction == 1 else lx + bw // 3
                        cab_y = deck_y - cab_h
                        cab_col = self._dim((220, 220, 215), mult)
                        pygame.draw.rect(self.screen, cab_col, (cab_x, cab_y, cab_w, cab_h))
                        pygame.draw.rect(self.screen, outline, (cab_x, cab_y, cab_w, cab_h), 1)
                        win_col = (255, 240, 140) if is_dark else self._dim((100, 155, 210), mult)
                        ww = max(3, cab_w // 5)
                        for i in range(3):
                            pygame.draw.rect(self.screen, win_col,
                                             (cab_x + 3 + i * (cab_w // 3), cab_y + 3, ww, cab_h - 6))
                        # mast
                        mast_x = cab_x + cab_w // 3
                        mast_col = self._dim((190, 175, 150), mult)
                        pygame.draw.line(self.screen, mast_col,
                                         (mast_x, cab_y), (mast_x, cab_y - bh // 3), 2)
                        if is_dark:
                            l_col = self.GREEN if ag.direction == 1 else self.RED
                            bow_lx = rx - 3 if ag.direction == 1 else lx + 3
                            pygame.draw.circle(self.screen, self._dim(l_col, mult), (bow_lx, deck_y), 2)
                            pygame.draw.circle(self.screen, self._dim(self.WHITE, mult), (mast_x, cab_y - bh//3), 2)

                    elif vtype == "barge":
                        # Flat low-freeboard hull
                        pygame.draw.rect(self.screen, boat_col, (lx, deck_y, bw, by - deck_y))
                        pygame.draw.rect(self.screen, outline, (lx, deck_y, bw, by - deck_y), 2)
                        # Cargo holds
                        cargo_col = self._dim((80, 62, 45), mult)
                        seg_w = (bw - 6) // 3
                        cargo_h = bh * 2 // 5
                        for i in range(3):
                            cx_ = lx + 3 + i * seg_w
                            pygame.draw.rect(self.screen, cargo_col,
                                             (cx_, deck_y - cargo_h, seg_w - 2, cargo_h))
                            pygame.draw.rect(self.screen, outline,
                                             (cx_, deck_y - cargo_h, seg_w - 2, cargo_h), 1)
                        # Towboat at stern — flat-bowed river pusher
                        tug_w = max(16, bw // 4)
                        tx_ = lx - tug_w + 5 if ag.direction == 1 else rx - 5
                        tug_hull_col = self._dim((38, 38, 42), mult)
                        pygame.draw.rect(self.screen, tug_hull_col,
                                         (tx_, deck_y, tug_w, by - deck_y))
                        pygame.draw.rect(self.screen, outline,
                                         (tx_, deck_y, tug_w, by - deck_y), 1)
                        # Wheelhouse
                        tug_h = bh * 3 // 5
                        tug_y = deck_y - tug_h
                        tc_col = (255, 195, 90) if is_dark else self._dim((210, 55, 55), mult)
                        tc_w = tug_w * 3 // 4
                        pygame.draw.rect(self.screen, tc_col,
                                         (tx_ + (tug_w - tc_w) // 2, tug_y, tc_w, tug_h))
                        pygame.draw.rect(self.screen, outline,
                                         (tx_ + (tug_w - tc_w) // 2, tug_y, tc_w, tug_h), 1)
                        # Windows
                        win_col = (255, 245, 150) if is_dark else self._dim((140, 200, 235), mult)
                        ww = max(2, tc_w // 4)
                        for i in range(2):
                            pygame.draw.rect(self.screen, win_col,
                                             (tx_ + (tug_w - tc_w) // 2 + 2 + i * (tc_w // 2),
                                              tug_y + 2, ww, tug_h - 4))
                        # Two smokestacks at stern
                        stk_col = self._dim((22, 22, 22), mult)
                        stk_h = tug_h // 2 + 2
                        if ag.direction == 1:
                            s1x, s2x = tx_ + tug_w - 7, tx_ + tug_w - 12
                        else:
                            s1x, s2x = tx_ + 4, tx_ + 9
                        pygame.draw.rect(self.screen, stk_col, (s1x, tug_y - stk_h, 3, stk_h + 2))
                        pygame.draw.rect(self.screen, stk_col, (s2x, tug_y - stk_h + 2, 3, stk_h))
                        if is_dark:
                            pygame.draw.circle(self.screen, self._dim(self.WHITE, mult),
                                               (tx_ + tug_w // 2, tug_y - 2), 2)

                    elif vtype == "paddleboat":
                        bow_cut = max(10, bw // 5)
                        # Hull
                        if ag.direction == 1:
                            hull_pts = [(lx, deck_y), (lx, by),
                                        (rx - bow_cut, by), (rx, deck_y + bh // 4),
                                        (rx - bow_cut // 2, deck_y)]
                        else:
                            hull_pts = [(rx, deck_y), (rx, by),
                                        (lx + bow_cut, by), (lx, deck_y + bh // 4),
                                        (lx + bow_cut // 2, deck_y)]
                        pygame.draw.polygon(self.screen, boat_col, hull_pts)
                        pygame.draw.polygon(self.screen, outline, hull_pts, 2)
                        # Deck 1
                        cab_w  = bw * 3 // 5
                        cab_x  = lx + (bw - cab_w) // 2
                        d1_h   = bh * 2 // 7
                        d1_y   = deck_y - d1_h
                        cab_c1 = self._dim((215, 205, 185), mult)
                        pygame.draw.rect(self.screen, cab_c1, (cab_x, d1_y, cab_w, d1_h))
                        pygame.draw.rect(self.screen, outline, (cab_x, d1_y, cab_w, d1_h), 1)
                        # Deck 2
                        d2_w   = cab_w * 4 // 5
                        d2_x   = cab_x + (cab_w - d2_w) // 2
                        d2_h   = bh * 2 // 7
                        d2_y   = d1_y - d2_h
                        cab_c2 = self._dim((230, 222, 205), mult)
                        pygame.draw.rect(self.screen, cab_c2, (d2_x, d2_y, d2_w, d2_h))
                        pygame.draw.rect(self.screen, outline, (d2_x, d2_y, d2_w, d2_h), 1)
                        win_col = (255, 240, 140) if is_dark else self._dim((100, 150, 200), mult)
                        ww = max(3, cab_w // 8)
                        for i in range(4):
                            pygame.draw.rect(self.screen, win_col,
                                             (cab_x + 4 + i * (cab_w // 4), d1_y + 3, ww, d1_h - 6))
                        for i in range(3):
                            pygame.draw.rect(self.screen, win_col,
                                             (d2_x + 4 + i * (d2_w // 3), d2_y + 3, ww, d2_h - 6))
                        # Paddle wheel at stern
                        pw_w = max(10, bw // 6)
                        pw_h = bh * 2 // 3
                        pw_x  = lx - pw_w + 2 if ag.direction == 1 else rx - 2
                        pw_y  = deck_y - pw_h // 2
                        pw_col = self._dim((75, 38, 18), mult)
                        pygame.draw.rect(self.screen, pw_col, (pw_x, pw_y, pw_w, pw_h))
                        pygame.draw.rect(self.screen, outline, (pw_x, pw_y, pw_w, pw_h), 1)
                        wrot = self.time * 8 if ag.is_moving else 0
                        for i in range(4):
                            oy_ = int(math.sin(wrot + i * math.pi / 2) * (pw_h // 2 - 2))
                            pygame.draw.line(self.screen, outline,
                                             (pw_x + 2, pw_y + pw_h // 2 + oy_),
                                             (pw_x + pw_w - 2, pw_y + pw_h // 2 + oy_), 1)
                        # Smokestacks
                        for i in range(2):
                            sx_ = d2_x + (d2_w // 3) * (i + 1) - 2
                            sy_ = d2_y - 9
                            pygame.draw.rect(self.screen, self._dim((35, 35, 35), mult), (sx_, sy_, 4, 10))
                            if ag.is_moving:
                                for s in range(3):
                                    st = (self.time * 2 + s * 0.5) % 1.5
                                    sm = int(2 + st * 4)
                                    sa = int(255 * (1 - st / 1.5))
                                    ss = pygame.Surface((sm * 2, sm * 2), pygame.SRCALPHA)
                                    pygame.draw.circle(ss, (150, 150, 150, sa), (sm, sm), sm)
                                    self.screen.blit(ss, (sx_ + 2 - sm, sy_ - 4 - int(st * 18)))
                        if is_dark:
                            l_col = self.GREEN if ag.direction == 1 else self.RED
                            bow_lx = rx - 3 if ag.direction == 1 else lx + 3
                            pygame.draw.circle(self.screen, self._dim(l_col, mult), (bow_lx, deck_y), 2)

                    # Waterline shimmer below all boats
                    pygame.draw.line(self.screen, self._dim(self.WATER_SHIMMER, mult),
                                     (lx - 2, by), (rx + 2, by), 2)

                    # Name tag
                    lbl = self.fnt_sm.render(boat.name, True, self._dim(self.WHITE, mult))
                    tag = pygame.Surface((lbl.get_width() + 6, lbl.get_height() + 3), pygame.SRCALPHA)
                    tag.fill((0, 0, 0, 130))
                    self.screen.blit(tag, (lx, ty - lbl.get_height() - 6))
                    self.screen.blit(lbl, (lx + 3, ty - lbl.get_height() - 5))

                    # Permanent ropes for tied boats
                    if ag.tied_down:
                        rope_col = self._dim((180, 170, 130), mult)
                        target_by = boat_y + boat_h // 2
                        if ag.tied_side == op['side']:
                            # Tied to our wall
                            pygame.draw.line(self.screen, rope_col, (int(screen_cx), self.height), (int(screen_cx), int(target_by)), 4)
                        else:
                            # Tied to opposite wall
                            pygame.draw.line(self.screen, rope_col, (int(screen_cx), water_y), (int(screen_cx), int(target_by)), 4)

        # Active task rope (throwing/pulling)
        if op['target_boat'] and op['rope_progress'] > 0:
            target_ag = op['target_boat']
            rel_x = (target_ag.boat.position + target_ag.boat.length / 2) - op['x']
            screen_cx = self.width // 2 + rel_x * pov_scale
            
            # Vertical pos of target boat
            side_of_boat = 1 if target_ag.direction == -1 else 0
            lane_y_off = 120 if side_of_boat == op['side'] else 20
            boat_y = water_y + (10 - lvl) * 25 + lane_y_off
            boat_h = int(target_ag.boat.beam * pov_scale)
            target_by = boat_y + boat_h // 2
            
            rope_col = self._dim((180, 170, 130), mult)
            curr_rx = self.width // 2 + (screen_cx - self.width // 2) * op['rope_progress']
            curr_ry = self.height - (self.height - target_by) * op['rope_progress']
            pygame.draw.line(self.screen, rope_col, (self.width // 2, self.height), (int(curr_rx), int(curr_ry)), 8)

        # Foreground: The wall the operator is standing on
        pygame.draw.rect(self.screen, conc_col, (0, 700, self.width, 100))
        pygame.draw.line(self.screen, conc_dark, (0, 705), (self.width, 705), 4)

        # POV Text
        txt = self.fnt_md.render("FIRST-PERSON VIEW: LOCK OPERATOR", True, self.WHITE)
        self.screen.blit(txt, (self.width // 2 - txt.get_width() // 2, 30))
        inst = self.fnt_sm.render("Press V to return to Shore View", True, (200, 200, 200))
        self.screen.blit(inst, (self.width // 2 - inst.get_width() // 2, 60))

    def _draw_miter_gate(self, gate_x, wall_top, floor_y, progress, faces_right, top_face_scale=1.0, top_shrink=0):
        """Draw a miter gate pair animated by progress (0.0=closed, 1.0=open).

        Two leaves pivot on point hinges at opposite wall corners:
          - Upper leaf: hinge at (gate_x, wall_top); free end arcs into the outer channel.
          - Lower leaf: hinge at (gate_x, floor_y);  free end arcs into the outer channel.

        Upstream gate (faces_right=True):  leaves fold LEFT into the upstream channel.
        Downstream gate (faces_right=False): leaves fold RIGHT into the downstream channel.
        """
        mult      = self._get_ambient_mult()
        base      = (int(72 + 14 * progress), int(82 + 16 * progress), int(95 + 17 * progress))
        color     = self._dim(base, mult)
        edge      = self._dim((40, 46, 54), mult)
        rib       = self._dim((56, 64, 76), mult)
        hi        = self._dim((95, 108, 124), mult)
        hinge_col = self._dim((30, 34, 40), mult)

        angle = progress * math.pi / 2
        sin_a = math.sin(angle)
        cos_a = math.cos(angle)

        mid_y = (wall_top + floor_y) // 2
        L_u   = mid_y - wall_top   # upper leaf arm length (px)
        L_l   = floor_y - mid_y   # lower leaf arm length (px)
        lw    = 15                 # leaf thickness (px) — the physical gate depth
        half  = lw // 2

        # Direction the leaves sweep into when opening
        x_sign = -1 if faces_right else 1   # −1 = left/upstream, +1 = right/downstream

        # ── Upper leaf ─────────────────────────────────────────────────────────
        # Hinge at (gate_x, wall_top) — top of the gate opening (= water surface).
        # Closed: arm hangs down to mid_y.
        # Opening: arm sweeps x_sign direction; free end arcs from mid_y back up to wall_top.
        # When fully open the leaf lies flat at wall_top (water-surface) level.
        uf_x = int(gate_x + x_sign * L_u * sin_a)
        uf_y = int(wall_top + L_u * cos_a)   # = mid_y when closed, wall_top when open

        # Leaf direction = (x_sign·sin_a, cos_a). Perpendicular = (cos_a, −x_sign·sin_a).
        # Face grows visible as the leaf rotates outward (edge-on→face-on).
        up_half = max(half, int(sin_a * L_u * 0.35 * top_face_scale))
        # top_shrink clips the "outward" edge (corners 0 & 3) so the leaf doesn't
        # extend too far in the sky; the "inward" edge (corners 1 & 2) is unchanged.
        shrunk  = max(half, up_half - int(sin_a * top_shrink))
        up_px_a = int(cos_a          * shrunk)    # outward corners
        up_py_a = int(-x_sign * sin_a * shrunk)
        up_px_b = int(cos_a          * up_half)   # inward corners
        up_py_b = int(-x_sign * sin_a * up_half)

        pts_u = [
            (gate_x + up_px_a, wall_top + up_py_a),   # hinge end, outward
            (gate_x - up_px_b, wall_top - up_py_b),   # hinge end, inward
            (uf_x   - up_px_b, uf_y    - up_py_b),    # free end,  inward
            (uf_x   + up_px_a, uf_y    + up_py_a),    # free end,  outward
        ]

        # ── Lower leaf ─────────────────────────────────────────────────────────
        # Hinge at (gate_x, floor_y). Closed: points straight up to mid_y.
        # Opening: free end arcs x_sign direction (DOWN and out into the channel).
        lf_x = int(gate_x + x_sign * L_l * sin_a)
        lf_y = int(floor_y - L_l * cos_a)

        # Perpendicular to leaf direction (x_sign·sin_a, −cos_a) → (cos_a, x_sign·sin_a)
        lo_px = int(cos_a   * half)
        lo_py = int(x_sign  * sin_a * half)

        pts_l = [
            (gate_x + lo_px, floor_y + lo_py),
            (gate_x - lo_px, floor_y - lo_py),
            (lf_x   - lo_px, lf_y    - lo_py),
            (lf_x   + lo_px, lf_y    + lo_py),
        ]

        for pts in (pts_u, pts_l):
            pygame.draw.polygon(self.screen, color, pts)
            pygame.draw.polygon(self.screen, edge,  pts, 1)
            # Cross-brace ribs on the panel face (visible when mostly closed)
            if progress < 0.82:
                pygame.draw.line(self.screen, rib, pts[0], pts[2], 1)
                pygame.draw.line(self.screen, rib, pts[1], pts[3], 1)

        # Hinge pin circles — upper leaf pivots at wall_top, lower at floor_y
        for py in (wall_top + 4, wall_top + 14):
            pygame.draw.circle(self.screen, hinge_col, (gate_x, py), 3)
            pygame.draw.circle(self.screen, hi,         (gate_x, py), 3, 1)
        for py in (floor_y - 14, floor_y - 4):
            pygame.draw.circle(self.screen, hinge_col, (gate_x, py), 3)
            pygame.draw.circle(self.screen, hi,         (gate_x, py), 3, 1)

        # Status light
        lx_light = gate_x - 5 if faces_right else gate_x + 5
        pygame.draw.circle(self.screen,
                           self._dim(self.GREEN if progress > 0.5 else self.RED, mult),
                           (lx_light, wall_top + 8), 3)
        pygame.draw.circle(self.screen, edge, (lx_light, wall_top + 8), 3, 1)

    def _draw_boat_shore(self, ag, up_y, dn_y, lk_y, lk_sx, lk_ex):
        boat  = ag.boat
        vtype = boat.vessel_type
        bx    = self._sx(boat.position)
        bw   = max(self._sx(boat.position + boat.length) - bx, 8)

        cx     = boat.position + boat.length / 2   # sim-space centre
        surf_y = up_y if cx < self.lock_start else (dn_y if cx > self.lock_end else lk_y)
        hull_y = self._lane_y(ag, surf_y)
        bh     = max(int(boat.beam * 2.2), 8)

        if ag.state == "crashed":
            hull_col = self.RED
            outline  = (140, 25, 25)
        else:
            hull_col = self._boat_color(boat)
            outline  = self.DARK_GRAY

        mult = self._get_ambient_mult()
        hull_col = self._dim(hull_col, mult)
        outline = self._dim(outline, mult)
        is_dark = self.game_time < 6.5 or self.game_time > 18.5

        # Clip drawing to the boat's region so hulls never paint over lock walls.
        wt  = self._WALL_T_PX
        if cx < self.lock_start:
            clip = pygame.Rect(0, 0, lk_sx, self.height)
        elif cx > self.lock_end:
            clip = pygame.Rect(lk_ex, 0, self.width - lk_ex, self.height)
        else:
            clip = pygame.Rect(lk_sx + wt, 0, lk_ex - lk_sx - 2 * wt, self.height)

        prev_clip = self.screen.get_clip()
        self.screen.set_clip(clip)

        # ── Wake ──────────────────────────────────────────────────────────────
        if ag.state == "active" and ag.is_moving:
            wake_len = 20 + ag.speed * 10
            wake_col = (200, 220, 240, 100)
            wake_surf = pygame.Surface((wake_len, bh + 10), pygame.SRCALPHA)
            
            # For barges, the wake starts behind the tug boat.
            wx = bx
            if vtype == "barge":
                tug_w = max(20, bw // 4)
                wx -= (tug_w - 5) if ag.direction == 1 else -(bw + tug_w - 5)
            else:
                wx = bx if ag.direction == 1 else bx + bw

            if ag.direction == 1:
                pygame.draw.polygon(wake_surf, wake_col, [(0, 5), (wake_len, 0), (wake_len, bh+10), (0, bh+5)])
                self.screen.blit(wake_surf, (wx - wake_len, hull_y - bh//2 - 5))
            else:
                pygame.draw.polygon(wake_surf, wake_col, [(wake_len, 5), (0, 0), (0, bh+10), (wake_len, bh+5)])
                self.screen.blit(wake_surf, (wx, hull_y - bh//2 - 5))

        # ── Hull ──────────────────────────────────────────────────────────────
        ty = hull_y - bh // 2
        by = hull_y + bh // 2

        if vtype == "kayak":
            # Double pointed
            pts = [(bx, hull_y), (bx + bw // 2, ty), (bx + bw, hull_y), (bx + bw // 2, by)]
            pygame.draw.polygon(self.screen, hull_col, pts)
            pygame.draw.polygon(self.screen, outline,  pts, 1)
            # Cockpit
            pygame.draw.ellipse(self.screen, self.BLACK, (bx + bw//2 - 2, hull_y - 2, 4, 4))
            if is_dark:
                lx = bx + bw if ag.direction == 1 else bx
                pygame.draw.circle(self.screen, (255, 255, 200), (lx, hull_y), 2)

        elif vtype == "yacht":
            bow_cut = max(6, bw // 4)
            if ag.direction == 1:
                pts = [(bx, ty), (bx + bw - bow_cut, ty), (bx + bw, hull_y), (bx + bw - bow_cut, by), (bx, by)]
            else:
                pts = [(bx + bow_cut, ty), (bx + bw, ty), (bx + bw, by), (bx + bow_cut, by), (bx, hull_y)]
            pygame.draw.polygon(self.screen, hull_col, pts)
            pygame.draw.polygon(self.screen, outline,  pts, 2)
            # Cabin
            cab_w, cab_h = bw // 2, bh - 4
            cx_off = (bw - cab_w) // 3 if ag.direction == 1 else (bw - cab_w) // 1.5
            pygame.draw.rect(self.screen, self._dim((200, 200, 200), mult), (bx + cx_off, hull_y - cab_h // 2, cab_w, cab_h))
            pygame.draw.rect(self.screen, outline, (bx + cx_off, hull_y - cab_h // 2, cab_w, cab_h), 1)
            # Windows
            win_w = max(2, cab_w // 4)
            win_col = (255, 240, 150) if is_dark else self._dim((100, 150, 200), mult)
            for i in range(3):
                pygame.draw.rect(self.screen, win_col, (bx + cx_off + 2 + i * (win_w + 2), hull_y - cab_h // 2 + 2, win_w, cab_h - 4))
            
            if is_dark:
                # Nav lights
                lx = bx + bw - 4 if ag.direction == 1 else bx + 4
                l_col = self.GREEN if ag.direction == 1 else self.RED
                pygame.draw.circle(self.screen, l_col, (lx, hull_y - 2), 2)
                # Stern
                sx = bx + 2 if ag.direction == 1 else bx + bw - 2
                pygame.draw.circle(self.screen, self.WHITE, (sx, hull_y - 2), 2)

        elif vtype == "barge":
            pygame.draw.rect(self.screen, hull_col, (bx, ty, bw, bh))
            pygame.draw.rect(self.screen, outline,  (bx, ty, bw, bh), 2)
            # Cargo
            cargo_col = self._dim((100, 80, 60), mult)
            for i in range(3):
                cargo_x = bx + 5 + i * (bw - 10) // 3
                pygame.draw.rect(self.screen, cargo_col, (cargo_x, ty + 3, (bw - 10) // 3 - 2, bh - 6))
            
            # Towboat (pushing from behind) — flat-bowed river pusher
            tug_w = max(20, bw // 4)
            if ag.direction == 1:
                tx = bx - tug_w + 5   # flat bow flush against barge stern
            else:
                tx = bx + bw - 5
            ty_tug = ty   # same top as barge hull

            # Dark lower hull — full barge height
            tug_hull_col = self._dim((38, 38, 42), mult)
            pygame.draw.rect(self.screen, tug_hull_col, (tx, ty_tug, tug_w, bh))
            pygame.draw.rect(self.screen, outline, (tx, ty_tug, tug_w, bh), 1)

            # Wheelhouse — tall superstructure above deck
            wh_w = max(8, tug_w * 3 // 4)
            wh_h = bh - 2
            wh_x = tx + (tug_w - wh_w) // 2
            wh_y = ty_tug - wh_h
            tc_col = (255, 200, 100) if is_dark else self._dim((210, 55, 50), mult)
            pygame.draw.rect(self.screen, tc_col, (wh_x, wh_y, wh_w, wh_h))
            pygame.draw.rect(self.screen, outline, (wh_x, wh_y, wh_w, wh_h), 1)
            # Wheelhouse windows
            win_col = (255, 245, 150) if is_dark else self._dim((140, 200, 235), mult)
            win_w = max(2, wh_w // 4)
            for i in range(2):
                pygame.draw.rect(self.screen, win_col,
                                 (wh_x + 2 + i * (wh_w // 2), wh_y + 2, win_w, wh_h - 4))

            # Two smokestacks at stern (away from barges)
            stk_col = self._dim((22, 22, 22), mult)
            stk_h = bh // 2 + 2
            if ag.direction == 1:
                s1x, s2x = tx + tug_w - 8, tx + tug_w - 13
            else:
                s1x, s2x = tx + 5, tx + 10
            pygame.draw.rect(self.screen, stk_col, (s1x, wh_y - stk_h, 3, stk_h + 2))
            pygame.draw.rect(self.screen, stk_col, (s2x, wh_y - stk_h + 2, 3, stk_h))

            if is_dark:
                # Masthead nav light
                pygame.draw.circle(self.screen, self.WHITE, (tx + tug_w // 2, wh_y - 2), 2)

        elif vtype == "paddleboat":
            # Chunky rectangular hull with rounded bow
            bow_w = max(10, bw // 4)
            if ag.direction == 1:
                pts = [(bx, ty), (bx + bw - bow_w, ty), (bx + bw, hull_y), (bx + bw - bow_w, by), (bx, by)]
            else:
                pts = [(bx + bow_w, ty), (bx + bw, ty), (bx + bw, by), (bx + bow_w, by), (bx, hull_y)]
            pygame.draw.polygon(self.screen, hull_col, pts)
            pygame.draw.polygon(self.screen, outline,  pts, 2)

            # Cabin - large and central
            cab_w, cab_h = bw // 1.5, bh - 6
            cx_off = (bw - cab_w) // 2
            pygame.draw.rect(self.screen, self._dim((220, 210, 190), mult), (bx + cx_off, hull_y - cab_h // 2, cab_w, cab_h))
            pygame.draw.rect(self.screen, outline, (bx + cx_off, hull_y - cab_h // 2, cab_w, cab_h), 1)

            # Windows (glowing at night)
            win_col = (255, 240, 150) if is_dark else self._dim((100, 150, 200), mult)
            for i in range(4):
                wx = bx + cx_off + 4 + i * (cab_w - 8) // 4
                pygame.draw.rect(self.screen, win_col, (wx, hull_y - cab_h // 2 + 3, (cab_w - 12) // 4, cab_h - 6))

            # Paddle wheel in the back
            wheel_w, wheel_h = max(12, bw // 6), bh + 4
            if ag.direction == 1:
                wx = bx - wheel_w + 2
            else:
                wx = bx + bw - 2
            
            # Animation for wheel
            wheel_rot = self.time * 8 if ag.is_moving else 0
            wheel_col = self._dim((80, 40, 20), mult)
            pygame.draw.rect(self.screen, wheel_col, (wx, hull_y - wheel_h // 2, wheel_w, wheel_h))
            pygame.draw.rect(self.screen, outline, (wx, hull_y - wheel_h // 2, wheel_w, wheel_h), 1)
            # Spokes/Blades
            for i in range(4):
                angle = wheel_rot + i * (math.pi / 2)
                offset = int(math.sin(angle) * (wheel_h // 2 - 2))
                pygame.draw.line(self.screen, outline, (wx + 2, hull_y + offset), (wx + wheel_w - 2, hull_y + offset), 1)

            # Smoke stacks
            stack_col = self._dim((40, 40, 40), mult)
            for i in range(2):
                sx = bx + cx_off + (cab_w // 3) * (i + 1) - 2
                sy = hull_y - cab_h // 2 - 8
                pygame.draw.rect(self.screen, stack_col, (sx, sy, 4, 10))
                # Animated smoke
                if ag.is_moving:
                    for s in range(3):
                        st = (self.time * 2 + s * 0.5) % 1.5
                        smoke_size = 2 + st * 4
                        smoke_alpha = int(255 * (1 - st / 1.5))
                        smoke_surf = pygame.Surface((smoke_size * 2, smoke_size * 2), pygame.SRCALPHA)
                        pygame.draw.circle(smoke_surf, (150, 150, 150, smoke_alpha), (smoke_size, smoke_size), smoke_size)
                        self.screen.blit(smoke_surf, (sx + 2 - smoke_size, sy - 5 - st * 20))

            if is_dark:
                # Nav lights
                lx = bx + bw - 4 if ag.direction == 1 else bx + 4
                l_col = self.GREEN if ag.direction == 1 else self.RED
                pygame.draw.circle(self.screen, l_col, (lx, hull_y - 2), 2)

        else: # Default trapezoid
            bow_cut = max(4, bw // 5)
            if ag.direction == 1:
                pts = [(bx, ty), (bx + bw - bow_cut, ty), (bx + bw, hull_y), (bx + bw - bow_cut, by), (bx, by)]
            else:
                pts = [(bx + bow_cut, ty), (bx + bw, ty), (bx, hull_y), (bx + bw, by), (bx + bow_cut, by)]
            pygame.draw.polygon(self.screen, hull_col, pts)
            pygame.draw.polygon(self.screen, outline,  pts, 2)

        pygame.draw.line(self.screen, self.WATER_SHIMMER,
                         (bx - 2, hull_y), (bx + bw + 2, hull_y), 1)

        lbl = self.fnt_sm.render(boat.name, True, self.BLACK)
        tag = pygame.Surface((lbl.get_width() + 6, lbl.get_height() + 3), pygame.SRCALPHA)
        tag.fill((255, 255, 255, 190))
        self.screen.blit(tag, (bx,     ty - lbl.get_height() - 6))
        self.screen.blit(lbl, (bx + 3, ty - lbl.get_height() - 5))

        self.screen.set_clip(prev_clip)

    def _wl_label(self, cx, surf_y, title, level):
        t1 = self.fnt_sm.render(title, True, self.WHITE)
        t2 = self.fnt_sm.render(f"{level:.1f} m", True, self.WATER_SHIMMER)
        self.screen.blit(t1, (cx - t1.get_width() // 2, surf_y - 36))
        self.screen.blit(t2, (cx - t2.get_width() // 2, surf_y - 20))

    # ── Input ─────────────────────────────────────────────────────────────────

    def handle_input(self):
        """Return 'continue', 'menu', or 'quit'."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return 'quit'
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._radio_popup:
                    # Option selection
                    for rect, rec in zip(self._radio_popup['option_rects'],
                                         self._radio_popup['options']):
                        if rect.collidepoint(event.pos):
                            self._select_radio_option(rec)
                            break
                    else:
                        # Close button
                        cr = self._radio_popup.get('close_rect')
                        if cr and cr.collidepoint(event.pos):
                            self._radio_popup = None
                else:
                    for btn_rect, ag in self._roster_buttons:
                        if btn_rect.collidepoint(event.pos):
                            self._open_radio_popup(ag)
                            break
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if self._radio_popup:
                        self._radio_popup = None
                        continue
                    return 'menu'
                elif event.key == pygame.K_g:
                    self._toggle_upstream_gate()
                elif event.key == pygame.K_h:
                    self._toggle_downstream_gate()
                elif event.key == pygame.K_f:
                    self.lock_dam.fill_chamber()
                elif event.key == pygame.K_d:
                    self.lock_dam.drain_chamber()
                elif event.key == pygame.K_v:
                    self.view_mode = "operator" if self.view_mode == "shore" else "shore"
                # Developer controls
                elif self.dev_mode:
                    if event.key == pygame.K_RIGHTBRACKET:
                        self.time_scale = min(60.0, self.time_scale * 2.0)
                    elif event.key == pygame.K_LEFTBRACKET:
                        self.time_scale = max(0.5, self.time_scale / 2.0)
                    elif event.key == pygame.K_END:
                        if self._cfg_shift_duration is not None:
                            self.shift_hours_elapsed = self._cfg_shift_duration
        return 'continue'

    def _toggle_upstream_gate(self):
        if not self.lock_dam.upstream_gates_open:
            diff = abs(self.lock_dam.lock_chamber_level - self.lock_dam.upstream_level)
            if diff > self.SURGE_THRESHOLD:
                self._surge_incident(
                    f"SURGE: upstream gate — {diff:.1f} m differential!")
        self.lock_dam.upstream_gates_open = not self.lock_dam.upstream_gates_open

    def _toggle_downstream_gate(self):
        if not self.lock_dam.downstream_gates_open:
            diff = abs(self.lock_dam.lock_chamber_level - self.lock_dam.downstream_level)
            if diff > self.SURGE_THRESHOLD:
                self._surge_incident(
                    f"SURGE: downstream gate — {diff:.1f} m differential!")
        self.lock_dam.downstream_gates_open = not self.lock_dam.downstream_gates_open

    def _update_operator(self, dt):
        op = self.operator

        # Advance wall-crossing animation; block other logic until complete.
        if op['state'] == 'crossing':
            # Match the same pixel-per-frame rate used for horizontal walking
            # (1.2 sim-units/frame × screen scale) relative to the gate height.
            walk_px_per_frame = 1.2 * self._sx_scale
            top_y_px    = self._wy(self.lock_dam.upstream_level) - 35 - 5
            bottom_y_px = self._water_bot_y + 10
            cross_dist  = max(1, abs(bottom_y_px - top_y_px))
            op['cross_progress'] = min(1.0, op['cross_progress'] + walk_px_per_frame / cross_dist)
            if op['cross_progress'] >= 1.0:
                op['side']           = op['target_side']
                op['cross_progress'] = 0.0
                op['state']          = 'idle'
            return

        # 1. Identify tasks
        tying_tasks = []
        untying_tasks = []
        for ag in self.agents:
            if ag.state == "active":
                # Tying: Stopped, not tied, MUST be fully inside
                if self._fully_in_lock(ag.boat) and not ag.is_moving and not ag.tied_down:
                    tying_tasks.append(ag)
                # Untying: Tied, ready to go (exit gate open)
                if ag.tied_down:
                    ready = False
                    if ag.direction == 1: # Downstream
                        if self.lock_dam.downstream_gates_open:
                            ready = True
                    else: # Upstream
                        if self.lock_dam.upstream_gates_open:
                            ready = True
                    if ready:
                        untying_tasks.append(ag)

        # 2. Pick a task if none active
        if op['target_boat'] is None:
            if untying_tasks: # Prioritize untying so boats can leave
                op['target_boat'] = untying_tasks[0]
                op['task'] = 'untie'
                op['rope_progress'] = 1.0 # Start with rope attached
            elif tying_tasks:
                op['target_boat'] = tying_tasks[0]
                op['task'] = 'tie'
                op['rope_progress'] = 0.0
            else:
                op['task'] = None
        
        # 3. Execute task
        if op['target_boat']:
            target_ag = op['target_boat']
            # Check if task is still valid
            is_valid = target_ag.state == "active"
            if is_valid:
                if op['task'] == 'tie':
                    # Must stay stopped and mostly inside to tie
                    if target_ag.is_moving or not self._in_lock(target_ag.boat):
                        is_valid = False
                else: # untie
                    # Must stay in lock to untie
                    if not self._in_lock(target_ag.boat):
                        is_valid = False
            
            if not is_valid:
                op['target_boat'] = None
                return

            # Determine side for the boat: +1 downstream is top side (0), -1 upstream is bottom side (1)
            boat_side = 0 if target_ag.direction == 1 else 1
            
            if op['side'] != boat_side:
                # Need to cross to the other wall via a closed gate
                u_open = self.lock_dam.upstream_gates_open
                d_open = self.lock_dam.downstream_gates_open
                u_dist = abs(op['x'] - self.lock_start)
                d_dist = abs(op['x'] - self.lock_end)
                
                gate_x = None
                if not u_open and not d_open:
                    gate_x = self.lock_start if u_dist < d_dist else self.lock_end
                elif not u_open:
                    gate_x = self.lock_start
                elif not d_open:
                    gate_x = self.lock_end
                
                if gate_x is not None:
                    dx = gate_x - op['x']
                    if abs(dx) > 1.0:
                        op['state'] = 'walking'
                        op['x'] += 1.2 if dx > 0 else -1.2
                    else:
                        # Begin animated crossing to the other wall.
                        op['state']          = 'crossing'
                        op['target_side']    = boat_side
                        op['cross_progress'] = 0.0
                else:
                    # Both gates open? Wait at the best spot.
                    op['state'] = 'waiting'
            else:
                # On the correct side, walk to boat center (clamped to lock wall)
                target_x = target_ag.boat.position + target_ag.boat.length / 2
                target_x = max(self.lock_start, min(self.lock_end, target_x))
                dx = target_x - op['x']
                if abs(dx) > 1.0:
                    op['state'] = 'walking'
                    op['x'] += 1.2 if dx > 0 else -1.2
                else:
                    # At boat, perform tie or untie
                    if op['task'] == 'tie':
                        op['state'] = 'tying'
                        if op['rope_progress'] < 1.0:
                            op['rope_progress'] = min(1.0, op['rope_progress'] + 0.05)
                        else:
                            target_ag.tied_down = True
                            target_ag.tied_side = op['side']
                            op['target_boat'] = None # Task finished
                    elif op['task'] == 'untie':
                        op['state'] = 'untying'
                        if op['rope_progress'] > 0.0:
                            op['rope_progress'] = max(0.0, op['rope_progress'] - 0.05)
                        else:
                            target_ag.tied_down = False
                            target_ag.tied_side = None
                            self._trigger_radio_departure(target_ag)
                            op['target_boat'] = None # Task finished
        else:
            # No task: Return to idle position on top side (0) near upstream gate
            if op['side'] != 0:
                # Need to cross back
                u_open = self.lock_dam.upstream_gates_open
                d_open = self.lock_dam.downstream_gates_open
                gate_x = self.lock_start if not u_open else (self.lock_end if not d_open else None)
                if gate_x is not None:
                    dx = gate_x - op['x']
                    if abs(dx) > 1.0:
                        op['state'] = 'walking'
                        op['x'] += 1.2 if dx > 0 else -1.2
                    else:
                        # Begin animated crossing back to top wall.
                        op['state']          = 'crossing'
                        op['target_side']    = 0
                        op['cross_progress'] = 0.0
                else:
                    op['state'] = 'idle'
            else:
                target_x = self.lock_start + 10
                dx = target_x - op['x']
                if abs(dx) > 1.0:
                    op['state'] = 'walking'
                    op['x'] += 0.8 if dx > 0 else -0.8
                else:
                    op['state'] = 'idle'
            
            # Gradually retract rope if visible
            if op['rope_progress'] > 0:
                op['rope_progress'] = max(0.0, op['rope_progress'] - 0.05)

    # ── Gate animation ────────────────────────────────────────────────────────

    def _update_gate_anims(self):
        """Advance gate open/close animation by one frame toward their target state."""
        speed = 0.025  # ~40 frames = 0.67 s to fully open or close
        target_up = 1.0 if self.lock_dam.upstream_gates_open   else 0.0
        target_dn = 1.0 if self.lock_dam.downstream_gates_open else 0.0
        if self._gate_anim_up < target_up:
            self._gate_anim_up = min(target_up, self._gate_anim_up + speed)
        elif self._gate_anim_up > target_up:
            self._gate_anim_up = max(target_up, self._gate_anim_up - speed)
        if self._gate_anim_dn < target_dn:
            self._gate_anim_dn = min(target_dn, self._gate_anim_dn + speed)
        elif self._gate_anim_dn > target_dn:
            self._gate_anim_dn = max(target_dn, self._gate_anim_dn - speed)

    # ── Agent simulation ──────────────────────────────────────────────────────

    def _update_weather(self, dt):
        # Move clouds
        for c in self.clouds:
            c['x'] += c['speed']
            if c['x'] > self.width + 100:
                c['x'] = -200
                c['y'] = random.uniform(10, 140)

        # Weather state transitions
        self.weather_timer -= 1
        if self.weather_timer <= 0:
            self.rain_active = not self.rain_active
            if self.rain_active:
                self.weather_timer = random.randint(1200, 2400) # Rain lasts 20-40s
            else:
                self.weather_timer = random.randint(3600, 9000) # Clear lasts 1-2.5m

        # Lightning timer always runs down so the bolt never gets stuck
        if self.lightning_timer > 0:
            self.lightning_timer -= 1
            if self.lightning_timer == 0:
                self.lightning_bolt = None

        # Update rain drops
        if self.rain_active:
            for d in self.rain_drops:
                d['y'] += d['s']
                d['x'] -= 2 # slanted rain
                if d['y'] > self.height:
                    d['y'] = -10
                    d['x'] = random.randint(0, self.width + 100)

            # New lightning strikes only while raining
            if self.lightning_timer == 0 and random.random() < 0.003:
                self.lightning_timer = random.randint(5, 12)
                bx = random.randint(100, self.width - 100)
                by = 0
                self.lightning_bolt = [(bx, by)]
                for _ in range(6):
                    by += random.randint(40, 100)
                    bx += random.randint(-50, 50)
                    self.lightning_bolt.append((bx, by))

    def _update_nature(self, dt):
        h = self.game_time
        is_day = 6.0 <= h < 19.5
        
        for b in self.birds:
            if is_day:
                if b['state'] == 'sleeping' or b['state'] == 'homing':
                    b['state'] = 'flying'
                    b['vx'] = random.uniform(0.5, 1.5)
                    b['vy'] = random.uniform(-0.3, 0.3)
                
                # Normal flight
                b['x'] += b['vx']
                b['y'] += b['vy']
                
                # Randomly change direction slightly
                if random.random() < 0.01:
                    b['vx'] = random.uniform(0.5, 1.5)
                    b['vy'] = random.uniform(-0.3, 0.3)
                
                # Screen wrap
                if b['x'] > self.width + 20:
                    b['x'] = -20
                    b['y'] = random.uniform(50, 150)
                elif b['x'] < -20:
                    b['x'] = self.width + 20
                    b['y'] = random.uniform(50, 150)
            else:
                # Night time - go to sleep
                if b['state'] == 'flying':
                    b['state'] = 'homing'
                    b['target_tree'] = random.choice(self.trees)
                
                if b['state'] == 'homing':
                    # Find target screen coords
                    tree = b['target_tree']
                    tx = self._sx(tree['x'])
                    ty = 0
                    if tree['type'] == 'up': ty = self._wy(self.lock_dam.upstream_level) - 45
                    elif tree['type'] == 'chamber': ty = self._wy(self.lock_dam.lock_chamber_level) - 45
                    else: ty = self._wy(self.lock_dam.downstream_level) - 45
                    
                    dx = tx - b['x']
                    dy = ty - b['y']
                    dist = math.sqrt(dx*dx + dy*dy)
                    if dist < 3:
                        b['state'] = 'sleeping'
                        b['x'], b['y'] = tx, ty
                    else:
                        speed = 3.0
                        b['x'] += (dx / dist) * speed
                        b['y'] += (dy / dist) * speed

    # ── Asset-DB helpers ──────────────────────────────────────────────────────

    def _load_captain_portraits(self, db) -> dict:
        """
        Return {vessel_name: pygame.Surface} for every captain that has a portrait.
        Portrait path is looked up via art_assets tags: 'crew_id:<n>'.
        """
        portrait_dir = os.path.join('assets', 'generated', 'portraits')
        portraits = {}
        try:
            captains = db.crew_list(role='captain')
            logger.debug("_load_captain_portraits: %d captains found", len(captains))
            all_char_assets = db.art_assets(category='character')
            for cap in captains:
                vessel = cap.get('vessel_name')
                cid = cap['id']
                if not vessel:
                    logger.debug("  crew_id=%d (%s): no vessel_name, skipping",
                                 cid, cap.get('name'))
                    continue
                tag_target = f"crew_id:{cid}"
                matching = [
                    a for a in all_char_assets
                    if tag_target in [t.strip() for t in (a.get('tags') or '').split(',')]
                ]
                # Always record crew_id so debug logging works even without a portrait.
                self._captain_meta[vessel] = {
                    'crew_id':  cid,
                    'filename': None,
                    'name':     cap.get('name', ''),
                }

                if not matching:
                    logger.debug("  crew_id=%d (%s) vessel=%r: no art_asset tagged %r",
                                 cid, cap.get('name'), vessel, tag_target)
                    continue
                filename = matching[0]['filename']
                filepath = os.path.join(portrait_dir, filename)
                if not os.path.exists(filepath):
                    logger.debug("  crew_id=%d (%s) vessel=%r: asset %r registered but file missing at %r",
                                 cid, cap.get('name'), vessel, filename, filepath)
                    continue
                try:
                    surf = pygame.image.load(filepath).convert_alpha()
                    portraits[vessel] = surf
                    self._captain_meta[vessel]['filename'] = filename
                    logger.debug("  crew_id=%d (%s) vessel=%r: loaded portrait %r",
                                 cid, cap.get('name'), vessel, filename)
                except Exception as exc:
                    logger.debug("  crew_id=%d (%s) vessel=%r: failed to load %r — %s",
                                 cid, cap.get('name'), vessel, filename, exc)
        except Exception as exc:
            logger.debug("_load_captain_portraits: exception — %s", exc)
        return portraits

    @staticmethod
    def _reading_ttl(text: str) -> int:
        """Frames to display a message at ~3.5 words/sec with a 1.5 s lead-in."""
        words = len(text.split())
        return max(300, int((words / 3.5 + 1.5) * 60))

    # Keywords that identify a "currently entering the lock" transmission
    _ENTRY_KEYWORDS  = ('entering', 'proceeding to chamber', 'entering chamber')
    # Keywords that identify a "lines cleared / departing lock" transmission
    _DEPART_KEYWORDS = ('departing', 'exiting', 'lockage complete', 'lines away', 'underway')

    def _trigger_radio_bubble(self, ag):
        """Fire a speech bubble for the captain of ag's vessel (if available)."""
        ship = self._agent_ship_map.get(id(ag))
        if not ship:
            logger.debug("radio bubble: no ship record for agent %d (%s)",
                         id(ag), ag.boat.name)
            return
        vessel_name = ship.get('name', '')
        buckets = self._db_radio.get(vessel_name)
        if not buckets:
            logger.debug("radio bubble: no radio messages for vessel %r", vessel_name)
            return
        # Messages are written for the ship's canonical DB direction, not for the
        # direction it happens to be travelling this spawn.
        ship_dir = ship.get('direction')   # 'downstream' / 'upstream' / None
        all_records = buckets.get(ship_dir) or buckets.get(None) or []
        if not all_records:
            logger.debug("radio bubble: vessel=%r ship_dir=%r — no records in bucket",
                         vessel_name, ship_dir)
            return
        # Prefer messages that are contextually about entering the lock.
        entry_records = [
            r for r in all_records
            if any(k in r['message'].lower() for k in self._ENTRY_KEYWORDS)
        ]
        records = entry_records if entry_records else all_records
        record = random.choice(records)

        portrait = self._captain_portraits.get(vessel_name)
        meta = self._captain_meta.get(vessel_name)
        logger.debug(
            "radio bubble: vessel=%r lock_radio.id=%d crew_id=%s portrait=%s  msg=%r",
            vessel_name,
            record['id'],
            meta['crew_id'] if meta else 'none',
            meta['filename'] if meta else 'none',
            record['message'],
        )

        ttl = self._reading_ttl(record['message'])
        self._radio_bubbles.append({
            'text':     record['message'],
            'portrait': portrait,
            'ttl':      ttl,
            'max_ttl':  ttl,
        })
        self._queue_operator_response(vessel_name, delay=ttl // 2)

    def _trigger_radio_departure(self, ag):
        """Fire a departure speech bubble when the operator clears mooring lines."""
        if id(ag) in self._radio_depart:
            return
        self._radio_depart.add(id(ag))

        ship = self._agent_ship_map.get(id(ag))
        if not ship:
            logger.debug("radio depart: no ship record for agent %d (%s)",
                         id(ag), ag.boat.name)
            return
        vessel_name = ship.get('name', '')
        buckets = self._db_radio.get(vessel_name)
        if not buckets:
            logger.debug("radio depart: no radio messages for vessel %r", vessel_name)
            return
        ship_dir    = ship.get('direction')
        all_records = buckets.get(ship_dir) or buckets.get(None) or []
        if not all_records:
            return
        depart_records = [
            r for r in all_records
            if any(k in r['message'].lower() for k in self._DEPART_KEYWORDS)
        ]
        records = depart_records if depart_records else all_records
        record  = random.choice(records)

        portrait = self._captain_portraits.get(vessel_name)
        meta     = self._captain_meta.get(vessel_name)
        logger.debug(
            "radio depart: vessel=%r lock_radio.id=%d crew_id=%s portrait=%s  msg=%r",
            vessel_name,
            record['id'],
            meta['crew_id'] if meta else 'none',
            meta['filename'] if meta else 'none',
            record['message'],
        )

        ttl = self._reading_ttl(record['message'])
        self._radio_bubbles.append({
            'text':     record['message'],
            'portrait': portrait,
            'ttl':      ttl,
            'max_ttl':  ttl,
        })
        self._queue_operator_response(vessel_name, delay=ttl // 2)

    def _queue_operator_response(self, vessel_name: str, delay: int = 120):
        """Queue a random operator reply for vessel_name, shown after delay frames."""
        op_msgs = self._db_operator_radio.get(vessel_name, [])
        if not op_msgs:
            return
        rec = random.choice(op_msgs)
        op_ttl = self._reading_ttl(rec['message'])
        self._radio_bubbles.append({
            'text':        rec['message'],
            'portrait':    None,
            'ttl':         op_ttl,
            'max_ttl':     op_ttl,
            'is_operator': True,
            'delay':       delay,
        })

    def _draw_radio_bubbles(self):
        """Render captain speech bubbles.

        Single bubble: bottom-right corner with portrait to the right and a
        speech-bubble tail pointing at the portrait.
        Multiple bubbles: all cards laid out side-by-side across the bottom so
        they can be read simultaneously rather than queuing sequentially.
        """
        if not self._radio_bubbles:
            return

        # Tick delays first, then TTLs; keep anything still alive or waiting.
        surviving = []
        for b in self._radio_bubbles:
            if b.get('delay', 0) > 0:
                b['delay'] -= 1
                surviving.append(b)
            else:
                b['ttl'] -= 1
                if b['ttl'] > 0:
                    surviving.append(b)
        self._radio_bubbles = surviving

        # Only render bubbles whose delay has expired.
        visible = [b for b in self._radio_bubbles if b.get('delay', 0) == 0]
        if not visible:
            return

        # Operator bubbles are always drawn anchored to the operator figure.
        # Ship bubbles use the corner layout (single) or horizontal row (multiple).
        op_bubbles   = [b for b in visible if b.get('is_operator')]
        ship_bubbles = [b for b in visible if not b.get('is_operator')]

        for b in op_bubbles:
            self._draw_bubble_single(b)

        if len(ship_bubbles) == 1:
            self._draw_bubble_single(ship_bubbles[0])
        elif len(ship_bubbles) > 1:
            self._draw_bubble_row(ship_bubbles)

    # ── Radio bubble rendering helpers ────────────────────────────────────────

    def _draw_bubble_single(self, bubble):
        """Render a single speech bubble.

        Operator bubbles float above the operator figure on the lock wall with
        a cartoon tail pointing down to their head.  Ship bubbles use the
        original bottom-right corner layout with a portrait to the right.
        """
        alpha_frac = min(1.0, bubble['ttl'] / 40)
        alpha      = int(255 * alpha_frac)
        is_op      = bubble.get('is_operator', False)

        body_col = (210, 228, 255, alpha) if is_op else (240, 240, 240, alpha)
        bord_col = (55,  100, 200, alpha) if is_op else (80,  80,  100, alpha)
        text_col = (10,  20,  60)         if is_op else (20,  20,   40)

        line_h = self.fnt_sm.get_height() + 2

        if is_op:
            # ── Operator bubble anchored to the operator figure ───────────────
            chars_per_line = 26
            lines  = self._wrap_text(bubble['text'], chars_per_line)
            bub_w  = chars_per_line * 9 + 20
            bub_h  = line_h * len(lines) + 16
            tail_h = 16
            tail_w = 12

            ox, oy = self._op_screen_pos
            # Place bubble centered above the operator; clamp to screen edges.
            bub_x = max(4, min(self.width - bub_w - 4, ox - bub_w // 2))
            # Operator on top wall (oy low): bubble goes further up.
            # Operator on bottom wall (oy high): bubble goes above them.
            bub_y = oy - bub_h - tail_h - 18

            surf = pygame.Surface((bub_w, bub_h + tail_h), pygame.SRCALPHA)
            pygame.draw.rect(surf, body_col, (0, 0, bub_w, bub_h), border_radius=10)
            pygame.draw.rect(surf, bord_col, (0, 0, bub_w, bub_h), 2, border_radius=10)

            # Tail points downward from bubble bottom-centre toward operator head
            tail_cx = ox - bub_x   # tail centre in surf-local coords
            tail_cx = max(tail_w + 2, min(bub_w - tail_w - 2, tail_cx))
            tail_pts = [
                (tail_cx - tail_w, bub_h),
                (tail_cx + tail_w, bub_h),
                (tail_cx,          bub_h + tail_h),
            ]
            pygame.draw.polygon(surf, body_col, tail_pts)
            pygame.draw.lines(surf, bord_col, False, tail_pts, 2)

            for i, line in enumerate(lines):
                ts = self.fnt_sm.render(line, True, text_col)
                ts.set_alpha(alpha)
                surf.blit(ts, (10, 8 + i * line_h))
            self.screen.blit(surf, (bub_x, bub_y))

        else:
            # ── Ship bubble: bottom-right corner, portrait to the right ───────
            portrait_size  = 80
            margin         = 12
            chars_per_line = 28

            lines  = self._wrap_text(bubble['text'], chars_per_line)
            bub_w  = chars_per_line * 9 + 16
            bub_h  = line_h * len(lines) + 16
            tail_h = 14

            px    = self.width - portrait_size - margin
            py    = self.height - portrait_size - margin
            bub_x = px - bub_w - 10
            bub_y = py + portrait_size - bub_h - tail_h

            bub_surf = pygame.Surface((bub_w, bub_h + tail_h), pygame.SRCALPHA)
            pygame.draw.rect(bub_surf, body_col, (0, 0, bub_w, bub_h), border_radius=8)
            pygame.draw.rect(bub_surf, bord_col, (0, 0, bub_w, bub_h), 2, border_radius=8)

            tail_pts = [
                (bub_w,          bub_h - 10),
                (bub_w + tail_h, bub_h + 4),
                (bub_w,          bub_h + 4),
            ]
            pygame.draw.polygon(bub_surf, body_col, tail_pts)
            pygame.draw.lines(bub_surf, bord_col, False, tail_pts, 2)

            for i, line in enumerate(lines):
                ts = self.fnt_sm.render(line, True, text_col)
                ts.set_alpha(alpha)
                bub_surf.blit(ts, (8, 8 + i * line_h))
            self.screen.blit(bub_surf, (bub_x, bub_y))

            self._draw_bubble_portrait(bubble, px, py, portrait_size, alpha)

    def _draw_bubble_row(self, bubbles):
        """Horizontal row layout across the bottom for multiple simultaneous bubbles."""
        portrait_size  = 60
        chars_per_line = 18
        line_h         = self.fnt_sm.get_height() + 2
        margin         = 10
        gap            = 8
        card_margin    = 10

        max_lines = min(
            max(len(self._wrap_text(b['text'], chars_per_line)) for b in bubbles), 5)
        bub_h  = line_h * max_lines + 16
        bub_w  = chars_per_line * 9 + 16
        card_w = portrait_size + gap + bub_w
        card_h = max(portrait_size, bub_h)

        n       = len(bubbles)
        total_w = n * card_w + (n - 1) * card_margin
        start_x = max(margin, (self.width - total_w) // 2)
        card_top = self.height - margin - card_h

        for i, bubble in enumerate(bubbles):
            alpha_frac = min(1.0, bubble['ttl'] / 40)
            alpha      = int(255 * alpha_frac)
            is_op      = bubble.get('is_operator', False)

            body_col = (210, 228, 255) if is_op else (240, 240, 240)
            bord_col = (55,  100, 200) if is_op else (80,   80, 100)
            text_col = (10,   20,  60) if is_op else (20,   20,  40)

            cx = start_x + i * (card_w + card_margin)
            self._draw_bubble_portrait(
                bubble, cx, card_top + (card_h - portrait_size) // 2,
                portrait_size, alpha)

            lines = self._wrap_text(bubble['text'], chars_per_line)[:max_lines]
            bub_x = cx + portrait_size + gap
            bub_y = card_top + (card_h - bub_h) // 2
            surf  = pygame.Surface((bub_w, bub_h), pygame.SRCALPHA)
            pygame.draw.rect(surf, (*body_col, alpha), (0, 0, bub_w, bub_h), border_radius=8)
            pygame.draw.rect(surf, (*bord_col, alpha), (0, 0, bub_w, bub_h), 2, border_radius=8)
            for j, line in enumerate(lines):
                ts = self.fnt_sm.render(line, True, text_col)
                ts.set_alpha(alpha)
                surf.blit(ts, (8, 8 + j * line_h))
            self.screen.blit(surf, (bub_x, bub_y))

    def _draw_bubble_portrait(self, bubble, px, py, size, alpha):
        """Draw portrait, operator icon, or ship placeholder at (px, py) scaled to size."""
        is_op   = bubble.get('is_operator', False)
        portrait = bubble.get('portrait')

        if is_op:
            # Blue operator icon
            ph = pygame.Surface((size, size), pygame.SRCALPHA)
            ph.fill((30, 55, 110, alpha))
            pygame.draw.rect(ph, (55, 110, 210, alpha), (0, 0, size, size), 2, border_radius=4)
            op_lbl = self.fnt_sm.render("OP", True, (160, 200, 255))
            op_lbl.set_alpha(alpha)
            ph.blit(op_lbl, ((size - op_lbl.get_width()) // 2,
                              size // 2 - op_lbl.get_height() // 2))
            self.screen.blit(ph, (px, py))
        elif portrait:
            ps = pygame.transform.smoothscale(portrait, (size, size))
            ps.set_alpha(alpha)
            self.screen.blit(ps, (px, py))
            bord = pygame.Surface((size + 4, size + 4), pygame.SRCALPHA)
            pygame.draw.rect(bord, (80, 80, 100, alpha),
                             (0, 0, size + 4, size + 4), 2, border_radius=4)
            self.screen.blit(bord, (px - 2, py - 2))
        else:
            ph = pygame.Surface((size, size), pygame.SRCALPHA)
            ph.fill((60, 60, 80, alpha))
            pygame.draw.rect(ph, (80, 80, 100, alpha), (0, 0, size, size), 2, border_radius=4)
            cap_lbl = self.fnt_sm.render("CAPT", True, (180, 180, 200))
            cap_lbl.set_alpha(alpha)
            ph.blit(cap_lbl, ((size - cap_lbl.get_width()) // 2,
                               size // 2 - cap_lbl.get_height() // 2))
            self.screen.blit(ph, (px, py))

    # ── Lock roster panel ─────────────────────────────────────────────────────

    def _draw_lock_roster(self):
        """Draw a vertical centered list of ships currently in the lock."""
        self._roster_buttons = []

        in_lock = [
            ag for ag in self.agents
            if ag.state == 'active' and self._in_lock(ag.boat)
        ]
        if not in_lock:
            return

        row_h    = 30
        panel_w  = 300
        pad      = 12
        btn_w    = 60
        btn_h    = 22
        header_h = 28

        panel_h  = header_h + len(in_lock) * row_h + 8
        panel_x  = (self.width - panel_w) // 2
        panel_y  = self.height - panel_h - 8

        bg = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        bg.fill((8, 14, 34, 210))
        self.screen.blit(bg, (panel_x, panel_y))
        pygame.draw.rect(self.screen, (55, 100, 180), (panel_x, panel_y, panel_w, panel_h), 1)

        hdr = self.fnt_sm.render("Ships in Lock", True, (150, 185, 255))
        self.screen.blit(hdr, (panel_x + pad, panel_y + 5))
        pygame.draw.line(self.screen, (55, 100, 180),
                         (panel_x + 6, panel_y + header_h - 2),
                         (panel_x + panel_w - 6, panel_y + header_h - 2), 1)

        for i, ag in enumerate(in_lock):
            ry      = panel_y + header_h + i * row_h
            mid_y   = ry + row_h // 2

            name_lbl = self.fnt_sm.render(ag.boat.name[:28], True, (220, 230, 255))
            self.screen.blit(name_lbl, (panel_x + pad,
                                        mid_y - name_lbl.get_height() // 2))

            btn_x    = panel_x + panel_w - btn_w - pad
            btn_rect = pygame.Rect(btn_x, mid_y - btn_h // 2, btn_w, btn_h)
            pygame.draw.rect(self.screen, (38, 92, 168), btn_rect, border_radius=4)
            pygame.draw.rect(self.screen, (80, 140, 220), btn_rect, 1, border_radius=4)
            r_lbl    = self.fnt_sm.render("RADIO", True, (195, 218, 255))
            self.screen.blit(r_lbl, (btn_x + (btn_w - r_lbl.get_width()) // 2,
                                     mid_y - r_lbl.get_height() // 2))
            self._roster_buttons.append((btn_rect, ag))

    # ── Radio popup ───────────────────────────────────────────────────────────

    def _open_radio_popup(self, ag):
        """Open the operator radio popup for the given agent."""
        ship        = self._agent_ship_map.get(id(ag))
        vessel_name = ship['name'] if ship else ag.boat.name
        all_op_msgs = self._db_operator_radio.get(vessel_name, [])
        options     = random.sample(all_op_msgs, min(4, len(all_op_msgs))) if all_op_msgs else []
        self._radio_popup = {
            'ag':           ag,
            'vessel_name':  vessel_name,
            'options':      options,
            'option_rects': [],
            'close_rect':   None,
        }

    def _select_radio_option(self, record):
        """Player chose an operator message; show it and queue the ship's response."""
        popup       = self._radio_popup
        ag          = popup['ag']
        vessel_name = popup['vessel_name']
        self._radio_popup = None

        # Operator transmission bubble (blue tint, no portrait)
        op_ttl = self._reading_ttl(record['message'])
        self._radio_bubbles.append({
            'text':        record['message'],
            'portrait':    None,
            'ttl':         op_ttl,
            'max_ttl':     op_ttl,
            'is_operator': True,
        })

        # Ship response — delayed by 2 s so it doesn't overlap instantly
        ship     = self._agent_ship_map.get(id(ag))
        ship_dir = ship.get('direction') if ship else None
        buckets  = self._db_radio.get(vessel_name, {})
        records  = buckets.get(ship_dir) or buckets.get(None) or []
        if records:
            resp    = random.choice(records)
            portrait = self._captain_portraits.get(vessel_name)
            r_ttl   = self._reading_ttl(resp['message'])
            self._radio_bubbles.append({
                'text':        resp['message'],
                'portrait':    portrait,
                'ttl':         r_ttl,
                'max_ttl':     r_ttl,
                'is_operator': False,
                'delay':       120,   # 2 s at 60 fps
            })

    def _draw_radio_popup(self):
        """Render the operator radio selection popup."""
        popup = self._radio_popup
        if not popup:
            return

        options  = popup['options']
        opt_h    = 54
        pad      = 14
        pop_w    = 560
        header_h = 52
        gap      = 6

        pop_h = header_h + len(options) * (opt_h + gap) + 44   # 44 for close btn + margin
        pop_x = (self.width  - pop_w) // 2
        pop_y = (self.height - pop_h) // 2

        # Screen dim
        dim = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 130))
        self.screen.blit(dim, (0, 0))

        # Panel
        panel = pygame.Surface((pop_w, pop_h), pygame.SRCALPHA)
        panel.fill((10, 16, 40, 245))
        self.screen.blit(panel, (pop_x, pop_y))
        pygame.draw.rect(self.screen, (65, 115, 195), (pop_x, pop_y, pop_w, pop_h), 2, border_radius=6)

        # Header
        title = self.fnt_md.render(f"RADIO — {popup['vessel_name']}", True, (170, 205, 255))
        self.screen.blit(title, (pop_x + pad, pop_y + 10))
        sub = self.fnt_sm.render("Select operator transmission:", True, (110, 140, 185))
        self.screen.blit(sub, (pop_x + pad, pop_y + 32))
        pygame.draw.line(self.screen, (65, 115, 195),
                         (pop_x + 8, pop_y + header_h - 4),
                         (pop_x + pop_w - 8, pop_y + header_h - 4), 1)

        option_rects = []
        for i, rec in enumerate(options):
            oy       = pop_y + header_h + i * (opt_h + gap)
            opt_rect = pygame.Rect(pop_x + pad, oy, pop_w - 2 * pad, opt_h)
            pygame.draw.rect(self.screen, (22, 46, 90), opt_rect, border_radius=4)
            pygame.draw.rect(self.screen, (65, 115, 195), opt_rect, 1, border_radius=4)

            # Number badge
            num = self.fnt_md.render(str(i + 1), True, (130, 175, 255))
            self.screen.blit(num, (opt_rect.x + 8, oy + (opt_h - num.get_height()) // 2))

            # Message text — up to 2 lines
            for j, line in enumerate(self._wrap_text(rec['message'], 54)[:2]):
                line_surf = self.fnt_sm.render(line, True, (205, 222, 255))
                self.screen.blit(line_surf, (opt_rect.x + 32, oy + 8 + j * 20))

            option_rects.append(opt_rect)

        popup['option_rects'] = option_rects

        # If no operator messages exist for this vessel show a note
        if not options:
            note = self.fnt_sm.render("No operator messages on file for this vessel.",
                                      True, (160, 140, 120))
            self.screen.blit(note, (pop_x + pad, pop_y + header_h + 10))

        # Close button
        close_y    = pop_y + pop_h - 34
        close_rect = pygame.Rect(pop_x + (pop_w - 80) // 2, close_y, 80, 24)
        pygame.draw.rect(self.screen, (65, 32, 32), close_rect, border_radius=4)
        pygame.draw.rect(self.screen, (180, 80, 80), close_rect, 1, border_radius=4)
        cl = self.fnt_sm.render("CLOSE", True, (235, 175, 175))
        self.screen.blit(cl, (close_rect.x + (80 - cl.get_width()) // 2,
                               close_rect.y + (24 - cl.get_height()) // 2))
        popup['close_rect'] = close_rect

    @staticmethod
    def _wrap_text(text: str, chars_per_line: int) -> list[str]:
        """Word-wrap text to a list of lines."""
        words = text.split()
        lines, cur = [], ''
        for w in words:
            if len(cur) + len(w) + 1 <= chars_per_line:
                cur = (cur + ' ' + w).strip()
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines or ['']

    def _spawn_boat(self, direction, position=None):
        self._boat_counter += 1
        h = self.game_time
        # Spawning restrictions: no Kayaks at night, minimal Yachts.
        is_night = h < 6.0 or h > 20.0

        if is_night:
            # 70% Barge, 20% PaddleBoat, 10% Yacht, 0% Kayak
            cls = random.choices([Barge, PaddleBoat, Yacht], weights=[0.7, 0.2, 0.1])[0]
        else:
            # Equal probability during the day
            cls = random.choice([Yacht, Barge, Kayak, PaddleBoat])

        # Try to assign a real ship from the asset DB
        db_ship = None
        pool = self._db_ships_by_cls.get(cls, [])
        if pool:
            # Prefer ships not currently active on screen
            active_names = {
                self._agent_ship_map[id(ag)]['name']
                for ag in self.agents
                if id(ag) in self._agent_ship_map
            }
            available = [s for s in pool if s['name'] not in active_names]

            # Filter out ships still "in transit" this week — a ship last seen going
            # direction D may not travel D again until it has been seen returning (-D).
            log_ships = self.ship_log.get('ships', {})
            available_unrestricted = [
                s for s in available
                if log_ships.get(s['name'], {}).get('last_dir') != direction
            ]
            # Fall back to the unfiltered available pool (then full pool) so spawning
            # never hard-stalls when every named ship has already transited this way.
            if available_unrestricted:
                available = available_unrestricted
            # (if available_unrestricted is empty, we keep original available/pool as-is)

            if available:
                db_ship = random.choice(available)
            else:
                # Every named ship is already on screen — last resort: pick from
                # the full pool but still exclude active names so we never duplicate.
                fallback = [s for s in pool if s['name'] not in active_names]
                db_ship = random.choice(fallback) if fallback else None

        name = db_ship['name'] if db_ship else f"{cls.__name__[0]}{self._boat_counter}"
        boat = cls(name)
        boat.position = (-120 if direction == 1 else 1100) if position is None else position
        ag = Agent(boat, direction)
        if db_ship:
            self._agent_ship_map[id(ag)] = db_ship
        self.agents.append(ag)

    def _spawn_if_needed(self):
        self.spawn_timer += 1
        if self.spawn_timer < self.spawn_interval:
            return
        self.spawn_timer = 0
        d = self._next_direction
        spawn_pos = -80 if d == 1 else 1080
        # Only spawn if spawn zone is clear
        clear = all(
            ag.boat.position + ag.boat.length < spawn_pos - 30 or
            ag.boat.position > spawn_pos + 30
            for ag in self.agents if ag.state == "active"
        )
        if clear:
            self._spawn_boat(d)
            self._next_direction *= -1

    def _update_agents(self):
        active = [ag for ag in self.agents if ag.state == "active"]
        
        # Track previous positions to determine movement
        old_pos = {id(ag): ag.boat.position for ag in active}

        for ag in active:
            self._step_agent(ag, active)

        # Update movement flag
        for ag in active:
            ag.is_moving = abs(ag.boat.position - old_pos.get(id(ag), ag.boat.position)) > 0.001

        # Radio: fire once when a boat first crosses into the lock interior
        for ag in active:
            if id(ag) in self._radio_approach:
                continue
            if self._in_lock(ag.boat):
                self._radio_approach.add(id(ag))
                self._trigger_radio_bubble(ag)

        # Crash detection: same-direction boats share a lane and can collide.
        # Opposite-direction boats are always in separate lanes — no collision.
        for i in range(len(active)):
            for j in range(i + 1, len(active)):
                ag1, ag2 = active[i], active[j]
                if (ag1.state == "active" and ag2.state == "active"
                        and ag1.direction == ag2.direction
                        and ag1.boat.check_collision(ag2.boat)):
                    self._crash_incident(ag1, ag2)

        # Tick crashed boat TTLs
        for ag in self.agents:
            if ag.state == "crashed" and ag.ttl is not None:
                ag.ttl -= 1
                if ag.ttl <= 0:
                    ag.state = "done"

        # Remove done agents and clean up their tracking data
        done_ids = {id(ag) for ag in self.agents if ag.state == "done"}
        for aid in done_ids:
            self._agent_ship_map.pop(aid, None)
            self._radio_triggered.discard(aid)
            self._radio_approach.discard(aid)
            self._radio_depart.discard(aid)
        self.agents = [ag for ag in self.agents if ag.state != "done"]

    def _step_agent(self, ag, all_active):
        if ag.tied_down:
            ag.is_moving = False
            return

        d    = ag.direction
        boat = ag.boat
        
        # Apply night-time speed reduction
        v_mult = self._get_speed_mult()
        new_pos = boat.position + d * ag.speed * v_mult

        # ── Gate blocking ─────────────────────────────────────────────────────
        # Boats approaching from outside stop at the outer wall face.
        # Boats inside the lock stopping at a closed gate use the inner wall face
        # so they don't visually clip into the concrete.
        wt            = self._wall_t_sim
        outer_gap     = int(100 / self._sx_scale)   # 100 px gap approaching from outside
        inner_gap     = int(20  / self._sx_scale)   # 20 px gap when stopped inside lock
        if d == 1:
            gate_order = [
                (self.lock_start,      self.lock_dam.upstream_gates_open,   outer_gap),
                (self.lock_end - wt,   self.lock_dam.downstream_gates_open, inner_gap),
            ]
        else:
            gate_order = [
                (self.lock_end,        self.lock_dam.downstream_gates_open, outer_gap),
                (self.lock_start + wt, self.lock_dam.upstream_gates_open,   inner_gap),
            ]

        for gate_x, open_, gap in gate_order:
            if open_:
                continue
            if d == 1:
                if boat.position + boat.length <= gate_x - gap < new_pos + boat.length:
                    boat.position = gate_x - boat.length - gap
                    return
            else:
                if boat.position >= gate_x + gap > new_pos:
                    boat.position = gate_x + gap
                    return

        # ── Same-lane boat blocking (same direction only) ────────────────────────
        gap = 25
        if d == 1:
            ahead = sorted(
                [o for o in all_active if o is not ag
                 and o.direction == 1
                 and o.boat.position > boat.position],
                key=lambda o: o.boat.position
            )
            for other in ahead:
                ob = other.boat
                if new_pos + boat.length + gap > ob.position:
                    clamped = ob.position - boat.length - gap
                    if clamped > boat.position:
                        new_pos = clamped
                    else:
                        return
                break
        else:
            ahead = sorted(
                [o for o in all_active if o is not ag
                 and o.direction == -1
                 and o.boat.position + o.boat.length < boat.position + boat.length],
                key=lambda o: -(o.boat.position + o.boat.length)
            )
            for other in ahead:
                ob = other.boat
                if new_pos - gap < ob.position + ob.length:
                    clamped = ob.position + ob.length + gap
                    if clamped < boat.position:
                        new_pos = clamped
                    else:
                        return
                break

        boat.position = new_pos

        # ── Done check ────────────────────────────────────────────────────────
        if d == 1 and boat.position > 1100:
            ag.state = "done"
            self.score += 1
            self._record_ship_transit(ag, 1)
        elif d == -1 and boat.position + boat.length < -100:
            ag.state = "done"
            self.score += 1
            self._record_ship_transit(ag, -1)

    def _record_ship_transit(self, ag, direction):
        """Record that a named ship has completed a transit in *direction* (+1/-1)."""
        ship = self._agent_ship_map.get(id(ag))
        if not ship:
            return
        name = ship.get('name', '')
        if not name:
            return
        self.ship_log['ships'][name] = {'last_dir': direction}

    def _incident(self, text, color=None):
        self.incident_count += 1
        self.incidents.append(text)
        if len(self.incidents) > 5:
            self.incidents.pop(0)
        self.flash_timer = 90
        self.flash_color = color if color else self.RED

    def _surge_incident(self, text):
        self._incident(text, self.ORANGE)
        # Crash any boat currently inside the lock chamber
        for ag in self.agents:
            if ag.state == "active":
                b = ag.boat
                if b.position < self.lock_end and b.position + b.length > self.lock_start:
                    ag.state = "crashed"
                    ag.ttl   = 150

    def _crash_incident(self, ag1, ag2):
        self._incident(f"CRASH: {ag1.boat.name} × {ag2.boat.name}")
        ag1.state = ag2.state = "crashed"
        ag1.ttl   = ag2.ttl   = 150

    # ── UI overlay ────────────────────────────────────────────────────────────

    def draw_ui(self):
        # ── Left control panel ────────────────────────────────────────────────
        pw, ph = 258, 256
        panel = pygame.Surface((pw, ph), pygame.SRCALPHA)
        panel.fill((8, 12, 28, 172))
        self.screen.blit(panel, (8, 8))
        pygame.draw.rect(self.screen, (70, 110, 195), (8, 8, pw, ph), 1)

        self.screen.blit(
            self.fnt_md.render("Lock & Dam Operator", True, (170, 195, 255)), (16, 13))
        
        h = int(self.game_time)
        m = int((self.game_time * 60) % 60)
        time_str = f"Time: {h:02d}:{m:02d}"
        time_col = (255, 255, 150) if (h < 6 or h > 19) else (200, 220, 255)

        pygame.draw.line(self.screen, (70, 110, 195), (16, 34), (pw + 6, 34), 1)

        fill_col  = (170, 170, 255) if not self.lock_dam.downstream_gates_open else (100, 100, 130)
        drain_col = (170, 170, 255) if not self.lock_dam.upstream_gates_open else (100, 100, 130)

        # Shift progress row (only shown when inside a timed shift)
        shift_row = None
        if self._cfg_shift_duration is not None:
            remaining = max(0.0, self._cfg_shift_duration - self.shift_hours_elapsed)
            rm, rs = int(remaining * 60), int((remaining * 3600) % 60)
            shift_phase = getattr(self, '_shift_phase_label', '')
            shift_num   = getattr(self, '_shift_num_label',   '')
            clean       = getattr(self, '_shift_clean_label', '')
            shift_row   = (f"{shift_phase} {shift_num}  {clean}  left: {rm}:{rs:02d}",
                           (255, 210, 100))

        wages_so_far   = self.HOURLY_WAGE * self.shift_hours_elapsed
        bonuses_so_far = self.BOAT_BONUS  * self.score
        pay_so_far     = wages_so_far + bonuses_so_far
        rows = [
            (f"Score: {self.score} boats passed",      (255, 238, 140)),
            (time_str,                                  time_col),
            (f"Pay:  ${pay_so_far:.2f}  (wages ${wages_so_far:.2f} + bonus ${bonuses_so_far:.0f})",
             (160, 220, 160)),
        ]
        if shift_row:
            rows.append(shift_row)
        if self.dev_mode:
            rows.append((f"[DEV]  {self.time_scale:.1f}x  [/] slow  []] fast  [End] end shift",
                         (255, 100, 255)))
        rows += [
            ("",                                        None),
            ("[G]    Upstream gate",                    (170, 170, 255)),
            ("[H]    Downstream gate",                  (170, 170, 255)),
            ("[F]    Fill chamber",                     fill_col),
            ("[D]    Drain chamber",                    drain_col),
            ("[V]    Toggle POV View",                  (255, 255, 100)),
        ]
        for j, (txt, col) in enumerate(rows):
            if txt:
                self.screen.blit(self.fnt_sm.render(txt, True, col), (16, 40 + j * 22))

        # ── Right status panel ────────────────────────────────────────────────
        inc_h  = max(0, len(self.incidents) * 20)
        gw, gh = 265, 102 + inc_h
        gx, gy = self.width - gw - 8, 8
        gpanel = pygame.Surface((gw, gh), pygame.SRCALPHA)
        gpanel.fill((8, 12, 28, 172))
        self.screen.blit(gpanel, (gx, gy))
        pygame.draw.rect(self.screen, (70, 110, 195), (gx, gy, gw, gh), 1)

        self.screen.blit(
            self.fnt_sm.render("Lock Status", True, (170, 195, 255)), (gx + 10, gy + 6))
        for gi, (label, open_) in enumerate([
            ("Upstream gate",   self.lock_dam.upstream_gates_open),
            ("Downstream gate", self.lock_dam.downstream_gates_open),
        ]):
            col = self.GREEN if open_ else self.RED
            self.screen.blit(
                self.fnt_sm.render(f"{label}: {'OPEN' if open_ else 'CLOSED'}", True, col),
                (gx + 10, gy + 24 + gi * 22))
        # Show fill/drain status
        status_text = f"Chamber: {self.lock_dam.lock_chamber_level:.1f} m"
        if self.lock_dam.is_filling:
            status_text += " (Filling...)"
        elif self.lock_dam.is_draining:
            status_text += " (Draining...)"
        self.screen.blit(
            self.fnt_sm.render(status_text, True, (100, 200, 255)),
            (gx + 10, gy + 68))

        if self.incidents:
            pygame.draw.line(self.screen, (70, 110, 195),
                             (gx + 10, gy + 88), (gx + gw - 10, gy + 88), 1)
            self.screen.blit(
                self.fnt_sm.render("Incidents", True, (255, 140, 140)), (gx + 10, gy + 92))
            for ii, inc in enumerate(reversed(self.incidents)):
                fade = max(180, 255 - ii * 35)
                col  = (fade, max(80, fade - 60), max(80, fade - 60))
                self.screen.blit(
                    self.fnt_sm.render(inc[:40], True, col),
                    (gx + 10, gy + 110 + ii * 20))

        # ── Incident flash overlay ────────────────────────────────────────────
        if self.flash_timer > 0:
            alpha = min(110, self.flash_timer * 2)
            overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            overlay.fill((*self.flash_color, alpha))
            self.screen.blit(overlay, (0, 0))
            self.flash_timer = max(0, self.flash_timer - 1)

    def _check_both_gates(self):
        """Track how long both gates are open; trigger game over if too long."""
        if self.lock_dam.upstream_gates_open and self.lock_dam.downstream_gates_open:
            self.both_gates_timer += 1
            # Pulse the flash intensity so it visibly escalates
            pulse = int(60 + 50 * math.sin(self.time * 12))
            overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            overlay.fill((220, 30, 30, pulse))
            self.screen.blit(overlay, (0, 0))
            # Countdown warning
            secs_left = max(0, (self.BOTH_GATES_LIMIT - self.both_gates_timer) / 60)
            warn = self.fnt_lg.render(
                f"BOTH GATES OPEN — close one!  {secs_left:.1f}s", True, (255, 80, 80))
            wx = self.width // 2 - warn.get_width() // 2
            bg = pygame.Surface((warn.get_width() + 16, warn.get_height() + 8), pygame.SRCALPHA)
            bg.fill((0, 0, 0, 160))
            self.screen.blit(bg, (wx - 8, self.height // 2 - warn.get_height() // 2 - 4))
            self.screen.blit(warn, (wx, self.height // 2 - warn.get_height() // 2))
            if self.both_gates_timer >= self.BOTH_GATES_LIMIT:
                self.game_over = True
        else:
            self.both_gates_timer = 0

    def _draw_game_over(self):
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 200))
        self.screen.blit(overlay, (0, 0))

        title = self.fnt_lg.render("GAME OVER", True, (220, 50, 50))
        reason = self.fnt_md.render(
            "Both gates left open — the lock surged.", True, (200, 180, 180))
        score_txt = self.fnt_md.render(
            f"Final score: {self.score} boat{'s' if self.score != 1 else ''} passed",
            True, (255, 230, 100))
        restart = self.fnt_sm.render("Press R to restart  |  Q to quit", True, (160, 160, 200))

        cx = self.width // 2
        cy = self.height // 2
        for i, surf in enumerate([title, reason, score_txt, restart]):
            self.screen.blit(surf, (cx - surf.get_width() // 2, cy - 70 + i * 40))

    # ── Utility ───────────────────────────────────────────────────────────────

    def _boat_color(self, boat):
        return self._boat_colors.get(type(boat).__name__, self.WHITE)

    # ── State serialization ───────────────────────────────────────────────────

    def save_state(self) -> dict:
        """Return a JSON-serializable snapshot of the full simulation state."""
        op = self.operator
        try:
            target_idx = self.agents.index(op['target_boat']) if op['target_boat'] is not None else None
        except ValueError:
            target_idx = None

        return {
            'time':             self.time,
            'game_time':        self.game_time,
            'score':            self.score,
            'incidents':        list(self.incidents),
            'flash_timer':      self.flash_timer,
            'flash_color':      list(self.flash_color),
            'game_over':        self.game_over,
            'both_gates_timer': self.both_gates_timer,
            'spawn_timer':      self.spawn_timer,
            'spawn_interval':   self.spawn_interval,
            'boat_counter':     self._boat_counter,
            'agent_counter':    Agent._counter,
            'next_direction':   self._next_direction,
            'view_mode':        self.view_mode,
            'lock': {
                'chamber_level':         self.lock_dam.lock_chamber_level,
                'upstream_gates_open':   self.lock_dam.upstream_gates_open,
                'downstream_gates_open': self.lock_dam.downstream_gates_open,
                'is_filling':            self.lock_dam.is_filling,
                'is_draining':           self.lock_dam.is_draining,
                'gate_anim_up':          self._gate_anim_up,
                'gate_anim_dn':          self._gate_anim_dn,
            },
            'agents': [
                {
                    'vessel_type': ag.boat.vessel_type,
                    'name':        ag.boat.name,
                    'position':    ag.boat.position,
                    'length':      ag.boat.length,
                    'beam':        ag.boat.beam,
                    'draft':       ag.boat.draft,
                    'direction':   ag.direction,
                    'state':       ag.state,
                    'speed':       ag.speed,
                    'is_moving':   ag.is_moving,
                    'tied_down':   ag.tied_down,
                    'tied_side':   ag.tied_side,
                    'ttl':         ag.ttl,
                }
                for ag in self.agents
            ],
            'operator': {
                'x':               op['x'],
                'target_x':        op['target_x'],
                'state':           op['state'],
                'side':            op['side'],
                'target_side':     op['target_side'],
                'cross_progress':  op['cross_progress'],
                'rope_progress':   op['rope_progress'],
                'target_boat_idx': target_idx,
                'task':            op['task'],
            },
            'weather': {
                'clouds':          self.clouds,
                'rain_active':     self.rain_active,
                'weather_timer':   self.weather_timer,
                'rain_drops':      self.rain_drops,
                'lightning_timer': self.lightning_timer,
                'lightning_bolt':  self.lightning_bolt,
            },
            'birds':    self.birds,
            'ship_log': self.ship_log,
        }

    def load_state(self, state: dict):
        """Restore simulation from a snapshot produced by save_state()."""
        _cls_map = {'yacht': Yacht, 'barge': Barge, 'kayak': Kayak, 'paddleboat': PaddleBoat}

        self.time             = state['time']
        self.game_time        = state['game_time']
        self.score            = state['score']
        self.incidents        = state['incidents']
        self.flash_timer      = state['flash_timer']
        self.flash_color      = tuple(state['flash_color'])
        self.game_over        = state['game_over']
        self.both_gates_timer = state['both_gates_timer']
        self.spawn_timer      = state['spawn_timer']
        self.spawn_interval   = state['spawn_interval']
        self._boat_counter    = state['boat_counter']
        Agent._counter        = state['agent_counter']
        self._next_direction  = state['next_direction']
        self.view_mode        = state['view_mode']

        lk = state['lock']
        self.lock_dam.lock_chamber_level     = lk['chamber_level']
        self.lock_dam.upstream_gates_open    = lk['upstream_gates_open']
        self.lock_dam.downstream_gates_open  = lk['downstream_gates_open']
        self.lock_dam.is_filling             = lk['is_filling']
        self.lock_dam.is_draining            = lk['is_draining']
        self._gate_anim_up = lk.get('gate_anim_up', 1.0 if lk['upstream_gates_open']   else 0.0)
        self._gate_anim_dn = lk.get('gate_anim_dn', 1.0 if lk['downstream_gates_open'] else 0.0)

        self.agents = []
        for ad in state['agents']:
            cls  = _cls_map.get(ad['vessel_type'], Yacht)
            boat = cls(ad['name'])
            boat.position = ad['position']
            boat.length   = ad['length']
            boat.beam     = ad['beam']
            boat.draft    = ad['draft']
            ag            = Agent(boat, ad['direction'])
            ag.state      = ad['state']
            ag.speed      = ad['speed']
            ag.is_moving  = ad['is_moving']
            ag.tied_down  = ad['tied_down']
            ag.tied_side  = ad['tied_side']
            ag.ttl        = ad['ttl']
            self.agents.append(ag)

        op_d = state['operator']
        tgt  = op_d['target_boat_idx']
        self.operator = {
            'x':             op_d['x'],
            'target_x':      op_d['target_x'],
            'state':         op_d['state'],
            'side':          op_d['side'],
            'target_side':   op_d['target_side'],
            'cross_progress': op_d.get('cross_progress', 0.0),
            'rope_progress': op_d['rope_progress'],
            'target_boat':   self.agents[tgt] if tgt is not None and tgt < len(self.agents) else None,
            'task':          op_d['task'],
        }

        w = state['weather']
        self.clouds          = w['clouds']
        self.rain_active     = w['rain_active']
        self.weather_timer   = w['weather_timer']
        self.rain_drops      = w['rain_drops']
        self.lightning_timer = w['lightning_timer']
        self.lightning_bolt  = w['lightning_bolt']
        self.birds    = state['birds']
        self.ship_log = state.get('ship_log', {'week': 0, 'ships': {}})

    def save_to_file(self, path: str):
        """Write simulation state to a JSON file."""
        import json
        with open(path, 'w') as f:
            json.dump(self.save_state(), f)

    def load_from_file(self, path: str):
        """Restore simulation state from a JSON file written by save_to_file()."""
        import json
        with open(path) as f:
            self.load_state(json.load(f))

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> str:
        """Run the operator game. Returns 'menu', 'quit', or 'shift_complete'."""
        result = 'menu'
        running = True
        while running:
            # ── Event handling ────────────────────────────────────────────────
            if self.game_over:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        result = 'quit'
                        running = False
                    elif event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_q:
                            result = 'quit'
                            running = False
                        elif event.key == pygame.K_ESCAPE:
                            running = False
                        elif event.key == pygame.K_r:
                            self.__init__(
                                shift_duration=self._cfg_shift_duration,
                                shift_start_time=self._cfg_shift_start_time,
                                cfg_time_scale=self._cfg_time_scale,
                                dev_mode=self.dev_mode,
                            )
            else:
                signal = self.handle_input()
                if signal == 'quit':
                    result = 'quit'
                    running = False
                elif signal == 'menu':
                    running = False
                else:
                    dt = 1 / 60
                    self.time += dt
                    game_dt = (dt * self.time_scale) / 60.0
                    self.game_time = (self.game_time + game_dt) % 24
                    self.shift_hours_elapsed += game_dt
                    if (self._cfg_shift_duration is not None
                            and self.shift_hours_elapsed >= self._cfg_shift_duration):
                        self.shift_complete = True
                        result = 'shift_complete'
                        running = False
                        continue
                    self.lock_dam.update(dt)
                    self._update_weather(dt)
                    self._update_nature(dt)
                    self._update_operator(dt)
                    self._update_gate_anims()
                    self._spawn_if_needed()
                    self._update_agents()

            # ── Rendering ─────────────────────────────────────────────────────
            self.screen.fill(self.SKY_BOTTOM)

            if self.view_mode == "shore":
                self.draw_shore_view()
            else:
                self.draw_operator_view()

            self._draw_birds()
            self._draw_rain()
            self._draw_lightning()

            self.draw_ui()
            if self.view_mode == "shore":
                self._draw_lock_roster()
            self._draw_radio_bubbles()
            self._draw_radio_popup()

            if not self.game_over:
                self._check_both_gates()
            else:
                self._draw_game_over()

            pygame.display.flip()
            self.clock.tick(60)

        return result

