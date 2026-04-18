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
VREF_Y  = int(SH * 0.18)   # towboat sits this many pixels from the top of screen

# ── River geometry (world units; 1 wu ≈ 1 px at 1:1 zoom) ────────────────────
RIVER_HALF   = 400    # half-width of the full river
CHANNEL_HALF = 210     # half-width of the safe navigable channel
BUOY_SPACING = 215    # world-Y between consecutive buoy pairs
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


class Dock:
    __slots__ = ('wx', 'wy', 'side', 'visited')

    def __init__(self, wx, wy, side):
        self.wx      = wx
        self.wy      = wy
        self.side    = side    # +1 = river-right, -1 = river-left
        self.visited = False


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
    def bow_pos(self):
        fx, fy = self.fwd
        d = TH / 2 + PUSH + FORM_L
        return self.x + fx * d, self.y + fy * d

    @property
    def stern_pos(self):
        fx, fy = self.fwd
        return self.x - fx * TH / 2, self.y - fy * TH / 2

    def corners(self):
        """Four approximate hull corners for collision checks."""
        fx, fy = self.fwd
        rx, ry = self.rgt
        hw = FORM_W / 2 + 3
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
        bow_d = TH / 2 + PUSH + FORM_L
        bx = self.x + fx_old * bow_d
        by = self.y + fy_old * bow_d
        self.heading = (self.heading + self.yaw_vel) % 360.0
        fx, fy = self.fwd
        bx += fx * self.speed
        by += fy * self.speed
        self.x = bx - fx * bow_d
        self.y = by - fy * bow_d

    # ── Draw ───────────────────────────────────────────────────────────────────
    def draw(self, surf, cam_x, cam_y, ambient):
        def ws(wx, wy):
            return int(wx - cam_x + SW // 2), int(wy - cam_y + VREF_Y)

        fx, fy = self.fwd
        rx, ry = self.rgt
        dark   = ambient < 0.5

        # ── Barges ────────────────────────────────────────────────────────────
        for row in range(B_ROWS):
            for col in range(B_COLS):
                fwd_off = TH / 2 + PUSH + row * (BH + BGAP) + BH / 2
                lat_off = (col - (B_COLS - 1) / 2.0) * (BW + BGAP)
                bcx = self.x + fx * fwd_off + rx * lat_off
                bcy = self.y + fy * fwd_off + ry * lat_off
                hw, hl = BW / 2, BH / 2
                pts = [
                    ws(bcx + fx * hl - rx * hw, bcy + fy * hl - ry * hw),
                    ws(bcx + fx * hl + rx * hw, bcy + fy * hl + ry * hw),
                    ws(bcx - fx * hl + rx * hw, bcy - fy * hl + ry * hw),
                    ws(bcx - fx * hl - rx * hw, bcy - fy * hl - ry * hw),
                ]
                bc = dim3(BARGE_COL, ambient * 0.60 + 0.12)
                be = dim3(BARGE_TRIM, ambient * 0.55 + 0.12)
                pygame.draw.polygon(surf, bc, pts)
                pygame.draw.polygon(surf, be, pts, 2)
                # cargo hatch
                if ambient > 0.35:
                    mf = ws(bcx + fx * (hl * 0.5) - rx * (hw * 0.7),
                            bcy + fy * (hl * 0.5) - ry * (hw * 0.7))
                    mr = ws(bcx + fx * (hl * 0.5) + rx * (hw * 0.7),
                            bcy + fy * (hl * 0.5) + ry * (hw * 0.7))
                    pygame.draw.line(surf, be, mf, mr, 1)

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

        # Hit flash
        if self.hit_cd > HIT_COOLDOWN - 15:
            fl = pygame.Surface((SW, SH), pygame.SRCALPHA)
            fl.fill((255, 40, 40, 55))
            surf.blit(fl, (0, 0))


# ── World generation ───────────────────────────────────────────────────────────
def generate_world(river: RiverCurve):
    """Pre-generate buoys, obstacles and docks for the full GEN_LIMIT range."""
    buoys, obstacles, docks = [], [], []

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
        docks.append(Dock(dx, dy, side))
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

    # Simple trees on banks (daytime only)
    if ambient > 0.5:
        tree_col   = dim3((28, 90, 28), ambient)
        trunk_col  = dim3((80, 55, 20), ambient)
        rng = random.Random(int(cam_y // 400))
        for i in range(22):
            wy = top_y + rng.randint(0, bot_y - top_y)
            cx = river.cx(wy)
            side = rng.choice((-1, 1))
            off  = rng.uniform(RIVER_HALF + 12, RIVER_HALF + 65)
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
             active_dock, unload_t, font, font_sm):
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
    sc = font_sm.render(f"MILES: {int(score / 100)}", True, (190, 210, 190))
    surf.blit(sc, (SW - sc.get_width() - 16, 14 + ts.get_height() + 4))

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


# ── Main game class ────────────────────────────────────────────────────────────
class PilotGame:

    HOURLY_WAGE = 18.0    # $/game-hour (aligns with other sim stages)
    DOCK_BONUS  = 110.0   # $ per completed terminal visit

    def __init__(self, shift_duration=None, shift_start_time=START_HOUR,
                 cfg_time_scale=None, dev_mode=False):
        seed = random.randint(0, 99999)
        self.river     = RiverCurve(seed)
        self.buoys, self.obstacles, self.docks = generate_world(self.river)

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

    # ── Camera ─────────────────────────────────────────────────────────────────
    @property
    def cam_x(self):
        return self.vessel.x

    @property
    def cam_y(self):
        return self.vessel.y

    # ── Nearest upcoming dock info ─────────────────────────────────────────────
    def _nearest_dock_dist(self):
        for d in self.docks:
            if not d.visited and d.wy > self.vessel.y:
                dx = d.wx - self.vessel.x
                dy = d.wy - self.vessel.y
                return math.hypot(dx, dy), d
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

    # ── Update ─────────────────────────────────────────────────────────────────
    def update(self, keys, dt):
        if self.game_over or self.show_intro:
            return

        self.vessel.update(keys)
        self.wave_t += dt

        # Advance game time and shift clock
        game_dt = (dt * MINS_PER_SEC) / 60.0
        self.game_time += game_dt
        if self.game_time >= 24.0:
            self.game_time -= 24.0
        self.shift_hours_elapsed += game_dt

        # Hit detection
        if self.vessel.hit_cd == 0:
            if self._bank_collision() or self._obstacle_collision():
                self.vessel.damage   += 1
                self.incident_count  += 1
                self.vessel.hit_cd    = HIT_COOLDOWN
                self.vessel.speed    *= -0.3   # bounce back
                if self.vessel.damage >= MAX_DAMAGE:
                    self.game_over = True
                    return

        # Docking logic
        if self.active_dock:
            self.unload_timer -= dt
            if self.unload_timer <= 0:
                self.active_dock.visited = True
                self.active_dock  = None
                self.unload_timer = 0.0
                self.score       += 1   # count completed dock visits
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

        dock_dist_val, nearest_d = self._nearest_dock_dist()
        draw_docks(surf, self.docks, self.cam_x, self.cam_y,
                   ambient, self.active_dock, self.unload_timer, self.game_time)

        draw_buoys(surf, self.buoys, self.cam_x, self.cam_y,
                   ambient, self.wave_t)

        # Vessel (drawn on top of buoys so it occludes them)
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
                 font, font_sm)

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