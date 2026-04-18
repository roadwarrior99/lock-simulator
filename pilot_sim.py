#!/usr/bin/env python3
"""
pilot_sim.py – River Towboat Pilot Simulation

Pilot a towboat pushing a 2×2 barge tow down a procedurally-generated river.
Stay inside the red/green buoy channel, dodge hazards lurking outside it, and
pull into terminals when the unloading signal appears.

Progression: shift starts at dawn, night arrives gradually — navigation
depends more on buoy lights and nav lights as darkness falls.

Controls
--------
  W / ↑     Throttle up           S / ↓   Throttle down / reverse
  A / ←     Steer left            D / →   Steer right
  SPACE      Sound horn            R       Restart
  ESC        Quit
"""

import math
import random
import sys
import pygame

# ── Display ────────────────────────────────────────────────────────────────────
SW, SH  = 1200, 800
FPS     = 60
VREF_Y  = int(SH * 0.10)   # towboat sits this many pixels from the top of screen

# ── River geometry (world units; 1 wu ≈ 1 px at 1:1 zoom) ────────────────────
RIVER_HALF   = 400    # half-width of the full river
CHANNEL_HALF = 210     # half-width of the safe navigable channel
BUOY_SPACING = 645    # world-Y between consecutive buoy pairs
OBS_STEP     = 365    # world-Y between obstacle placement tries
OBS_CHANCE   = 0.62   # probability an obstacle slot is actually filled
DOCK_INTERVAL= 2500   # world-Y between terminal docks
GEN_LIMIT    = 60_000 # world-Y extent of pre-generated world

# ── Vessel dimensions ──────────────────────────────────────────────────────────
TW, TH   = 42, 74          # towboat width × length along heading
BW, BH   = 55, 176          # single barge width × length
BGAP     = 5               # gap between adjacent barge units
PUSH     = 12              # space between towboat bow and barge stern

B_ROWS, B_COLS = 2, 2
FORM_W = B_COLS * BW + (B_COLS - 1) * BGAP    # 115  side-to-side
FORM_L = B_ROWS * BH + (B_ROWS - 1) * BGAP    # 157  fore-aft
VESSEL_L = TH + PUSH + FORM_L                  # 223  stern-to-bow

# ── Physics ────────────────────────────────────────────────────────────────────
MAX_FWD  = 3.0    # world units/frame at full forward throttle
MAX_REV  = 0.7    # world units/frame at full reverse
ACCEL    = 0.055  # speed change per frame while key held
DRAG     = 0.988  # speed multiplied each frame (water resistance)
YAW_MAX  = 0.55   # degrees/frame at full steer and full speed (bow-pivot: long lever arm)
YAW_DAMP = 0.82   # angular-velocity damped each frame
CURRENT_Y  = 1.2  # river current speed downstream (+Y), world units/frame
CURRENT_CD = 0.05 # hydrodynamic drag coefficient (quadratic: F ∝ Cd·v_rel²)

# ── Deckhands ──────────────────────────────────────────────────────────────────
DECKHAND_WALK  = 1.4   # wu/frame on deck
DECKHAND_COUNT = 3
CARGO_TYPES = [
    ('coal',   ( 32,  32,  40)),
    ('grain',  (195, 170,  68)),
    ('steel',  (118, 130, 140)),
    ('gravel', (110, 100,  78)),
    ('corn',   (210, 180,  50)),
]
DECKHAND_COLORS = [
    (210,  85,  45),   # orange vest
    ( 48, 108, 200),   # blue vest
    ( 48, 172,  72),   # green vest
]
_DH_FALLBACK_NAMES = ['Pat', 'Lou', 'Sam', 'Casey', 'River', 'Dale', 'Jo', 'Mac']

# ── AI river traffic ───────────────────────────────────────────────────────────
TRAFFIC_SPAWN_INTERVAL = 38.0   # real seconds between spawn attempts
TRAFFIC_MAX            = 2      # max simultaneous AI vessels on screen
TRAFFIC_SPAWN_AHEAD    = 1400   # world units ahead of player to spawn
TRAFFIC_CULL_DIST      = 1800   # cull when this far behind the vessel's own travel direction

_AI_DIMS = {          # (half-width, half-length) in world units — barges excluded: no self-propulsion
    'kayak':      ( 3,   6),
    'yacht':      ( 6,  14),
    'paddleboat': (16,  28),
    'towboat':    (22,  45),
}
_AI_SPEEDS = {        # base world units/frame
    'kayak':      1.9,
    'yacht':      2.3,
    'paddleboat': 1.1,
    'towboat':    1.6,
}
_AI_COLORS = {
    'kayak':      (220, 110,  40),
    'yacht':      (210, 210, 215),
    'paddleboat': (170,  55,  55),
    'towboat':    (130,  68,  24),
}
_FALLBACK_POOL = [
    ('MV River Queen',   'towboat',    'Capt. Harris'),
    ('Cape May',         'yacht',      None),
    ('MV Prairie Star',  'towboat',    'Capt. Nolan'),
    ('Sundancer',        'kayak',      None),
    ('Betty Ann',        'paddleboat', None),
    ('Island Spirit',    'yacht',      None),
    ('MV Ohio Lady',     'towboat',    'Capt. Reyes'),
    ('Whispering Pines', 'paddleboat', None),
    ('Blue Heron',       'kayak',      None),
]

_FALLBACK_DOCK_NAMES = [
    {'name': 'Riverside Terminal', 'accepts': 'coal,steel',  'produces': 'grain'},
    {'name': 'Harbor Freight',     'accepts': 'grain,corn',  'produces': 'steel'},
    {'name': 'Mill Creek Landing', 'accepts': 'gravel',      'produces': 'coal'},
    {'name': 'Valley Port',        'accepts': 'corn,grain',  'produces': 'gravel'},
    {'name': 'Iron Bridge Dock',   'accepts': 'steel',       'produces': 'corn'},
    {'name': 'South Bend Wharf',   'accepts': 'coal,gravel', 'produces': 'grain'},
    {'name': 'River Bend Station', 'accepts': 'grain',       'produces': 'steel'},
    {'name': 'Lakeside Terminal',  'accepts': 'corn',        'produces': 'coal'},
    {'name': 'Crescent City Dock', 'accepts': 'steel,coal',  'produces': 'gravel'},
    {'name': 'Bayou Freight',      'accepts': 'gravel,corn', 'produces': 'grain'},
]

# ── Game time ──────────────────────────────────────────────────────────────────
MINS_PER_SEC = 2.5    # game-minutes per real second
START_HOUR   = 6.1    # 6:06 AM  (pre-dawn → dawn → full day → dusk → night)

# ── Docking ────────────────────────────────────────────────────────────────────
DOCK_SLOW    = 0.85   # max speed to register docking contact
DOCK_RADIUS  = 62     # world-unit radius to count as "at the dock"
UNLOAD_TIME  = 8.0    # real seconds to complete unloading

# ── Damage ─────────────────────────────────────────────────────────────────────
MAX_DAMAGE   = 6
HIT_COOLDOWN = 80     # frames of invulnerability after each hit

# ── Colour helpers ─────────────────────────────────────────────────────────────
def lerp3(a, b, t):
    t = max(0.0, min(1.0, t))
    return (int(a[0]+(b[0]-a[0])*t),
            int(a[1]+(b[1]-a[1])*t),
            int(a[2]+(b[2]-a[2])*t))

def dim3(c, m):
    return (max(0, min(255, int(c[0]*m))),
            max(0, min(255, int(c[1]*m))),
            max(0, min(255, int(c[2]*m))))

# Sky palette
SKY_DAWN  = (195,  82,  18)
SKY_DAY   = (128, 198, 238)
SKY_DUSK  = (205,  65,  10)
SKY_NIGHT = (  5,   8,  30)

WATER_DAY   = (48, 140, 200)
WATER_NIGHT = ( 9,  28,  68)
BANK_DAY    = (22,  74,  22)
BANK_NIGHT  = ( 5,  16,   5)

BUOY_G   = (  0, 200,  55)
BUOY_R   = (210,  18,  18)

TOW_BODY   = (135,  74,  26)
TOW_CABIN  = (180, 142,  50)
BARGE_COL  = (135, 122,  82)
BARGE_TRIM = ( 76,  68,  42)

OBS_ROCK    = ( 85,  72,  30)
OBS_SAND    = (190, 165,  90)
OBS_LOG     = ( 95,  68,  30)

DOCK_COL  = (158, 112,  44)
DOCK_LIT  = (255, 205,  60)

NAV_RED   = (160,   0,   0)
NAV_GREEN = (  0, 160,  40)
NAV_WHITE = (230, 230, 195)


# ── River curve ────────────────────────────────────────────────────────────────
class RiverCurve:
    """Smooth procedural river centreline: sum of three sinusoids.

    cx(y)  – X coordinate of the river centre at world-Y y
    dcx(y) – slope dx/dy (used to draw banks perpendicular to the flow)
    """

    def __init__(self, seed=None):
        rng = random.Random(seed)
        # (amplitude wu, angular-frequency 1/wu, phase rad)
        self._comp = [
            (rng.uniform( 55, 100), rng.uniform(0.0018, 0.0027), rng.uniform(0, 6.28)),
            (rng.uniform( 20,  45), rng.uniform(0.0065, 0.012 ), rng.uniform(0, 6.28)),
            (rng.uniform(  6,  16), rng.uniform(0.022,  0.040 ), rng.uniform(0, 6.28)),
        ]

    def cx(self, y: float) -> float:
        return sum(A * math.sin(w * y + p) for A, w, p in self._comp)

    def dcx(self, y: float) -> float:
        return sum(A * w * math.cos(w * y + p) for A, w, p in self._comp)


# ── World objects ──────────────────────────────────────────────────────────────
class Buoy:
    __slots__ = ('wx', 'wy', 'color', 'bob')

    def __init__(self, wx, wy, color):
        self.wx    = wx
        self.wy    = wy
        self.color = color
        self.bob   = random.uniform(0, 6.28)   # wave-bob phase


class Obstacle:
    __slots__ = ('wx', 'wy', 'kind', 'r')
    KINDS = ('rock', 'sandbar', 'log')

    def __init__(self, wx, wy, kind=None):
        self.wx   = wx
        self.wy   = wy
        self.kind = kind or random.choice(self.KINDS)
        self.r    = {'rock': 20, 'sandbar': 34, 'log': 11}[self.kind]


class DockedBarge:
    """A barge left at a dock — persists in world space."""
    def __init__(self, wx, wy, heading, cargo=None):
        self.wx      = wx
        self.wy      = wy
        self.heading = heading   # degrees; preserves orientation at detach
        self.cargo   = cargo     # None or (label, rgb)


