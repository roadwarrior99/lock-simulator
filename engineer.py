"""
engineer.py — Engine Room simulation.

Top-down view of the towboat engine room. Four instrument panels:
  diesel      — Throttle & RPM management, temperature control
  electrical  — Circuit breaker load balancing
  water       — Bilge, cooling, and freshwater valve control
  hydraulic   — Steering & lock hydraulic pressure regulation

Player walks between panels; [E] hold launches the panel's first-person mini-game.
"""

import math
import random
import pygame


class EngineerSimulation:
    WIDTH  = 1200
    HEIGHT = 800
    HUD_W  = 225
    PLAY_W = WIDTH - HUD_W   # 975

    # Colors
    C_BG       = (18, 22, 28)
    C_FLOOR    = (28, 32, 38)
    C_HUD_BG   = (18, 26, 42)
    C_TEXT     = (210, 215, 225)
    C_DIM      = (120, 128, 145)
    C_ALARM    = (228, 68,  48)
    C_OK       = (48,  188, 88)
    C_WARN     = (228, 168, 48)
    C_PLAYER   = (230, 85,  50)
    C_PLAYER_H = (255, 195, 160)

    PANELS = [
        {'id': 'diesel',     'label': 'DIESEL ENGINE', 'color': (55, 78, 48)},
        {'id': 'electrical', 'label': 'ELECTRICAL',    'color': (48, 68, 92)},
        {'id': 'water',      'label': 'WATER SYSTEM',  'color': (38, 68, 98)},
        {'id': 'hydraulic',  'label': 'HYDRAULIC',     'color': (82, 58, 38)},
    ]

    PANEL_W    = 130
    PANEL_H    = 72
    PLAYER_R   = 10
    WALK_SPEED = 165   # px / sec
    TASK_HOLD  = 2.0   # seconds to hold [E] to enter panel

    TASK_INTERVAL_MIN = 18.0
    TASK_INTERVAL_MAX = 36.0

    # Diesel success: hold RPM in zone for this long
    DIESEL_HOLD_NEEDED = 3.5
    # Hydraulic success: hold pressure in zone for this long
    HYDRO_HOLD_NEEDED  = 3.5

    HOURLY_WAGE = 18.0
    TASK_BONUS  = 20.0

    def __init__(self, screen=None, shift_duration=4.0, shift_start_time=6.0,
                 cfg_time_scale=5.0, dev_mode=False):
        pygame.init()
        if screen is None:
            self.screen = pygame.display.set_mode((self.WIDTH, self.HEIGHT))
            pygame.display.set_caption("Engine Room")
        else:
            self.screen = screen

        self.clock = pygame.time.Clock()
        self.fnt_lg = pygame.font.Font(None, 44)
        self.fnt_md = pygame.font.Font(None, 29)
        self.fnt_sm = pygame.font.Font(None, 21)

        self.cfg_shift_duration = shift_duration
        self.cfg_time_scale     = cfg_time_scale
        self.dev_mode           = dev_mode

        self.game_time           = float(shift_start_time)
        self.shift_hours_elapsed = 0.0
        self.score               = 0
        self.incident_count      = 0
        self.incidents           = []

        self._task_timer    = 0.0
        self._next_task_t   = random.uniform(self.TASK_INTERVAL_MIN, self.TASK_INTERVAL_MAX)
        self._alerted_panel = None   # which panel has the current pending task

        self._panel_active  = False
        self._panel_id      = None
        self._hold_progress = 0.0   # 0–1, E-hold at panel entrance

        self._notif   = ''
        self._notif_t = 0.0

        # ── Per-system state ───────────────────────────────────────────────
        self._diesel = {
            'throttle': 0.50,
            'rpm':      0.50,
            'temp':     0.30,
            'target':   0.65,   # target RPM fraction
            'hold_t':   0.0,
            'phase':    'work', 'result': None, 'result_t': 0.0,
        }

        self._elec = {
            # Six breakers: True = closed (on)
            'breakers': [True, True, False, True, False, True],
            'labels':   ['Main Bus', 'Port Eng', 'Stbd Eng',
                         'Nav Sys',  'Aux Pump', 'Lighting'],
            'load':     0.0,
            'tgt_min':  0.40,
            'tgt_max':  0.72,
            'phase':    'work', 'result': None, 'result_t': 0.0,
        }

        self._water = {
            'valves':    [0.50, 0.50, 0.50],
            'pressures': [0.50, 0.50, 0.50],
            'targets':   [0.60, 0.45, 0.55],
            'labels':    ['BILGE', 'COOLING', 'FRESH'],
            'key_pairs': [('Q', 'E'), ('U', 'I'), ('O', 'P')],
            'phase':     'work', 'result': None, 'result_t': 0.0,
        }

        self._hydro = {
            'pump':    0.50,
            'pressure': 0.50,
            'tgt_min': 0.45,
            'tgt_max': 0.65,
            'hold_t':  0.0,
            'phase':   'work', 'result': None, 'result_t': 0.0,
        }

        self._alarms = {pid: False for pid in ('diesel', 'electrical', 'water', 'hydraulic')}

        self._build_room()

    # ── Room layout ───────────────────────────────────────────────────────────

    def _build_room(self):
        cx = self.PLAY_W // 2
        cy = self.HEIGHT // 2
        mg = 90   # margin from edge to panel centre
        hw = self.PANEL_W // 2
        hh = self.PANEL_H // 2
        self._panel_rects = {
            'diesel':     pygame.Rect(cx - hw,          mg,                  self.PANEL_W, self.PANEL_H),
            'electrical': pygame.Rect(cx - hw,          self.HEIGHT - mg - self.PANEL_H, self.PANEL_W, self.PANEL_H),
            'water':      pygame.Rect(mg,                cy - hh,             self.PANEL_W, self.PANEL_H),
            'hydraulic':  pygame.Rect(self.PLAY_W - mg - self.PANEL_W, cy - hh, self.PANEL_W, self.PANEL_H),
        }
        self._px = float(cx)
        self._py = float(cy)

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        while True:
            result = self._handle_input()
            if result in ('quit', 'menu'):
                return result

            dt = min(self.clock.tick(60) / 1000.0, 0.05)
            game_dt = dt * self.cfg_time_scale / 60.0
            self.shift_hours_elapsed += game_dt
            self.game_time = (self.game_time + game_dt) % 24.0

            if self.shift_hours_elapsed >= self.cfg_shift_duration:
                return 'shift_complete'

            self._update(dt)
            self._draw()
            pygame.display.flip()

    # ── Input ─────────────────────────────────────────────────────────────────

    def _handle_input(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return 'quit'
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if self._panel_active:
                        self._exit_panel()
                    else:
                        return 'menu'
                # Electrical breaker toggles via number keys
                if self._panel_active and self._panel_id == 'electrical':
                    for i, k in enumerate([pygame.K_1, pygame.K_2, pygame.K_3,
                                           pygame.K_4, pygame.K_5, pygame.K_6]):
                        if event.key == k and self._elec['phase'] == 'work':
                            self._elec['breakers'][i] = not self._elec['breakers'][i]
        return 'continue'

    def _exit_panel(self):
        self._panel_active = False
        self._panel_id     = None
        self._hold_progress = 0.0

    # ── Update ────────────────────────────────────────────────────────────────

    def _update(self, dt):
        keys = pygame.key.get_pressed()

        if self._panel_active:
            self._update_panel(dt, keys)
            return

        # Player movement
        dx, dy = 0.0, 0.0
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:  dx -= 1
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]: dx += 1
        if keys[pygame.K_w] or keys[pygame.K_UP]:    dy -= 1
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:  dy += 1
        if dx and dy:
            dx *= 0.707; dy *= 0.707
        self._px = max(self.PLAYER_R,
                       min(self.PLAY_W - self.PLAYER_R, self._px + dx * self.WALK_SPEED * dt))
        self._py = max(self.PLAYER_R,
                       min(self.HEIGHT - self.PLAYER_R, self._py + dy * self.WALK_SPEED * dt))

        # Panel proximity + E-hold to enter
        near = self._nearest_panel()
        if near and keys[pygame.K_e]:
            self._hold_progress += dt / self.TASK_HOLD
            if self._hold_progress >= 1.0:
                self._hold_progress = 0.0
                self._launch_panel(near)
        else:
            self._hold_progress = max(0.0, self._hold_progress - dt * 0.6)

        # Task spawning
        self._task_timer += dt
        if self._task_timer >= self._next_task_t:
            self._task_timer  = 0.0
            self._next_task_t = random.uniform(self.TASK_INTERVAL_MIN, self.TASK_INTERVAL_MAX)
            ids = list(self._panel_rects)
            self._alerted_panel = random.choice(ids)
            self._notify(f"Check {self._alerted_panel.upper()} panel!")

        # Background system drift
        self._drift_systems(dt)

        if self._notif_t > 0:
            self._notif_t -= dt

    def _nearest_panel(self):
        for pid, rect in self._panel_rects.items():
            if math.hypot(self._px - rect.centerx, self._py - rect.centery) < 90:
                return pid
        return None

    def _launch_panel(self, pid):
        self._panel_active  = True
        self._panel_id      = pid
        self._reset_panel(pid)
        if pid == self._alerted_panel:
            self._alerted_panel = None

    def _reset_panel(self, pid):
        if pid == 'diesel':
            d = self._diesel
            d['hold_t'] = 0.0
            d['phase'] = 'work'; d['result'] = None; d['result_t'] = 0.0
        elif pid == 'electrical':
            e = self._elec
            e['phase'] = 'work'; e['result'] = None; e['result_t'] = 0.0
        elif pid == 'water':
            w = self._water
            w['phase'] = 'work'; w['result'] = None; w['result_t'] = 0.0
        elif pid == 'hydraulic':
            h = self._hydro
            h['hold_t'] = 0.0
            h['phase'] = 'work'; h['result'] = None; h['result_t'] = 0.0

    def _notify(self, msg):
        self._notif   = msg
        self._notif_t = 3.5

    # ── Background system drift ───────────────────────────────────────────────

    def _drift_systems(self, dt):
        t = pygame.time.get_ticks() * 0.001

        # Diesel: temp slowly rises at high throttle
        d = self._diesel
        noise = math.sin(t * 1.4) * 0.006
        d['rpm'] = max(0.0, min(1.0, d['rpm'] + noise))
        d['temp'] += (d['throttle'] - 0.42) * 0.015 * dt
        d['temp'] = max(0.0, min(1.0, d['temp']))
        self._alarms['diesel'] = d['temp'] > 0.82

        # Electrical: load = fraction of closed breakers
        e = self._elec
        e['load'] = sum(e['breakers']) / len(e['breakers'])
        self._alarms['electrical'] = not (e['tgt_min'] <= e['load'] <= e['tgt_max'])

        # Water: pressures track valve settings
        w = self._water
        for i in range(3):
            target = w['targets'][i] * (w['valves'][i] / 0.5)
            w['pressures'][i] += (target - w['pressures'][i]) * 0.25 * dt
            w['pressures'][i] = max(0.0, min(1.0, w['pressures'][i]))
        self._alarms['water'] = any(
            abs(w['pressures'][i] - w['targets'][i]) > 0.22 for i in range(3))

        # Hydraulic: pressure bleeds off slowly
        h = self._hydro
        drift = -0.04 * dt + h['pump'] * 0.07 * dt
        noise = math.sin(t * 2.2) * 0.004
        h['pressure'] = max(0.0, min(1.0, h['pressure'] + drift + noise))
        self._alarms['hydraulic'] = not (h['tgt_min'] <= h['pressure'] <= h['tgt_max'])

    # ── Panel dispatch ────────────────────────────────────────────────────────

    def _update_panel(self, dt, keys):
        pid = self._panel_id
        if   pid == 'diesel':     self._update_diesel(dt, keys)
        elif pid == 'electrical': self._update_electrical(dt, keys)
        elif pid == 'water':      self._update_water(dt, keys)
        elif pid == 'hydraulic':  self._update_hydraulic(dt, keys)

    # ── Diesel update ─────────────────────────────────────────────────────────

    def _update_diesel(self, dt, keys):
        d = self._diesel
        if d['phase'] == 'result':
            d['result_t'] -= dt
            if d['result_t'] <= 0:
                success = d['result'] == 'success'
                self._exit_panel()
                if success:
                    self.score += 1
                    self._notify("Engine running smooth.")
                else:
                    self.incident_count += 1
                    self.incidents.append('diesel_overtemp')
                    self._notify("Engine overheated!")
            return

        if keys[pygame.K_q]:
            d['throttle'] = min(1.0, d['throttle'] + 0.55 * dt)
        if keys[pygame.K_e]:
            d['throttle'] = max(0.0, d['throttle'] - 0.55 * dt)

        t = pygame.time.get_ticks() * 0.001
        target_rpm = d['throttle'] * 0.9
        d['rpm'] += (target_rpm - d['rpm']) * 1.8 * dt
        d['rpm'] = max(0.0, min(1.0, d['rpm'] + math.sin(t * 3.8) * 0.008))

        d['temp'] += (d['throttle'] - 0.44) * 0.11 * dt
        d['temp'] = max(0.0, min(1.0, d['temp']))

        # Overheat = fail
        if d['temp'] >= 0.95:
            d['phase'] = 'result'; d['result'] = 'fail'; d['result_t'] = 2.5
            self.incident_count += 1
            self.incidents.append('diesel_overtemp')
            return

        # Success: RPM in target zone AND temp safe, held for DIESEL_HOLD_NEEDED seconds
        in_zone = abs(d['rpm'] - d['target']) < 0.08 and d['temp'] < 0.72
        if in_zone:
            d['hold_t'] += dt
        else:
            d['hold_t'] = max(0.0, d['hold_t'] - dt * 0.6)

        if d['hold_t'] >= self.DIESEL_HOLD_NEEDED:
            d['phase'] = 'result'; d['result'] = 'success'; d['result_t'] = 2.0
            self.score += 1

    # ── Electrical update ─────────────────────────────────────────────────────

    def _update_electrical(self, dt, keys):
        e = self._elec
        if e['phase'] == 'result':
            e['result_t'] -= dt
            if e['result_t'] <= 0:
                success = e['result'] == 'success'
                self._exit_panel()
                if success:
                    self.score += 1
                    self._notify("Load balanced.")
                else:
                    self.incident_count += 1
                    self._notify("Load imbalance.")
            return

        e['load'] = sum(e['breakers']) / len(e['breakers'])
        if e['tgt_min'] <= e['load'] <= e['tgt_max']:
            e['phase'] = 'result'; e['result'] = 'success'; e['result_t'] = 2.0
            self.score += 1

    # ── Water update ──────────────────────────────────────────────────────────

    def _update_water(self, dt, keys):
        w = self._water
        if w['phase'] == 'result':
            w['result_t'] -= dt
            if w['result_t'] <= 0:
                success = w['result'] == 'success'
                self._exit_panel()
                if success:
                    self.score += 1
                    self._notify("Water systems nominal.")
                else:
                    self.incident_count += 1
                    self._notify("Pressure fault!")
            return

        valve_keys = [
            (pygame.K_q, pygame.K_e, 0),
            (pygame.K_u, pygame.K_i, 1),
            (pygame.K_o, pygame.K_p, 2),
        ]
        for up_k, dn_k, idx in valve_keys:
            if keys[up_k]:
                w['valves'][idx] = min(1.0, w['valves'][idx] + 0.45 * dt)
            if keys[dn_k]:
                w['valves'][idx] = max(0.0, w['valves'][idx] - 0.45 * dt)

        for i in range(3):
            target = w['targets'][i] * (w['valves'][i] / 0.5)
            w['pressures'][i] += (target - w['pressures'][i]) * 1.8 * dt
            w['pressures'][i] = max(0.0, min(1.0, w['pressures'][i]))

        if all(abs(w['pressures'][i] - w['targets'][i]) < 0.09 for i in range(3)):
            w['phase'] = 'result'; w['result'] = 'success'; w['result_t'] = 2.0
            self.score += 1

    # ── Hydraulic update ──────────────────────────────────────────────────────

    def _update_hydraulic(self, dt, keys):
        h = self._hydro
        if h['phase'] == 'result':
            h['result_t'] -= dt
            if h['result_t'] <= 0:
                success = h['result'] == 'success'
                self._exit_panel()
                if success:
                    self.score += 1
                    self._notify("Hydraulic pressure stable.")
                else:
                    self.incident_count += 1
                    self.incidents.append('hydraulic_pressure_loss')
                    self._notify("Hydraulic failure!")
            return

        if keys[pygame.K_q]:
            h['pump'] = min(1.0, h['pump'] + 0.75 * dt)
        if keys[pygame.K_e]:
            h['pump'] = max(0.0, h['pump'] - 0.75 * dt)

        t = pygame.time.get_ticks() * 0.001
        drift = -0.055 * dt + h['pump'] * 0.10 * dt
        h['pressure'] = max(0.0, min(1.0, h['pressure'] + drift + math.sin(t * 2.6) * 0.006))

        if h['pressure'] <= 0.04:
            h['phase'] = 'result'; h['result'] = 'fail'; h['result_t'] = 2.5
            return

        in_zone = h['tgt_min'] <= h['pressure'] <= h['tgt_max']
        if in_zone:
            h['hold_t'] += dt
        else:
            h['hold_t'] = max(0.0, h['hold_t'] - dt * 0.6)

        if h['hold_t'] >= self.HYDRO_HOLD_NEEDED:
            h['phase'] = 'result'; h['result'] = 'success'; h['result_t'] = 2.0
            self.score += 1

    # ── Draw ──────────────────────────────────────────────────────────────────

    def _draw(self):
        self.screen.fill(self.C_BG)
        if self._panel_active:
            self._draw_panel(self._panel_id)
        else:
            self._draw_room()
        self._draw_hud()

    def _draw_room(self):
        # Floor with grid
        pygame.draw.rect(self.screen, self.C_FLOOR, (0, 0, self.PLAY_W, self.HEIGHT))
        for x in range(0, self.PLAY_W, 52):
            pygame.draw.line(self.screen, (32, 36, 44), (x, 0), (x, self.HEIGHT), 1)
        for y in range(0, self.HEIGHT, 52):
            pygame.draw.line(self.screen, (32, 36, 44), (0, y), (self.PLAY_W, y), 1)

        # Pipes running along walls (decorative)
        for py_ in (30, 50, self.HEIGHT - 30, self.HEIGHT - 50):
            pygame.draw.line(self.screen, (55, 65, 80), (0, py_), (self.PLAY_W, py_), 4)
        for px_ in (30, 50, self.PLAY_W - 30, self.PLAY_W - 50):
            pygame.draw.line(self.screen, (55, 65, 80), (px_, 0), (px_, self.HEIGHT), 4)

        near = self._nearest_panel()
        for pinfo in self.PANELS:
            pid   = pinfo['id']
            rect  = self._panel_rects[pid]
            alarm = self._alarms[pid]
            is_near = pid == near

            # Alarm flash
            base = list(pinfo['color'])
            if alarm:
                f = int((math.sin(pygame.time.get_ticks() * 0.006) + 1) * 40)
                base[0] = min(255, base[0] + f + 55)

            pygame.draw.rect(self.screen, base, rect, border_radius=6)
            border = (200, 220, 255) if is_near else (75, 88, 108)
            pygame.draw.rect(self.screen, border, rect, 2, border_radius=6)

            # Panel label
            lbl = self.fnt_sm.render(pinfo['label'], True, self.C_TEXT)
            self.screen.blit(lbl, (rect.centerx - lbl.get_width() // 2, rect.y + 5))

            # Status
            if alarm:
                al = self.fnt_sm.render("! ALARM", True, self.C_ALARM)
                self.screen.blit(al, (rect.centerx - al.get_width() // 2, rect.y + 22))
            else:
                ok = self.fnt_sm.render("OK", True, self.C_OK)
                self.screen.blit(ok, (rect.centerx - ok.get_width() // 2, rect.y + 22))

            # Task ring
            if pid == self._alerted_panel:
                pygame.draw.circle(self.screen, (255, 215, 50), rect.center, 26, 3)

            # E-hold bar
            if is_near and self._hold_progress > 0:
                bw = int(rect.width * self._hold_progress)
                pygame.draw.rect(self.screen, (75, 195, 115),
                                 (rect.x, rect.bottom - 6, bw, 6), border_radius=3)

        # Player body + head
        px, py = int(self._px), int(self._py)
        pygame.draw.circle(self.screen, self.C_PLAYER,   (px, py), self.PLAYER_R)
        pygame.draw.circle(self.screen, self.C_PLAYER_H, (px, py - self.PLAYER_R - 4), 5)

        # Proximity prompt
        if near:
            p = self.fnt_sm.render("[E] Hold to enter panel", True, (210, 225, 255))
            self.screen.blit(p, (self.PLAY_W // 2 - p.get_width() // 2, self.HEIGHT - 28))

        # Notification
        if self._notif_t > 0:
            a = min(1.0, self._notif_t / 0.4)
            c = (int(220 * a), int(230 * a), int(255 * a))
            nl = self.fnt_md.render(self._notif, True, c)
            self.screen.blit(nl, (self.PLAY_W // 2 - nl.get_width() // 2, 22))

    # ── Panel drawing ─────────────────────────────────────────────────────────

    def _draw_panel(self, pid):
        if   pid == 'diesel':     self._draw_diesel()
        elif pid == 'electrical': self._draw_electrical()
        elif pid == 'water':      self._draw_water()
        elif pid == 'hydraulic':  self._draw_hydraulic()

    def _panel_bg(self, title, subtitle=''):
        """Engine room interior background + panel frame. Returns the inner Rect."""
        pw = self.PLAY_W
        # Ceiling / overhead
        pygame.draw.rect(self.screen, (20, 24, 32), (0, 0, pw, self.HEIGHT))
        # Grated floor
        pygame.draw.rect(self.screen, (26, 30, 36), (0, 580, pw, 220))
        for x in range(0, pw, 36):
            pygame.draw.line(self.screen, (32, 36, 44), (x, 580), (x, self.HEIGHT), 1)
        # Overhead fluorescent strips
        for lx in range(60, pw - 60, 190):
            pygame.draw.rect(self.screen, (195, 210, 165), (lx, 8, 90, 10), border_radius=3)
        # Panel face
        panel = pygame.Rect(50, 105, pw - 100, 445)
        pygame.draw.rect(self.screen, (30, 36, 48), panel, border_radius=8)
        pygame.draw.rect(self.screen, (58, 74, 105), panel, 2, border_radius=8)
        # Title
        t = self.fnt_lg.render(title, True, (215, 225, 242))
        self.screen.blit(t, (pw // 2 - t.get_width() // 2, 66))
        if subtitle:
            st = self.fnt_sm.render(subtitle, True, self.C_DIM)
            self.screen.blit(st, (pw // 2 - st.get_width() // 2, 90))
        esc = self.fnt_sm.render("ESC — leave panel", True, self.C_DIM)
        self.screen.blit(esc, (8, self.HEIGHT - 20))
        return panel

    def _gauge(self, cx, cy, r, value, label, zones=None):
        """Semicircular dial gauge. zones = [(lo, hi, color), ...]."""
        pygame.draw.arc(self.screen, (38, 44, 56),
                        (cx - r, cy - r, r * 2, r * 2), 0, math.pi, 10)
        if zones:
            for zlo, zhi, zc in zones:
                pygame.draw.arc(self.screen, zc,
                                (cx - r, cy - r, r * 2, r * 2),
                                math.pi * (1 - zhi), math.pi * (1 - zlo), 8)
        pygame.draw.arc(self.screen, (75, 88, 108),
                        (cx - r, cy - r, r * 2, r * 2), 0, math.pi, 2)
        # Needle
        ang = math.pi * (1 - value)
        nx  = cx + int((r - 14) * math.cos(ang))
        ny  = cy - int((r - 14) * math.sin(ang))
        pygame.draw.line(self.screen, (235, 240, 248), (cx, cy), (nx, ny), 2)
        pygame.draw.circle(self.screen, (175, 182, 198), (cx, cy), 6)
        # Labels
        lbl = self.fnt_sm.render(label, True, self.C_TEXT)
        self.screen.blit(lbl, (cx - lbl.get_width() // 2, cy + 10))
        vl = self.fnt_sm.render(f"{int(value * 100)}%", True, self.C_TEXT)
        self.screen.blit(vl, (cx - vl.get_width() // 2, cy - r - 20))

    def _bar(self, x, y, w, h, value, label, col=(75, 178, 85), vertical=False):
        """Filled bar gauge."""
        pygame.draw.rect(self.screen, (28, 32, 44), (x, y, w, h), border_radius=3)
        if vertical:
            fh = int(value * h)
            pygame.draw.rect(self.screen, col, (x, y + h - fh, w, fh), border_radius=3)
        else:
            fw = int(value * w)
            pygame.draw.rect(self.screen, col, (x, y, fw, h), border_radius=3)
        pygame.draw.rect(self.screen, (58, 66, 80), (x, y, w, h), 1, border_radius=3)
        if label:
            ll = self.fnt_sm.render(label, True, self.C_DIM)
            self.screen.blit(ll, (x, y - 18))

    def _btn(self, x, y, w, h, key_lbl, action_lbl, pressed):
        on_bg  = (44, 148, 68) if not pressed else (28, 210, 88)
        off_bg = (22, 74, 36)
        bg     = on_bg if pressed else off_bg
        pygame.draw.rect(self.screen, bg, (x, y, w, h), border_radius=5)
        border = (88, 210, 118) if pressed else (40, 108, 58)
        pygame.draw.rect(self.screen, border, (x, y, w, h), 2, border_radius=5)
        kl = self.fnt_md.render(key_lbl,    True, (225, 240, 225))
        al = self.fnt_sm.render(action_lbl, True, self.C_DIM)
        self.screen.blit(kl, (x + 8, y + 5))
        self.screen.blit(al, (x + 8, y + 24))

    def _result_overlay(self, success, msg):
        s = pygame.Surface((self.PLAY_W, self.HEIGHT), pygame.SRCALPHA)
        s.fill((28, 158, 68, 130) if success else (158, 28, 28, 130))
        self.screen.blit(s, (0, 0))
        lbl = self.fnt_lg.render(msg, True,
                                  (240, 252, 240) if success else (255, 228, 228))
        self.screen.blit(lbl, (self.PLAY_W // 2 - lbl.get_width() // 2,
                                self.HEIGHT // 2 - 22))

    # ── Diesel panel ──────────────────────────────────────────────────────────

    def _draw_diesel(self):
        self._panel_bg("DIESEL ENGINE", "Main propulsion — RPM & temperature")
        d   = self._diesel
        pw  = self.PLAY_W
        cx  = pw // 2
        keys = pygame.key.get_pressed()

        # RPM gauge (left)
        rpm_zones = [
            (0.0, 0.30, (128, 42, 22)),
            (0.30, d['target'] - 0.08, (72, 118, 42)),
            (d['target'] - 0.08, d['target'] + 0.08, (42, 195, 82)),   # sweet spot
            (d['target'] + 0.08, 0.80, (72, 118, 42)),
            (0.80, 1.0, (168, 42, 22)),
        ]
        self._gauge(cx - 200, 310, 95, d['rpm'], "RPM", rpm_zones)

        # Temp gauge (right)
        temp_zones = [
            (0.0, 0.50, (42, 148, 68)),
            (0.50, 0.72, (185, 158, 38)),
            (0.72, 1.0,  (178, 42, 28)),
        ]
        self._gauge(cx + 200, 310, 95, d['temp'], "TEMP", temp_zones)

        # Throttle slider (centre)
        sl_x, sl_y, sl_h = cx - 18, 168, 130
        pygame.draw.rect(self.screen, (24, 28, 38), (sl_x, sl_y, 36, sl_h), border_radius=4)
        knob_y = sl_y + int((1.0 - d['throttle']) * (sl_h - 24))
        pygame.draw.rect(self.screen, (82, 148, 102), (sl_x - 6, knob_y, 48, 24), border_radius=4)
        pygame.draw.rect(self.screen, (115, 198, 140), (sl_x - 6, knob_y, 48, 24), 2, border_radius=4)
        tl = self.fnt_sm.render("THROTTLE", True, self.C_DIM)
        self.screen.blit(tl, (cx - tl.get_width() // 2, sl_y - 20))
        tv = self.fnt_sm.render(f"{int(d['throttle']*100)}%", True, self.C_TEXT)
        self.screen.blit(tv, (cx - tv.get_width() // 2, sl_y + sl_h + 4))

        # Buttons
        self._btn(cx - 240, 440, 130, 48, '[Q]', 'THROTTLE UP',   keys[pygame.K_q])
        self._btn(cx + 110, 440, 130, 48, '[E]', 'THROTTLE DOWN', keys[pygame.K_e])

        # Hold progress
        if d['hold_t'] > 0:
            bw = int(d['hold_t'] / self.DIESEL_HOLD_NEEDED * 220)
            self._bar(cx - 110, 502, 220, 12, d['hold_t'] / self.DIESEL_HOLD_NEEDED,
                      "Hold RPM in green zone...", (42, 188, 82))

        if d['phase'] == 'result':
            self._result_overlay(d['result'] == 'success',
                                  "ENGINE STABLE" if d['result'] == 'success' else "OVERHEAT!")

    # ── Electrical panel ──────────────────────────────────────────────────────

    def _draw_electrical(self):
        self._panel_bg("ELECTRICAL SYSTEM", "Circuit breaker load balancing — keys [1]–[6]")
        e    = self._elec
        pw   = self.PLAY_W
        cx   = pw // 2

        # Six breakers in a 3×2 grid
        for i in range(6):
            col_i, row_i = i % 3, i // 3
            bx = cx - 218 + col_i * 148
            by = 170 + row_i * 118
            on = e['breakers'][i]

            pygame.draw.rect(self.screen, (26, 30, 40), (bx, by, 100, 90), border_radius=5)
            pygame.draw.rect(self.screen, (52, 60, 78), (bx, by, 100, 90), 1, border_radius=5)

            # Lever position
            lever_col = (42, 195, 72) if on else (42, 48, 60)
            lever_y   = by + 14 if on else by + 50
            pygame.draw.rect(self.screen, lever_col,
                             (bx + 32, lever_y, 36, 24), border_radius=4)
            pygame.draw.rect(self.screen, (70, 210, 100) if on else (55, 62, 78),
                             (bx + 32, lever_y, 36, 24), 1, border_radius=4)

            # ON/OFF dot
            dot_col = (42, 195, 72) if on else (148, 42, 32)
            pygame.draw.circle(self.screen, dot_col, (bx + 15, by + 15), 6)

            # Label + key
            ll = self.fnt_sm.render(e['labels'][i], True, self.C_TEXT if on else self.C_DIM)
            self.screen.blit(ll, (bx + 50 - ll.get_width() // 2, by + 72))
            kl = self.fnt_sm.render(f"[{i+1}]", True, (155, 168, 192))
            self.screen.blit(kl, (bx + 4, by + 4))

        # Load meter
        load     = e['load']
        load_col = (self.C_OK if e['tgt_min'] <= load <= e['tgt_max'] else self.C_ALARM)
        bar_x    = cx - 165
        self._bar(bar_x, 422, 330, 22, load, "SYSTEM LOAD", load_col)

        # Green target zone overlay
        t1 = bar_x + int(e['tgt_min'] * 330)
        t2 = bar_x + int(e['tgt_max'] * 330)
        tz = pygame.Surface((t2 - t1, 22), pygame.SRCALPHA)
        tz.fill((42, 195, 72, 55))
        self.screen.blit(tz, (t1, 422))
        pygame.draw.line(self.screen, (42, 195, 72), (t1, 418), (t1, 448), 2)
        pygame.draw.line(self.screen, (42, 195, 72), (t2, 418), (t2, 448), 2)

        hint = self.fnt_sm.render(
            f"Target {int(e['tgt_min']*100)}–{int(e['tgt_max']*100)}%   "
            f"Current {int(load*100)}%", True, self.C_TEXT)
        self.screen.blit(hint, (cx - hint.get_width() // 2, 450))

        if e['phase'] == 'result':
            self._result_overlay(e['result'] == 'success',
                                  "LOAD BALANCED" if e['result'] == 'success' else "LOAD ERROR")

    # ── Water panel ───────────────────────────────────────────────────────────

    def _draw_water(self):
        self._panel_bg("WATER SYSTEM", "Bilge · Cooling · Freshwater pressure")
        w    = self._water
        pw   = self.PLAY_W
        cx   = pw // 2
        cols = [(82, 145, 188), (42, 168, 128), (62, 122, 188)]
        keys = pygame.key.get_pressed()

        for i in range(3):
            bx = cx - 270 + i * 185
            by = 160

            # Vertical pressure bar
            p_col = cols[i] if abs(w['pressures'][i] - w['targets'][i]) < 0.12 else self.C_ALARM
            self._bar(bx + 38, by, 32, 175, w['pressures'][i],
                      w['labels'][i], p_col, vertical=True)

            # Target line
            ty = by + int((1.0 - w['targets'][i]) * 175)
            pygame.draw.line(self.screen, (42, 215, 88), (bx + 28, ty), (bx + 78, ty), 2)
            tl = self.fnt_sm.render(f"T{int(w['targets'][i]*100)}", True, (42, 215, 88))
            self.screen.blit(tl, (bx + 82, ty - 8))

            # Valve bar (horizontal, below)
            v_col = (68, 148, 108) if w['valves'][i] > 0.25 else (148, 68, 48)
            self._bar(bx + 8, by + 185, 92, 18, w['valves'][i], '', v_col)
            vl = self.fnt_sm.render(f"Valve {int(w['valves'][i]*100)}%", True, self.C_DIM)
            self.screen.blit(vl, (bx + 8, by + 207))

            # Key hints
            kp = w['key_pairs'][i]
            kh = self.fnt_sm.render(f"[{kp[0]}] up  [{kp[1]}] dn", True, self.C_DIM)
            self.screen.blit(kh, (bx + 54 - kh.get_width() // 2, by + 228))

            # Pressure value
            pv = self.fnt_sm.render(f"{int(w['pressures'][i]*100)} PSI", True, self.C_TEXT)
            self.screen.blit(pv, (bx + 54 - pv.get_width() // 2, by - 22))

        if w['phase'] == 'result':
            self._result_overlay(w['result'] == 'success',
                                  "SYSTEMS NOMINAL" if w['result'] == 'success' else "PRESSURE FAULT")

    # ── Hydraulic panel ───────────────────────────────────────────────────────

    def _draw_hydraulic(self):
        self._panel_bg("HYDRAULIC SYSTEM", "Steering & lock pressure regulation")
        h    = self._hydro
        pw   = self.PLAY_W
        cx   = pw // 2
        keys = pygame.key.get_pressed()

        # Large central pressure gauge
        hyd_zones = [
            (0.0,        h['tgt_min'], (168, 42, 28)),
            (h['tgt_min'], h['tgt_max'], (42, 188, 68)),
            (h['tgt_max'], 1.0,        (168, 108, 28)),
        ]
        self._gauge(cx, 305, 125, h['pressure'], "PRESSURE", hyd_zones)

        # Pump speed bar
        self._bar(cx - 165, 440, 330, 22, h['pump'], "PUMP SPEED", (65, 122, 188))

        # Hold progress
        if h['hold_t'] > 0:
            self._bar(cx - 110, 480, 220, 12,
                      h['hold_t'] / self.HYDRO_HOLD_NEEDED,
                      "Hold in green zone...", (42, 188, 82))

        # Buttons
        self._btn(cx - 240, 510, 130, 48, '[Q]', 'PUMP UP',   keys[pygame.K_q])
        self._btn(cx + 110, 510, 130, 48, '[E]', 'PUMP DOWN', keys[pygame.K_e])

        if h['phase'] == 'result':
            self._result_overlay(h['result'] == 'success',
                                  "PRESSURE STABLE" if h['result'] == 'success' else "PRESSURE LOST")

    # ── HUD ───────────────────────────────────────────────────────────────────

    def _draw_hud(self):
        hx = self.PLAY_W
        pygame.draw.rect(self.screen, self.C_HUD_BG, (hx, 0, self.HUD_W, self.HEIGHT))
        pygame.draw.line(self.screen, (50, 60, 82), (hx, 0), (hx, self.HEIGHT), 2)

        y = 14

        def row(text, fnt=None, col=None, center=False):
            nonlocal y
            fnt = fnt or self.fnt_sm
            col = col or self.C_TEXT
            lbl = fnt.render(text, True, col)
            x   = hx + (self.HUD_W // 2 - lbl.get_width() // 2 if center else 10)
            self.screen.blit(lbl, (x, y))
            y  += lbl.get_height() + 4

        row("ENGINEER", self.fnt_lg, center=True)

        h_  = int(self.game_time)
        m_  = int((self.game_time % 1) * 60)
        ap  = 'AM' if h_ < 12 else 'PM'
        row(f"{h_ % 12 or 12}:{m_:02d} {ap}", self.fnt_md, center=True)
        y  += 4

        rem   = self.cfg_shift_duration - self.shift_hours_elapsed
        rem_m = max(0, int(rem * 60))
        row(f"Shift: {rem_m // 60}h {rem_m % 60:02d}m left", col=self.C_DIM)
        row(f"Tasks done: {self.score}")
        if self.incident_count:
            row(f"Incidents: {self.incident_count}", col=self.C_ALARM)
        y += 8

        row("── SYSTEMS ──", col=self.C_DIM, center=True)
        snames = [('diesel',     'Diesel Eng'),
                  ('electrical', 'Electrical'),
                  ('water',      'Water Sys'),
                  ('hydraulic',  'Hydraulic')]
        for sid, sname in snames:
            alarm = self._alarms[sid]
            col   = self.C_ALARM if alarm else self.C_OK
            row(f"{sname}: {'ALARM' if alarm else 'OK'}", col=col)

        y = self.HEIGHT - 88
        row("WASD      Move",       col=self.C_DIM)
        row("[E] Hold  Enter panel", col=self.C_DIM)
        row("[ESC]     Menu",        col=self.C_DIM)