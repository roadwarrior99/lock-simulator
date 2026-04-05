import pygame
import sys
import math
from lock_and_dam import LockAndDam
from boat import Yacht, Barge, Kayak
from waterway import Canal


class LockDamVisualizer:
    def __init__(self):
        pygame.init()
        self.width = 1200
        self.height = 800
        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption("Lock and Dam System")
        self.clock = pygame.time.Clock()
        self.view_mode = "shore"
        self.selected_boat = 0
        self.time = 0.0

        # ── Palette ───────────────────────────────────────────────────────────
        self.SKY_TOP        = (85,  140, 220)
        self.SKY_BOTTOM     = (170, 205, 245)
        self.WATER_TOP      = (55,  135, 205)
        self.WATER_BOT      = (20,   70, 150)
        self.WATER_SHIMMER  = (100, 175, 230)
        self.LOCK_WATER_TOP = (45,  120, 195)
        self.CONCRETE       = (175, 165, 148)
        self.CONCRETE_DARK  = (130, 122, 108)
        self.GRASS          = ( 72, 155,  68)
        self.GRASS_DARK     = ( 50, 115,  48)
        self.DIRT           = (130, 102,  72)
        self.DARK_GRAY      = ( 70,  70,  70)
        self.WHITE          = (255, 255, 255)
        self.BLACK          = ( 20,  20,  20)
        self.YELLOW         = (255, 215,  40)
        self.RED            = (215,  55,  55)
        self.GREEN          = ( 50, 200,  80)

        # Boat hull colours by class name
        self._boat_colors = {
            "Yacht": (230, 230, 230),
            "Barge": (175, 135,  75),
            "Kayak": (235,  95,  35),
        }

        # ── Simulation objects ─────────────────────────────────────────────────
        self.lock_dam = LockAndDam("Main Lock", 10, 0)
        self.canal    = Canal("Main Canal")
        self.boats    = [Yacht("Yacht A"), Barge("Barge B"), Kayak("Kayak C")]
        self.boats[0].position = 200
        self.boats[1].position = 400
        self.boats[2].position = 100

        self.lock_start = 500   # simulation coords
        self.lock_end   = 700

        # ── Shore-view layout constants ────────────────────────────────────────
        # Simulation x range [0, 1000] → screen x range [50, 1150]
        self._sx_offset = 50
        self._sx_scale  = (self.width - 100) / 1000.0

        # Water-level → screen-y:  level 0 → y=430, level 10 → y=380
        self._wl_base  = 430   # y at water level 0 m
        self._wl_scale = 5     # pixels per metre (higher water = lower y value)
        self._water_bot_y = 540

        # Fonts
        self.fnt_lg = pygame.font.Font(None, 36)
        self.fnt_md = pygame.font.Font(None, 28)
        self.fnt_sm = pygame.font.Font(None, 22)

    # ── Coordinate helpers ────────────────────────────────────────────────────

    def _sx(self, sim_x):
        """Simulation x  →  screen x."""
        return int(self._sx_offset + sim_x * self._sx_scale)

    def _wy(self, level):
        """Water level (m)  →  screen y (top of water surface)."""
        return int(self._wl_base - level * self._wl_scale)

    # ── Drawing primitives ────────────────────────────────────────────────────

    def _gradient_rect(self, c1, c2, rect):
        """Fill rect with a vertical gradient from c1 (top) to c2 (bottom)."""
        x, y, w, h = rect
        if h <= 0 or w <= 0:
            return
        for i in range(h):
            t = i / (h - 1) if h > 1 else 0
            r = int(c1[0] + (c2[0] - c1[0]) * t)
            g = int(c1[1] + (c2[1] - c1[1]) * t)
            b = int(c1[2] + (c2[2] - c1[2]) * t)
            pygame.draw.line(self.screen, (r, g, b), (x, y + i), (x + w - 1, y + i))

    def _draw_sky(self, bottom_y):
        self._gradient_rect(self.SKY_TOP, self.SKY_BOTTOM, (0, 0, self.width, bottom_y))

    def _draw_water_band(self, x, y, w):
        """Draw a water column from surface y down to the channel bottom."""
        h = self._water_bot_y - y
        if h <= 0 or w <= 0:
            return
        self._gradient_rect(self.WATER_TOP, self.WATER_BOT, (x, y, w, h))
        # Surface shimmer line
        pygame.draw.line(self.screen, self.WATER_SHIMMER, (x, y), (x + w, y), 2)

    def _draw_bank_strip(self, x, top_y, w):
        """Draw grass/dirt bank above the water surface."""
        pygame.draw.rect(self.screen, self.DIRT,       (x, top_y - 12, w, 12))
        pygame.draw.rect(self.screen, self.GRASS,      (x, top_y - 26, w, 14))
        pygame.draw.rect(self.screen, self.GRASS_DARK, (x, top_y - 38, w, 12))

    def _draw_channel_floor(self, x, w):
        """Draw the muddy channel floor below the water."""
        pygame.draw.rect(self.screen, self.DIRT,  (x, self._water_bot_y,      w, 16))
        pygame.draw.rect(self.screen, self.GRASS, (x, self._water_bot_y + 16, w, 16))

    # ── Shore view ────────────────────────────────────────────────────────────

    def draw_shore_view(self):
        up_y   = self._wy(self.lock_dam.upstream_level)
        dn_y   = self._wy(self.lock_dam.downstream_level)
        lk_y   = self._wy(self.lock_dam.lock_chamber_level)
        lk_sx  = self._sx(self.lock_start)
        lk_ex  = self._sx(self.lock_end)
        lk_w   = lk_ex - lk_sx
        wall_t = 18          # lock wall thickness (px)
        wall_top_y = up_y - 35   # top of lock wall (above water)

        # Background sky
        sky_bot = min(up_y, dn_y) - 40
        self._draw_sky(sky_bot)

        # ── Upstream channel ──────────────────────────────────────────────────
        self._draw_water_band(0, up_y, lk_sx)
        self._draw_bank_strip(0, up_y, lk_sx)
        self._draw_channel_floor(0, lk_sx)

        # Animated surface ripples (upstream)
        t = self.time * 1.8
        for wx in range(0, lk_sx - 10, 35):
            oy = int(3 * math.sin(t + wx * 0.06))
            pygame.draw.line(self.screen, self.WATER_SHIMMER,
                             (wx + 5, up_y + oy), (wx + 25, up_y + oy), 1)

        # ── Downstream channel ────────────────────────────────────────────────
        self._draw_water_band(lk_ex, dn_y, self.width - lk_ex)
        self._draw_bank_strip(lk_ex, dn_y, self.width - lk_ex)
        self._draw_channel_floor(lk_ex, self.width - lk_ex)

        for wx in range(lk_ex + 5, self.width - 10, 35):
            oy = int(2 * math.sin(t + wx * 0.06))
            pygame.draw.line(self.screen, self.WATER_SHIMMER,
                             (wx, dn_y + oy), (wx + 20, dn_y + oy), 1)

        # ── Lock chamber ──────────────────────────────────────────────────────
        # Water inside
        inner_x = lk_sx + wall_t
        inner_w = lk_w - 2 * wall_t
        self._gradient_rect(self.LOCK_WATER_TOP, self.WATER_BOT,
                            (inner_x, lk_y, inner_w, self._water_bot_y - lk_y))
        pygame.draw.line(self.screen, self.WATER_SHIMMER,
                         (inner_x, lk_y), (inner_x + inner_w, lk_y), 2)

        # Concrete cap (above water on both side-walls and across top)
        pygame.draw.rect(self.screen, self.CONCRETE,
                         (lk_sx, wall_top_y, lk_w, lk_y - wall_top_y))
        # Horizontal stone course lines
        for cy in range(wall_top_y + 10, lk_y, 14):
            pygame.draw.line(self.screen, self.CONCRETE_DARK,
                             (lk_sx, cy), (lk_sx + lk_w, cy), 1)
        # Left wall
        pygame.draw.rect(self.screen, self.CONCRETE,
                         (lk_sx, wall_top_y, wall_t, self._water_bot_y - wall_top_y))
        # Right wall
        pygame.draw.rect(self.screen, self.CONCRETE,
                         (lk_ex - wall_t, wall_top_y, wall_t, self._water_bot_y - wall_top_y))
        # Floor
        pygame.draw.rect(self.screen, self.CONCRETE_DARK,
                         (inner_x, self._water_bot_y, inner_w, 10))

        # ── Gates ─────────────────────────────────────────────────────────────
        self._draw_miter_gate(lk_sx + wall_t, wall_top_y,
                              self._water_bot_y, self.lock_dam.upstream_gates_open,
                              faces_right=True)
        self._draw_miter_gate(lk_ex - wall_t, wall_top_y,
                              self._water_bot_y, self.lock_dam.downstream_gates_open,
                              faces_right=False)

        # ── Boats ─────────────────────────────────────────────────────────────
        for i, boat in enumerate(self.boats):
            self._draw_boat_shore(i, boat, up_y, dn_y, lk_y, lk_sx, lk_ex)

        # ── Water-level labels ────────────────────────────────────────────────
        self._wl_label(lk_sx // 2, up_y, "Upstream", self.lock_dam.upstream_level)
        self._wl_label(lk_ex + (self.width - lk_ex) // 2, dn_y,
                       "Downstream", self.lock_dam.downstream_level)
        self._wl_label(lk_sx + lk_w // 2, lk_y,
                       "Chamber", self.lock_dam.lock_chamber_level)

    def _draw_miter_gate(self, gate_x, wall_top, floor_y, is_open, faces_right):
        """Draw a pair of miter-gate leaves."""
        mid_y  = (wall_top + floor_y) // 2
        color  = self.GREEN if is_open else self.RED
        shadow = (max(0, color[0] - 60), max(0, color[1] - 60), max(0, color[2] - 60))
        leaf_w = 12

        if is_open:
            # Leaves folded back against the wall, angled away from channel
            offset = 20 if faces_right else -20
            # Upper leaf
            pts_u = [(gate_x, wall_top),
                     (gate_x + offset, wall_top + 8),
                     (gate_x + offset, mid_y - 4),
                     (gate_x, mid_y)]
            # Lower leaf
            pts_l = [(gate_x, mid_y),
                     (gate_x + offset, mid_y + 4),
                     (gate_x + offset, floor_y - 8),
                     (gate_x, floor_y)]
        else:
            # V-shape closed, apex pointing into the upstream side
            apex_offset = 10 if faces_right else -10
            apex_x = gate_x + apex_offset
            pts_u = [(gate_x, wall_top),
                     (gate_x + leaf_w // 2, wall_top),
                     (apex_x + leaf_w // 2, mid_y),
                     (apex_x, mid_y)]
            pts_l = [(apex_x, mid_y),
                     (apex_x + leaf_w // 2, mid_y),
                     (gate_x + leaf_w // 2, floor_y),
                     (gate_x, floor_y)]

        for pts in (pts_u, pts_l):
            pygame.draw.polygon(self.screen, color, pts)
            pygame.draw.polygon(self.screen, shadow, pts, 2)

    def _draw_boat_shore(self, idx, boat, up_y, dn_y, lk_y, lk_sx, lk_ex):
        bx = self._sx(boat.position)
        # Determine which water surface the boat sits on
        if bx < lk_sx:
            surf_y = up_y
        elif bx > lk_ex:
            surf_y = dn_y
        else:
            surf_y = lk_y

        bw = max(int(boat.length * self._sx_scale * 0.85), 14)
        bh = max(int(boat.beam * 4.5), 7)

        would_block = not self.move_boat_safely(idx, 1, test_only=True)
        if idx == self.selected_boat:
            hull_col = self.YELLOW
            outline  = (180, 145, 0)
        elif would_block:
            hull_col = self.RED
            outline  = (140, 25, 25)
        else:
            hull_col = self._boat_color(boat)
            outline  = self.DARK_GRAY

        # Trapezoid hull (bow tapers to right)
        bow_cut = max(4, bw // 5)
        ty = surf_y - bh // 2          # top of hull
        by = surf_y + bh // 2          # bottom of hull
        pts = [
            (bx,            ty),
            (bx + bw - bow_cut, ty),
            (bx + bw,       surf_y),
            (bx + bw - bow_cut, by),
            (bx,            by),
        ]
        pygame.draw.polygon(self.screen, hull_col, pts)
        pygame.draw.polygon(self.screen, outline,  pts, 2)

        # Waterline highlight
        pygame.draw.line(self.screen, self.WATER_SHIMMER,
                         (bx - 5, surf_y), (bx + bw + 5, surf_y), 1)

        # Name tag
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

    # ── Boat view ─────────────────────────────────────────────────────────────

    def draw_boat_view(self):
        cur = self.boats[self.selected_boat]
        t   = self.time

        # Sky
        self._gradient_rect((75, 130, 210), (155, 195, 240),
                            (0, 0, self.width, 400))

        # Clouds
        cloud_data = [(180, 75, 55), (480, 55, 75), (820, 90, 45), (1050, 70, 60)]
        for ci, (cx, cy, cr) in enumerate(cloud_data):
            ox = int(18 * math.sin(t * 0.25 + ci * 1.4))
            pygame.draw.ellipse(self.screen, (220, 230, 248),
                                (cx + ox - cr, cy - 18, cr * 2, 36))
            pygame.draw.ellipse(self.screen, (240, 245, 255),
                                (cx + ox - cr + 12, cy - 28, int(cr * 1.6), 36))

        horizon = 400
        pygame.draw.line(self.screen, (195, 215, 245), (0, horizon), (self.width, horizon), 2)

        # Water
        self._gradient_rect((50, 128, 198), (18, 65, 145),
                            (0, horizon, self.width, self.height - horizon))

        # Perspective ripple lines
        for row in range(6):
            ry = horizon + 18 + row * 38
            for wx in range(0, self.width, int(38 + row * 18)):
                oy = int(4 * math.sin(t * 2.2 + wx * 0.04 + row))
                seg = int(14 + row * 8)
                pygame.draw.line(self.screen, (75, 155, 215),
                                 (wx, ry + oy), (wx + seg, ry + oy), 1)

        # Shore banks (flanking the channel)
        for bx, bw in [(0, 75), (self.width - 75, 75)]:
            pygame.draw.rect(self.screen, self.GRASS,
                             (bx, horizon - 35, bw, 38))
            pygame.draw.rect(self.screen, self.DIRT,
                             (bx, horizon + 3,  bw, 22))

        # Other boats with perspective
        for i, boat in enumerate(self.boats):
            if i == self.selected_boat:
                continue
            dist = boat.position - cur.position
            if -boat.length < dist < 450:
                scale = max(0.08, 1 - abs(dist) / 450)
                scx   = self.width // 2 + int(dist * 2.5 * scale)
                bw    = max(10, int(boat.length * scale * 2.8))
                bh    = max(6,  int(boat.beam   * scale * 8))
                hull  = self._boat_color(boat)
                bx2   = scx - bw // 2
                by2   = horizon - bh
                bow   = max(3, bw // 6)
                pts   = [(bx2, by2), (bx2 + bw - bow, by2),
                         (bx2 + bw, by2 + bh // 2),
                         (bx2 + bw - bow, by2 + bh), (bx2, by2 + bh)]
                pygame.draw.polygon(self.screen, hull,          pts)
                pygame.draw.polygon(self.screen, self.DARK_GRAY, pts, 1)
                lbl = self.fnt_sm.render(boat.name, True, self.WHITE)
                self.screen.blit(lbl, (bx2, by2 - 16))

        # Lock gates in perspective
        for gate_pos, gate_open, gate_name in [
            (self.lock_start, self.lock_dam.upstream_gates_open,   "Upstream Gate"),
            (self.lock_end,   self.lock_dam.downstream_gates_open, "Downstream Gate"),
        ]:
            dist = gate_pos - cur.position
            if abs(dist) < 520:
                scale = max(0.12, 1 - abs(dist) / 520)
                gx    = self.width // 2 + int(dist * 2.2)
                gh    = int(160 * scale)
                gw    = int(16  * scale)
                gt    = horizon - gh
                color = self.GREEN if gate_open else self.RED
                # Abutment walls
                pygame.draw.rect(self.screen, self.CONCRETE,
                                 (gx - gw * 4, gt, gw * 8, gh + 28))
                # Gate panels
                pygame.draw.rect(self.screen, color, (gx - gw, gt, gw * 2, gh))
                pygame.draw.rect(self.screen, self.DARK_GRAY,
                                 (gx - gw, gt, gw * 2, gh), 2)
                lbl = self.fnt_sm.render(gate_name, True, self.WHITE)
                self.screen.blit(lbl, (gx - lbl.get_width() // 2, gt - 18))

        # Bow of the player's boat (decorative overlay at screen bottom)
        hull_col = self._boat_color(cur)
        bow_pts = [
            (self.width // 2 - 160, self.height),
            (self.width // 2 -  85, self.height - 155),
            (self.width // 2,       self.height - 185),
            (self.width // 2 +  85, self.height - 155),
            (self.width // 2 + 160, self.height),
        ]
        pygame.draw.polygon(self.screen, hull_col,        bow_pts)
        pygame.draw.polygon(self.screen, self.DARK_GRAY,  bow_pts, 3)
        name_lbl = self.fnt_md.render(cur.name, True, self.DARK_GRAY)
        self.screen.blit(name_lbl,
                         (self.width // 2 - name_lbl.get_width() // 2, self.height - 135))

    # ── Input ─────────────────────────────────────────────────────────────────

    def handle_input(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_v:
                    self.view_mode = "boat" if self.view_mode == "shore" else "shore"
                elif event.key == pygame.K_LEFT:
                    self.selected_boat = (self.selected_boat - 1) % len(self.boats)
                elif event.key == pygame.K_RIGHT:
                    self.selected_boat = (self.selected_boat + 1) % len(self.boats)
                elif event.key == pygame.K_SPACE:
                    self.move_boat_safely(self.selected_boat, 10)
                elif event.key == pygame.K_g:
                    self.lock_dam.upstream_gates_open = not self.lock_dam.upstream_gates_open
                elif event.key == pygame.K_h:
                    self.lock_dam.downstream_gates_open = not self.lock_dam.downstream_gates_open
                elif event.key == pygame.K_f:
                    self.lock_dam.fill_chamber()
                elif event.key == pygame.K_d:
                    self.lock_dam.drain_chamber()
        return True

    # ── Simulation helpers ────────────────────────────────────────────────────

    def move_boat_safely(self, boat_index, distance, test_only=False):
        boat = self.boats[boat_index]
        orig = boat.position
        boat.position = orig + distance

        if self.check_lock_collision(boat, boat.position):
            boat.position = orig
            return False

        collision = any(
            i != boat_index and boat.check_collision(other)
            for i, other in enumerate(self.boats)
        )

        if test_only or collision:
            boat.position = orig
            return not collision
        return True

    def check_lock_collision(self, boat, new_pos):
        s, e = new_pos, new_pos + boat.length
        if not self.lock_dam.upstream_gates_open:
            if e > self.lock_start and s < self.lock_start:
                return True
        if not self.lock_dam.downstream_gates_open:
            if s < self.lock_end and e > self.lock_end:
                return True
        return False

    # ── UI overlay ────────────────────────────────────────────────────────────

    def draw_ui(self):
        boat = self.boats[self.selected_boat]

        # Left control panel
        pw, ph = 258, 262
        panel = pygame.Surface((pw, ph), pygame.SRCALPHA)
        panel.fill((8, 12, 28, 172))
        self.screen.blit(panel, (8, 8))
        pygame.draw.rect(self.screen, (70, 110, 195), (8, 8, pw, ph), 1)

        title = self.fnt_md.render("Lock & Dam Controls", True, (170, 195, 255))
        self.screen.blit(title, (16, 13))
        pygame.draw.line(self.screen, (70, 110, 195), (16, 34), (pw + 6, 34), 1)

        mode_col = (90, 245, 140) if self.view_mode == "shore" else (255, 195, 90)
        rows = [
            (f"View: {self.view_mode.capitalize()}",          mode_col),
            (f"Boat: {boat.name}  ({type(boat).__name__})",   (255, 238, 140)),
            (f"Position: {boat.position} m",                  (200, 200, 200)),
            ("",                                               None),
            ("[V]      Toggle view",                           (170, 170, 255)),
            ("[← / →]  Select boat",                          (170, 170, 255)),
            ("[Space]  Move forward",                          (170, 170, 255)),
            ("[G / H]  Toggle gates",                          (170, 170, 255)),
            ("[F]      Fill chamber",                          (170, 170, 255)),
            ("[D]      Drain chamber",                         (170, 170, 255)),
        ]
        for j, (txt, col) in enumerate(rows):
            if txt:
                self.screen.blit(self.fnt_sm.render(txt, True, col), (16, 40 + j * 22))

        # Gate + chamber status panel (top right)
        gw, gh = 210, 98
        gx, gy = self.width - gw - 8, 8
        gpanel = pygame.Surface((gw, gh), pygame.SRCALPHA)
        gpanel.fill((8, 12, 28, 172))
        self.screen.blit(gpanel, (gx, gy))
        pygame.draw.rect(self.screen, (70, 110, 195), (gx, gy, gw, gh), 1)

        self.screen.blit(self.fnt_sm.render("Lock Status", True, (170, 195, 255)),
                         (gx + 10, gy + 6))
        for gi, (label, open_) in enumerate([
            ("Upstream gate",   self.lock_dam.upstream_gates_open),
            ("Downstream gate", self.lock_dam.downstream_gates_open),
        ]):
            col  = self.GREEN if open_ else self.RED
            stat = "OPEN" if open_ else "CLOSED"
            self.screen.blit(
                self.fnt_sm.render(f"{label}: {stat}", True, col),
                (gx + 10, gy + 24 + gi * 22))

        chamber_col = (100, 200, 255)
        self.screen.blit(
            self.fnt_sm.render(
                f"Chamber: {self.lock_dam.lock_chamber_level:.1f} m", True, chamber_col),
            (gx + 10, gy + 68))

    # ── Utility ───────────────────────────────────────────────────────────────

    def _boat_color(self, boat):
        return self._boat_colors.get(type(boat).__name__, self.WHITE)

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        running = True
        while running:
            running = self.handle_input()
            self.time += 1 / 60

            self.screen.fill(self.SKY_BOTTOM)   # fallback fill

            if self.view_mode == "shore":
                self.draw_shore_view()
            else:
                self.draw_boat_view()

            self.draw_ui()
            pygame.display.flip()
            self.clock.tick(60)

        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    visualizer = LockDamVisualizer()
    visualizer.run()