class FreeBargeCluster:
    """Barge tow floating free after towboat disconnects — drifts with current."""
    CONNECT_RADIUS = 80   # world units: how close the towboat must be to reconnect

    def __init__(self, wx, wy, heading, barges):
        self.wx      = float(wx)
        self.wy      = float(wy)
        self.heading = heading
        self.barges  = barges   # list of TowBarge

    def update(self):
        # Drift downstream with hydrodynamic current (speed ≈ 0)
        self.wy += CURRENT_CD * CURRENT_Y * abs(CURRENT_Y)

    def draw(self, surf, cam_x, cam_y, ambient):
        sx = int(self.wx - cam_x + SW // 2)
        sy = int(self.wy - cam_y + VREF_Y)
        if not (-220 < sx < SW + 220 and -220 < sy < SH + 220):
            return
        r   = math.radians(self.heading)
        fx  = math.sin(r);  fy  = math.cos(r)
        rx  = math.cos(r);  ry  = -math.sin(r)
        bc  = dim3(BARGE_COL, ambient * 0.55 + 0.12)
        be  = dim3(BARGE_TRIM, ambient * 0.50 + 0.12)
        for b in self.barges:
            fwd_off = TH / 2 + PUSH + b.row * (BH + BGAP) + BH / 2
            lat_off = (b.col - (B_COLS - 1) / 2.0) * (BW + BGAP)
            bcx = sx + fx * fwd_off + rx * lat_off
            bcy = sy + fy * fwd_off + ry * lat_off
            hw, hl = BW / 2, BH / 2
            def _p(dx, dy, _x=bcx, _y=bcy):
                return (int(_x + dx), int(_y + dy))
            pts = [_p(fx*hl - rx*hw, fy*hl - ry*hw),
                   _p(fx*hl + rx*hw, fy*hl + ry*hw),
                   _p(-fx*hl + rx*hw, -fy*hl + ry*hw),
                   _p(-fx*hl - rx*hw, -fy*hl - ry*hw)]
            pygame.draw.polygon(surf, bc, pts)
            pygame.draw.polygon(surf, be, pts, 2)
            if b.cargo:
                _, cc = b.cargo
                cc = dim3(cc, ambient * 0.50 + 0.12)
                cpts = [_p(fx*hl*0.7 - rx*hw*0.6, fy*hl*0.7 - ry*hw*0.6),
                        _p(fx*hl*0.7 + rx*hw*0.6, fy*hl*0.7 + ry*hw*0.6),
                        _p(-fx*hl*0.7 + rx*hw*0.6, -fy*hl*0.7 + ry*hw*0.6),
                        _p(-fx*hl*0.7 - rx*hw*0.6, -fy*hl*0.7 - ry*hw*0.6)]
                pygame.draw.polygon(surf, cc, cpts)


class Dock:
    def __init__(self, wx, wy, side, name='', accepts=None, produces=None):
        self.wx             = wx
        self.wy             = wy
        self.side           = side       # +1 = river-right, -1 = river-left
        self.visited        = False
        self.name           = name
        self.accepts        = accepts or []   # cargo types this dock receives
        self.produces       = produces or []  # cargo types available to load here
        self.available_barge= None            # DockedBarge waiting for pickup, or None


# ── Barge unit ────────────────────────────────────────────────────────────────
_barge_id_counter = 0

class TowBarge:
    def __init__(self, row: int, col: int, cargo=None, bid: str = None):
        global _barge_id_counter
        self.row   = row
        self.col   = col
        self.cargo = cargo   # None  or  (label_str, rgb_tuple)
        self.tied  = False
        if bid:
            self.bid = bid
        else:
            self.bid = f'B{_barge_id_counter}'
            _barge_id_counter += 1

# Gap edges a deckhand must jump when walking between towboat and barges
_GAP_EDGES = [TH / 2, TH / 2 + PUSH]   # towboat-bow → barge-stern crossing

# ── Deckhand ───────────────────────────────────────────────────────────────────
class Deckhand:
    JUMP_DUR  = 0.28   # seconds airborne per gap crossing
    JUMP_HEIGHT = 10   # screen pixels at apex

    def __init__(self, name: str, color):
        self.name  = name
        self.color = color
        self.fwd   = 0.0
        self.lat   = 0.0
        self._tfwd = 0.0
        self._tlat = 0.0
        self.state      = 'idle'
        self.task       = None
        self._work_t    = 0.0
        self._work_dur  = 0.0
        self._on_done   = None
        self._jump_t    = 0.0   # > 0 while airborne

    def assign(self, task: str, tfwd: float, tlat: float, duration: float, on_done=None):
        self.task      = task
        self._tfwd     = tfwd
        self._tlat     = tlat
        self._work_dur = duration
        self._work_t   = 0.0
        self._on_done  = on_done
        self.state     = 'walking'

    def return_to_boat(self):
        """Override current task and walk back to towboat centre."""
        self.assign('return', 0.0, 0.0, 0.01)

    def update(self, dt):
        if self._jump_t > 0:
            self._jump_t = max(0.0, self._jump_t - dt)

        if self.state == 'idle':
            return

        if self.state == 'walking':
            prev_fwd = self.fwd
            dfwd = self._tfwd - self.fwd
            dlat = self._tlat - self.lat
            dist = math.hypot(dfwd, dlat)
            if dist <= DECKHAND_WALK:
                self.fwd, self.lat = self._tfwd, self._tlat
                self.state   = 'working'
                self._work_t = 0.0
            else:
                self.fwd += dfwd / dist * DECKHAND_WALK
                self.lat += dlat / dist * DECKHAND_WALK
            # Detect gap crossing → trigger jump
            for edge in _GAP_EDGES:
                if (prev_fwd - edge) * (self.fwd - edge) < 0:
                    self._jump_t = self.JUMP_DUR
                    break

        elif self.state == 'working':
            self._work_t += dt
            if self._work_t >= self._work_dur:
                self.state = 'idle'
                if self._on_done:
                    self._on_done()
                    self._on_done = None

    def world_pos(self, vessel):
        fx, fy = vessel.fwd
        rx, ry = vessel.rgt
        return (vessel.x + fx * self.fwd + rx * self.lat,
                vessel.y + fy * self.fwd + ry * self.lat)

    def draw(self, surf, vessel, cam_x, cam_y, ambient):
        if ambient < 0.15:
            return
        wx, wy = self.world_pos(vessel)
        sx = int(wx - cam_x + SW // 2)
        sy = int(wy - cam_y + VREF_Y)
        if not (-12 < sx < SW + 12 and -12 < sy < SH + 12):
            return
        # Vertical offsets: work bob or jump arc
        if self._jump_t > 0:
            frac = self._jump_t / self.JUMP_DUR
            rise = int(math.sin(frac * math.pi) * self.JUMP_HEIGHT)
        else:
            rise = 0
        bob  = int(math.sin(self._work_t * 9) * 2) if self.state == 'working' else 0
        lift = -(rise + bob)   # screen Y goes up when negative
        col  = dim3(self.color, ambient * 0.6 + 0.2)
        skin = dim3((220, 182, 135), ambient * 0.65 + 0.15)
        pygame.draw.circle(surf, col,  (sx, sy + lift),     4)
        pygame.draw.circle(surf, skin, (sx, sy - 6 + lift), 3)

# ── Vessel ─────────────────────────────────────────────────────────────────────
class Vessel:
    """Player-controlled towboat + barge formation.

    self.x, self.y is the geometric centre of the TOWBOAT.
    The barge formation lies ahead (in the forward direction):
      distance  TH/2 + PUSH … TH/2 + PUSH + FORM_L  from towboat centre.
    """

    def __init__(self, x: float, y: float):
        self.x          = float(x)
        self.y          = float(y)
        self.heading    = 0.0    # degrees; 0 = south (+Y = downward on screen)
        self.speed      = 0.0    # world units/frame (+ = forward)
        self.yaw_vel    = 0.0    # degrees/frame
        self.throttle   = 0.0   # -1 … +1  (driver input accumulator)
        self.steer      = 0.0   # -1=left, +1=right
        self.damage     = 0
        self.hit_cd     = 0     # frames of invulnerability remaining
        self.horn_timer = 0
        self.barges     = [TowBarge(r, c)
                           for r in range(B_ROWS) for c in range(B_COLS)]
        self.deckhands  = []   # populated by PilotGame

    # ── Direction helpers ──────────────────────────────────────────────────────
    @property
    def fwd(self):
        """Unit forward vector (in screen/world coords, Y increases downward)."""
        r = math.radians(self.heading)
        return math.sin(r), math.cos(r)

    @property
    def rgt(self):
        """Unit right-hand vector perpendicular to forward."""
        r = math.radians(self.heading)
        return math.cos(r), -math.sin(r)

    # ── Key positions ──────────────────────────────────────────────────────────
    @property
    def form_length(self):
        if not self.barges:
            return 0.0
        max_row = max(b.row for b in self.barges)
        return (max_row + 1) * BH + max_row * BGAP

    @property
    def bow_pos(self):
        fx, fy = self.fwd
        d = TH / 2 + PUSH + self.form_length
        return self.x + fx * d, self.y + fy * d

    @property
    def barge_center(self):
        fx, fy = self.fwd
        d = TH / 2 + PUSH + self.form_length / 2
        return self.x + fx * d, self.y + fy * d

    @property
    def stern_pos(self):
        fx, fy = self.fwd
        return self.x - fx * TH / 2, self.y - fy * TH / 2

    @property
    def form_half_width(self):
        if not self.barges:
            return TW / 2
        lats = [(b.col - (B_COLS - 1) / 2.0) * (BW + BGAP) for b in self.barges]
        return max(abs(l) for l in lats) + BW / 2

    def corners(self):
        """Hull corners sized to actual barge formation."""
        fx, fy = self.fwd
        rx, ry = self.rgt
        hw = self.form_half_width + 3
        bx, by = self.bow_pos
        sx, sy = self.stern_pos
        return [
            (bx - rx * hw, by - ry * hw),
            (bx + rx * hw, by + ry * hw),
            (sx + rx * (TW / 2), sy + ry * (TW / 2)),
            (sx - rx * (TW / 2), sy - ry * (TW / 2)),
        ]

    # ── Update ─────────────────────────────────────────────────────────────────
    def update(self, keys):
        if self.horn_timer > 0:
            self.horn_timer -= 1
        if self.hit_cd > 0:
            self.hit_cd -= 1

        # Throttle
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            self.throttle = min(1.0, self.throttle + 0.022)
        elif keys[pygame.K_s] or keys[pygame.K_DOWN]:
            self.throttle = max(-0.5, self.throttle - 0.022)
        else:
            self.throttle *= 0.96

        # Steer
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            self.steer = -1.0
        elif keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            self.steer = +1.0
        else:
            self.steer = 0.0

        # Speed
        self.speed += self.throttle * ACCEL
        self.speed *= DRAG
        self.speed  = max(-MAX_REV, min(MAX_FWD, self.speed))

        # Yaw  (sluggish barge tow — harder to turn at low speed)
        spd_f = min(1.0, abs(self.speed) / (MAX_FWD * 0.4))
        target_yaw = self.steer * YAW_MAX * spd_f
        self.yaw_vel += (target_yaw - self.yaw_vel) * 0.07
        self.yaw_vel *= YAW_DAMP

        # Pivot around the barge bow: towboat (at rear) swings the stern,
        # bow traces the path — like forklift / rear-wheel steering.
        fx_old, fy_old = self.fwd
        bow_d = (TH / 2 + PUSH + self.form_length) if self.barges else TH / 2
        bx = self.x + fx_old * bow_d
        by = self.y + fy_old * bow_d
        self.heading = (self.heading + self.yaw_vel) % 360.0
        fx, fy = self.fwd
        bx += fx * self.speed
        by += fy * self.speed
        self.x = bx - fx * bow_d
        self.y = by - fy * bow_d

        # Hydrodynamic current drag: F = Cd · v_rel · |v_rel|  (quadratic)
        # River flows +Y; relative velocity is (current - vessel world velocity).
        vrel_x = 0.0 - fx * self.speed
        vrel_y = CURRENT_Y - fy * self.speed
        self.x += CURRENT_CD * vrel_x * abs(vrel_x)
        self.y += CURRENT_CD * vrel_y * abs(vrel_y)

    # ── Draw ───────────────────────────────────────────────────────────────────
    def draw(self, surf, cam_x, cam_y, ambient):
        def ws(wx, wy):
            return int(wx - cam_x + SW // 2), int(wy - cam_y + VREF_Y)

        fx, fy = self.fwd
        rx, ry = self.rgt
        dark   = ambient < 0.5

        # ── Barges ────────────────────────────────────────────────────────────
        bc_base = dim3(BARGE_COL, ambient * 0.60 + 0.12)
        be_base = dim3(BARGE_TRIM, ambient * 0.55 + 0.12)
        for barge in self.barges:
            fwd_off = TH / 2 + PUSH + barge.row * (BH + BGAP) + BH / 2
            lat_off = (barge.col - (B_COLS - 1) / 2.0) * (BW + BGAP)
            bcx = self.x + fx * fwd_off + rx * lat_off
            bcy = self.y + fy * fwd_off + ry * lat_off
            hw, hl = BW / 2, BH / 2
            pts = [
                ws(bcx + fx * hl - rx * hw, bcy + fy * hl - ry * hw),
                ws(bcx + fx * hl + rx * hw, bcy + fy * hl + ry * hw),
                ws(bcx - fx * hl + rx * hw, bcy - fy * hl + ry * hw),
                ws(bcx - fx * hl - rx * hw, bcy - fy * hl - ry * hw),
            ]
            pygame.draw.polygon(surf, bc_base, pts)
            pygame.draw.polygon(surf, be_base, pts, 2)
            # cargo load fill
            if barge.cargo:
                _, cargo_col = barge.cargo
                cc = dim3(cargo_col, ambient * 0.55 + 0.12)
                cargo_pts = [
                    ws(bcx + fx * (hl * 0.72) - rx * (hw * 0.62),
                       bcy + fy * (hl * 0.72) - ry * (hw * 0.62)),
                    ws(bcx + fx * (hl * 0.72) + rx * (hw * 0.62),
                       bcy + fy * (hl * 0.72) + ry * (hw * 0.62)),
                    ws(bcx - fx * (hl * 0.72) + rx * (hw * 0.62),
                       bcy - fy * (hl * 0.72) + ry * (hw * 0.62)),
                    ws(bcx - fx * (hl * 0.72) - rx * (hw * 0.62),
                       bcy - fy * (hl * 0.72) - ry * (hw * 0.62)),
                ]
                pygame.draw.polygon(surf, cc, cargo_pts)
            elif ambient > 0.35:
                # empty hatch line
                mf = ws(bcx + fx * (hl * 0.5) - rx * (hw * 0.7),
                        bcy + fy * (hl * 0.5) - ry * (hw * 0.7))
                mr = ws(bcx + fx * (hl * 0.5) + rx * (hw * 0.7),
                        bcy + fy * (hl * 0.5) + ry * (hw * 0.7))
                pygame.draw.line(surf, be_base, mf, mr, 1)
            # tied indicator (small dot at bow edge)
            if barge.tied:
                bp = ws(bcx + fx * hl, bcy + fy * hl)
                pygame.draw.circle(surf, (220, 200, 80), bp, 3)

        # ── Towboat hull ───────────────────────────────────────────────────────
        hw, hl = TW / 2, TH / 2
        hull = [
            ws(self.x + fx * hl - rx * hw, self.y + fy * hl - ry * hw),
            ws(self.x + fx * hl + rx * hw, self.y + fy * hl + ry * hw),
            ws(self.x - fx * hl + rx * hw, self.y - fy * hl + ry * hw),
            ws(self.x - fx * hl - rx * hw, self.y - fy * hl - ry * hw),
        ]
        tc = dim3(TOW_BODY, ambient * 0.55 + 0.15)
        pygame.draw.polygon(surf, tc, hull)
        pygame.draw.polygon(surf, dim3((10, 10, 10), 1), hull, 2)

        # Pilothouse
        ph_f = hl * 0.18
        ph_hw = hw * 0.5
        ph_hl = hl * 0.62
        ph = [
            ws(self.x + fx * (ph_f + ph_hl) - rx * ph_hw,
               self.y + fy * (ph_f + ph_hl) - ry * ph_hw),
            ws(self.x + fx * (ph_f + ph_hl) + rx * ph_hw,
               self.y + fy * (ph_f + ph_hl) + ry * ph_hw),
            ws(self.x + fx * (ph_f - ph_hl) + rx * ph_hw,
               self.y + fy * (ph_f - ph_hl) + ry * ph_hw),
            ws(self.x + fx * (ph_f - ph_hl) - rx * ph_hw,
               self.y + fy * (ph_f - ph_hl) - ry * ph_hw),
        ]
        pygame.draw.polygon(surf, dim3(TOW_CABIN, ambient * 0.52 + 0.15), ph)

        # ── Navigation lights ──────────────────────────────────────────────────
        glow_a = int(max(0, min(220, (0.55 - ambient) * 550)))
        port_ws  = ws(self.x - rx * hw * 0.9, self.y - ry * hw * 0.9)
        stbd_ws  = ws(self.x + rx * hw * 0.9, self.y + ry * hw * 0.9)
        stern_ws = ws(self.x - fx * hl * 0.9, self.y - fy * hl * 0.9)
        for pos, col, r in [(port_ws, NAV_RED, 5), (stbd_ws, NAV_GREEN, 5),
                            (stern_ws, NAV_WHITE, 4)]:
            pygame.draw.circle(surf, col, pos, r)
            if glow_a > 15:
                gr = r * 5
                gsurf = pygame.Surface((gr * 2, gr * 2), pygame.SRCALPHA)
                pygame.draw.circle(gsurf, (*col, glow_a), (gr, gr), gr)
                surf.blit(gsurf, (pos[0] - gr, pos[1] - gr))

        # Deckhands
        for dh in self.deckhands:
            dh.draw(surf, self, cam_x, cam_y, ambient)

        # Hit flash
        if self.hit_cd > HIT_COOLDOWN - 15:
            fl = pygame.Surface((SW, SH), pygame.SRCALPHA)
            fl.fill((255, 40, 40, 55))
            surf.blit(fl, (0, 0))


# ── Daily goal ─────────────────────────────────────────────────────────────────
class DailyGoal:
    def __init__(self, bid: str, dock_name: str, cargo_label: str, bonus: float = 180.0):
        self.bid        = bid          # which barge (e.g. 'B0')
        self.dock_name  = dock_name
        self.cargo_label= cargo_label  # required cargo type
        self.bonus      = bonus
        self.completed  = False

    def describe(self) -> str:
        return f'{self.bid}  →  {self.dock_name}  [{self.cargo_label}]'


# ── World generation ───────────────────────────────────────────────────────────
def generate_world(river: RiverCurve, dock_name_pool=None):
    """Pre-generate buoys, obstacles and docks for the full GEN_LIMIT range."""
    buoys, obstacles, docks = [], [], []
    if dock_name_pool is None:
        dock_name_pool = list(_FALLBACK_DOCK_NAMES)
    rng_dock = random.Random(42)   # stable names across restarts within a session

    # Buoy pairs
    y = BUOY_SPACING
    while y < GEN_LIMIT:
        cx = river.cx(y)
        slope = river.dcx(y)
        # Perpendicular direction to river centreline (normalised)
        length = math.hypot(slope, 1.0)
        perp_x = slope / length    # perpendicular points "river-right"
        perp_y = -1.0   / length   # (rotated 90° from flow direction)
        # Wait — for a flow direction (dcx, 1) the perpendicular rightward is (1, -dcx) normalised
        # flow direction: (dcx, 1) unnormalised → normalised: (dcx/L, 1/L)
        # right-perp: (1/L, -dcx/L)
        L = math.hypot(slope, 1.0)
        px, py = 1.0 / L, -slope / L

        # Green (starboard/river-right) buoy
        gx = cx + px * CHANNEL_HALF
        gy = y  + py * CHANNEL_HALF
        buoys.append(Buoy(gx, gy, 'green'))

        # Red (port/river-left) buoy
        rx = cx - px * CHANNEL_HALF
        ry = y  - py * CHANNEL_HALF
        buoys.append(Buoy(rx, ry, 'red'))

        y += BUOY_SPACING

    # Obstacles (outside channel, inside river)
    y = OBS_STEP
    while y < GEN_LIMIT:
        if random.random() < OBS_CHANCE:
            cx = river.cx(y)
            slope = river.dcx(y)
            L = math.hypot(slope, 1.0)
            px, py = 1.0 / L, -slope / L
            # Place on a random side, between channel edge and river bank
            side  = random.choice((-1, 1))
            dist  = random.uniform(CHANNEL_HALF + 8, RIVER_HALF - 22)
            ox    = cx + side * px * dist
            oy    = y  + side * py * dist
            obstacles.append(Obstacle(ox, oy))
        y += OBS_STEP

    # Docks
    y = DOCK_INTERVAL
    side_alt = 1
    while y < GEN_LIMIT:
        cx = river.cx(y)
        slope = river.dcx(y)
        L = math.hypot(slope, 1.0)
        px, py = 1.0 / L, -slope / L
        side = side_alt
        side_alt *= -1
        dist = RIVER_HALF - 20
        dx = cx + side * px * dist
        dy = y  + side * py * dist
        info = rng_dock.choice(dock_name_pool)
        accepts  = [s.strip() for s in info.get('accepts', '').split(',') if s.strip()]
        produces = [s.strip() for s in info.get('produces', '').split(',') if s.strip()]
        dock = Dock(dx, dy, side, name=info['name'], accepts=accepts, produces=produces)
        # 35 % chance a barge is already waiting at this dock
        if rng_dock.random() < 0.35 and produces:
            cargo_label = rng_dock.choice(produces)
            cargo_col   = next((c for n, c in CARGO_TYPES if n == cargo_label), (120,120,80))
            dock.available_barge = DockedBarge(dx, dy, 0.0, (cargo_label, cargo_col))
        docks.append(dock)
        y += DOCK_INTERVAL

    return buoys, obstacles, docks


# ── Ambient / sky ──────────────────────────────────────────────────────────────
def get_ambient(game_hour: float) -> float:
    """Return a 0..1 brightness factor based on time of day."""
    h = game_hour % 24
    if 8.0 <= h < 17.5:
        return 1.0
    if 17.5 <= h < 20.5:
        return 1.0 - (h - 17.5) / 3.0 * 0.75   # dusk: 1→0.25
    if 20.5 <= h or h < 5.0:
        return 0.20
    if 5.0 <= h < 7.0:
        return 0.20 + (h - 5.0) / 2.0 * 0.70    # dawn: 0.20→0.90
    if 7.0 <= h < 8.0:
        return 0.90 + (h - 7.0) * 0.10           # late-dawn: 0.90→1.0
    return 1.0


def get_sky_color(game_hour: float):
    h = game_hour % 24
    if 8.0 <= h < 17.0:
        return SKY_DAY
    if 17.0 <= h < 19.0:
        return lerp3(SKY_DAY, SKY_DUSK, (h - 17.0) / 2.0)
    if 19.0 <= h < 21.0:
        return lerp3(SKY_DUSK, SKY_NIGHT, (h - 19.0) / 2.0)
    if 21.0 <= h or h < 5.5:
        return SKY_NIGHT
    if 5.5 <= h < 7.0:
        return lerp3(SKY_NIGHT, SKY_DAWN, (h - 5.5) / 1.5)
    if 7.0 <= h < 8.0:
        return lerp3(SKY_DAWN, SKY_DAY, (h - 7.0) / 1.0)
    return SKY_DAY


# ── River rendering ────────────────────────────────────────────────────────────
def draw_river(surf, river: RiverCurve, cam_x, cam_y, ambient, wave_t):
    """Draw sky, banks, water, and channel tint for the visible area."""
    sky_col   = get_sky_color   # actually we call below with time
    water_col = lerp3(WATER_DAY, WATER_NIGHT, 1.0 - ambient)
    bank_col  = lerp3(BANK_DAY,  BANK_NIGHT,  1.0 - ambient)

    # Fill entire surface with bank colour (land background)
    surf.fill(bank_col)

    # Compute visible Y range in world space
    top_y = int(cam_y - VREF_Y - 50)
    bot_y = int(cam_y + (SH - VREF_Y) + 50)
    step  = 8    # world-unit sample spacing

    # Build left-bank and right-bank screen polylines
    left_pts  = []
    right_pts = []
    for wy in range(top_y, bot_y + step, step):
        cx = river.cx(wy)
        sx = int(cx - cam_x + SW // 2)
        sy = int(wy - cam_y + VREF_Y)
        left_pts.append ((sx - RIVER_HALF, sy))
        right_pts.append((sx + RIVER_HALF, sy))

    # Water polygon
    if len(left_pts) >= 2:
        water_poly = left_pts + list(reversed(right_pts))
        pygame.draw.polygon(surf, water_col, water_poly)

    # Channel tint (slightly lighter/bluer than general river)
    ch_tint = lerp3(water_col, (90, 165, 225), 0.18 * ambient)
    ch_left  = []
    ch_right = []
    for wy in range(top_y, bot_y + step, step):
        cx = river.cx(wy)
        sx = int(cx - cam_x + SW // 2)
        sy = int(wy - cam_y + VREF_Y)
        ch_left.append ((sx - CHANNEL_HALF, sy))
        ch_right.append((sx + CHANNEL_HALF, sy))
    if len(ch_left) >= 2:
        pygame.draw.polygon(surf, ch_tint, ch_left + list(reversed(ch_right)))

    # Subtle water sparkle lines
    if ambient > 0.3:
        rng = random.Random(int(wave_t * 0.3))
        sparkle_col = lerp3(water_col, (180, 220, 240), 0.25)
        for _ in range(18):
            wy = rng.randint(top_y, bot_y)
            cx = river.cx(wy)
            off = rng.uniform(-RIVER_HALF * 0.8, RIVER_HALF * 0.8)
            sx = int(cx + off - cam_x + SW // 2)
            sy = int(wy - cam_y + VREF_Y)
            pygame.draw.line(surf, sparkle_col, (sx - 6, sy), (sx + 6, sy), 1)

    # Bank edge lines for definition
    edge_col = dim3(bank_col, 0.65)
    if len(left_pts) >= 2:
        pygame.draw.lines(surf, edge_col, False, left_pts,  2)
        pygame.draw.lines(surf, edge_col, False, right_pts, 2)

    # Simple trees on banks (daytime only) — seeded per strip so positions are fixed
    if ambient > 0.5:
        tree_col   = dim3((28, 90, 28), ambient)
        trunk_col  = dim3((80, 55, 20), ambient)
        STRIP = 90   # world-Y between tree strips
        strip_start = top_y - (top_y % STRIP)
        for strip_wy in range(strip_start, bot_y + STRIP, STRIP):
            rng  = random.Random(strip_wy)
            side = rng.choice((-1, 1))
            off  = rng.uniform(RIVER_HALF + 12, RIVER_HALF + 65)
            cx   = river.cx(strip_wy)
            wy   = strip_wy
            tx = int(cx + side * off - cam_x + SW // 2)
            ty = int(wy - cam_y + VREF_Y)
            if 0 <= tx < SW and 0 <= ty < SH:
                pygame.draw.line(surf, trunk_col, (tx, ty + 8), (tx, ty - 2), 2)
                pygame.draw.circle(surf, tree_col, (tx, ty - 4), 8)


# ── Object rendering ───────────────────────────────────────────────────────────
def draw_buoys(surf, buoys, cam_x, cam_y, ambient, wave_t):
    for b in buoys:
        sx = int(b.wx - cam_x + SW // 2)
        sy = int(b.wy - cam_y + VREF_Y)
        if -20 < sx < SW + 20 and -20 < sy < SH + 20:
            bob_off = int(math.sin(wave_t * 1.4 + b.bob) * 2)
            sy += bob_off
            col = BUOY_G if b.color == 'green' else BUOY_R
            dc  = dim3(col, ambient * 0.55 + 0.15)
            # Buoy body
            pygame.draw.circle(surf, dc, (sx, sy), 6)
            pygame.draw.circle(surf, dim3(col, 0.5), (sx, sy), 6, 1)
            # Pole / spar
            pygame.draw.line(surf, dim3(col, 0.55), (sx, sy - 6), (sx, sy - 14), 1)
            # Light glow at night
            glow_a = int(max(0, min(255, (0.55 - ambient) * 600)))
            if glow_a > 20:
                gr = 14
                gsurf = pygame.Surface((gr * 2, gr * 2), pygame.SRCALPHA)
                r, g, bv = col
                pygame.draw.circle(gsurf, (r, g, bv, glow_a), (gr, gr), gr)
                surf.blit(gsurf, (sx - gr, sy - gr))
                # Flashing: every ~2 s
                flash_phase = (wave_t * 0.5 + b.bob) % (2 * math.pi)
                if math.sin(flash_phase * 2) > 0.6:
                    pygame.draw.circle(surf, col, (sx, sy), 9)


def draw_obstacles(surf, obstacles, cam_x, cam_y, ambient):
    for o in obstacles:
        sx = int(o.wx - cam_x + SW // 2)
        sy = int(o.wy - cam_y + VREF_Y)
        if -60 < sx < SW + 60 and -60 < sy < SH + 60:
            if o.kind == 'rock':
                col = dim3(OBS_ROCK, ambient * 0.5 + 0.18)
                pygame.draw.ellipse(surf, col,
                    (sx - o.r, sy - int(o.r * 0.65), o.r * 2, int(o.r * 1.3)))
                pygame.draw.ellipse(surf, dim3(OBS_ROCK, 0.3),
                    (sx - o.r, sy - int(o.r * 0.65), o.r * 2, int(o.r * 1.3)), 1)
            elif o.kind == 'sandbar':
                col = dim3(OBS_SAND, ambient * 0.6 + 0.2)
                pygame.draw.ellipse(surf, col,
                    (sx - o.r, sy - int(o.r * 0.4), o.r * 2, int(o.r * 0.8)))
            else:   # log
                col = dim3(OBS_LOG, ambient * 0.5 + 0.15)
                pygame.draw.ellipse(surf, col,
                    (sx - o.r * 2, sy - o.r // 2, o.r * 4, o.r))


def draw_docked_barges(surf, docked_barges, cam_x, cam_y, ambient):
    for db in docked_barges:
        sx = int(db.wx - cam_x + SW // 2)
        sy = int(db.wy - cam_y + VREF_Y)
        if not (-120 < sx < SW + 120 and -120 < sy < SH + 120):
            continue
        r   = math.radians(db.heading)
        fx  = math.sin(r);  fy  = math.cos(r)
        rx  = math.cos(r);  ry  = -math.sin(r)
        hw, hl = BW / 2, BH / 2
        def _ws(dx, dy, _sx=sx, _sy=sy):
            return (int(_sx + dx), int(_sy + dy))
        pts = [
            _ws( fx*hl - rx*hw,  fy*hl - ry*hw),
            _ws( fx*hl + rx*hw,  fy*hl + ry*hw),
            _ws(-fx*hl + rx*hw, -fy*hl + ry*hw),
            _ws(-fx*hl - rx*hw, -fy*hl - ry*hw),
        ]
        bc = dim3(BARGE_COL, ambient * 0.55 + 0.12)
        be = dim3(BARGE_TRIM, ambient * 0.50 + 0.12)
        pygame.draw.polygon(surf, bc, pts)
        pygame.draw.polygon(surf, be, pts, 2)
        if db.cargo:
            _, cc = db.cargo
            cc = dim3(cc, ambient * 0.50 + 0.12)
            cpts = [
                _ws( fx*hl*0.7 - rx*hw*0.6,  fy*hl*0.7 - ry*hw*0.6),
                _ws( fx*hl*0.7 + rx*hw*0.6,  fy*hl*0.7 + ry*hw*0.6),
                _ws(-fx*hl*0.7 + rx*hw*0.6, -fy*hl*0.7 + ry*hw*0.6),
                _ws(-fx*hl*0.7 - rx*hw*0.6, -fy*hl*0.7 - ry*hw*0.6),
            ]
            pygame.draw.polygon(surf, cc, cpts)
        # Mooring line to dock
        pygame.draw.line(surf, dim3((180, 155, 90), ambient * 0.5 + 0.1),
                         _ws(0, 0), (sx + int(rx * (hw + 14)), sy + int(ry * (hw + 14))), 1)


def draw_docks(surf, docks, cam_x, cam_y, ambient, active_dock, unload_t, game_hour):
    for d in docks:
        sx = int(d.wx - cam_x + SW // 2)
        sy = int(d.wy - cam_y + VREF_Y)
        if -80 < sx < SW + 80 and -80 < sy < SH + 80:
            is_active = (d is active_dock)
            dc = dim3(DOCK_COL, ambient * 0.55 + 0.20)
            # Dock platform
            pygame.draw.rect(surf, dc, (sx - 24, sy - 12, 48, 24))
            pygame.draw.rect(surf, dim3(DOCK_COL, 0.4), (sx - 24, sy - 12, 48, 24), 2)
            # Pilings
            for dx in (-14, 0, 14):
                pygame.draw.line(surf, dim3((100, 75, 30), ambient * 0.5 + 0.1),
                                 (sx + dx, sy + 12), (sx + dx, sy + 22), 3)
            # Active / unloading indicator
            if is_active and unload_t > 0:
                # Progress bar
                frac = 1.0 - unload_t / UNLOAD_TIME
                pygame.draw.rect(surf, (60, 60, 60), (sx - 22, sy - 24, 44, 7))
                pygame.draw.rect(surf, (60, 200, 60),
                                 (sx - 22, sy - 24, int(44 * frac), 7))
            # Lights
            light_on = ambient < 0.7
            lc = DOCK_LIT if light_on else dim3(DOCK_LIT, 0.4)
            pygame.draw.circle(surf, lc, (sx - 18, sy - 16), 4)
            pygame.draw.circle(surf, lc, (sx + 18, sy - 16), 4)
            if light_on:
                for lx in (sx - 18, sx + 18):
                    gsurf = pygame.Surface((24, 24), pygame.SRCALPHA)
                    pygame.draw.circle(gsurf, (*DOCK_LIT, 80), (12, 12), 12)
                    surf.blit(gsurf, (lx - 12, sy - 28))
            # "DOCK" approach arrow if not visited
            if not d.visited:
                arrow_col = (255, 230, 60)
                if is_active:
                    arrow_col = (60, 255, 60)
                font_sm = pygame.font.SysFont('monospace', 11, bold=True)
                lbl = font_sm.render('DOCK', True, arrow_col)
                surf.blit(lbl, (sx - lbl.get_width() // 2, sy - 38))


# ── HUD ────────────────────────────────────────────────────────────────────────
def draw_hud(surf, vessel: Vessel, game_hour, score, dock_dist,
             active_dock, unload_t, font, font_sm,
             earnings=0.0, reward_msg='', reward_timer=0.0):
    h = int(game_hour)
    m = int((game_hour - h) * 60)
    time_str = f"{h:02d}:{m:02d}"
    speed_kts = abs(vessel.speed) / MAX_FWD * 12.0  # scale to ~0-12 kts

    # Damage bar
    BAR_X, BAR_Y = 16, 16
    BAR_W, BAR_H = 140, 16
    pygame.draw.rect(surf, (40, 40, 40), (BAR_X - 1, BAR_Y - 1, BAR_W + 2, BAR_H + 2))
    dmg_frac = vessel.damage / MAX_DAMAGE
    bar_col = lerp3((40, 210, 40), (220, 30, 30), dmg_frac)
    fill_w = int((1.0 - dmg_frac) * BAR_W)
    pygame.draw.rect(surf, bar_col, (BAR_X, BAR_Y, fill_w, BAR_H))
    lbl = font_sm.render('HULL', True, (210, 210, 210))
    surf.blit(lbl, (BAR_X, BAR_Y + BAR_H + 3))

    # Speed indicator
    spd_col = (200, 200, 80) if vessel.throttle >= 0 else (80, 180, 220)
    spd_str = f"{'FWD' if vessel.speed >= 0 else 'REV'}  {speed_kts:.1f} kts"
    surf.blit(font_sm.render(spd_str, True, spd_col), (BAR_X, BAR_Y + BAR_H + 20))

    # Throttle bar
    thr_w = 80
    thr_frac = (vessel.throttle + 0.5) / 1.5  # map -0.5..1 → 0..1
    pygame.draw.rect(surf, (40, 40, 40), (BAR_X, BAR_Y + BAR_H + 38, thr_w, 8))
    pygame.draw.rect(surf, (80, 160, 80),
                     (BAR_X, BAR_Y + BAR_H + 38, int(thr_w * thr_frac), 8))
    surf.blit(font_sm.render('THROTTLE', True, (180, 180, 180)),
              (BAR_X, BAR_Y + BAR_H + 48))

    # Time and score (top right)
    ts = font.render(time_str, True, (230, 220, 190))
    surf.blit(ts, (SW - ts.get_width() - 16, 14))
    sc = font_sm.render(f"MILES: {int(score / 100)}   ${earnings:.0f}", True, (190, 210, 190))
    surf.blit(sc, (SW - sc.get_width() - 16, 14 + ts.get_height() + 4))

    if reward_msg and reward_timer > 0:
        alpha = min(255, int(reward_timer * 120))
        rc = (80, 235, 120) if reward_timer > 1.0 else (235, 220, 80)
        rl = font.render(reward_msg, True, rc)
        surf.blit(rl, (SW // 2 - rl.get_width() // 2, SH - 100))


def draw_goals(surf, goals, font_sm):
    """Draw the daily goals list in the top-right below the earnings line."""
    if not goals:
        return
    GX = SW - 310
    GY = 70
    for goal in goals:
        done   = goal.completed
        col    = (80, 220, 100) if done else (200, 195, 140)
        prefix = '[x] ' if done else '[ ] '
        lbl    = font_sm.render(prefix + goal.describe(), True, col)
        surf.blit(lbl, (GX, GY))
        GY += lbl.get_height() + 3

    # Dock approach indicator
    if dock_dist is not None and not active_dock:
        if dock_dist < 600:
            a = max(0.0, min(1.0, 1.0 - dock_dist / 600))
            col = lerp3((200, 200, 60), (60, 255, 60), a)
            msg = f"TERMINAL  {int(dock_dist)} m"
            lbl = font.render(msg, True, col)
            surf.blit(lbl, (SW // 2 - lbl.get_width() // 2, SH - 52))

    # Unloading status
    if active_dock and unload_t > 0:
        frac = 1.0 - unload_t / UNLOAD_TIME
        msg = f"UNLOADING  {int(frac * 100)}%"
        lbl = font.render(msg, True, (60, 230, 60))
        surf.blit(lbl, (SW // 2 - lbl.get_width() // 2, SH - 52))

    # Night warning
    amb = get_ambient(game_hour)
    if amb < 0.45:
        nlbl = font_sm.render('NIGHT NAVIGATION  –  watch the buoys',
                               True, (180, 160, 80))
        surf.blit(nlbl, (SW // 2 - nlbl.get_width() // 2, SH - 80))

    # Heading compass (simple)
    hx, hy = SW - 55, SH - 55
    pygame.draw.circle(surf, (50, 50, 50), (hx, hy), 30)
    pygame.draw.circle(surf, (80, 80, 80), (hx, hy), 30, 1)
    hr = math.radians(vessel.heading)
    nx = int(hx + math.sin(hr) * 22)
    ny = int(hy + math.cos(hr) * 22)
    pygame.draw.line(surf, (220, 50, 50), (hx, hy), (nx, ny), 3)
    pygame.draw.circle(surf, (220, 220, 220), (hx, hy), 3)
    surf.blit(font_sm.render('N', True, (200, 200, 200)),
              (hx - 4, hy - 30 - 14))


# ── Game over / pause overlays ─────────────────────────────────────────────────
def draw_game_over(surf, score, font_lg, font):
    ov = pygame.Surface((SW, SH), pygame.SRCALPHA)
    ov.fill((0, 0, 0, 170))
    surf.blit(ov, (0, 0))
    t1 = font_lg.render('GROUNDED', True, (220, 60, 60))
    t2 = font.render(f'Distance covered: {int(score / 100)} miles', True, (200, 200, 200))
    t3 = font.render('Press  R  to restart', True, (160, 210, 160))
    surf.blit(t1, (SW // 2 - t1.get_width() // 2, SH // 2 - 80))
    surf.blit(t2, (SW // 2 - t2.get_width() // 2, SH // 2))
    surf.blit(t3, (SW // 2 - t3.get_width() // 2, SH // 2 + 50))


def draw_intro(surf, font_lg, font):
    ov = pygame.Surface((SW, SH), pygame.SRCALPHA)
    ov.fill((0, 0, 0, 185))
    surf.blit(ov, (0, 0))
    lines = [
        ('RIVER TOWBOAT PILOT', font_lg, (200, 180, 100)),
        ('Steer the 2×2 barge tow downriver', font, (210, 210, 210)),
        ('Stay inside the channel markers (green right, red left)', font, (210, 210, 210)),
        ('Avoid rocks, sandbars and logs outside the channel', font, (210, 210, 210)),
        ('Pull into terminals when signalled — keep speed low', font, (210, 210, 210)),
        ('', font, (0, 0, 0)),
        ('W/S  throttle     A/D  steer     SPACE  horn', font, (160, 200, 160)),
        ('', font, (0, 0, 0)),
        ('Press  SPACE  to begin', font, (255, 220, 60)),
    ]
    y = SH // 2 - len(lines) * 22
    for txt, fnt, col in lines:
        if txt:
            r = fnt.render(txt, True, col)
            surf.blit(r, (SW // 2 - r.get_width() // 2, y))
        y += fnt.size('A')[1] + 8


# ── AI river traffic vessel ────────────────────────────────────────────────────
class AIVessel:
    def __init__(self, wx, wy, direction, vessel_type, name, captain=None):
        self.wx          = float(wx)
        self.wy          = float(wy)
        self.direction   = direction      # +1 downstream, -1 upstream
        self.vessel_type = vessel_type
        self.name        = name
        self.captain     = captain
        self.speed       = (_AI_SPEEDS.get(vessel_type, 1.5)
                            * random.uniform(0.85, 1.15))

    def update(self, river: RiverCurve):
        self.wy += self.speed * self.direction
        self.wx  = river.cx(self.wy)

    def draw(self, surf, cam_x, cam_y, ambient, river: RiverCurve, wave_t, font_sm):
        sx = int(self.wx - cam_x + SW // 2)
        sy = int(self.wy - cam_y + VREF_Y)
        if not (-200 < sx < SW + 200 and -200 < sy < SH + 200):
            return

        # Heading follows river tangent; flip 180° for upstream
        slope   = river.dcx(self.wy)
        L       = math.hypot(slope, 1.0)
        fx, fy  = slope / L * self.direction, 1.0 / L * self.direction
        rx, ry  = fy, -fx   # right-hand perpendicular

        hw, hl = _AI_DIMS.get(self.vessel_type, (10, 30))
        col    = dim3(_AI_COLORS.get(self.vessel_type, (120, 120, 120)),
                      ambient * 0.55 + 0.15)
        trim   = dim3(_AI_COLORS.get(self.vessel_type, (120, 120, 120)),
                      ambient * 0.30 + 0.10)

        def ws(dx, dy):
            return (int(sx + dx), int(sy + dy))

        pts = [
            ws( fx*hl - rx*hw,  fy*hl - ry*hw),
            ws( fx*hl + rx*hw,  fy*hl + ry*hw),
            ws(-fx*hl + rx*hw, -fy*hl + ry*hw),
            ws(-fx*hl - rx*hw, -fy*hl - ry*hw),
        ]
        pygame.draw.polygon(surf, col, pts)
        pygame.draw.polygon(surf, trim, pts, 2)

        # Nav lights at night
        glow_a = int(max(0, min(200, (0.55 - ambient) * 500)))
        port_s  = ws(-rx * hw * 0.9, -ry * hw * 0.9)
        stbd_s  = ws( rx * hw * 0.9,  ry * hw * 0.9)
        stern_s = ws(-fx * hl * 0.9, -fy * hl * 0.9)
        for pos, ncol, r in [(port_s, NAV_RED, 3), (stbd_s, NAV_GREEN, 3),
                              (stern_s, NAV_WHITE, 2)]:
            pygame.draw.circle(surf, ncol, pos, r)
            if glow_a > 20:
                gr = r * 4
                gs = pygame.Surface((gr*2, gr*2), pygame.SRCALPHA)
                pygame.draw.circle(gs, (*ncol, glow_a), (gr, gr), gr)
                surf.blit(gs, (pos[0]-gr, pos[1]-gr))

        # Name label
        if ambient > 0.25:
            label = self.name if not self.captain else f'{self.name}'
            lbl   = font_sm.render(label, True, dim3((220, 220, 200), ambient * 0.7 + 0.15))
            surf.blit(lbl, (sx - lbl.get_width() // 2, sy - hl - 14))


# ── Main game class ────────────────────────────────────────────────────────────
class PilotGame:

    HOURLY_WAGE = 18.0    # $/game-hour (aligns with other sim stages)
    DOCK_BONUS  = 110.0   # $ per completed terminal visit

    def __init__(self, shift_duration=None, shift_start_time=START_HOUR,
                 cfg_time_scale=None, dev_mode=False):
        seed = random.randint(0, 99999)
        self.river          = RiverCurve(seed)
        self._dock_name_pool = self._load_dock_name_pool()
        self.buoys, self.obstacles, self.docks = generate_world(
            self.river, self._dock_name_pool)

        start_cx = self.river.cx(0)
        self.vessel = Vessel(start_cx, 0.0)

        self.game_time   = shift_start_time
        self.score       = 0           # dock visits completed
        self.game_over   = False
        self.show_intro  = True
        self.dev_mode    = dev_mode

        # Shift tracking (mirrors other sims)
        self._shift_duration    = shift_duration
        self.shift_hours_elapsed = 0.0
        self.incident_count     = 0    # hull hits

        # Docking state
        self.active_dock  = None
        self.unload_timer = 0.0

        self.wave_t = 0.0

        # AI traffic
        self.ai_vessels     = []
        self.traffic_timer  = 0.0
        self._traffic_pool  = self._load_traffic_pool()

        # Deckhands
        dh_names = self._load_deckhand_names()
        self.vessel.deckhands = [
            Deckhand(dh_names[i % len(dh_names)],
                     DECKHAND_COLORS[i % len(DECKHAND_COLORS)])
            for i in range(DECKHAND_COUNT)
        ]
        # Stagger starting positions across the towboat deck
        offsets = [(-TH * 0.1, -8), (-TH * 0.1, 8), (TH * 0.25, 0)]
        for dh, (f, l) in zip(self.vessel.deckhands, offsets):
            dh.fwd, dh.lat = f, l
        self._prev_docked   = False
        self._barge_buttons = []
        self.docked_barges       = []
        self.free_barge_clusters = []
        self.earnings       = 0.0
        self._reward_msg    = ''
        self._reward_timer  = 0.0

        # Populate available barges from dock slots into the world
        for dock in self.docks:
            if dock.available_barge is not None:
                self.docked_barges.append(dock.available_barge)
                dock.available_barge = None

        # Daily goals
        self.daily_goals = self._generate_goals()

    # ── Deckhand names ─────────────────────────────────────────────────────────
    def _load_deckhand_names(self):
        try:
            from assets import GameDatabase
            h = self.game_time % 24
            shift = 'night' if (h >= 18 or h < 6) else 'day'
            db   = GameDatabase()
            rows = db.crew_list(vessel_name='MV Prairie Star')
            db.close()
            deck_roles = {'Deck Hand', 'Deck Lead'}
            matched = [r['name'] for r in rows
                       if r['name'] and r.get('role') in deck_roles
                       and r.get('shift') == shift]
            if not matched:
                matched = [r['name'] for r in rows
                           if r['name'] and r.get('role') in deck_roles]
            if matched:
                return matched
        except Exception:
            pass
        return list(_DH_FALLBACK_NAMES)

    # ── Dock name pool ────────────────────────────────────────────────────────
    def _load_dock_name_pool(self):
        try:
            from assets import GameDatabase
            db   = GameDatabase()
            rows = db.dock_names()
            db.close()
            pool = [{'name': r['name'],
                     'accepts':  r.get('accepts', '') or '',
                     'produces': r.get('produces', '') or ''}
                    for r in rows if r.get('name')]
            if pool:
                return pool
        except Exception:
            pass
        return list(_FALLBACK_DOCK_NAMES)

    # ── Daily goals ───────────────────────────────────────────────────────────
    def _generate_goals(self):
        """Pick 2-3 delivery goals: barge bid → dock accepting its cargo."""
        goals = []
        # Assign cargo to starting barges if they don't have any
        for b in self.vessel.barges:
            if not b.cargo:
                b.cargo = random.choice(CARGO_TYPES)

        cargo_labels = [b.cargo[0] for b in self.vessel.barges if b.cargo]
        # Find docks that accept at least one starting cargo
        candidate_docks = [d for d in self.docks
                           if any(c in d.accepts for c in cargo_labels)]
        random.shuffle(candidate_docks)

        n_goals = min(3, len(candidate_docks), len(self.vessel.barges))
        barges  = list(self.vessel.barges)
        random.shuffle(barges)

        used_docks = set()
        for dock in candidate_docks:
            if len(goals) >= n_goals:
                break
            if dock.name in used_docks:
                continue
            # Find a barge whose cargo this dock accepts
            barge = next((b for b in barges
                          if b.cargo and b.cargo[0] in dock.accepts), None)
            if not barge:
                continue
            goals.append(DailyGoal(barge.bid, dock.name, barge.cargo[0],
                                   bonus=180.0))
            used_docks.add(dock.name)
            barges.remove(barge)

        return goals

    def _check_goals(self, barge: TowBarge, dock):
        """After a TIE action, check if any goal is satisfied."""
        if not dock or not barge.cargo:
            return
        for goal in self.daily_goals:
            if goal.completed:
                continue
            if goal.bid == barge.bid and goal.dock_name == dock.name \
                    and goal.cargo_label == barge.cargo[0]:
                goal.completed = True
                self.earnings       += goal.bonus
                self._reward_msg     = f'+${goal.bonus:.0f}  GOAL: {goal.describe()}'
                self._reward_timer   = 4.0
                break

    # ── Deckhand surface / recall ──────────────────────────────────────────────
    def _is_on_surface(self, fwd: float, lat: float) -> bool:
        """Return True if (fwd, lat) is over the towboat deck or any attached barge."""
        if abs(fwd) <= TH / 2 + 2 and abs(lat) <= TW / 2 + 2:
            return True
        for b in self.vessel.barges:
            bf  = TH / 2 + PUSH + b.row * (BH + BGAP)
            bl  = (b.col - (B_COLS - 1) / 2.0) * (BW + BGAP)
            if bf - 2 <= fwd <= bf + BH + 2 and abs(lat - bl) <= BW / 2 + 2:
                return True
        return False

    def _recall_stranded_deckhands(self):
        """Send any deckhand standing over water back to the towboat."""
        for dh in self.vessel.deckhands:
            if not self._is_on_surface(dh.fwd, dh.lat):
                dh.return_to_boat()

    # ── Deckhand helpers ───────────────────────────────────────────────────────
    def _idle_dh(self):
        return next((dh for dh in self.vessel.deckhands if dh.state == 'idle'), None)

    def _barge_local_pos(self, barge: TowBarge):
        fwd = TH / 2 + PUSH + barge.row * (BH + BGAP) + BH / 2
        lat = (barge.col - (B_COLS - 1) / 2.0) * (BW + BGAP)
        return fwd, lat

    def _update_deckhands(self, dt):
        for dh in self.vessel.deckhands:
            dh.update(dt)

    # ── Barge button actions ───────────────────────────────────────────────────
    def _handle_barge_button(self, action: str, row: int, col: int):
        dh = self._idle_dh()
        if not dh:
            return
        barge = next((b for b in self.vessel.barges
                      if b.row == row and b.col == col), None)

        if action == 'tie' and barge and not barge.tied:
            tfwd, tlat = self._barge_local_pos(barge)
            active = self.active_dock
            def _tie(b=barge, g=self, d=active):
                b.tied = True
                g.earnings       += 20.0
                g._reward_msg     = '+$20  BARGE TIED'
                g._reward_timer   = 2.0
                g._check_goals(b, d)
            dh.assign('tie', tfwd, tlat, 2.0, _tie)

        elif action == 'untie' and barge and barge.tied:
            tfwd, tlat = self._barge_local_pos(barge)
            def _untie(b=barge): b.tied = False
            dh.assign('untie', tfwd, tlat, 1.5, _untie)

        elif action == 'detach' and barge:
            tfwd, tlat = self._barge_local_pos(barge)
            fx, fy = self.vessel.fwd
            rx, ry = self.vessel.rgt
            bwx = self.vessel.x + fx * tfwd + rx * tlat
            bwy = self.vessel.y + fy * tfwd + ry * tlat
            hdg = self.vessel.heading
            dl  = self.docked_barges
            def _detach(b=barge, v=self.vessel,
                        wx=bwx, wy=bwy, h=hdg, c=barge.cargo, g=self):
                if b in v.barges:
                    v.barges.remove(b)
                    dl.append(DockedBarge(wx, wy, h, c))
                g._recall_stranded_deckhands()
            dh.assign('detach', tfwd, tlat, 2.2, _detach)

        elif action == 'pickup':
            # barge argument is a DockedBarge index stored in col
            db_idx = col
            if db_idx < len(self.docked_barges):
                db = self.docked_barges[db_idx]
                occupied = {(b.row, b.col) for b in self.vessel.barges}
                free = [(r, c) for r in range(B_ROWS) for c in range(B_COLS)
                        if (r, c) not in occupied]
                if not free:
                    return
                nr, nc = free[0]
                new_b  = TowBarge(nr, nc, db.cargo)
                tfwd   = TH / 2 + PUSH + nr * (BH + BGAP) + BH / 2
                tlat   = (nc - (B_COLS - 1) / 2.0) * (BW + BGAP)
                dl     = self.docked_barges
                def _pickup(b=new_b, v=self.vessel, di=db_idx):
                    v.barges.append(b)
                    if di < len(dl):
                        dl.pop(di)
                dh.assign('attach', tfwd, tlat, 2.5, _pickup)

        elif action == 'load' and barge and not barge.cargo:
            tfwd, tlat = self._barge_local_pos(barge)
            cargo = random.choice(CARGO_TYPES)
            def _load(b=barge, c=cargo): b.cargo = c
            dh.assign('load', tfwd, tlat, 1.8, _load)

        elif action == 'disconnect' and self.vessel.barges:
            fx, fy = self.vessel.fwd
            fl = self.vessel.form_length
            cwx = self.vessel.x + fx * (TH / 2 + PUSH + fl / 2)
            cwy = self.vessel.y + fy * (TH / 2 + PUSH + fl / 2)
            cluster = FreeBargeCluster(cwx, cwy, self.vessel.heading,
                                       list(self.vessel.barges))
            self.free_barge_clusters.append(cluster)
            self.vessel.barges.clear()
            self._recall_stranded_deckhands()

        elif action == 'connect':
            fc_idx = col   # encoded as col
            if fc_idx < len(self.free_barge_clusters):
                fc = self.free_barge_clusters[fc_idx]
                self.vessel.barges.extend(fc.barges)
                self.free_barge_clusters.pop(fc_idx)

        elif action == 'attach' and not barge:
            new_b = TowBarge(row, col)
            tfwd = TH / 2 + PUSH + row * (BH + BGAP) + BH / 2
            tlat = (col - (B_COLS - 1) / 2.0) * (BW + BGAP)
            def _attach(b=new_b, v=self.vessel): v.barges.append(b)
            dh.assign('attach', tfwd, tlat, 2.5, _attach)

    # ── Barge operations panel ─────────────────────────────────────────────────
    def _draw_barge_panel(self, surf, font_sm, near_dock: bool):
        self._barge_buttons = []
        if not near_dock:
            return

        all_slots   = [(r, c) for r in range(B_ROWS) for c in range(B_COLS)]
        occupied    = {(b.row, b.col): b for b in self.vessel.barges}
        nearby_db   = self.docked_barges
        # Free clusters within connect range
        nearby_fc   = [(i, fc) for i, fc in enumerate(self.free_barge_clusters)
                       if math.hypot(fc.wx - self.vessel.x,
                                     fc.wy - self.vessel.y) < FreeBargeCluster.CONNECT_RADIUS * 3]

        PX, BTN_W, BTN_H, ROW_H = 16, 54, 18, 30
        PW = 16 + 110 + 3 * (BTN_W + 3) + 8
        extra_rows = len(nearby_db) + len(nearby_fc) + (1 if self.vessel.barges else 0)
        PH = 22 + (len(all_slots) + extra_rows) * ROW_H + 6
        PY = SH - PH - 70   # sit just above compass / speed block

        bg = pygame.Surface((PW, PH), pygame.SRCALPHA)
        bg.fill((12, 18, 24, 190))
        surf.blit(bg, (PX, PY))
        pygame.draw.rect(surf, (55, 78, 88), (PX, PY, PW, PH), 1)

        hdr = font_sm.render('BARGE OPS', True, (140, 195, 175))
        surf.blit(hdr, (PX + 6, PY + 4))

        y = PY + 22
        for row, col in all_slots:
            barge = occupied.get((row, col))

            # Slot indicator
            ind = (55, 190, 80) if (barge and barge.tied) else \
                  (190, 160, 50) if barge else (60, 60, 70)
            pygame.draw.rect(surf, ind, (PX + 6, y + 5, 9, 9))
            lbl_txt = f'B{row}{col}' + (' [tied]' if barge and barge.tied else
                                         ' [load]' if barge and barge.cargo else '')
            surf.blit(font_sm.render(lbl_txt, True, (190, 190, 190)),
                      (PX + 20, y + 2))

            bx = PX + 118
            if barge:
                # TIE / UNTIE
                if not barge.tied:
                    tr = pygame.Rect(bx, y + 1, BTN_W, BTN_H)
                    pygame.draw.rect(surf, (35, 110, 48), tr)
                    pygame.draw.rect(surf, (70, 160, 85), tr, 1)
                    surf.blit(font_sm.render('TIE', True, (170, 235, 175)),
                              (tr.x + (BTN_W - font_sm.size('TIE')[0]) // 2, tr.y + 2))
                    self._barge_buttons.append(('tie', row, col, tr))
                else:
                    tr = pygame.Rect(bx, y + 1, BTN_W, BTN_H)
                    pygame.draw.rect(surf, (80, 55, 20), tr)
                    pygame.draw.rect(surf, (140, 100, 45), tr, 1)
                    surf.blit(font_sm.render('UNTIE', True, (235, 200, 140)),
                              (tr.x + (BTN_W - font_sm.size('UNTIE')[0]) // 2, tr.y + 2))
                    self._barge_buttons.append(('untie', row, col, tr))
                bx += BTN_W + 3

                # LOAD (send deckhand to load cargo)
                lr = pygame.Rect(bx, y + 1, BTN_W, BTN_H)
                pygame.draw.rect(surf, (30, 60, 110), lr)
                pygame.draw.rect(surf, (60, 100, 165), lr, 1)
                surf.blit(font_sm.render('LOAD', True, (160, 190, 240)),
                          (lr.x + (BTN_W - font_sm.size('LOAD')[0]) // 2, lr.y + 2))
                self._barge_buttons.append(('load', row, col, lr))
                bx += BTN_W + 3

                # DETACH
                dr = pygame.Rect(bx, y + 1, BTN_W, BTN_H)
                pygame.draw.rect(surf, (115, 38, 22), dr)
                pygame.draw.rect(surf, (175, 72, 45), dr, 1)
                surf.blit(font_sm.render('DETACH', True, (240, 172, 152)),
                          (dr.x + (BTN_W - font_sm.size('DETACH')[0]) // 2, dr.y + 2))
                self._barge_buttons.append(('detach', row, col, dr))

            else:
                # Empty slot — ATTACH
                ar = pygame.Rect(bx, y + 1, BTN_W * 3 + 6, BTN_H)
                pygame.draw.rect(surf, (28, 50, 90), ar)
                pygame.draw.rect(surf, (55, 85, 140), ar, 1)
                surf.blit(font_sm.render('ATTACH BARGE', True, (150, 185, 235)),
                          (ar.x + (ar.width - font_sm.size('ATTACH BARGE')[0]) // 2,
                           ar.y + 2))
                self._barge_buttons.append(('attach', row, col, ar))

            y += ROW_H

        # Disconnect towboat from barge formation
        if self.vessel.barges:
            dc_r = pygame.Rect(PX + 6, y + 1, PW - 12, BTN_H)
            pygame.draw.rect(surf, (90, 30, 30), dc_r)
            pygame.draw.rect(surf, (160, 60, 50), dc_r, 1)
            surf.blit(font_sm.render('DISCONNECT TOW FROM BARGES',
                                     True, (240, 160, 140)),
                      (dc_r.x + (dc_r.width - font_sm.size('DISCONNECT TOW FROM BARGES')[0]) // 2,
                       dc_r.y + 2))
            self._barge_buttons.append(('disconnect', 0, 0, dc_r))
            y += ROW_H

        # Connect to a nearby free cluster
        for fc_idx, fc in nearby_fc:
            n  = len(fc.barges)
            lr = pygame.Rect(PX + 6, y + 1, PW - 12, BTN_H)
            pygame.draw.rect(surf, (30, 75, 40), lr)
            pygame.draw.rect(surf, (60, 140, 75), lr, 1)
            surf.blit(font_sm.render(f'CONNECT TOW  ({n} barge{"s" if n != 1 else ""})',
                                     True, (155, 235, 170)),
                      (lr.x + (lr.width - font_sm.size(f'CONNECT TOW  ({n} barge{"s" if n != 1 else ""})')[0]) // 2,
                       lr.y + 2))
            self._barge_buttons.append(('connect', 0, fc_idx, lr))
            y += ROW_H

        # Docked barges available to pick up
        for db_idx, db in enumerate(nearby_db):
            cargo_lbl = db.cargo[0] if db.cargo else 'empty'
            lbl = font_sm.render(f'DOCK {db_idx}  [{cargo_lbl}]',
                                 True, (160, 180, 200))
            surf.blit(lbl, (PX + 6, y + 2))
            pu_r = pygame.Rect(PX + 118, y + 1, BTN_W * 3 + 6, BTN_H)
            pygame.draw.rect(surf, (40, 80, 55), pu_r)
            pygame.draw.rect(surf, (70, 140, 90), pu_r, 1)
            surf.blit(font_sm.render('PICK UP', True, (160, 230, 175)),
                      (pu_r.x + (pu_r.width - font_sm.size('PICK UP')[0]) // 2,
                       pu_r.y + 2))
            # row unused for pickup; col encodes index into docked_barges
            self._barge_buttons.append(('pickup', 0, db_idx, pu_r))
            y += ROW_H

    # ── Traffic pool ───────────────────────────────────────────────────────────
    def _load_traffic_pool(self):
        try:
            from assets import GameDatabase
            db   = GameDatabase()
            rows = db.ships(limit=200)
            caps = {r['vessel_name']: r['name']
                    for r in db.crew_list(role='captain')}
            db.close()
            pool = [(r['name'], r['vessel_type'], caps.get(r['name']))
                    for r in rows
                    if r['vessel_type'] in _AI_DIMS and r['name']]
            if pool:
                return pool
        except Exception:
            pass
        return list(_FALLBACK_POOL)

    def _maybe_spawn_traffic(self):
        if len(self.ai_vessels) >= TRAFFIC_MAX:
            return
        direction   = random.choice((-1, 1))
        spawn_ahead = random.uniform(TRAFFIC_SPAWN_AHEAD * 0.7,
                                     TRAFFIC_SPAWN_AHEAD * 1.3)
        wy  = self.vessel.y + spawn_ahead
        wx  = self.river.cx(wy)
        name, vtype, captain = random.choice(self._traffic_pool)
        self.ai_vessels.append(
            AIVessel(wx, wy, direction, vtype, name, captain))

    # ── Camera ─────────────────────────────────────────────────────────────────
    @property
    def cam_x(self):
        return self.vessel.x

    @property
    def cam_y(self):
        return self.vessel.y

    # ── Nearest upcoming dock info ─────────────────────────────────────────────
    def _barge_sample_points(self):
        """Corners, edge midpoints, and centre of every barge in the formation."""
        fx, fy = self.vessel.fwd
        rx, ry = self.vessel.rgt
        pts = []
        for b in self.vessel.barges:
            fwd_off = TH / 2 + PUSH + b.row * (BH + BGAP) + BH / 2
            lat_off = (b.col - (B_COLS - 1) / 2.0) * (BW + BGAP)
            cx = self.vessel.x + fx * fwd_off + rx * lat_off
            cy = self.vessel.y + fy * fwd_off + ry * lat_off
            hw, hl = BW / 2, BH / 2
            pts += [
                (cx, cy),                                          # centre
                (cx + fx*hl - rx*hw, cy + fy*hl - ry*hw),         # bow-port
                (cx + fx*hl + rx*hw, cy + fy*hl + ry*hw),         # bow-stbd
                (cx - fx*hl - rx*hw, cy - fy*hl - ry*hw),         # stern-port
                (cx - fx*hl + rx*hw, cy - fy*hl + ry*hw),         # stern-stbd
                (cx + fx*hl,         cy + fy*hl        ),          # bow mid
                (cx - fx*hl,         cy - fy*hl        ),          # stern mid
                (cx - rx*hw,         cy - ry*hw        ),          # port mid
                (cx + rx*hw,         cy + ry*hw        ),          # stbd mid
            ]
        return pts

    def _nearest_dock_dist(self):
        sample_pts = self._barge_sample_points()
        for d in self.docks:
            if not d.visited and d.wy > self.vessel.y:
                dist = min(math.hypot(px - d.wx, py - d.wy)
                           for px, py in sample_pts) if sample_pts else float('inf')
                return dist, d
        return None, None

    # ── Collision with banks ────────────────────────────────────────────────────
    def _bank_collision(self):
        for cx, cy in self.vessel.corners():
            rcx = self.river.cx(cy)
            if abs(cx - rcx) > RIVER_HALF - 4:
                return True
        return False

    # ── Collision with obstacles ────────────────────────────────────────────────
    def _obstacle_collision(self):
        for o in self.obstacles:
            for px, py in self.vessel.corners():
                if math.hypot(px - o.wx, py - o.wy) < o.r + 6:
                    return True
        return False

    # ── Collision with AI traffic ───────────────────────────────────────────────
    def _ai_collision(self):
        for av in self.ai_vessels:
            hw, hl = _AI_DIMS.get(av.vessel_type, (10, 30))
            r = math.hypot(hw, hl) + 4
            for px, py in self.vessel.corners():
                if math.hypot(px - av.wx, py - av.wy) < r:
                    return True
        return False

    # ── Update ─────────────────────────────────────────────────────────────────
    def update(self, keys, dt):
        if self.game_over or self.show_intro:
            return

        self.vessel.update(keys)
        if any(b.tied for b in self.vessel.barges):
            self.vessel.speed    = 0.0
            self.vessel.throttle = 0.0
            self.vessel.yaw_vel  = 0.0
        self.wave_t += dt

        # Advance game time and shift clock
        game_dt = (dt * MINS_PER_SEC) / 60.0
        self.game_time += game_dt
        if self.game_time >= 24.0:
            self.game_time -= 24.0
        self.shift_hours_elapsed += game_dt

        # Hit detection
        if self.vessel.hit_cd == 0:
            if self._bank_collision() or self._obstacle_collision() or self._ai_collision():
                self.vessel.damage   += 1
                self.incident_count  += 1
                self.vessel.hit_cd    = HIT_COOLDOWN
                self.vessel.speed    *= -0.3   # bounce back
                if self.vessel.damage >= MAX_DAMAGE:
                    self.game_over = True
                    return

        # Deckhands
        self._update_deckhands(dt)

        # Free barge clusters drift with current
        for fc in self.free_barge_clusters:
            fc.update()

        # AI traffic: spawn and update
        self.traffic_timer += dt
        if self.traffic_timer >= TRAFFIC_SPAWN_INTERVAL:
            self.traffic_timer = 0.0
            self._maybe_spawn_traffic()
        for av in self.ai_vessels:
            av.update(self.river)
        self.ai_vessels = [
            av for av in self.ai_vessels
            if (av.wy - self.vessel.y) * av.direction > -TRAFFIC_CULL_DIST
        ]

        # Earnings: hourly wage
        self.earnings += self.HOURLY_WAGE * game_dt
        if self._reward_timer > 0:
            self._reward_timer -= dt

        # Docking logic
        if self.active_dock:
            self.unload_timer -= dt
            if self.unload_timer <= 0:
                tied = sum(1 for b in self.vessel.barges if b.tied)
                bonus = self.DOCK_BONUS + tied * 45.0
                self.earnings        += bonus
                self._reward_msg      = f'+${bonus:.0f}  DOCK COMPLETE'
                self._reward_timer    = 3.5
                self.active_dock.visited = True
                self.active_dock  = None
                self.unload_timer = 0.0
                self.score       += 1
        else:
            dist, nearest = self._nearest_dock_dist()
            if nearest and dist is not None and dist < DOCK_RADIUS:
                if abs(self.vessel.speed) < DOCK_SLOW:
                    self.active_dock  = nearest
                    self.unload_timer = UNLOAD_TIME

    # ── Draw ────────────────────────────────────────────────────────────────────
    def draw(self, surf, font, font_sm, font_lg):
        ambient = get_ambient(self.game_time)
        sky_col = get_sky_color(self.game_time)

        # Sky strip at top (below water the river background dominates)
        surf.fill(sky_col)

        # River background + banks
        draw_river(surf, self.river, self.cam_x, self.cam_y,
                   ambient, self.wave_t)

        # Objects
        draw_obstacles(surf, self.obstacles, self.cam_x, self.cam_y, ambient)
        draw_docked_barges(surf, self.docked_barges, self.cam_x, self.cam_y, ambient)
        for fc in self.free_barge_clusters:
            fc.draw(surf, self.cam_x, self.cam_y, ambient)

        dock_dist_val, nearest_d = self._nearest_dock_dist()
        draw_docks(surf, self.docks, self.cam_x, self.cam_y,
                   ambient, self.active_dock, self.unload_timer, self.game_time)

        draw_buoys(surf, self.buoys, self.cam_x, self.cam_y,
                   ambient, self.wave_t)

        # AI traffic
        for av in self.ai_vessels:
            av.draw(surf, self.cam_x, self.cam_y, ambient,
                    self.river, self.wave_t, font_sm)

        # Vessel (drawn on top of everything so it is always visible)
        self.vessel.draw(surf, self.cam_x, self.cam_y, ambient)

        # Night overlay — darkens the whole view
        if ambient < 0.95:
            dark_a = int((1.0 - ambient) * 160)
            night_ov = pygame.Surface((SW, SH), pygame.SRCALPHA)
            night_ov.fill((0, 0, 15, dark_a))
            surf.blit(night_ov, (0, 0))

        # HUD
        draw_hud(surf, self.vessel, self.game_time, self.score,
                 dock_dist_val, self.active_dock, self.unload_timer,
                 font, font_sm,
                 earnings=self.earnings,
                 reward_msg=self._reward_msg,
                 reward_timer=self._reward_timer)

        # Daily goals panel
        draw_goals(surf, self.daily_goals, font_sm)

        # Barge operations panel (visible near dock)
        dock_dist, _ = self._nearest_dock_dist()
        near = (self.active_dock is not None or
                (dock_dist is not None and dock_dist < DOCK_RADIUS * 2.5))
        self._draw_barge_panel(surf, font_sm, near)

        if self.show_intro:
            draw_intro(surf, font_lg, font)

        if self.game_over:
            draw_game_over(surf, self.score, font_lg, font)

        # Shift-complete overlay (when running inside GameEngine)
        if self._shift_duration and self.shift_hours_elapsed >= self._shift_duration:
            ov = pygame.Surface((SW, SH), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 160))
            surf.blit(ov, (0, 0))
            t1 = font_lg.render('SHIFT COMPLETE', True, (120, 230, 130))
            t2 = font.render(f'Terminals: {self.score}   Incidents: {self.incident_count}',
                             True, (200, 210, 200))
            t3 = font.render('Press  ESC  to return to menu', True, (160, 200, 160))
            surf.blit(t1, (SW // 2 - t1.get_width() // 2, SH // 2 - 70))
            surf.blit(t2, (SW // 2 - t2.get_width() // 2, SH // 2))
            surf.blit(t3, (SW // 2 - t3.get_width() // 2, SH // 2 + 50))

    # ── Game loop (called from GameEngine or standalone) ───────────────────────
    def run(self):
        """Run the pilot game and return 'shift_complete', 'menu', or 'quit'."""
        screen  = pygame.display.get_surface()
        clock   = pygame.time.Clock()
        font_lg = pygame.font.SysFont('monospace', 36, bold=True)
        font    = pygame.font.SysFont('monospace', 18)
        font_sm = pygame.font.SysFont('monospace', 13)

        while True:
            dt = clock.tick(FPS) / 1000.0

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return 'quit'
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return 'menu'
                    elif event.key == pygame.K_r:
                        if self.game_over:
                            # Restart the vessel but keep the shift clock running
                            start_cx = self.river.cx(self.vessel.y + 50)
                            self.vessel  = Vessel(start_cx, self.vessel.y + 50)
                            self.game_over = False
                    elif event.key == pygame.K_SPACE:
                        if self.show_intro:
                            self.show_intro = False
                        else:
                            self.vessel.horn_timer = 30
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    for action, row, col, rect in self._barge_buttons:
                        if rect.collidepoint(event.pos):
                            self._handle_barge_button(action, row, col)
                            break

            # Shift complete check
            if (self._shift_duration is not None
                    and self.shift_hours_elapsed >= self._shift_duration):
                self.draw(screen, font, font_sm, font_lg)
                pygame.display.flip()
                # Wait for ESC
                waiting = True
                while waiting:
                    for ev in pygame.event.get():
                        if ev.type == pygame.QUIT:
                            return 'quit'
                        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                            waiting = False
                return 'shift_complete'

            keys = pygame.key.get_pressed()
            self.update(keys, dt)
            self.draw(screen, font, font_sm, font_lg)
            pygame.display.flip()


# ── Standalone entry point ─────────────────────────────────────────────────────
def main():
    pygame.init()
    pygame.display.set_mode((SW, SH))
    pygame.display.set_caption('River Towboat Pilot')
    result = PilotGame().run()
    pygame.quit()
    sys.exit()


if __name__ == '__main__':
    main()