import pygame
import sys
import math
import random
from lock_and_dam import LockAndDam
from boat import Yacht, Barge, Kayak
from waterway import Canal


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
        self.ttl       = None        # frames until removal after crash


# ── Visualizer ────────────────────────────────────────────────────────────────

class LockDamVisualizer:

    SURGE_THRESHOLD = 2.0   # metres; opening gate above this differential → incident

    def __init__(self):
        pygame.init()
        self.width  = 1200
        self.height = 800
        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption("Lock & Dam Operator")
        self.clock  = pygame.time.Clock()
        self.view_mode = "shore"   # "shore" | "lock"
        self.time = 0.0

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
        }

        # ── Simulation ────────────────────────────────────────────────────────
        self.lock_dam  = LockAndDam("Main Lock", 10, 0)
        self.canal     = Canal("Main Canal")
        self.agents    = []

        self.lock_start = 500    # upstream gate (sim coords)
        self.lock_end   = 700    # downstream gate

        # ── Shore-view layout constants ───────────────────────────────────────
        # sim x ∈ [0, 1000]  →  screen x ∈ [50, 1150]
        self._sx_offset   = 50
        self._sx_scale    = (self.width - 100) / 1000.0
        self._wl_base     = 430   # screen-y at water level 0 m
        self._wl_scale    = 5     # px per metre (higher water = lower y)
        self._water_bot_y = 540

        # ── Gameplay ──────────────────────────────────────────────────────────
        self.score        = 0
        self.incidents    = []    # list of message strings
        self.flash_timer  = 0    # red-flash countdown (frames)
        self.flash_color  = self.RED

        # ── Spawning ──────────────────────────────────────────────────────────
        self.spawn_timer     = 0
        self.spawn_interval  = 300   # frames (~5 s at 60 fps)
        self._boat_counter   = 0
        self._next_direction = 1     # alternates each spawn

        # Fonts
        self.fnt_md = pygame.font.Font(None, 28)
        self.fnt_sm = pygame.font.Font(None, 22)

        # Seed two initial boats
        self._spawn_boat( 1, 150)
        self._spawn_boat(-1, 880)

    # ── Coordinate helpers ────────────────────────────────────────────────────

    def _sx(self, sim_x):
        """Simulation x → screen x."""
        return int(self._sx_offset + sim_x * self._sx_scale)

    def _wy(self, level):
        """Water level (m) → screen y (surface)."""
        return int(self._wl_base - level * self._wl_scale)

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

    def _in_lock(self, boat):
        return boat.position < self.lock_end and boat.position + boat.length > self.lock_start

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
        self._gradient_rect(self.SKY_TOP, self.SKY_BOTTOM, (0, 0, self.width, bottom_y))

    def _draw_water_band(self, x, y, w):
        h = self._water_bot_y - y
        if h <= 0 or w <= 0:
            return
        self._gradient_rect(self.WATER_TOP, self.WATER_BOT, (x, y, w, h))
        pygame.draw.line(self.screen, self.WATER_SHIMMER, (x, y), (x + w, y), 2)

    def _draw_bank_strip(self, x, top_y, w):
        pygame.draw.rect(self.screen, self.DIRT,       (x, top_y - 12, w, 12))
        pygame.draw.rect(self.screen, self.GRASS,      (x, top_y - 26, w, 14))
        pygame.draw.rect(self.screen, self.GRASS_DARK, (x, top_y - 38, w, 12))

    def _draw_channel_floor(self, x, w):
        pygame.draw.rect(self.screen, self.DIRT,  (x, self._water_bot_y,      w, 16))
        pygame.draw.rect(self.screen, self.GRASS, (x, self._water_bot_y + 16, w, 16))

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

        # Upstream channel
        self._draw_water_band(0, up_y, lk_sx)
        self._lane_divider(0, lk_sx, up_y)
        self._draw_bank_strip(0, up_y, lk_sx)
        self._draw_channel_floor(0, lk_sx)
        t = self.time * 1.8
        for wx in range(0, lk_sx - 10, 35):
            oy = int(3 * math.sin(t + wx * 0.06))
            pygame.draw.line(self.screen, self.WATER_SHIMMER,
                             (wx + 5, up_y + oy), (wx + 25, up_y + oy), 1)

        # Downstream channel
        self._draw_water_band(lk_ex, dn_y, self.width - lk_ex)
        self._lane_divider(lk_ex, self.width - lk_ex, dn_y)
        self._draw_bank_strip(lk_ex, dn_y, self.width - lk_ex)
        self._draw_channel_floor(lk_ex, self.width - lk_ex)
        for wx in range(lk_ex + 5, self.width - 10, 35):
            oy = int(2 * math.sin(t + wx * 0.06))
            pygame.draw.line(self.screen, self.WATER_SHIMMER,
                             (wx, dn_y + oy), (wx + 20, dn_y + oy), 1)

        # Lock chamber — water fill
        inner_x = lk_sx + wall_t
        inner_w = lk_w - 2 * wall_t
        self._gradient_rect(self.LOCK_WATER_TOP, self.WATER_BOT,
                            (inner_x, lk_y, inner_w, self._water_bot_y - lk_y))
        pygame.draw.line(self.screen, self.WATER_SHIMMER,
                         (inner_x, lk_y), (inner_x + inner_w, lk_y), 2)
        self._lane_divider(inner_x, inner_w, lk_y)

        # Concrete cap and walls
        pygame.draw.rect(self.screen, self.CONCRETE,
                         (lk_sx, wall_top, lk_w, lk_y - wall_top))
        for cy in range(wall_top + 10, lk_y, 14):
            pygame.draw.line(self.screen, self.CONCRETE_DARK,
                             (lk_sx, cy), (lk_sx + lk_w, cy), 1)
        pygame.draw.rect(self.screen, self.CONCRETE,
                         (lk_sx, wall_top, wall_t, self._water_bot_y - wall_top))
        pygame.draw.rect(self.screen, self.CONCRETE,
                         (lk_ex - wall_t, wall_top, wall_t, self._water_bot_y - wall_top))
        pygame.draw.rect(self.screen, self.CONCRETE_DARK,
                         (inner_x, self._water_bot_y, inner_w, 10))

        # Gates
        self._draw_miter_gate(lk_sx + wall_t, wall_top, self._water_bot_y,
                              self.lock_dam.upstream_gates_open, faces_right=True)
        self._draw_miter_gate(lk_ex - wall_t, wall_top, self._water_bot_y,
                              self.lock_dam.downstream_gates_open, faces_right=False)

        # Boats
        for ag in self.agents:
            if ag.state != "done":
                self._draw_boat_shore(ag, up_y, dn_y, lk_y, lk_sx, lk_ex)

        # Water level labels
        self._wl_label(lk_sx // 2, up_y, "Upstream", self.lock_dam.upstream_level)
        self._wl_label(lk_ex + (self.width - lk_ex) // 2, dn_y,
                       "Downstream", self.lock_dam.downstream_level)
        self._wl_label(lk_sx + lk_w // 2, lk_y,
                       "Chamber", self.lock_dam.lock_chamber_level)

    def _draw_miter_gate(self, gate_x, wall_top, floor_y, is_open, faces_right):
        mid_y  = (wall_top + floor_y) // 2
        color  = self.GREEN if is_open else self.RED
        shadow = (max(0, color[0] - 60), max(0, color[1] - 60), max(0, color[2] - 60))
        leaf_w = 12
        if is_open:
            offset = 20 if faces_right else -20
            pts_u = [(gate_x, wall_top), (gate_x + offset, wall_top + 8),
                     (gate_x + offset, mid_y - 4), (gate_x, mid_y)]
            pts_l = [(gate_x, mid_y), (gate_x + offset, mid_y + 4),
                     (gate_x + offset, floor_y - 8), (gate_x, floor_y)]
        else:
            apex_off = 10 if faces_right else -10
            ax = gate_x + apex_off
            pts_u = [(gate_x, wall_top), (gate_x + leaf_w // 2, wall_top),
                     (ax + leaf_w // 2, mid_y), (ax, mid_y)]
            pts_l = [(ax, mid_y), (ax + leaf_w // 2, mid_y),
                     (gate_x + leaf_w // 2, floor_y), (gate_x, floor_y)]
        for pts in (pts_u, pts_l):
            pygame.draw.polygon(self.screen, color, pts)
            pygame.draw.polygon(self.screen, shadow, pts, 2)

    def _draw_boat_shore(self, ag, up_y, dn_y, lk_y, lk_sx, lk_ex):
        boat = ag.boat
        bx   = self._sx(boat.position)
        bw   = max(self._sx(boat.position + boat.length) - bx, 8)

        surf_y = up_y if bx < lk_sx else (dn_y if bx > lk_ex else lk_y)
        hull_y = self._lane_y(ag, surf_y)   # vertical centre for this lane
        bh     = max(int(boat.beam * 2.2), 8)   # keep hull within lane bounds

        if ag.state == "crashed":
            hull_col = self.RED
            outline  = (140, 25, 25)
        else:
            hull_col = self._boat_color(boat)
            outline  = self.DARK_GRAY

        # Trapezoid hull — bow tapers to leading edge
        bow_cut = max(4, bw // 5)
        ty = hull_y - bh // 2
        by = hull_y + bh // 2
        if ag.direction == 1:
            pts = [(bx, ty), (bx + bw - bow_cut, ty),
                   (bx + bw, hull_y),
                   (bx + bw - bow_cut, by), (bx, by)]
        else:
            pts = [(bx + bow_cut, ty), (bx + bw, ty),
                   (bx, hull_y),
                   (bx + bw, by), (bx + bow_cut, by)]
        pygame.draw.polygon(self.screen, hull_col, pts)
        pygame.draw.polygon(self.screen, outline,  pts, 2)

        pygame.draw.line(self.screen, self.WATER_SHIMMER,
                         (bx - 5, hull_y), (bx + bw + 5, hull_y), 1)

        lbl = self.fnt_sm.render(boat.name, True, self.BLACK)
        tag = pygame.Surface((lbl.get_width() + 6, lbl.get_height() + 3), pygame.SRCALPHA)
        tag.fill((255, 255, 255, 190))
        self.screen.blit(tag, (bx,     ty - lbl.get_height() - 6))
        self.screen.blit(lbl, (bx + 3, ty - lbl.get_height() - 5))

    def _wl_label(self, cx, surf_y, title, level):
        t1 = self.fnt_sm.render(title, True, self.WHITE)
        t2 = self.fnt_sm.render(f"{level:.1f} m", True, self.WATER_SHIMMER)
        self.screen.blit(t1, (cx - t1.get_width() // 2, surf_y - 36))
        self.screen.blit(t2, (cx - t2.get_width() // 2, surf_y - 20))

    # ── Lock perspective view ─────────────────────────────────────────────────

    def draw_lock_view(self):
        """View from the lock house looking along the channel."""
        t   = self.time
        cam = (self.lock_start + self.lock_end) / 2   # camera sim-position

        # Sky
        self._gradient_rect((75, 130, 210), (155, 195, 240),
                            (0, 0, self.width, 400))
        for ci, (cx, cy, cr) in enumerate([(180, 75, 55), (480, 55, 75),
                                            (820, 90, 45), (1050, 70, 60)]):
            ox = int(18 * math.sin(t * 0.25 + ci * 1.4))
            pygame.draw.ellipse(self.screen, (220, 230, 248),
                                (cx + ox - cr, cy - 18, cr * 2, 36))
            pygame.draw.ellipse(self.screen, (240, 245, 255),
                                (cx + ox - cr + 12, cy - 28, int(cr * 1.6), 36))

        horizon = 400
        pygame.draw.line(self.screen, (195, 215, 245), (0, horizon), (self.width, horizon), 2)
        self._gradient_rect((50, 128, 198), (18, 65, 145),
                            (0, horizon, self.width, self.height - horizon))

        for row in range(6):
            ry = horizon + 18 + row * 38
            for wx in range(0, self.width, int(38 + row * 18)):
                oy = int(4 * math.sin(t * 2.2 + wx * 0.04 + row))
                seg = int(14 + row * 8)
                pygame.draw.line(self.screen, (75, 155, 215),
                                 (wx, ry + oy), (wx + seg, ry + oy), 1)

        for bx, bw in [(0, 75), (self.width - 75, 75)]:
            pygame.draw.rect(self.screen, self.GRASS, (bx, horizon - 35, bw, 38))
            pygame.draw.rect(self.screen, self.DIRT,  (bx, horizon + 3,  bw, 22))

        # Boats in perspective
        visible = sorted(
            [ag for ag in self.agents if ag.state != "done"],
            key=lambda a: -abs((a.boat.position + a.boat.length / 2) - cam)
        )
        for ag in visible:
            boat = ag.boat
            dist = (boat.position + boat.length / 2) - cam
            if abs(dist) > 520:
                continue
            scale = max(0.08, 1 - abs(dist) / 520)
            scx   = self.width // 2 + int(dist * 2.5 * scale)
            bw2   = max(10, int(boat.length * scale * 2.8))
            bh2   = max(6,  int(boat.beam   * scale * 8))
            bx2   = scx - bw2 // 2
            by2   = horizon - bh2
            bow   = max(3, bw2 // 6)
            hull  = self.RED if ag.state == "crashed" else self._boat_color(boat)
            if ag.direction == 1:
                pts = [(bx2, by2), (bx2 + bw2 - bow, by2),
                       (bx2 + bw2, by2 + bh2 // 2),
                       (bx2 + bw2 - bow, by2 + bh2), (bx2, by2 + bh2)]
            else:
                pts = [(bx2 + bow, by2), (bx2 + bw2, by2),
                       (bx2, by2 + bh2 // 2),
                       (bx2 + bw2, by2 + bh2), (bx2 + bow, by2 + bh2)]
            pygame.draw.polygon(self.screen, hull,           pts)
            pygame.draw.polygon(self.screen, self.DARK_GRAY, pts, 1)
            lbl = self.fnt_sm.render(boat.name, True, self.WHITE)
            self.screen.blit(lbl, (bx2, by2 - 16))

        # Gate structures in perspective
        for gate_pos, gate_open, gate_name in [
            (self.lock_start, self.lock_dam.upstream_gates_open,   "Upstream Gate"),
            (self.lock_end,   self.lock_dam.downstream_gates_open, "Downstream Gate"),
        ]:
            dist = gate_pos - cam
            if abs(dist) > 500:
                continue
            scale = max(0.12, 1 - abs(dist) / 500)
            gx    = self.width // 2 + int(dist * 2.2)
            gh    = int(160 * scale)
            gw    = int(16  * scale)
            gt    = horizon - gh
            color = self.GREEN if gate_open else self.RED
            pygame.draw.rect(self.screen, self.CONCRETE, (gx - gw * 4, gt, gw * 8, gh + 28))
            pygame.draw.rect(self.screen, color,         (gx - gw, gt, gw * 2, gh))
            pygame.draw.rect(self.screen, self.DARK_GRAY, (gx - gw, gt, gw * 2, gh), 2)
            lbl = self.fnt_sm.render(gate_name, True, self.WHITE)
            self.screen.blit(lbl, (gx - lbl.get_width() // 2, gt - 18))

    # ── Input ─────────────────────────────────────────────────────────────────

    def handle_input(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_v:
                    self.view_mode = "lock" if self.view_mode == "shore" else "shore"
                elif event.key == pygame.K_g:
                    self._toggle_upstream_gate()
                elif event.key == pygame.K_h:
                    self._toggle_downstream_gate()
                elif event.key == pygame.K_f:
                    self.lock_dam.fill_chamber()
                elif event.key == pygame.K_d:
                    self.lock_dam.drain_chamber()
        return True

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

    # ── Agent simulation ──────────────────────────────────────────────────────

    def _spawn_boat(self, direction, position=None):
        self._boat_counter += 1
        cls  = random.choice([Yacht, Barge, Kayak])
        name = f"{cls.__name__[0]}{self._boat_counter}"
        boat = cls(name)
        boat.position = (-120 if direction == 1 else 1100) if position is None else position
        self.agents.append(Agent(boat, direction))

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

        for ag in active:
            self._step_agent(ag, active)

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

        # Remove done agents
        self.agents = [ag for ag in self.agents if ag.state != "done"]

    def _step_agent(self, ag, all_active):
        d    = ag.direction
        boat = ag.boat
        new_pos = boat.position + d * ag.speed

        # ── Gate blocking ─────────────────────────────────────────────────────
        if d == 1:
            gate_order = [(self.lock_start, self.lock_dam.upstream_gates_open),
                          (self.lock_end,   self.lock_dam.downstream_gates_open)]
        else:
            gate_order = [(self.lock_end,   self.lock_dam.downstream_gates_open),
                          (self.lock_start, self.lock_dam.upstream_gates_open)]

        for gate_x, open_ in gate_order:
            if open_:
                continue
            if d == 1:
                # Block if front hasn't passed gate but would after this step
                if boat.position + boat.length <= gate_x < new_pos + boat.length:
                    boat.position = gate_x - boat.length
                    return
            else:
                # Block if front (left edge) is right of gate but would cross it
                if boat.position >= gate_x > new_pos:
                    boat.position = gate_x
                    return

        # ── Same-lane boat blocking (same direction only) ────────────────────────
        gap = 5
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
        elif d == -1 and boat.position + boat.length < -100:
            ag.state = "done"
            self.score += 1

    def _incident(self, text, color=None):
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
        pw, ph = 258, 232
        panel = pygame.Surface((pw, ph), pygame.SRCALPHA)
        panel.fill((8, 12, 28, 172))
        self.screen.blit(panel, (8, 8))
        pygame.draw.rect(self.screen, (70, 110, 195), (8, 8, pw, ph), 1)

        self.screen.blit(
            self.fnt_md.render("Lock & Dam Operator", True, (170, 195, 255)), (16, 13))
        pygame.draw.line(self.screen, (70, 110, 195), (16, 34), (pw + 6, 34), 1)

        mode_col = (90, 245, 140) if self.view_mode == "shore" else (255, 195, 90)
        rows = [
            (f"View: {self.view_mode.capitalize()}",  mode_col),
            (f"Score: {self.score} boats passed",      (255, 238, 140)),
            ("",                                        None),
            ("[V]    Toggle view",                      (170, 170, 255)),
            ("[G]    Upstream gate",                    (170, 170, 255)),
            ("[H]    Downstream gate",                  (170, 170, 255)),
            ("[F]    Fill chamber",                     (170, 170, 255)),
            ("[D]    Drain chamber",                    (170, 170, 255)),
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
        self.screen.blit(
            self.fnt_sm.render(
                f"Chamber: {self.lock_dam.lock_chamber_level:.1f} m", True, (100, 200, 255)),
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

    # ── Utility ───────────────────────────────────────────────────────────────

    def _boat_color(self, boat):
        return self._boat_colors.get(type(boat).__name__, self.WHITE)

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        running = True
        while running:
            running = self.handle_input()
            self.time += 1 / 60

            self._spawn_if_needed()
            self._update_agents()

            self.screen.fill(self.SKY_BOTTOM)

            if self.view_mode == "shore":
                self.draw_shore_view()
            else:
                self.draw_lock_view()

            self.draw_ui()
            pygame.display.flip()
            self.clock.tick(60)

        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    visualizer = LockDamVisualizer()
    visualizer.run()