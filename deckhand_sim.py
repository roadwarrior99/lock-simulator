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

    def __init__(self, x: float, y: float):
        self.x      = float(x)
        self.y      = float(y)
        self.facing = 1   # +1 = right, -1 = left
        self.moving = False

    def update(self, dt: float, keys, bounds: tuple):
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
                 cfg_time_scale=2.0, dev_mode=False):
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

        # Task state — seed with all connect tasks (build the tow first)
        self.active_tasks = []
        for conn in self.connections:
            self.active_tasks.append(Task('connect', conn.midpoint, payload=conn))
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

        # Walk animation
        self._walk_t = 0.0

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

    # ── Update ───────────────────────────────────────────────────────────────

    def _update(self, dt: float, game_dt: float):
        keys = pygame.key.get_pressed()
        self.player.update(dt, keys, self._bounds)

        # Walk animation timer
        if self.player.moving:
            self._walk_t += dt

        # Notification fade
        if self.notif_timer > 0:
            self.notif_timer -= dt

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
        play_w = self.width - 225

        # ── River background ──
        self.screen.fill(self.C_RIVER)

        # Animated current streaks
        for i in range(-80, play_w + 80, 75):
            off = int((self.real_time * 28 + i * 9) % 75)
            x = i + off
            pygame.draw.line(self.screen, self.C_RIVER_LINE,
                             (x, 0), (x - 35, self.height), 1)

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

        # Walking bob
        bob = int(math.sin(self._walk_t * 10) * 2) if self.player.moving else 0

        # Body
        pygame.draw.ellipse(self.screen, self.C_PLAYER,
                            (px - 7, py - 5 + bob, 14, 10))
        # Head
        pygame.draw.circle(self.screen, self.C_PLAYER_HEAD, (px, py - 10 + bob), 6)
        # Hard hat
        pygame.draw.ellipse(self.screen, (255, 210, 30),
                            (px - 7, py - 17 + bob, 14, 7))
        # Direction pointer
        ex = px + self.player.facing * 14
        pygame.draw.line(self.screen, self.C_PLAYER, (px, py + bob), (ex, py + bob), 2)

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
                    return 'menu'
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