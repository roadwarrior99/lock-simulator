"""
deckhand_sim.py — Deck Hand simulation, Stage 2 of Lock & Dam.

Top-down view of a barge tow on the river.  The player controls a deck hand
completing five duty types that mirror real towboat operations:

  connect  — attach steel cables between adjacent barges (building the tow)
  tension  — operate a winch to tighten a connected cable
  moor     — secure mooring lines at dock cleats on port / starboard
  paint    — maintenance: scrub rust / paint a section of barge deck
  lookout  — stand watch at the bow; scan for oncoming river traffic

Compatible interface with LockDamVisualizer:
  DeckHandSimulation(...).run()  →  'menu' | 'quit' | 'shift_complete'
"""

import pygame
import math
import random


# ── Supporting data classes ──────────────────────────────────────────────────

class TowBarge:
    """One barge in the 2-column × 3-row tow grid."""

    def __init__(self, barge_id: int, row: int, col: int, rect: pygame.Rect):
        self.barge_id = barge_id
        self.row      = row
        self.col      = col
        self.rect     = rect   # position on screen


class CableConnection:
    """Steel cable linking two adjacent barges."""

    def __init__(self, conn_id: int, barge_a: TowBarge, barge_b: TowBarge,
                 midpoint: tuple):
        self.conn_id   = conn_id
        self.barge_a   = barge_a
        self.barge_b   = barge_b
        self.midpoint  = midpoint   # (x, y) screen position; interaction point
        self.connected = False      # cable shackled in place
        self.tensioned = False      # winch tightened


class Task:
    """
    An active job the deck hand must complete.

    task_type  label            hold_time  notes
    ---------  ---------------  ---------  -----------------------------------
    connect    Connect cable       1.5 s   sets CableConnection.connected
    tension    Tighten winch       3.0 s   sets CableConnection.tensioned
    moor       Secure mooring      2.0 s   mooring cleat on hull side
    paint      Maintenance         4.0 s   rust / paint on barge deck
    lookout    Stand watch         5.0 s   bow watch post
    """

    HOLD_TIMES = {
        'connect': 1.5,
        'tension': 3.0,
        'moor':    2.0,
        'paint':   4.0,
        'lookout': 5.0,
    }
    LABELS = {
        'connect': 'Connect cable',
        'tension': 'Tighten winch',
        'moor':    'Secure mooring',
        'paint':   'Maintenance',
        'lookout': 'Stand watch',
    }

    def __init__(self, task_type: str, position: tuple, payload=None):
        self.task_type = task_type
        self.position  = position   # (x, y) target on screen
        self.payload   = payload    # CableConnection for connect/tension tasks
        self.progress  = 0.0       # 0–1; resets slowly when player steps away
        self.complete  = False
        self.active    = False      # True while player is actively working it

    @property
    def hold_time(self) -> float:
        return self.HOLD_TIMES[self.task_type]

    @property
    def label(self) -> str:
        return self.LABELS[self.task_type]


class DeckHandCharacter:
    """Player-controlled figure walking on the tow deck."""

    SPEED = 95.0   # px / real-second
    REACH = 40.0   # px; interaction radius

    JUMP_HEIGHT   = 22   # px peak height of jump arc
    JUMP_DURATION = 0.32  # seconds for one full arc

    def __init__(self, x: float, y: float):
        self.x      = float(x)
        self.y      = float(y)
        self.facing = 1   # +1 = right, -1 = left
        self.moving = False
        self.state  = 'grounded'   # 'grounded' | 'jumping' | 'drowning'
        self.jump_t = 0.0
        self.jump_h = 0            # visual vertical offset in px (upward)

    def update(self, dt: float, keys, bounds: tuple):
        if self.state == 'drowning':
            self.moving = False
            return
        dx = dy = 0
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:  dx -= 1
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]: dx += 1
        if keys[pygame.K_w] or keys[pygame.K_UP]:    dy -= 1
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:  dy += 1
        self.moving = (dx != 0 or dy != 0)
        if self.moving:
            mag = math.hypot(dx, dy)
            self.x += (dx / mag) * self.SPEED * dt
            self.y += (dy / mag) * self.SPEED * dt
            if dx != 0:
                self.facing = 1 if dx > 0 else -1
        x0, y0, x1, y1 = bounds
        self.x = max(x0, min(x1, self.x))
        self.y = max(y0, min(y1, self.y))

    def near(self, pos: tuple) -> bool:
        return math.hypot(self.x - pos[0], self.y - pos[1]) < self.REACH


# ── Main simulation ──────────────────────────────────────────────────────────

