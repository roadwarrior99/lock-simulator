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
        {'id': 'battery',    'label': 'BATTERY',       'color': (52, 82, 52)},
        {'id': 'bilge',      'label': 'BILGE PUMPS',   'color': (38, 58, 88)},
        {'id': 'watermaker', 'label': 'WATERMAKER',    'color': (42, 72, 82)},
        {'id': 'vent',       'label': 'VENTILATION',   'color': (68, 52, 78)},
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

    HOURLY_WAGE = 19.5
    TASK_BONUS  = 30.0

    def __init__(self, screen=None, shift_duration=12.0, shift_start_time=6.0,
                 cfg_time_scale=2.0, dev_mode=False):
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
            'phase':   'work', 'result': None, 'result_t': 0.0,
            # Mini-game: 4 pressure columns to vent
            'cols':       [0.20, 0.35, 0.15, 0.28],
            'rates':      [0.08, 0.11, 0.07, 0.13],
            'bleed_anim': [0.0,  0.0,  0.0,  0.0],
            'survive_t':  0.0,
            'survive_needed': 14.0,
        }

        self._battery = {
            'banks':          [0.72, 0.55],
            'drain':          [0.018, 0.011],
            'ch_rates':       [[0.032, 0.008],   # [0] alternator
                               [0.008, 0.024],   # [1] solar
                               [0.018, 0.018]],  # [2] shore power
            'chargers':       [True, False, True],  # alternator toggle unused; solar off; shore on
            'labels':         ['HOUSE 12V', 'START 12V'],
            'ch_labels':      ['ALTERNATOR', 'SOLAR', 'SHORE PWR'],
            'alternator_ok':  True,
            'tgt_min': 0.28, 'tgt_max': 0.92,
            'hold_t': 0.0, 'hold_needed': 10.0,
            'phase': 'work', 'result': None, 'result_t': 0.0,
        }

        self._bilge = {
            'levels':     [0.12, 0.22, 0.08, 0.18],
            'ingress':    [0.016, 0.022, 0.013, 0.019],
            'pump_t':     [0.0, 0.0, 0.0, 0.0],
            'pump_dur':   1.8,
            'pump_rate':  0.16,
            'labels':     ['BOW', 'FWD', 'AFT', 'STERN'],
            'danger':     0.88,
            'survive_t':  0.0, 'survive_needed': 16.0,
            'phase': 'work', 'result': None, 'result_t': 0.0,
        }

        self._wmaker = {
            'fp': 0.65,   # starting point where all 4 outputs are in range
            'fr': 0.45,
            'hold_t': 0.0, 'hold_needed': 8.0,
            'phase': 'work', 'result': None, 'result_t': 0.0,
        }

        self._vent = {
            'fans':     [0.45, 0.40, 0.35],   # default keeps temps stable
            'temps':    [0.42, 0.38, 0.30, 0.28],
            'heat_gen': [0.048, 0.038, 0.026, 0.024],
            'cool_mat': [[0.080, 0.010, 0.060],
                         [0.050, 0.050, 0.010],
                         [0.010, 0.080, 0.010],
                         [0.010, 0.010, 0.080]],
            'labels':   ['ENGINE', 'BILGE', 'CABIN', 'WHEELHOUSE'],
            'tgt_max':  0.76,
            'hold_t': 0.0, 'hold_needed': 8.0,
            'phase': 'work', 'result': None, 'result_t': 0.0,
        }

        self._alarms = {pid: False for pid in ('diesel', 'electrical', 'water', 'hydraulic',
                                                'battery', 'bilge', 'watermaker', 'vent')}

        self._build_room()

    # ── Room layout ───────────────────────────────────────────────────────────

    def _build_room(self):
        cx = self.PLAY_W // 2   # 487
        cy = self.HEIGHT // 2   # 400
        mg = 90
        W  = self.PANEL_W       # 130
        H  = self.PANEL_H       # 72
        self._panel_rects = {
            # Top wall
            'diesel':      pygame.Rect(cx - W - 12,                    mg,                         W, H),
            'battery':     pygame.Rect(cx + 12,                        mg,                         W, H),
            # Bottom wall
            'electrical':  pygame.Rect(cx - W - 12,                    self.HEIGHT - mg - H,       W, H),
            'vent':        pygame.Rect(cx + 12,                        self.HEIGHT - mg - H,       W, H),
            # Left wall
            'water':       pygame.Rect(mg,                             cy - H - 18,                W, H),
            'bilge':       pygame.Rect(mg,                             cy + 18,                    W, H),
            # Right wall
            'hydraulic':   pygame.Rect(self.PLAY_W - mg - W,          cy - H - 18,                W, H),
            'watermaker':  pygame.Rect(self.PLAY_W - mg - W,          cy + 18,                    W, H),
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
                # Hydraulic column bleed via [1]–[4]
                if self._panel_active and self._panel_id == 'hydraulic':
                    for i, k in enumerate([pygame.K_1, pygame.K_2,
                                           pygame.K_3, pygame.K_4]):
                        if event.key == k and self._hydro['phase'] == 'work':
                            self._hydro['cols'][i] = max(0.0, self._hydro['cols'][i] - 0.38)
                            self._hydro['bleed_anim'][i] = 1.0
                # Battery charger toggles: [2] SOLAR, [3] SHORE PWR
                # (Alternator/[1] is automatic — controlled by engine state)
                if self._panel_active and self._panel_id == 'battery':
                    for i, k in [(1, pygame.K_2), (2, pygame.K_3)]:
                        if event.key == k and self._battery['phase'] == 'work':
                            self._battery['chargers'][i] = not self._battery['chargers'][i]
                # Bilge pump keys [1][2][3][4]
                if self._panel_active and self._panel_id == 'bilge':
                    for i, k in enumerate([pygame.K_1, pygame.K_2,
                                           pygame.K_3, pygame.K_4]):
                        if event.key == k and self._bilge['phase'] == 'work':
                            self._bilge['pump_t'][i] = self._bilge['pump_dur']
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
            # Battery is driven by engine state, not random tasks
            ids = [pid for pid in self._panel_rects if pid != 'battery']
            self._alerted_panel = random.choice(ids)
            self._notify(f"Check {self._alerted_panel.upper()} panel!")
            self._disturb_system(self._alerted_panel)

        # Background system drift
        self._drift_systems(dt)

        if self._notif_t > 0:
            self._notif_t -= dt

    def _disturb_system(self, pid):
        """Push a system out of its safe range so its alarm lights up."""
        if pid == 'electrical':
            e = self._elec
            # Flip breakers until load lands outside the target band
            for _ in range(10):
                e['breakers'][random.randrange(6)] = not e['breakers'][random.randrange(6)]
                load = sum(e['breakers']) / len(e['breakers'])
                if not (e['tgt_min'] <= load <= e['tgt_max']):
                    break
        elif pid == 'water':
            w = self._water
            # Slam one or two valves to an extreme so pressure drifts out of range
            for i in random.sample(range(3), k=random.randint(1, 2)):
                w['valves'][i] = random.choice([0.05, 0.10, 0.90, 0.95])
        elif pid == 'diesel':
            # Spike throttle so temperature will rise — manageable if player acts quickly
            self._diesel['throttle'] = random.uniform(0.68, 0.80)
            # Engine trouble also takes the alternator offline — drain banks a bit
            b = self._battery
            b['banks'][0] = random.uniform(0.30, 0.45)
            b['banks'][1] = random.uniform(0.30, 0.45)
        elif pid == 'battery':
            b = self._battery
            b['banks'][0] = random.uniform(0.10, 0.22)
            b['banks'][1] = random.uniform(0.10, 0.22)
            b['chargers'] = [False, False, False]
        elif pid == 'bilge':
            bl = self._bilge
            for i in random.sample(range(4), k=random.randint(2, 3)):
                bl['levels'][i] = random.uniform(0.45, 0.62)
        elif pid == 'watermaker':
            wm = self._wmaker
            wm['fp'] = random.uniform(0.25, 0.42)
            wm['fr'] = random.uniform(0.62, 0.85)
        elif pid == 'vent':
            v = self._vent
            # Reduce fans to simulate partial failure — don't zero them
            v['fans'] = [0.15, 0.12, 0.14]
            # Push temps above alarm/success threshold
            v['temps'] = [random.uniform(0.74, 0.84) for _ in range(4)]

    def _nearest_panel(self):
        best_pid, best_dist = None, 85
        for pid, rect in self._panel_rects.items():
            d = math.hypot(self._px - rect.centerx, self._py - rect.centery)
            if d < best_dist:
                best_pid, best_dist = pid, d
        return best_pid

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
            h['cols']       = [random.uniform(0.10, 0.30) for _ in range(4)]
            h['rates']      = [random.uniform(0.06, 0.16) for _ in range(4)]
            h['bleed_anim'] = [0.0, 0.0, 0.0, 0.0]
            h['survive_t']  = 0.0
            h['phase'] = 'work'; h['result'] = None; h['result_t'] = 0.0
        elif pid == 'battery':
            b = self._battery
            b['hold_t'] = 0.0
            b['phase'] = 'work'; b['result'] = None; b['result_t'] = 0.0
        elif pid == 'bilge':
            bl = self._bilge
            bl['levels']  = [random.uniform(0.08, 0.25) for _ in range(4)]
            bl['ingress'] = [random.uniform(0.012, 0.026) for _ in range(4)]
            bl['pump_t']  = [0.0, 0.0, 0.0, 0.0]
            bl['survive_t'] = 0.0
            bl['phase'] = 'work'; bl['result'] = None; bl['result_t'] = 0.0
        elif pid == 'watermaker':
            wm = self._wmaker
            wm['hold_t'] = 0.0
            wm['phase'] = 'work'; wm['result'] = None; wm['result_t'] = 0.0
        elif pid == 'vent':
            v = self._vent
            v['hold_t'] = 0.0
            v['phase'] = 'work'; v['result'] = None; v['result_t'] = 0.0

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

        # Hydraulic: pressure slowly mean-reverts to zone centre with small noise;
        # alarm only fires if something genuinely pushes it out of range.
        h = self._hydro
        center = (h['tgt_min'] + h['tgt_max']) / 2   # 0.55
        noise  = math.sin(t * 2.2) * 0.002
        h['pressure'] += (center - h['pressure']) * 0.25 * dt + noise
        h['pressure'] = max(0.0, min(1.0, h['pressure']))
        # Hysteresis: don't flicker at the zone boundary
        hyst = 0.03
        if self._alarms['hydraulic']:
            self._alarms['hydraulic'] = not (h['tgt_min'] + hyst <= h['pressure'] <= h['tgt_max'] - hyst)
        else:
            self._alarms['hydraulic'] = not (h['tgt_min'] - hyst <= h['pressure'] <= h['tgt_max'] + hyst)

        # Battery: alternator keeps banks charged while engine is healthy
        b = self._battery
        engine_ok = (not self._alarms['diesel'] and
                     0.28 <= self._diesel['rpm'] <= 0.88 and
                     self._diesel['temp'] < 0.80)
        b['alternator_ok'] = engine_ok
        for i in range(2):
            # Alternator cuts out near tgt_max (float-charge behaviour — no overcharge)
            alt_active = engine_ok and b['banks'][i] < b['tgt_max'] - 0.04
            alt_rate = b['ch_rates'][0][i] if alt_active else 0.0
            other_charge = sum(b['ch_rates'][j][i] * b['chargers'][j] for j in range(1, 3))
            net = alt_rate + other_charge - b['drain'][i]
            b['banks'][i] = max(0.0, min(1.0, b['banks'][i] + net * dt))
        self._alarms['battery'] = any(
            not (0.25 <= b['banks'][i] <= 0.95) for i in range(2))

        # Bilge: water ingress in all compartments
        # Background is capped at 0.72 so normal drift never triggers the alarm —
        # only an explicit _disturb_system call (which sets levels to 0.45–0.62 and
        # lets the in-panel ingress run uncapped) can push them past 0.80.
        bl = self._bilge
        for i in range(4):
            bl['levels'][i] = min(0.72, bl['levels'][i] + bl['ingress'][i] * dt)
            if bl['pump_t'][i] > 0:
                bl['levels'][i] = max(0.0, bl['levels'][i] - bl['pump_rate'] * dt)
                bl['pump_t'][i] -= dt
        self._alarms['bilge'] = any(bl['levels'][i] > 0.80 for i in range(4))

        # Watermaker: no background drift; alarm if any output is out of range
        wm = self._wmaker
        wm_psi      = 0.80 * wm['fp'] + 0.15 * wm['fr']
        wm_salinity = 1.0  - 0.60 * wm['fp'] - 0.25 * wm['fr']
        wm_recovery = 0.40 * wm['fp'] + 0.45 * wm['fr']
        wm_filter   = 0.30 * wm['fp'] + 0.55 * wm['fr']
        self._alarms['watermaker'] = not (
            0.45 <= wm_psi <= 0.75 and
            0.15 <= wm_salinity <= 0.55 and
            0.30 <= wm_recovery <= 0.65 and
            0.25 <= wm_filter <= 0.60)

        # Ventilation: temperature update with current fan speeds
        v = self._vent
        for z in range(4):
            cooling = sum(v['fans'][f] * v['cool_mat'][z][f] for f in range(3))
            # Cap at 0.88 in the background so temps never reach the in-panel fail
            # threshold while the player is walking to the panel
            v['temps'][z] = max(0.0, min(0.88,
                v['temps'][z] + (v['heat_gen'][z] - cooling) * dt))
        self._alarms['vent'] = any(v['temps'][z] > 0.75 for z in range(4))

    # ── Panel dispatch ────────────────────────────────────────────────────────

    def _update_panel(self, dt, keys):
        pid = self._panel_id
        if   pid == 'diesel':     self._update_diesel(dt, keys)
        elif pid == 'electrical': self._update_electrical(dt, keys)
        elif pid == 'water':      self._update_water(dt, keys)
        elif pid == 'hydraulic':  self._update_hydraulic(dt, keys)
        elif pid == 'battery':    self._update_battery(dt, keys)
        elif pid == 'bilge':      self._update_bilge(dt, keys)
        elif pid == 'watermaker': self._update_watermaker(dt, keys)
        elif pid == 'vent':       self._update_vent(dt, keys)

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

        # Temp rises when throttle is high, cools when throttle is low
        d['temp'] += (d['throttle'] - 0.44) * 0.14 * dt
        d['temp'] = max(0.0, min(1.0, d['temp']))

        # Overheat = fail
        if d['temp'] >= 0.95:
            d['phase'] = 'result'; d['result'] = 'fail'; d['result_t'] = 2.5
            self.incident_count += 1
            self.incidents.append('diesel_overtemp')
            return

        # Success: RPM in target zone for long enough (temp is managed by overheat threat alone)
        in_zone = abs(d['rpm'] - d['target']) < 0.08
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

        # Fill each column; bleed-anim fades out
        for i in range(4):
            h['cols'][i] = min(1.0, h['cols'][i] + h['rates'][i] * dt)
            h['bleed_anim'][i] = max(0.0, h['bleed_anim'][i] - dt * 3.5)
            if h['cols'][i] >= 1.0:
                h['phase'] = 'result'; h['result'] = 'fail'; h['result_t'] = 2.5
                return

        h['survive_t'] += dt
        if h['survive_t'] >= h['survive_needed']:
            h['phase'] = 'result'; h['result'] = 'success'; h['result_t'] = 2.0
            self.score += 1

    # ── Battery update ────────────────────────────────────────────────────────

    def _update_battery(self, dt, keys):
        b = self._battery
        if b['phase'] == 'result':
            b['result_t'] -= dt
            if b['result_t'] <= 0:
                success = b['result'] == 'success'
                self._exit_panel()
                if success:
                    self.score += 1
                    self._notify("Battery banks charged.")
                else:
                    self.incident_count += 1
                    self._notify("Battery bank depleted!")
            return

        engine_ok = b['alternator_ok']
        for i in range(2):
            # Alternator cuts out near tgt_max (float-charge behaviour — no overcharge)
            alt_active = engine_ok and b['banks'][i] < b['tgt_max'] - 0.04
            alt_rate = b['ch_rates'][0][i] if alt_active else 0.0
            other_charge = sum(b['ch_rates'][j][i] * b['chargers'][j] for j in range(1, 3))
            net = alt_rate + other_charge - b['drain'][i]
            b['banks'][i] = max(0.0, min(1.0, b['banks'][i] + net * dt))

        if any(b['banks'][i] < 0.05 for i in range(2)):
            b['phase'] = 'result'; b['result'] = 'fail'; b['result_t'] = 2.5
            self.incident_count += 1
            self.incidents.append('battery_depleted')
            return

        both_in = all(b['tgt_min'] <= b['banks'][i] <= b['tgt_max'] for i in range(2))
        if both_in:
            b['hold_t'] += dt
        else:
            b['hold_t'] = max(0.0, b['hold_t'] - dt * 0.8)

        if b['hold_t'] >= b['hold_needed']:
            b['phase'] = 'result'; b['result'] = 'success'; b['result_t'] = 2.0
            self.score += 1

    # ── Bilge update ──────────────────────────────────────────────────────────

    def _update_bilge(self, dt, keys):
        bl = self._bilge
        if bl['phase'] == 'result':
            bl['result_t'] -= dt
            if bl['result_t'] <= 0:
                success = bl['result'] == 'success'
                self._exit_panel()
                if success:
                    self.score += 1
                    self._notify("Bilge under control.")
                else:
                    self.incident_count += 1
                    self.incidents.append('bilge_overflow')
                    self._notify("Bilge overflow!")
            return

        for i in range(4):
            bl['levels'][i] = min(1.0, bl['levels'][i] + bl['ingress'][i] * dt)
            if bl['pump_t'][i] > 0:
                bl['levels'][i] = max(0.0, bl['levels'][i] - bl['pump_rate'] * dt)
                bl['pump_t'][i] -= dt

        if any(bl['levels'][i] >= bl['danger'] for i in range(4)):
            bl['phase'] = 'result'; bl['result'] = 'fail'; bl['result_t'] = 2.5
            self.incident_count += 1
            self.incidents.append('bilge_overflow')
            return

        bl['survive_t'] += dt
        if bl['survive_t'] >= bl['survive_needed']:
            bl['phase'] = 'result'; bl['result'] = 'success'; bl['result_t'] = 2.0
            self.score += 1

    # ── Watermaker update ─────────────────────────────────────────────────────

    def _update_watermaker(self, dt, keys):
        wm = self._wmaker
        if wm['phase'] == 'result':
            wm['result_t'] -= dt
            if wm['result_t'] <= 0:
                success = wm['result'] == 'success'
                self._exit_panel()
                if success:
                    self.score += 1
                    self._notify("Watermaker calibrated.")
                else:
                    self.incident_count += 1
                    self.incidents.append('watermaker_burst')
                    self._notify("Membrane burst!")
            return

        if keys[pygame.K_q]:
            wm['fp'] = min(1.0, wm['fp'] + 0.40 * dt)
        if keys[pygame.K_w]:
            wm['fp'] = max(0.0, wm['fp'] - 0.40 * dt)
        if keys[pygame.K_e]:
            wm['fr'] = min(1.0, wm['fr'] + 0.40 * dt)
        if keys[pygame.K_r]:
            wm['fr'] = max(0.0, wm['fr'] - 0.40 * dt)

        psi      = 0.80 * wm['fp'] + 0.15 * wm['fr']
        salinity = 1.0  - 0.60 * wm['fp'] - 0.25 * wm['fr']
        recovery = 0.40 * wm['fp'] + 0.45 * wm['fr']
        filt     = 0.30 * wm['fp'] + 0.55 * wm['fr']

        if psi > 0.86:
            wm['phase'] = 'result'; wm['result'] = 'fail'; wm['result_t'] = 2.5
            self.incident_count += 1
            self.incidents.append('watermaker_burst')
            return

        all_in = (0.45 <= psi <= 0.75 and
                  0.15 <= salinity <= 0.55 and
                  0.30 <= recovery <= 0.65 and
                  0.25 <= filt <= 0.60)
        if all_in:
            wm['hold_t'] += dt
        else:
            wm['hold_t'] = max(0.0, wm['hold_t'] - dt * 0.5)

        if wm['hold_t'] >= wm['hold_needed']:
            wm['phase'] = 'result'; wm['result'] = 'success'; wm['result_t'] = 2.0
            self.score += 1

    # ── Ventilation update ────────────────────────────────────────────────────

    def _update_vent(self, dt, keys):
        v = self._vent
        if v['phase'] == 'result':
            v['result_t'] -= dt
            if v['result_t'] <= 0:
                success = v['result'] == 'success'
                self._exit_panel()
                if success:
                    self.score += 1
                    self._notify("Ventilation nominal.")
                else:
                    self.incident_count += 1
                    self.incidents.append('vent_overheat')
                    self._notify("Zone overheated!")
            return

        if keys[pygame.K_q]:
            v['fans'][0] = min(1.0, v['fans'][0] + 1.2 * dt)
        if keys[pygame.K_w]:
            v['fans'][0] = max(0.0, v['fans'][0] - 1.2 * dt)
        if keys[pygame.K_e]:
            v['fans'][1] = min(1.0, v['fans'][1] + 1.2 * dt)
        if keys[pygame.K_r]:
            v['fans'][1] = max(0.0, v['fans'][1] - 1.2 * dt)
        if keys[pygame.K_d]:
            v['fans'][2] = min(1.0, v['fans'][2] + 1.2 * dt)
        if keys[pygame.K_f]:
            v['fans'][2] = max(0.0, v['fans'][2] - 1.2 * dt)

        for z in range(4):
            cooling = sum(v['fans'][f] * v['cool_mat'][z][f] for f in range(3))
            v['temps'][z] = max(0.0, min(1.0,
                v['temps'][z] + (v['heat_gen'][z] - cooling) * dt))

        if any(v['temps'][z] >= 0.96 for z in range(4)):
            v['phase'] = 'result'; v['result'] = 'fail'; v['result_t'] = 2.5
            self.incident_count += 1
            self.incidents.append('vent_overheat')
            return

        all_cool = all(v['temps'][z] < v['tgt_max'] for z in range(4))
        if all_cool:
            v['hold_t'] += dt
        else:
            v['hold_t'] = max(0.0, v['hold_t'] - dt * 0.5)

        if v['hold_t'] >= v['hold_needed']:
            v['phase'] = 'result'; v['result'] = 'success'; v['result_t'] = 2.0
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
        elif pid == 'battery':    self._draw_battery()
        elif pid == 'bilge':      self._draw_bilge()
        elif pid == 'watermaker': self._draw_watermaker()
        elif pid == 'vent':       self._draw_vent()

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
        self._panel_bg("HYDRAULIC SYSTEM", "Vent rising pressure — [1] [2] [3] [4]")
        h   = self._hydro
        pw  = self.PLAY_W
        cx  = pw // 2

        col_labels = ['PORT STEER', 'STBD STEER', 'LOCK RAM', 'AUX HYD']
        col_keys   = ['[1]', '[2]', '[3]', '[4]']
        col_x_base = cx - 260
        col_spacing = 140
        bar_w, bar_h = 60, 220
        bar_top = 155

        for i in range(4):
            bx = col_x_base + i * col_spacing
            val = h['cols'][i]

            # Background track
            pygame.draw.rect(self.screen, (22, 26, 36),
                             (bx, bar_top, bar_w, bar_h), border_radius=4)

            # Colour zone bands (green/yellow/red)
            green_h  = int(0.75 * bar_h)
            yellow_h = int(0.15 * bar_h)
            red_h    = bar_h - green_h - yellow_h
            pygame.draw.rect(self.screen, (28, 80, 38),
                             (bx, bar_top + bar_h - green_h, bar_w, green_h), border_radius=4)
            pygame.draw.rect(self.screen, (80, 72, 22),
                             (bx, bar_top + red_h, bar_w, yellow_h))
            pygame.draw.rect(self.screen, (80, 26, 22),
                             (bx, bar_top, bar_w, red_h), border_radius=4)

            # Filled column
            fill_h = int(val * bar_h)
            if val < 0.75:
                fill_col = (42, 195, 72)
            elif val < 0.90:
                fill_col = (225, 175, 38)
            else:
                fill_col = (228, 52, 38)

            # Bleed flash overlay
            if h['bleed_anim'][i] > 0:
                a = int(h['bleed_anim'][i] * 120)
                flash = pygame.Surface((bar_w, bar_h), pygame.SRCALPHA)
                flash.fill((80, 220, 120, a))
                self.screen.blit(flash, (bx, bar_top))

            pygame.draw.rect(self.screen, fill_col,
                             (bx, bar_top + bar_h - fill_h, bar_w, fill_h), border_radius=4)
            pygame.draw.rect(self.screen, (58, 66, 80), (bx, bar_top, bar_w, bar_h), 1, border_radius=4)

            # Percent readout
            pct = self.fnt_sm.render(f"{int(val * 100)}%", True, self.C_TEXT)
            self.screen.blit(pct, (bx + bar_w // 2 - pct.get_width() // 2, bar_top - 20))

            # Key label (button)
            btn_col = (38, 148, 62) if h['bleed_anim'][i] > 0.5 else (30, 38, 52)
            pygame.draw.rect(self.screen, btn_col,
                             (bx + 4, bar_top + bar_h + 12, bar_w - 8, 30), border_radius=4)
            pygame.draw.rect(self.screen, (60, 80, 100),
                             (bx + 4, bar_top + bar_h + 12, bar_w - 8, 30), 1, border_radius=4)
            kl = self.fnt_md.render(col_keys[i], True, (210, 225, 240))
            self.screen.blit(kl, (bx + bar_w // 2 - kl.get_width() // 2,
                                   bar_top + bar_h + 18))

            # System name
            nl = self.fnt_sm.render(col_labels[i], True, self.C_DIM)
            self.screen.blit(nl, (bx + bar_w // 2 - nl.get_width() // 2,
                                   bar_top + bar_h + 50))

        # Survive-time progress bar
        prog = min(1.0, h['survive_t'] / h['survive_needed'])
        self._bar(cx - 165, 510, 330, 14, prog, "Hold pressure stable...", (65, 122, 188))
        rem = max(0.0, h['survive_needed'] - h['survive_t'])
        tl = self.fnt_sm.render(f"{rem:.1f}s remaining", True, self.C_DIM)
        self.screen.blit(tl, (cx - tl.get_width() // 2, 528))

        if h['phase'] == 'result':
            self._result_overlay(h['result'] == 'success',
                                  "PRESSURE STABLE" if h['result'] == 'success' else "PRESSURE LOST")

    # ── Battery panel ─────────────────────────────────────────────────────────

    def _draw_battery(self):
        engine_ok = self._battery['alternator_ok']
        subtitle = "Solar [2] · Shore Pwr [3]" if not engine_ok else "Alternator charging — engine running normally"
        self._panel_bg("BATTERY MANAGEMENT", subtitle)
        b  = self._battery
        pw = self.PLAY_W
        cx = pw // 2

        # Alternator status banner
        if not engine_ok:
            banner_col = (180, 40, 40)
            banner_surf = self.fnt_sm.render("  ALTERNATOR OFFLINE — ENGINE FAULT  ", True, (255, 220, 80))
            bw = banner_surf.get_width() + 16
            pygame.draw.rect(self.screen, banner_col,
                             (cx - bw // 2 - 4, 108, bw + 8, 26), border_radius=4)
            self.screen.blit(banner_surf, (cx - bw // 2, 113))
        else:
            ok_surf = self.fnt_sm.render("  ALTERNATOR OK  ", True, (80, 220, 100))
            ow = ok_surf.get_width() + 16
            pygame.draw.rect(self.screen, (20, 60, 30),
                             (cx - ow // 2 - 4, 108, ow + 8, 26), border_radius=4)
            self.screen.blit(ok_surf, (cx - ow // 2, 113))

        # 2 large vertical battery bars
        bar_w, bar_h = 70, 210
        bar_tops = [cx - 180, cx - 60]
        for i in range(2):
            bx = bar_tops[i]
            by = 155
            val = b['banks'][i]
            in_zone = b['tgt_min'] <= val <= b['tgt_max']
            col = self.C_OK if in_zone else (self.C_WARN if val > 0.05 else self.C_ALARM)
            self._bar(bx, by, bar_w, bar_h, val, b['labels'][i], col, vertical=True)

            # tgt_min / tgt_max lines
            for tgt, tc in [(b['tgt_min'], (42, 195, 72)), (b['tgt_max'], (42, 195, 72))]:
                ty = by + int((1.0 - tgt) * bar_h)
                pygame.draw.line(self.screen, tc, (bx - 4, ty), (bx + bar_w + 4, ty), 2)

            # Net rate readout
            alt_rate = b['ch_rates'][0][i] if engine_ok else 0.0
            other = sum(b['ch_rates'][j][i] * b['chargers'][j] for j in range(1, 3))
            net = alt_rate + other - b['drain'][i]
            rate_col = self.C_OK if net >= 0 else self.C_WARN
            rl = self.fnt_sm.render(f"{'+'if net>=0 else ''}{net*100:.1f}%/s", True, rate_col)
            self.screen.blit(rl, (bx + bar_w // 2 - rl.get_width() // 2, by + bar_h + 4))

        # Alternator status (read-only indicator) + 2 toggleable chargers
        alt_col = self.C_OK if engine_ok else self.C_ALARM
        alt_lbl = self.fnt_sm.render("ALTERNATOR", True, alt_col)
        alt_state = self.fnt_sm.render("ONLINE" if engine_ok else "FAULT", True, alt_col)
        ax = cx + 40
        pygame.draw.rect(self.screen, (28, 34, 48), (ax, 390, 120, 52), border_radius=6)
        pygame.draw.rect(self.screen, alt_col, (ax, 390, 120, 52), 2, border_radius=6)
        self.screen.blit(alt_lbl, (ax + 60 - alt_lbl.get_width() // 2, 400))
        self.screen.blit(alt_state, (ax + 60 - alt_state.get_width() // 2, 416))

        # Charger toggles [2] SOLAR, [3] SHORE PWR  (only useful when engine offline)
        for idx, j in enumerate([1, 2]):
            bx = cx + 40 + (idx + 1) * 140
            self._btn(bx, 390, 120, 52, f'[{j+1}]', b['ch_labels'][j], b['chargers'][j])

        # Hold progress bar
        prog = min(1.0, b['hold_t'] / b['hold_needed'])
        self._bar(cx - 165, 500, 330, 14, prog, "Both banks in target zone...", (42, 188, 82))

        if b['phase'] == 'result':
            self._result_overlay(b['result'] == 'success',
                                  "BANKS CHARGED" if b['result'] == 'success' else "BATTERY DEAD")

    # ── Bilge panel ───────────────────────────────────────────────────────────

    def _draw_bilge(self):
        self._panel_bg("BILGE PUMPS", "Pump each compartment — [1] [2] [3] [4]")
        bl  = self._bilge
        pw  = self.PLAY_W
        cx  = pw // 2

        bar_w, bar_h = 60, 220
        bar_top = 155
        col_x_base  = cx - 260
        col_spacing = 140
        keys = pygame.key.get_pressed()

        for i in range(4):
            bx = col_x_base + i * col_spacing
            val = bl['levels'][i]

            # Background track
            pygame.draw.rect(self.screen, (22, 26, 36),
                             (bx, bar_top, bar_w, bar_h), border_radius=4)

            # Fill colour
            if val < 0.80:
                fill_col = (42, 148, 188)
            elif val < 0.88:
                fill_col = (225, 175, 38)
            else:
                fill_col = (228, 52, 38)

            fill_h = int(val * bar_h)
            pygame.draw.rect(self.screen, fill_col,
                             (bx, bar_top + bar_h - fill_h, bar_w, fill_h), border_radius=4)

            # Pump active animation
            if bl['pump_t'][i] > 0:
                a = int(abs(math.sin(pygame.time.get_ticks() * 0.008)) * 100)
                flash = pygame.Surface((bar_w, bar_h), pygame.SRCALPHA)
                flash.fill((80, 180, 220, a))
                self.screen.blit(flash, (bx, bar_top))
                arrow = self.fnt_md.render("▼", True, (80, 200, 240))
                self.screen.blit(arrow, (bx + bar_w // 2 - arrow.get_width() // 2,
                                          bar_top + bar_h // 2 - 10))

            pygame.draw.rect(self.screen, (58, 66, 80),
                             (bx, bar_top, bar_w, bar_h), 1, border_radius=4)

            # Percent readout
            pct = self.fnt_sm.render(f"{int(val * 100)}%", True, self.C_TEXT)
            self.screen.blit(pct, (bx + bar_w // 2 - pct.get_width() // 2, bar_top - 20))

            # Key button
            btn_col = (38, 148, 62) if bl['pump_t'][i] > 0 else (30, 38, 52)
            pygame.draw.rect(self.screen, btn_col,
                             (bx + 4, bar_top + bar_h + 12, bar_w - 8, 30), border_radius=4)
            pygame.draw.rect(self.screen, (60, 80, 100),
                             (bx + 4, bar_top + bar_h + 12, bar_w - 8, 30), 1, border_radius=4)
            kl = self.fnt_md.render(f"[{i+1}]", True, (210, 225, 240))
            self.screen.blit(kl, (bx + bar_w // 2 - kl.get_width() // 2,
                                   bar_top + bar_h + 18))

            # Zone label
            nl = self.fnt_sm.render(bl['labels'][i], True, self.C_DIM)
            self.screen.blit(nl, (bx + bar_w // 2 - nl.get_width() // 2,
                                   bar_top + bar_h + 50))

        # Survive-time progress bar
        prog = min(1.0, bl['survive_t'] / bl['survive_needed'])
        self._bar(cx - 165, 510, 330, 14, prog, "Survive without overflow...", (65, 122, 188))
        rem = max(0.0, bl['survive_needed'] - bl['survive_t'])
        tl = self.fnt_sm.render(f"{rem:.1f}s remaining", True, self.C_DIM)
        self.screen.blit(tl, (cx - tl.get_width() // 2, 528))

        if bl['phase'] == 'result':
            self._result_overlay(bl['result'] == 'success',
                                  "BILGE CLEAR" if bl['result'] == 'success' else "FLOODING!")

    # ── Watermaker panel ──────────────────────────────────────────────────────

    def _draw_watermaker(self):
        self._panel_bg("WATERMAKER (RO)", "Feed pressure Q/W · Flow rate E/R")
        wm  = self._wmaker
        pw  = self.PLAY_W
        cx  = pw // 2
        keys = pygame.key.get_pressed()

        psi      = 0.80 * wm['fp'] + 0.15 * wm['fr']
        salinity = 1.0  - 0.60 * wm['fp'] - 0.25 * wm['fr']
        recovery = 0.40 * wm['fp'] + 0.45 * wm['fr']
        filt     = 0.30 * wm['fp'] + 0.55 * wm['fr']

        out_vals   = [psi, salinity, recovery, filt]
        out_labels = ['MEMBRANE PSI', 'SALINITY', 'RECOVERY %', 'FILTER LOAD']
        out_ranges = [(0.45, 0.75), (0.15, 0.55), (0.30, 0.65), (0.25, 0.60)]

        # Left half — 2 vertical sliders (fp, fr)
        slider_configs = [
            (cx - 310, 'FEED PRESS', wm['fp'], 'fp', '[Q]', '[W]'),
            (cx - 190, 'FLOW RATE',  wm['fr'], 'fr', '[E]', '[R]'),
        ]
        sl_h = 200
        sl_y = 155
        for sx, slabel, sval, _, up_k, dn_k in slider_configs:
            pygame.draw.rect(self.screen, (24, 28, 38), (sx, sl_y, 28, sl_h), border_radius=4)
            knob_y = sl_y + int((1.0 - sval) * (sl_h - 20))
            pygame.draw.rect(self.screen, (82, 148, 102), (sx - 6, knob_y, 40, 20), border_radius=4)
            pygame.draw.rect(self.screen, (115, 198, 140), (sx - 6, knob_y, 40, 20), 2, border_radius=4)
            lbl = self.fnt_sm.render(slabel, True, self.C_DIM)
            self.screen.blit(lbl, (sx + 14 - lbl.get_width() // 2, sl_y - 18))
            vl = self.fnt_sm.render(f"{int(sval*100)}%", True, self.C_TEXT)
            self.screen.blit(vl, (sx + 14 - vl.get_width() // 2, sl_y + sl_h + 4))
            kh = self.fnt_sm.render(f"{up_k} up  {dn_k} dn", True, self.C_DIM)
            self.screen.blit(kh, (sx + 14 - kh.get_width() // 2, sl_y + sl_h + 22))

        # Right half — 4 horizontal output bars
        bar_x = cx - 80
        bar_w = 290
        bar_h_each = 28
        bar_spacing = 62
        bar_y0 = 155

        for i, (oval, olbl, (olo, ohi)) in enumerate(zip(out_vals, out_labels, out_ranges)):
            by = bar_y0 + i * bar_spacing
            in_range = olo <= oval <= ohi
            col = self.C_OK if in_range else self.C_ALARM
            self._bar(bar_x, by, bar_w, bar_h_each, oval, olbl, col)

            # Target zone overlay
            t1 = bar_x + int(olo * bar_w)
            t2 = bar_x + int(ohi * bar_w)
            tz = pygame.Surface((t2 - t1, bar_h_each), pygame.SRCALPHA)
            tz.fill((42, 195, 72, 45))
            self.screen.blit(tz, (t1, by))
            pygame.draw.line(self.screen, (42, 195, 72), (t1, by - 2), (t1, by + bar_h_each + 2), 1)
            pygame.draw.line(self.screen, (42, 195, 72), (t2, by - 2), (t2, by + bar_h_each + 2), 1)

            vl = self.fnt_sm.render(f"{int(oval*100)}%", True, self.C_TEXT)
            self.screen.blit(vl, (bar_x + bar_w + 6, by + 6))

        # Hold progress bar
        prog = min(1.0, wm['hold_t'] / wm['hold_needed'])
        self._bar(cx - 165, 510, 330, 14, prog, "Hold all outputs in range...", (42, 188, 82))

        if wm['phase'] == 'result':
            self._result_overlay(wm['result'] == 'success',
                                  "SYSTEM CALIBRATED" if wm['result'] == 'success' else "MEMBRANE BURST")

    # ── Ventilation panel ─────────────────────────────────────────────────────

    def _draw_vent(self):
        self._panel_bg("VENTILATION", "Fan speeds: Q/W · E/R · D/F")
        v   = self._vent
        pw  = self.PLAY_W
        cx  = pw // 2
        keys = pygame.key.get_pressed()

        fan_labels   = ['FAN 1 (ENG/WHL)', 'FAN 2 (BILGE/CAB)', 'FAN 3 (ENG/WHL)']
        fan_key_hint = ['Q+ / W-', 'E+ / R-', 'D+ / F-']

        # Top half — 3 fan speed bars (horizontal)
        fan_y0 = 145
        fan_bw = 320
        fan_bh = 22
        fan_spacing = 52
        fan_x = cx - fan_bw // 2

        for j in range(3):
            fy = fan_y0 + j * fan_spacing
            speed = v['fans'][j]
            fan_col = (82, 148, 188) if speed > 0.1 else (48, 55, 70)
            self._bar(fan_x, fy, fan_bw, fan_bh, speed, fan_labels[j], fan_col)
            kh = self.fnt_sm.render(fan_key_hint[j], True, self.C_DIM)
            self.screen.blit(kh, (fan_x + fan_bw + 8, fy + 4))
            sv = self.fnt_sm.render(f"{int(speed*100)}%", True, self.C_TEXT)
            self.screen.blit(sv, (fan_x - sv.get_width() - 8, fy + 4))

        # Bottom half — 4 zone temp bars (vertical)
        bar_w, bar_h = 55, 145
        bar_top = 330
        tz_x_base = cx - 220
        tz_spacing = 120

        for z in range(4):
            bx = tz_x_base + z * tz_spacing
            temp = v['temps'][z]
            if temp < 0.55:
                tc = (42, 195, 72)
            elif temp < 0.72:
                tc = (225, 175, 38)
            else:
                tc = (228, 52, 38)
            self._bar(bx, bar_top, bar_w, bar_h, temp, v['labels'][z], tc, vertical=True)

            # tgt_max line
            ty = bar_top + int((1.0 - v['tgt_max']) * bar_h)
            pygame.draw.line(self.screen, (225, 175, 38), (bx - 3, ty), (bx + bar_w + 3, ty), 2)

            tv = self.fnt_sm.render(f"{int(temp*100)}%", True, self.C_TEXT)
            self.screen.blit(tv, (bx + bar_w // 2 - tv.get_width() // 2, bar_top - 20))

        # Hold progress bar
        prog = min(1.0, v['hold_t'] / v['hold_needed'])
        self._bar(cx - 165, 502, 330, 14, prog, "Keep all zones cool...", (42, 188, 82))

        if v['phase'] == 'result':
            self._result_overlay(v['result'] == 'success',
                                  "TEMPS NOMINAL" if v['result'] == 'success' else "ZONE OVERHEATED")

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
        snames = [
            ('diesel',     'Diesel'),
            ('electrical', 'Electrical'),
            ('water',      'Water Sys'),
            ('hydraulic',  'Hydraulic'),
            ('battery',    'Battery'),
            ('bilge',      'Bilge'),
            ('watermaker', 'Watermaker'),
            ('vent',       'Ventilation'),
        ]
        for sid, sname in snames:
            alarm = self._alarms[sid]
            col   = self.C_ALARM if alarm else self.C_OK
            row(f"{sname}: {'ALARM' if alarm else 'OK'}", col=col)

        y = self.HEIGHT - 88
        row("WASD      Move",       col=self.C_DIM)
        row("[E] Hold  Enter panel", col=self.C_DIM)
        row("[ESC]     Menu",        col=self.C_DIM)