class DeckHandSimulation:
    """
    Deck Hand stage — top-down overhead view of a barge tow.

    Keyboard:
      WASD / arrow keys  Move deck hand
      E (hold)           Work a nearby task
      ESC                Return to menu
      ] / [              (dev) speed up / slow down game time
      End                (dev) skip to end of shift
    """

    HOURLY_WAGE = 15
    TASK_BONUS  = 25.0   # $ per completed task

    # Tow geometry (2 cols × 3 rows)
    TOW_COLS    = 2
    TOW_ROWS    = 3
    BARGE_W     = 190    # px width  (beam direction on screen)
    BARGE_H     = 95     # px height (length direction on screen)
    BARGE_GAP_X = 20     # px gap between columns (cable run)
    BARGE_GAP_Y = 20     # px gap between rows

    # Task timing
    TASK_INTERVAL_MIN = 14.0   # real seconds between random task spawns
    TASK_INTERVAL_MAX = 28.0

    # Colours
    C_RIVER       = ( 36,  68, 108)
    C_RIVER_LINE  = ( 48,  85, 130)
    C_BARGE_HULL  = (120, 108,  80)
    C_BARGE_DECK  = (148, 135, 100)
    C_TOWBOAT     = ( 72,  88, 108)
    C_CABLE_NONE  = ( 65,  65,  65)
    C_CABLE_CONN  = (200, 175,  65)
    C_CABLE_TAUT  = (220, 220, 210)
    C_TASK_IDLE   = (255, 215,  50)
    C_TASK_ACTIVE = ( 70, 215,  95)
    C_PLAYER      = (230,  85,  50)
    C_PLAYER_HEAD = (255, 195, 160)
    C_LOOKOUT     = (200, 200, 150)
    C_CLEAT       = (155, 140,  95)
    C_HUD_BG      = ( 18,  26,  42)

    def __init__(self, shift_duration=None, shift_start_time=6.0,
                 cfg_time_scale=2.0, dev_mode=False, first_shift=True):
        pygame.init()
        self.width  = 1200
        self.height = 800
        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption("Lock & Dam — Deck Hand")
        self.clock  = pygame.time.Clock()

        # Shift config (preserved across dev restarts)
        self._cfg_shift_duration   = shift_duration
        self._cfg_shift_start_time = shift_start_time
        self._cfg_time_scale       = cfg_time_scale
        self.dev_mode              = dev_mode

        # Time
        self.real_time           = 0.0
        self.game_time           = shift_start_time
        self.time_scale          = cfg_time_scale
        self.shift_hours_elapsed = 0.0
        self.shift_complete      = False

        # Progress / earnings
        self.score          = 0   # tasks completed this shift
        self.incident_count = 0
        self.incidents      = []

        # Labels injected by GameEngine for the shift HUD
        self._shift_phase_label = ''
        self._shift_num_label   = ''
        self._shift_clean_label = ''

        # Fonts
        self.fnt_lg = pygame.font.Font(None, 44)
        self.fnt_md = pygame.font.Font(None, 29)
        self.fnt_sm = pygame.font.Font(None, 21)

        # Layout & objects
        self._build_tow()

        # Task state
        self.active_tasks = []
        if first_shift:
            # First shift only: player must connect and tension all cables
            for conn in self.connections:
                self.active_tasks.append(Task('connect', conn.midpoint, payload=conn))
        else:
            # Tow is already rigged — all cables pre-connected and tensioned
            for conn in self.connections:
                conn.connected = True
                conn.tensioned = True
        self._next_task_t = random.uniform(self.TASK_INTERVAL_MIN,
                                           self.TASK_INTERVAL_MAX)

        # Player — start at towboat helm area
        px = self.tow_origin_x + (self.TOW_COLS * self.BARGE_W +
                                   (self.TOW_COLS - 1) * self.BARGE_GAP_X) // 2
        py = self.towboat_rect.centery
        self.player = DeckHandCharacter(px, py)

        # Notification banner
        self.notif       = ''
        self.notif_timer = 0.0

        # Overboard / game-over state
        self._overboard      = False
        self._overboard_t    = 0.0     # countdown until return to menu
        self._splash_pos     = (0, 0)

        # Walk animation
        self._walk_t = 0.0

        # Docking state — mooring tasks only available while docked
        self._docking         = False
        self._dock_timer      = random.uniform(40.0, 80.0)   # seconds until first dock
        self._dock_duration   = 0.0

        # Winch mini-game state
        self._winch_active     = False
        self._winch_task       = None
        self._winch_tension    = 0.5
        self._winch_vel        = 0.0
        self._winch_noise_t    = 0.0
        self._winch_timer      = 10.0
        self._winch_phase      = 'working'   # 'working' | 'lock_window' | 'result'
        self._winch_result     = None        # None | 'success' | 'fail'
        self._winch_result_t   = 0.0
        self._winch_drum_angle = 0.0
        self._winch_space_flag = False
        self._winch_grace_t    = 0.0

    # ── Tow geometry ─────────────────────────────────────────────────────────

    def _build_tow(self):
        """Create barge grid, cable connections, mooring cleats, and lookout."""
        hud_w = 225
        play_w = self.width - hud_w
        play_h = self.height

        tow_w = self.TOW_COLS * self.BARGE_W + (self.TOW_COLS - 1) * self.BARGE_GAP_X
        tow_h = self.TOW_ROWS * self.BARGE_H + (self.TOW_ROWS - 1) * self.BARGE_GAP_Y

        self.tow_origin_x = (play_w - tow_w) // 2
        self.tow_origin_y = (play_h - tow_h) // 2 - 30   # shift up to fit towboat below

        self.barges      = []
        self.connections = []

        for row in range(self.TOW_ROWS):
            for col in range(self.TOW_COLS):
                bx   = self.tow_origin_x + col * (self.BARGE_W + self.BARGE_GAP_X)
                by   = self.tow_origin_y + row * (self.BARGE_H + self.BARGE_GAP_Y)
                rect = pygame.Rect(bx, by, self.BARGE_W, self.BARGE_H)
                self.barges.append(
                    TowBarge(row * self.TOW_COLS + col, row, col, rect)
                )

        conn_id = 0
        for b in self.barges:
            # Horizontal connection to right neighbour
            right = self._barge_at(b.row, b.col + 1)
            if right:
                mx = b.rect.right + self.BARGE_GAP_X // 2
                my = (b.rect.centery + right.rect.centery) // 2
                self.connections.append(
                    CableConnection(conn_id, b, right, (mx, my))
                )
                conn_id += 1
            # Vertical connection to row below
            below = self._barge_at(b.row + 1, b.col)
            if below:
                mx = (b.rect.centerx + below.rect.centerx) // 2
                my = b.rect.bottom + self.BARGE_GAP_Y // 2
                self.connections.append(
                    CableConnection(conn_id, b, below, (mx, my))
                )
                conn_id += 1

        # Towboat — pushes from stern (bottom of screen)
        tb_w = tow_w
        tb_h = 68
        tb_x = self.tow_origin_x
        tb_y = self.tow_origin_y + tow_h + self.BARGE_GAP_Y
        self.towboat_rect = pygame.Rect(tb_x, tb_y, tb_w, tb_h)

        # Lookout post — bow (top centre of tow)
        self.lookout_pos = (
            self.tow_origin_x + tow_w // 2,
            self.tow_origin_y - 32,
        )

        # Mooring cleats — port (left) and starboard (right) of each row
        self.mooring_positions = []
        for row in range(self.TOW_ROWS):
            cy = self.tow_origin_y + row * (self.BARGE_H + self.BARGE_GAP_Y) + self.BARGE_H // 2
            self.mooring_positions.append((self.tow_origin_x - 22, cy))          # port
            self.mooring_positions.append((self.tow_origin_x + tow_w + 22, cy))  # starboard

        # Maintenance spots — centre of each barge deck
        self.maintenance_positions = [b.rect.center for b in self.barges]

        # Inter-barge gap rects (jumping zones)
        self._gap_rects = []
        for b in self.barges:
            right = self._barge_at(b.row, b.col + 1)
            if right:
                self._gap_rects.append(
                    pygame.Rect(b.rect.right, b.rect.top,
                                self.BARGE_GAP_X, b.rect.height))
            below = self._barge_at(b.row + 1, b.col)
            if below:
                self._gap_rects.append(
                    pygame.Rect(b.rect.left, b.rect.bottom,
                                b.rect.width, self.BARGE_GAP_Y))

        # Player movement bounds — slightly outside the tow perimeter
        buf = 55
        self._bounds = (
            self.tow_origin_x - buf,
            self.tow_origin_y - buf,
            self.tow_origin_x + tow_w + buf,
            self.towboat_rect.bottom + buf,
        )

    def _barge_at(self, row: int, col: int):
        for b in self.barges:
            if b.row == row and b.col == col:
                return b
        return None

    # ── Task management ──────────────────────────────────────────────────────

    def _spawn_task(self):
        """Add one random ongoing task, avoiding positions already occupied."""
        occupied = {t.position for t in self.active_tasks}
        candidates = []

        for pos in self.maintenance_positions:
            if pos not in occupied:
                candidates.append(Task('paint', pos))

        if self._docking:
            for pos in self.mooring_positions:
                if pos not in occupied:
                    candidates.append(Task('moor', pos))

        if self.lookout_pos not in occupied:
            candidates.append(Task('lookout', self.lookout_pos))

        # Tension tasks for cables that are connected but not yet tightened
        for conn in self.connections:
            if conn.connected and not conn.tensioned and conn.midpoint not in occupied:
                candidates.append(Task('tension', conn.midpoint, payload=conn))

        if candidates:
            self.active_tasks.append(random.choice(candidates))

    def _complete_task(self, task: Task):
        self.score   += 1
        task.complete = True
        if task.task_type == 'connect' and task.payload:
            task.payload.connected = True
        elif task.task_type == 'tension' and task.payload:
            task.payload.tensioned = True
        self._notify(f'+${self.TASK_BONUS:.0f}  {task.label} done')

    def _notify(self, msg: str):
        self.notif       = msg
        self.notif_timer = 3.2

    # ── Zone helpers ─────────────────────────────────────────────────────────

    def _is_safe_zone(self, x: float, y: float) -> bool:
        """True if the player is on solid deck (barge, towboat, mooring, lookout, bow)."""
        px, py = int(x), int(y)
        for b in self.barges:
            if b.rect.inflate(4, 4).collidepoint(px, py):
                return True
        if self.towboat_rect.inflate(4, 4).collidepoint(px, py):
            return True
        for pos in self.mooring_positions:
            if math.hypot(x - pos[0], y - pos[1]) < 18:
                return True
        if math.hypot(x - self.lookout_pos[0], y - self.lookout_pos[1]) < 38:
            return True
        # Connector strip between bottom barge row and towboat
        tow_w = self.TOW_COLS * self.BARGE_W + (self.TOW_COLS - 1) * self.BARGE_GAP_X
        conn  = pygame.Rect(self.tow_origin_x,
                            self.tow_origin_y + self.TOW_ROWS * (self.BARGE_H + self.BARGE_GAP_Y) - self.BARGE_GAP_Y,
                            tow_w, self.BARGE_GAP_Y + 4)
        if conn.collidepoint(px, py):
            return True
        return False

    def _is_gap_zone(self, x: float, y: float) -> bool:
        """True if the player is over an inter-barge gap (about to jump)."""
        px, py = int(x), int(y)
        for gap in self._gap_rects:
            if gap.collidepoint(px, py):
                return True
        return False

    def _trigger_overboard(self):
        """Called when the player hits the water."""
        self._overboard   = True
        self._overboard_t = 3.0
        self._splash_pos  = (int(self.player.x), int(self.player.y))
        self.player.state = 'drowning'
        self.incident_count += 1
        self.incidents.append('overboard')

    # ── Winch mini-game ──────────────────────────────────────────────────────

    def _start_winch(self, task: Task):
        """Launch the first-person winch tensioning mini-game."""
        self._winch_active     = True
        self._winch_task       = task
        self._winch_tension    = 0.5 + random.uniform(-0.2, 0.2)
        self._winch_vel        = random.uniform(-0.05, 0.05)
        self._winch_noise_t    = random.uniform(0, 100)
        self._winch_timer      = 10.0 + random.uniform(-1.0, 1.0)
        self._winch_phase      = 'working'
        self._winch_result     = None
        self._winch_result_t   = 0.0
        self._winch_drum_angle = 0.0
        self._winch_space_flag = False
        self._winch_grace_t    = 0.25   # ignore buttons briefly to avoid E-launch bleed

    def _update_winch(self, dt: float):
        """Update winch mini-game physics and phase transitions."""
        if self._winch_phase == 'result':
            self._winch_result_t -= dt
            if self._winch_result_t <= 0:
                task = self._winch_task
                if self._winch_result == 'success':
                    self._complete_task(task)
                    if task in self.active_tasks:
                        self.active_tasks.remove(task)
                else:
                    self._notify("Cable tension off — try again")
                self._winch_active = False
                self._winch_task   = None
                self._winch_result = None
                self._winch_phase  = 'working'
            return

        # Grace period: ignore player input briefly after launch
        if self._winch_grace_t > 0:
            self._winch_grace_t = max(0.0, self._winch_grace_t - dt)

        keys = pygame.key.get_pressed()

        # Oscillating load noise (cable tension from current, barge drift)
        self._winch_noise_t += dt
        noise = (math.sin(self._winch_noise_t * 1.7)  * 0.14 +
                 math.sin(self._winch_noise_t * 3.1)  * 0.07 +
                 math.sin(self._winch_noise_t * 0.5)  * 0.11)
        natural_drift = -0.07   # river load tends to loosen the cable

        player_force = 0.0
        if self._winch_grace_t <= 0:
            if keys[pygame.K_q]:
                player_force += 0.85   # tighten
            if keys[pygame.K_e]:
                player_force -= 0.85   # release

        accel = natural_drift + noise + player_force
        self._winch_vel += accel * dt
        self._winch_vel *= 0.90   # damping
        self._winch_tension = max(0.0, min(1.0,
                                  self._winch_tension + self._winch_vel * dt))

        # Drum rotates with cable movement (visual)
        self._winch_drum_angle += self._winch_vel * 180 * dt

        # Count down to lock
        self._winch_timer -= dt

        if self._winch_phase == 'working' and self._winch_timer <= 3.0:
            self._winch_phase = 'lock_window'

        # Player locks with SPACE during lock window
        if self._winch_phase == 'lock_window' and self._winch_space_flag:
            self._lock_winch()
            self._winch_space_flag = False
            return

        # Auto-lock when timer expires
        if self._winch_timer <= 0:
            self._lock_winch()

    def _lock_winch(self):
        """Evaluate current tension and record result."""
        t = self._winch_tension
        if 0.38 <= t <= 0.62:
            self._winch_result = 'success'
        else:
            self._winch_result = 'fail'
            if t > 0.62:
                self.incident_count += 1
                self.incidents.append('winch_overtension')
        self._winch_phase    = 'result'
        self._winch_result_t = 2.2

    def _draw_winch(self):
        """First-person view of the winch tensioning station."""
        play_w = self.width - 225
        cx     = play_w // 2

        # ── Background: deck with sky visible ────────────────────────────────
        # Sky
        pygame.draw.rect(self.screen, (58, 84, 124), (0, 0, play_w, 210))
        # River horizon strip
        pygame.draw.rect(self.screen, (36, 64, 104), (0, 155, play_w, 55))
        # Deck floor
        pygame.draw.rect(self.screen, (50, 44, 34), (0, 210, play_w, 210))
        # Deck planks
        for px in range(0, play_w, 22):
            pygame.draw.line(self.screen, (42, 36, 27), (px, 210), (px, 420), 1)
        pygame.draw.line(self.screen, (68, 60, 46), (0, 210), (play_w, 210), 2)

        # ── Winch drum ────────────────────────────────────────────────────────
        drum_cx = cx
        drum_cy = 310
        drum_w  = 340
        drum_h  = 110
        cap_d   = 44

        # Mount base
        base = pygame.Rect(drum_cx - drum_w // 2 - 30, drum_cy + drum_h // 2,
                           drum_w + 60, 22)
        pygame.draw.rect(self.screen, (38, 42, 52), base, border_radius=4)
        pygame.draw.rect(self.screen, (55, 62, 74), base, 2, border_radius=4)

        # Support uprights
        for ux in (drum_cx - drum_w // 2 - 22, drum_cx + drum_w // 2):
            pygame.draw.rect(self.screen, (44, 50, 62),
                             (ux, drum_cy - drum_h // 2 - 8, 22, drum_h + 30),
                             border_radius=3)

        # Drum shadow
        pygame.draw.ellipse(self.screen, (28, 24, 18),
                            (drum_cx - drum_w // 2 + 12, drum_cy + drum_h // 2 + 4,
                             drum_w, 16))

        # Drum body
        pygame.draw.rect(self.screen, (58, 64, 76),
                         (drum_cx - drum_w // 2, drum_cy - drum_h // 2,
                          drum_w, drum_h))

        # Cable wrapping — waves when loose, taut lines when tight
        cable_col = (128, 116, 86)
        n_wraps   = 9
        for i in range(n_wraps):
            wy = drum_cy - drum_h // 2 + 5 + i * (drum_h - 10) // n_wraps
            thick = max(2, int(2 + self._winch_tension * 2))
            if self._winch_tension < 0.4:
                wave_amp = int((0.4 - self._winch_tension) * 22)
                pts = []
                for s in range(21):
                    frac = s / 20
                    wx  = drum_cx - drum_w // 2 + int(frac * drum_w)
                    wwy = wy + int(math.sin(frac * math.pi * 3 + i * 1.1) * wave_amp)
                    pts.append((wx, wwy))
                if len(pts) > 1:
                    pygame.draw.lines(self.screen, cable_col, False, pts, thick)
            else:
                pygame.draw.line(self.screen, cable_col,
                                 (drum_cx - drum_w // 2, wy),
                                 (drum_cx + drum_w // 2, wy), thick)

        # Right end cap (3-D cylinder effect)
        cap_x = drum_cx + drum_w // 2 - cap_d
        pygame.draw.ellipse(self.screen, (70, 78, 92),
                            (cap_x, drum_cy - drum_h // 2, cap_d * 2, drum_h))
        pygame.draw.ellipse(self.screen, (88, 98, 114),
                            (cap_x, drum_cy - drum_h // 2, cap_d * 2, drum_h), 2)

        # Axle hub + animated spokes
        hub_x = drum_cx + drum_w // 2
        pygame.draw.circle(self.screen, (95, 105, 122), (hub_x, drum_cy), 16)
        pygame.draw.circle(self.screen, (118, 130, 148), (hub_x, drum_cy), 16, 2)
        for s in range(4):
            ang = self._winch_drum_angle * math.pi / 180 + s * math.pi / 2
            sx  = hub_x + int(math.cos(ang) * 12)
            sy  = drum_cy + int(math.sin(ang) * 12)
            pygame.draw.line(self.screen, (78, 88, 104), (hub_x, drum_cy), (sx, sy), 2)

        # Left end cap
        pygame.draw.ellipse(self.screen, (52, 58, 70),
                            (drum_cx - drum_w // 2 - cap_d,
                             drum_cy - drum_h // 2, cap_d * 2, drum_h))
        pygame.draw.ellipse(self.screen, (70, 78, 90),
                            (drum_cx - drum_w // 2 - cap_d,
                             drum_cy - drum_h // 2, cap_d * 2, drum_h), 2)

        # Cable leaving drum toward barge (with sag when loose)
        cable_exit_y = drum_cy + int((self._winch_tension - 0.5) * drum_h * 0.6)
        sag = int((1.0 - self._winch_tension) * 36)
        pts = [(hub_x + cap_d + int((s / 20) * 230),
                cable_exit_y + int(math.sin((s / 20) * math.pi) * sag))
               for s in range(21)]
        pygame.draw.lines(self.screen, cable_col, False, pts, 3)
        end_lbl = self.fnt_sm.render("-> BARGE", True, (148, 138, 108))
        self.screen.blit(end_lbl, (hub_x + cap_d + 238, cable_exit_y - 8))

        # ── Control panel (bottom half) ───────────────────────────────────────
        panel_y = 420
        pygame.draw.rect(self.screen, (26, 30, 38),
                         (0, panel_y, play_w, self.height - panel_y))
        pygame.draw.rect(self.screen, (44, 50, 64), (0, panel_y, play_w, 5))

        # ── Tension gauge ─────────────────────────────────────────────────────
        gauge_w = 520
        gauge_h = 36
        gauge_x = cx - gauge_w // 2
        gauge_y = panel_y + 44

        # Bezel
        pygame.draw.rect(self.screen, (16, 20, 26),
                         (gauge_x - 8, gauge_y - 8, gauge_w + 16, gauge_h + 16),
                         border_radius=6)
        # Zone colours
        for seg_s, seg_e, col in [
            (0.00, 0.25, (158, 34, 34)),
            (0.25, 0.38, (182, 128, 24)),
            (0.38, 0.62, (34, 158, 54)),
            (0.62, 0.75, (182, 128, 24)),
            (0.75, 1.00, (158, 34, 34)),
        ]:
            zx = gauge_x + int(seg_s * gauge_w)
            zw = max(1, int((seg_e - seg_s) * gauge_w))
            pygame.draw.rect(self.screen, col, (zx, gauge_y, zw, gauge_h))
        # Sweet-spot edge highlights
        ss_x = gauge_x + int(0.38 * gauge_w)
        ss_w = int(0.24 * gauge_w)
        pygame.draw.rect(self.screen, (58, 208, 78), (ss_x, gauge_y, ss_w, 3))
        pygame.draw.rect(self.screen, (58, 208, 78),
                         (ss_x, gauge_y + gauge_h - 3, ss_w, 3))
        # Gauge border
        pygame.draw.rect(self.screen, (88, 98, 115),
                         (gauge_x, gauge_y, gauge_w, gauge_h), 2, border_radius=2)

        # Needle
        nx = gauge_x + int(self._winch_tension * gauge_w)
        pygame.draw.line(self.screen, (238, 238, 238),
                         (nx, gauge_y - 14), (nx, gauge_y + gauge_h + 14), 3)
        pygame.draw.polygon(self.screen, (238, 238, 238),
                            [(nx, gauge_y - 14),
                             (nx - 7, gauge_y - 4),
                             (nx + 7, gauge_y - 4)])

        # Gauge labels
        ll = self.fnt_sm.render("<< TOO LOOSE", True, (208, 108, 108))
        lt = self.fnt_sm.render("TOO TIGHT >>", True, (208, 108, 108))
        ls = self.fnt_sm.render("SWEET SPOT",   True, (88, 218, 108))
        self.screen.blit(ll, (gauge_x, gauge_y + gauge_h + 10))
        self.screen.blit(lt, (gauge_x + gauge_w - lt.get_width(), gauge_y + gauge_h + 10))
        self.screen.blit(ls, (cx - ls.get_width() // 2, gauge_y + gauge_h + 10))
        gt = self.fnt_sm.render("CABLE TENSION", True, (135, 152, 172))
        self.screen.blit(gt, (cx - gt.get_width() // 2, gauge_y - 22))

        # ── Timer / phase display ─────────────────────────────────────────────
        timer_y = panel_y + 104
        if self._winch_phase == 'working':
            ts = self.fnt_md.render(
                f"Lock in: {max(0.0, self._winch_timer):.1f}s", True, (155, 180, 210))
            self.screen.blit(ts, (cx - ts.get_width() // 2, timer_y))
        elif self._winch_phase == 'lock_window':
            if int(self.real_time * 4) % 2 == 0:
                fs = self.fnt_lg.render("** LOCK IT NOW! **", True, (78, 238, 100))
                self.screen.blit(fs, (cx - fs.get_width() // 2, timer_y - 6))

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_y = panel_y + 150
        btn_w = 150
        btn_h = 58
        keys  = pygame.key.get_pressed()
        q_on  = keys[pygame.K_q]
        e_on  = keys[pygame.K_e]

        # Q — TIGHTEN (left)
        q_x  = cx - 290
        q_bg = (74, 148, 192) if q_on else (36, 70, 98)
        q_br = (98, 182, 232) if q_on else (52, 92, 128)
        pygame.draw.rect(self.screen, q_bg, (q_x, btn_y, btn_w, btn_h), border_radius=8)
        pygame.draw.rect(self.screen, q_br, (q_x, btn_y, btn_w, btn_h), 2, border_radius=8)
        for lbl, dy in (("[Q]", 6), ("TIGHTEN", 32)):
            surf = (self.fnt_md if dy == 6 else self.fnt_sm).render(lbl, True, (218, 235, 252))
            self.screen.blit(surf, (q_x + btn_w // 2 - surf.get_width() // 2, btn_y + dy))
        # Arrow →
        ax, ay = q_x + btn_w + 12, btn_y + btn_h // 2
        arr_c = (98, 182, 232) if q_on else (58, 98, 128)
        pygame.draw.polygon(self.screen, arr_c,
                            [(ax, ay), (ax + 18, ay - 12), (ax + 18, ay + 12)])

        # E — RELEASE (right)
        e_x  = cx + 140
        e_bg = (192, 88, 52) if e_on else (102, 46, 26)
        e_br = (232, 112, 72) if e_on else (132, 62, 38)
        pygame.draw.rect(self.screen, e_bg, (e_x, btn_y, btn_w, btn_h), border_radius=8)
        pygame.draw.rect(self.screen, e_br, (e_x, btn_y, btn_w, btn_h), 2, border_radius=8)
        for lbl, dy in (("[E]", 6), ("RELEASE", 32)):
            surf = (self.fnt_md if dy == 6 else self.fnt_sm).render(lbl, True, (252, 225, 208))
            self.screen.blit(surf, (e_x + btn_w // 2 - surf.get_width() // 2, btn_y + dy))
        # Arrow ←
        ax2, ay2 = e_x - 30, btn_y + btn_h // 2
        arr_c2 = (232, 112, 72) if e_on else (132, 62, 38)
        pygame.draw.polygon(self.screen, arr_c2,
                            [(ax2 + 18, ay2), (ax2, ay2 - 12), (ax2, ay2 + 12)])

        # SPACE — LOCK IN (center, only during lock window)
        if self._winch_phase == 'lock_window':
            lk_w = 160
            lk_x = cx - lk_w // 2
            lk_f = int(self.real_time * 3) % 2 == 0
            lk_bg = (44, 172, 72) if lk_f else (26, 108, 46)
            lk_br = (72, 228, 108) if lk_f else (44, 152, 68)
            pygame.draw.rect(self.screen, lk_bg,
                             (lk_x, btn_y - 4, lk_w, btn_h + 8), border_radius=10)
            pygame.draw.rect(self.screen, lk_br,
                             (lk_x, btn_y - 4, lk_w, btn_h + 8), 3, border_radius=10)
            for lbl, dy in (("[SPACE]", 4), ("LOCK IN", 32)):
                surf = (self.fnt_md if dy == 4 else self.fnt_sm).render(
                    lbl, True, (208, 244, 218))
                self.screen.blit(surf, (cx - surf.get_width() // 2, btn_y + dy))

        # ── Result overlay ────────────────────────────────────────────────────
        if self._winch_result is not None:
            overlay = pygame.Surface((play_w, self.height), pygame.SRCALPHA)
            if self._winch_result == 'success':
                overlay.fill((28, 158, 68, 148))
                r_text, r_col = "TENSION LOCKED!", (118, 252, 148)
            else:
                overlay.fill((158, 28, 28, 148))
                r_text, r_col = "TENSION OFF -- RETRY", (252, 128, 108)
            self.screen.blit(overlay, (0, 0))
            rs = self.fnt_lg.render(r_text, True, r_col)
            self.screen.blit(rs, (cx - rs.get_width() // 2, self.height // 2 - 28))

        # ── Sidebar HUD + controls hint ───────────────────────────────────────
        self._draw_hud()
        hint = self.fnt_sm.render("ESC -- leave winch", True, (84, 94, 114))
        self.screen.blit(hint, (10, self.height - 26))
        title = self.fnt_md.render("WINCH STATION", True, (152, 138, 104))
        self.screen.blit(title, (cx - title.get_width() // 2, 12))

    # ── Update ───────────────────────────────────────────────────────────────

    def _update(self, dt: float, game_dt: float):
        # Winch mini-game takes over completely
        if self._winch_active:
            if self.notif_timer > 0:
                self.notif_timer -= dt
            self.game_time = (self.game_time + game_dt) % 24
            self._update_winch(dt)
            return

        if self._overboard:
            self._overboard_t -= dt
            if self.notif_timer > 0:
                self.notif_timer -= dt
            self.game_time = (self.game_time + game_dt) % 24
            return

        keys = pygame.key.get_pressed()
        self.player.update(dt, keys, self._bounds)

        # Jump / overboard state machine
        in_gap  = self._is_gap_zone(self.player.x, self.player.y)
        on_safe = self._is_safe_zone(self.player.x, self.player.y)

        if self.player.state == 'grounded':
            if in_gap:
                self.player.state  = 'jumping'
                self.player.jump_t = 0.0
            elif not on_safe:
                self._trigger_overboard()
                return

        elif self.player.state == 'jumping':
            self.player.jump_t += dt
            frac = min(self.player.jump_t / DeckHandCharacter.JUMP_DURATION, 1.0)
            self.player.jump_h = int(math.sin(frac * math.pi) * DeckHandCharacter.JUMP_HEIGHT)
            if not in_gap:
                if on_safe:
                    self.player.state  = 'grounded'
                    self.player.jump_h = 0
                else:
                    self._trigger_overboard()
                    return

        # Walk animation timer
        if self.player.moving:
            self._walk_t += dt

        # Notification fade
        if self.notif_timer > 0:
            self.notif_timer -= dt

        # Docking cycle
        self._dock_timer -= dt
        if self._dock_timer <= 0:
            if self._docking:
                # Undock — remove any pending mooring tasks
                self._docking = False
                self.active_tasks = [t for t in self.active_tasks
                                     if t.task_type != 'moor']
                self._notify("Underway — lines cast off")
                self._dock_timer = random.uniform(50.0, 100.0)
            else:
                # Begin docking
                self._docking       = True
                self._dock_duration = random.uniform(25.0, 50.0)
                self._dock_timer    = self._dock_duration
                self._notify("Docking — secure the mooring lines!")

        # Task spawn
        self._next_task_t -= dt
        if self._next_task_t <= 0:
            self._spawn_task()
            self._next_task_t = random.uniform(self.TASK_INTERVAL_MIN,
                                               self.TASK_INTERVAL_MAX)

        # Interaction: hold E near a task to advance its progress
        e_held    = keys[pygame.K_e]
        completed = []

        for task in self.active_tasks:
            # Tension tasks launch the winch mini-game instead of hold-E
            if task.task_type == 'tension':
                if self.player.near(task.position) and e_held:
                    self._start_winch(task)
                    break
                continue

            if self.player.near(task.position):
                if e_held:
                    task.active   = True
                    task.progress = min(1.0, task.progress + dt / task.hold_time)
                    if task.progress >= 1.0:
                        self._complete_task(task)
                        completed.append(task)
                else:
                    task.active = False
            else:
                task.active   = False
                # Progress drains slowly when player walks away
                task.progress = max(0.0, task.progress - dt * 0.4)

        for t in completed:
            self.active_tasks.remove(t)

        # Game time
        self.game_time = (self.game_time + game_dt) % 24

    # ── Rendering ────────────────────────────────────────────────────────────

    def _draw(self):
        if self._winch_active:
            self._draw_winch()
            return

        play_w = self.width - 225

        # ── River background ──
        self.screen.fill(self.C_RIVER)

        # Animated current streaks — water flows downward toward the towboat
        scroll = int(self.real_time * 48) % (self.height + 80)
        for i in range(0, play_w, 68):
            phase = (i * 17) % (self.height + 80)
            y0 = (phase + scroll) % (self.height + 80) - 40
            pygame.draw.line(self.screen, self.C_RIVER_LINE,
                             (i + 8, y0), (i, y0 + 44), 1)

        # ── Towboat ──
        pygame.draw.rect(self.screen, self.C_TOWBOAT,
                         self.towboat_rect, border_radius=8)
        # Wheelhouse
        wh = pygame.Rect(self.towboat_rect.centerx - 32,
                         self.towboat_rect.y + 6, 64, 48)
        pygame.draw.rect(self.screen, (88, 104, 126), wh, border_radius=5)
        # Windows
        for wx in (wh.x + 10, wh.x + 36):
            pygame.draw.rect(self.screen, (160, 190, 215),
                             pygame.Rect(wx, wh.y + 10, 14, 12), border_radius=2)
        # "TOWBOAT" label
        lbl = self.fnt_sm.render("TOWBOAT", True, (160, 175, 195))
        self.screen.blit(lbl, (self.towboat_rect.centerx - lbl.get_width() // 2,
                               self.towboat_rect.y + 4))

        # ── Cables (draw under barges so they appear to pass between them) ──
        for conn in self.connections:
            col = (self.C_CABLE_TAUT  if conn.tensioned else
                   self.C_CABLE_CONN  if conn.connected else
                   self.C_CABLE_NONE)
            width = 3 if conn.tensioned else 2
            pygame.draw.line(self.screen, col,
                             conn.barge_a.rect.center,
                             conn.barge_b.rect.center, width)

        # ── Barges ──
        for b in self.barges:
            pygame.draw.rect(self.screen, self.C_BARGE_HULL, b.rect, border_radius=4)
            inner = b.rect.inflate(-10, -10)
            pygame.draw.rect(self.screen, self.C_BARGE_DECK, inner, border_radius=3)
            # Deck planking lines
            for lx in range(inner.x + 20, inner.right, 20):
                pygame.draw.line(self.screen, (135, 122, 88),
                                 (lx, inner.y), (lx, inner.bottom), 1)
            # Barge ID
            id_lbl = self.fnt_sm.render(f"B{b.barge_id}", True, (95, 85, 60))
            self.screen.blit(id_lbl, (b.rect.x + 5, b.rect.y + 4))

        # ── Mooring cleats ──
        for pos in self.mooring_positions:
            pygame.draw.rect(self.screen, self.C_CLEAT,
                             pygame.Rect(pos[0] - 6, pos[1] - 4, 12, 8),
                             border_radius=3)
            pygame.draw.rect(self.screen, (185, 168, 118),
                             pygame.Rect(pos[0] - 6, pos[1] - 4, 12, 8),
                             1, border_radius=3)

        # ── Lookout post (bow triangle) ──
        lx, ly = self.lookout_pos
        pygame.draw.polygon(self.screen, self.C_LOOKOUT,
                            [(lx, ly - 14), (lx - 12, ly + 10), (lx + 12, ly + 10)])
        pygame.draw.polygon(self.screen, (160, 158, 120),
                            [(lx, ly - 14), (lx - 12, ly + 10), (lx + 12, ly + 10)], 2)

        # ── Task rings ──
        for task in self.active_tasks:
            ring_col = self.C_TASK_ACTIVE if task.active else self.C_TASK_IDLE
            r        = 16
            tx, ty   = task.position

            # Background ring
            pygame.draw.circle(self.screen, ring_col, (tx, ty), r, 3)

            # Progress arc (clockwise from 12 o'clock)
            if task.progress > 0:
                arc_rect = pygame.Rect(tx - r, ty - r, r * 2, r * 2)
                ang_end   = math.pi / 2
                ang_start = ang_end - task.progress * 2 * math.pi
                pygame.draw.arc(self.screen, (70, 215, 95),
                                arc_rect, ang_start, ang_end, 4)

            # Label when player is close
            if self.player.near(task.position):
                hold_s = self.fnt_sm.render(f'[E] {task.label}', True, (255, 240, 150))
                self.screen.blit(hold_s,
                                 (tx - hold_s.get_width() // 2, ty + r + 5))

        # ── Player character ──
        px, py = int(self.player.x), int(self.player.y)
        jh  = self.player.jump_h
        bob = int(math.sin(self._walk_t * 10) * 2) if (self.player.moving and jh == 0) else 0
        draw_y = py - jh   # visual position (elevated during jump)

        # Shadow on deck below when jumping
        if jh > 0:
            shadow_r = max(3, 8 - jh // 4)
            shadow_a = max(30, 120 - jh * 4)
            sh_surf = pygame.Surface((shadow_r * 2, shadow_r), pygame.SRCALPHA)
            pygame.draw.ellipse(sh_surf, (0, 0, 0, shadow_a),
                                (0, 0, shadow_r * 2, shadow_r))
            self.screen.blit(sh_surf, (px - shadow_r, py - shadow_r // 2))

        # Body
        pygame.draw.ellipse(self.screen, self.C_PLAYER,
                            (px - 7, draw_y - 5 + bob, 14, 10))
        # Head
        pygame.draw.circle(self.screen, self.C_PLAYER_HEAD, (px, draw_y - 10 + bob), 6)
        # Hard hat
        pygame.draw.ellipse(self.screen, (255, 210, 30),
                            (px - 7, draw_y - 17 + bob, 14, 7))
        # Direction pointer
        ex = px + self.player.facing * 14
        pygame.draw.line(self.screen, self.C_PLAYER,
                         (px, draw_y + bob), (ex, draw_y + bob), 2)

        # ── Overboard overlay ──
        if self._overboard:
            sx, sy   = self._splash_pos
            elapsed  = 3.0 - self._overboard_t
            # Expanding splash rings
            for ring_i in range(4):
                ring_age = elapsed - ring_i * 0.18
                if 0 < ring_age < 1.2:
                    r     = int(ring_age * 55)
                    alpha = max(0, int(180 * (1 - ring_age / 1.2)))
                    if r > 0 and alpha > 0:
                        rs = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
                        pygame.draw.ellipse(rs, (*self.C_RIVER_LINE, alpha),
                                            (0, 0, r * 2, r * 2), 2)
                        self.screen.blit(rs, (sx - r, sy - r))
            # Dark blue tint deepens over time
            tint_a = min(200, int(elapsed * 80))
            tint = pygame.Surface((play_w, self.height), pygame.SRCALPHA)
            tint.fill((10, 20, 60, tint_a))
            self.screen.blit(tint, (0, 0))
            # "MAN OVERBOARD!" flash
            if int(elapsed * 3) % 2 == 0 or elapsed > 1.5:
                mob = self.fnt_lg.render("MAN OVERBOARD!", True, (255, 80, 60))
                self.screen.blit(mob, (play_w // 2 - mob.get_width() // 2,
                                       self.height // 2 - 28))
            hint = self.fnt_sm.render("Returning to menu...", True, (180, 190, 220))
            self.screen.blit(hint, (play_w // 2 - hint.get_width() // 2,
                                    self.height // 2 + 18))

        # ── Notification banner ──
        if self.notif_timer > 0:
            alpha = min(1.0, self.notif_timer)
            col   = (int(255 * alpha), int(238 * alpha), int(100 * alpha))
            ns = self.fnt_md.render(self.notif, True, col)
            self.screen.blit(ns, (play_w // 2 - ns.get_width() // 2, 28))

        self._draw_hud()

    def _draw_hud(self):
        hud_x = self.width - 225
        pygame.draw.rect(self.screen, self.C_HUD_BG,
                         (hud_x, 0, 225, self.height))

        cx = hud_x + 112
        y  = 18

        # Title
        hdr = self.fnt_lg.render("DECK HAND", True, (175, 200, 240))
        self.screen.blit(hdr, (cx - hdr.get_width() // 2, y)); y += 46

        # Game time
        h24 = int(self.game_time)
        m   = int((self.game_time % 1) * 60)
        ampm = "AM" if h24 < 12 else "PM"
        h12  = h24 % 12 or 12
        ts = self.fnt_md.render(f'{h12}:{m:02d} {ampm}', True, (200, 212, 235))
        self.screen.blit(ts, (cx - ts.get_width() // 2, y)); y += 28

        # Shift progress line
        if self._cfg_shift_duration:
            rem  = max(0.0, self._cfg_shift_duration - self.shift_hours_elapsed)
            rm   = int(rem * 60)
            rs   = int((rem * 3600) % 60)
            ph   = self.fnt_sm.render(
                f'{self._shift_phase_label} {self._shift_num_label}  {self._shift_clean_label}',
                True, (255, 210, 100))
            self.screen.blit(ph, (cx - ph.get_width() // 2, y)); y += 20
            tl = self.fnt_sm.render(f'Left: {rm}:{rs:02d}', True, (190, 200, 185))
            self.screen.blit(tl, (cx - tl.get_width() // 2, y)); y += 26

        # Pay ticker
        wages   = self.HOURLY_WAGE * self.shift_hours_elapsed
        bonuses = self.TASK_BONUS  * self.score
        p1 = self.fnt_md.render(f'Pay: ${wages + bonuses:.2f}', True, (145, 215, 145))
        self.screen.blit(p1, (cx - p1.get_width() // 2, y)); y += 22
        p2 = self.fnt_sm.render(f'  wages  ${wages:.2f}', True, (115, 170, 115))
        self.screen.blit(p2, (cx - p2.get_width() // 2, y)); y += 18
        p3 = self.fnt_sm.render(f'  tasks  ${bonuses:.0f}', True, (115, 170, 115))
        self.screen.blit(p3, (cx - p3.get_width() // 2, y)); y += 28

        # Tasks completed
        sc = self.fnt_md.render(f'Tasks: {self.score}', True, (255, 238, 140))
        self.screen.blit(sc, (cx - sc.get_width() // 2, y)); y += 28

        # Docking status
        if self._docking:
            rem_d = max(0.0, self._dock_timer)
            ds = self.fnt_sm.render(
                f'DOCKED  {int(rem_d)}s remaining', True, (255, 200, 80))
            self.screen.blit(ds, (cx - ds.get_width() // 2, y)); y += 18
        else:
            next_d = max(0.0, self._dock_timer)
            ds = self.fnt_sm.render(f'Underway  dock in {int(next_d)}s',
                                    True, (130, 145, 160))
            self.screen.blit(ds, (cx - ds.get_width() // 2, y)); y += 18

        # Cable status
        n_conn = sum(1 for c in self.connections if c.connected)
        n_taut = sum(1 for c in self.connections if c.tensioned)
        n_tot  = len(self.connections)
        cs = self.fnt_sm.render(
            f'Cables  {n_conn}/{n_tot} connected  {n_taut} taut',
            True, (195, 185, 145))
        self.screen.blit(cs, (hud_x + 8, y)); y += 26

        # Active task list
        sep = self.fnt_sm.render('─── active tasks ───', True, (70, 95, 135))
        self.screen.blit(sep, (cx - sep.get_width() // 2, y)); y += 20
        for task in self.active_tasks[:7]:
            bar_col = (65, 175, 90) if task.active else (50, 65, 90)
            bar_w   = int(task.progress * 82)
            pygame.draw.rect(self.screen, (35, 45, 65),
                             (hud_x + 8, y, 82, 9), border_radius=3)
            if bar_w > 0:
                pygame.draw.rect(self.screen, bar_col,
                                 (hud_x + 8, y, bar_w, 9), border_radius=3)
            tc = (70, 215, 95) if task.active else (175, 180, 200)
            tl = self.fnt_sm.render(task.label, True, tc)
            self.screen.blit(tl, (hud_x + 96, y)); y += 18

        # Controls footer
        y = self.height - 108
        for line, col in [
            ('WASD / arrows  Move',    (120, 138, 168)),
            ('[E] hold  Work task',    (120, 138, 168)),
            ('[ESC]  Menu',            (95,  112, 142)),
        ]:
            ls = self.fnt_sm.render(line, True, col)
            self.screen.blit(ls, (hud_x + 8, y)); y += 20

        if self.dev_mode:
            ds = self.fnt_sm.render(
                f'[DEV] {self.time_scale:.1f}x  [/] ]] spd  End=skip',
                True, (255, 100, 255))
            self.screen.blit(ds, (hud_x + 8, y))

    # ── Input ────────────────────────────────────────────────────────────────

    def handle_input(self) -> str:
        """Return 'continue', 'menu', or 'quit'."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return 'quit'
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if self._winch_active:
                        # Cancel winch, leave task for retry
                        self._winch_active = False
                        self._winch_task   = None
                        self._winch_result = None
                        self._winch_phase  = 'working'
                    else:
                        return 'menu'
                elif event.key == pygame.K_SPACE:
                    if self._winch_active and self._winch_phase == 'lock_window':
                        self._winch_space_flag = True
                elif self.dev_mode:
                    if event.key == pygame.K_RIGHTBRACKET:
                        self.time_scale = min(60.0, self.time_scale * 2.0)
                    elif event.key == pygame.K_LEFTBRACKET:
                        self.time_scale = max(0.5, self.time_scale / 2.0)
                    elif event.key == pygame.K_END:
                        if self._cfg_shift_duration is not None:
                            self.shift_hours_elapsed = self._cfg_shift_duration
        return 'continue'

    # ── Main loop ────────────────────────────────────────────────────────────

    def run(self) -> str:
        """Run one shift.  Returns 'menu' | 'quit' | 'shift_complete'."""
        result  = 'menu'
        running = True

        while running:
            signal = self.handle_input()
            if signal == 'quit':
                result  = 'quit'
                running = False
                continue
            elif signal == 'menu':
                running = False
                continue

            dt      = 1 / 60
            game_dt = (dt * self.time_scale) / 60.0
            self.real_time           += dt
            self.shift_hours_elapsed += game_dt

            if self._overboard and self._overboard_t <= 0:
                result  = 'menu'
                running = False
                continue

            if (self._cfg_shift_duration is not None
                    and self.shift_hours_elapsed >= self._cfg_shift_duration):
                self.shift_complete = True
                result  = 'shift_complete'
                running = False
                continue

            self._update(dt, game_dt)
            self._draw()
            pygame.display.flip()
            self.clock.tick(60)

        return result