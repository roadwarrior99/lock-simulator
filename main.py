import pygame
import sys
import math
import os
import json
import glob
import argparse
import logging
import random

from ld_sim import LockDamVisualizer
from deckhand_sim import DeckHandSimulation
from engineer_sim import EngineerSimulation
from pilot_sim import PilotGame
from campaign_save import save_campaign, load_campaign, default_progressions


# ── Game engine ───────────────────────────────────────────────────────────────

class GameEngine:
    """Main launcher: menu, stage select, save/load."""

    SAVE_DIR      = 'saves'
    CAMPAIGN_SAVE = os.path.join('saves', 'campaign.json')

    STAGES = [
        {
            'id':        'operator',
            'title':     'Lock Operator',
            'desc':      ['Manage gates and water levels', 'to move boats safely.'],
            'color':     (40, 100, 185),
            'available': True,
        },
        {
            'id':        'deckhand',
            'title':     'Deck Hand',
            'desc':      ['Build tows, run cables,', 'and work the lines.'],
            'color':     (150, 45, 45),
            'available': True,
        },
        {
            'id':        'engineer',
            'title':     'Engineer',
            'desc':      ['Keep the engine room running.', 'Diesel, electric, hydraulic.'],
            'color':     (175, 115, 30),
            'available': True,
        },
        {
            'id':        'captain',
            'title':     'Boat Captain',
            'desc':      ['Pilot the towboat downriver.', 'Stay in the channel.'],
            'color':     (40, 145, 80),
            'available': True,
        },
    ]

    STORIES = {
        'operator': [
            {
                'location': 'Lock 12  —  Upper Mississippi River',
                'clock':    '11:47 PM',
                'lines': [
                    "Your truck rattles into the gravel lot beside the dam.",
                    "The river is black and flat under a half moon.",
                    "Somewhere upstream, a towboat sounds its horn.",
                    "You finish your coffee and head on in.",
                ],
            },
            {
                'location': None,
                'clock':    None,
                'lines': [
                    "The outgoing operator barely looks up.",
                    '',
                    '"G opens the upstream gate.  H opens the downstream."',
                    '"Fill the chamber with F.  Drain it with D."',
                    '"Level the water before you open a gate —',
                    ' or you\'ll get a surge.  Boats in the lock won\'t like that."',
                ],
            },
            {
                'location': None,
                'clock':    None,
                'lines': [
                    "He pours himself the last of the coffee.",
                    '',
                    '"Five clean nights and they\'ll move you to days."',
                    '"Five clean days, you\'re on the deck crew."',
                    '"Don\'t flood anything."',
                ],
            },
            {
                'location': None,
                'clock':    None,
                'lines': [
                    "He walks out without another word.",
                    '',
                    "The river doesn't care about your shift.",
                ],
                'cta': 'Press SPACE to begin Night 1',
            },
        ],
        'deckhand': [
            {
                'location': 'MV Prairie Star  —  Upper Mississippi River',
                'clock':    '5:45 AM',
                'lines': [
                    "The sky is grey and the river smells like diesel.",
                    "Six empty barges are lashed in the staging area.",
                    "The mate hands you a pair of work gloves.",
                ],
            },
            {
                'location': None,
                'clock':    None,
                'lines': [
                    '"Connect the cables between every barge."',
                    '"Then winch them tight — I mean tight."',
                    '',
                    '"Mooring lines fore and aft whenever we\'re docked."',
                    '"Someone needs to stand watch at the bow."',
                    '"Anything needs painting, you\'ll know it when you see it."',
                ],
            },
            {
                'location': None,
                'clock':    None,
                'lines': [
                    "He walks away without waiting for a response.",
                    '',
                    "Barges don't run on their own.",
                    "They run on whoever shows up.",
                ],
                'cta': 'Press SPACE to begin',
            },
        ],
        'engineer': [
            {
                'location': 'MV Prairie Star  —  Upper Mississippi River',
                'clock':    '5:50 AM',
                'lines': [
                    "The engine room is loud and warm before you're even down the ladder.",
                    "Diesel smell, gear oil, the hum of something that never stops.",
                    "The outgoing engineer is already pulling on his jacket.",
                ],
            },
            {
                'location': None,
                'clock':    None,
                'lines': [
                    '"She\'s been running clean. Don\'t let her overheat."',
                    '',
                    '"Eight panels. Walk the room every few minutes.',
                    ' Something starts flashing, you go fix it."',
                    '"Hydraulics drift. Bilge needs watching after rain."',
                ],
            },
            {
                'location': None,
                'clock':    None,
                'lines': [
                    '"Alternator keeps the batteries up as long as the engine\'s healthy.',
                    ' Engine goes down, you\'re on solar and shore power."',
                    '',
                    '"Ventilation gets away from you fast if you ignore it.',
                    ' Hot engine room is a tired crew."',
                ],
            },
            {
                'location': None,
                'clock':    None,
                'lines': [
                    "He heads up the ladder without looking back.",
                    '',
                    "The engine doesn't care what time it is.",
                ],
                'cta': 'Press SPACE to begin',
            },
        ],
        'captain': [
            {
                'location': 'MV Prairie Star  —  Upper Mississippi River',
                'clock':    '5:30 AM',
                'lines': [
                    "The mate finds you on the deck before sunrise.",
                    "The river is dark and the current is running hard.",
                ],
            },
            {
                'location': None,
                'clock':    None,
                'lines': [
                    '"You know the tow. You know the locks."',
                    '"Time to see if you know the river."',
                    '',
                    '"Stay in the channel — green to starboard, red to port."',
                    '"Hit a sandbar and we lose half a day. Hit a rock and we',
                    ' lose a lot more than that."',
                ],
            },
            {
                'location': None,
                'clock':    None,
                'lines': [
                    '"Terminals will signal when they need unloading."',
                    '"Come in slow. Real slow."',
                    '',
                    "He walks back to the engine room.",
                    "The river doesn't wait.",
                ],
                'cta': 'Press SPACE to begin',
            },
        ],
    }

    STAGE_TIPS = {
        'operator': [
            "Match the chamber level before opening a gate or you'll get a surge.",
            "Both gates open at once = game over.",
            "[ESC] returns to menu and auto-saves.",
        ],
        'deckhand': [
            "Connect cables between all adjacent barges first to build the tow.",
            "After connecting, find the same spot again to winch the cable tight.",
            "Hold [E] near a task marker to work it — step away and it resets slowly.",
        ],
        'engineer': [
            "Walk the room — panels flash red when a system needs attention.",
            "Hold [E] at a panel to enter it. [ESC] exits back to the room.",
            "The alternator charges batteries automatically while the engine runs clean.",
        ],
        'captain': [
            "Green buoys on your right, red on your left going downriver.",
            "Come in dead slow to dock — under 0.9 knots to register contact.",
            "[ESC] returns to menu and auto-saves your progress.",
        ],
    }

    def __init__(self, dev_mode=False):
        pygame.init()
        self.width  = 1200
        self.height = 800
        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption("Lock & Dam")
        self.clock  = pygame.time.Clock()
        self.fnt_xl = pygame.font.Font(None, 110)
        self.fnt_lg = pygame.font.Font(None, 54)
        self.fnt_md = pygame.font.Font(None, 32)
        self.fnt_sm = pygame.font.Font(None, 22)
        self.dev_mode        = dev_mode
        self.screen_name     = 'menu'
        self.bg_time         = 0.0
        self.hover           = None
        self.story_card      = 0     # current story card index
        self.debrief_data    = None  # dict set after each shift
        self.active_stage_id = 'operator'
        self.progressions    = default_progressions()
        self.debt            = 10000.0   # global debt shared across all stages
        self._save_notif     = 0.0   # countdown for "Saved" banner
        os.makedirs(self.SAVE_DIR, exist_ok=True)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _saves_for(self, stage_id):
        return sorted(glob.glob(os.path.join(self.SAVE_DIR, f'{stage_id}_*.json')))

    def _any_saves(self):
        return (os.path.exists(self.CAMPAIGN_SAVE)
                or any(self._saves_for(s['id']) for s in self.STAGES))

    def save_campaign_state(self):
        """Persist progression state to saves/campaign.json."""
        save_campaign(self.CAMPAIGN_SAVE, self.active_stage_id, self.progressions, self.debt)
        self._save_notif = 2.5   # seconds to display "Saved" banner

    def _gradient_rect(self, c1, c2, rect):
        x, y, w, h = rect
        if h <= 0 or w <= 0:
            return
        for i in range(h):
            t = i / (h - 1) if h > 1 else 0
            col = tuple(int(c1[k] + (c2[k] - c1[k]) * t) for k in range(3))
            pygame.draw.line(self.screen, col, (x, y + i), (x + w - 1, y + i))

    def _button(self, rect, label, hovered, color=(45, 75, 155), fnt=None):
        fnt = fnt or self.fnt_md
        bg  = tuple(min(255, c + 35) for c in color) if hovered else color
        pygame.draw.rect(self.screen, bg,            rect, border_radius=6)
        pygame.draw.rect(self.screen, (180, 200, 240), rect, 1, border_radius=6)
        lbl = fnt.render(label, True, (255, 255, 255))
        x, y, w, h = rect
        self.screen.blit(lbl, (x + w // 2 - lbl.get_width() // 2,
                                y + h // 2 - lbl.get_height() // 2))

    # ── Animated background ───────────────────────────────────────────────────

    def _draw_bg(self):
        t = self.bg_time
        # Sky
        self._gradient_rect((5, 12, 40), (18, 38, 85), (0, 0, self.width, 510))
        # Stars
        for i in range(70):
            sx = (i * 179 + 31) % self.width
            sy = (i * 107 + 13) % 290
            b  = int(140 + 90 * math.sin(t * 0.7 + i * 1.3))
            pygame.draw.circle(self.screen, (b, b, b), (sx, sy), 1)
        # Moon
        pygame.draw.circle(self.screen, (238, 232, 195), (940, 88), 42)
        pygame.draw.circle(self.screen, (14, 28, 72),    (926, 78), 36)
        # Far hills
        pts = [(0, 510)]
        for x in range(0, self.width + 20, 20):
            y = 390 + int(28 * math.sin(x * 0.007 + 1.1)) + int(14 * math.sin(x * 0.018))
            pts.append((x, y))
        pts += [(self.width, 510), (0, 510)]
        pygame.draw.polygon(self.screen, (16, 44, 30), pts)
        # River
        water_y = 460
        self._gradient_rect((12, 42, 95), (6, 22, 60), (0, water_y, self.width, self.height - water_y))
        for i in range(22):
            wx = int((i * 59 + t * 35) % self.width)
            wy = water_y + 8 + (i % 6) * 16
            oy = int(3 * math.sin(t * 1.6 + i * 0.8))
            pygame.draw.line(self.screen, (38, 80, 148), (wx, wy + oy), (wx + 28, wy + oy), 1)
        # Lock silhouette (centred)
        lx  = self.width // 2 - 175
        lw  = 350
        wh  = 190
        wy2 = water_y - wh
        wc  = (32, 38, 48)
        # Walls
        #pygame.draw.rect(self.screen, wc, (lx,          wy2, 30, wh + 55))
        #pygame.draw.rect(self.screen, wc, (lx + lw - 30, wy2, 30, wh + 55))
        # Chamber water
        #pygame.draw.rect(self.screen, (14, 52, 105), (lx + 30, water_y, lw - 60, 55))
        #pygame.draw.line(self.screen, (35, 78, 148),
        #                 (lx + 30, water_y), (lx + lw - 30, water_y), 2)
        # Miter gate silhouettes
        gc = (50, 58, 72)
        for gx in (lx + 30, lx + lw - 30):
            sign = 1 if gx == lx + 30 else -1
            mid  = water_y
        #    pygame.draw.polygon(self.screen, gc,
        #                        [(gx, wy2), (gx + sign * 16, mid - 12), (gx, mid)])
        #    pygame.draw.polygon(self.screen, gc,
        #                        [(gx, mid), (gx + sign * 16, mid + 12), (gx, mid + 50)])
        # Reflection ripple
        refl = pygame.Surface((lw, 70), pygame.SRCALPHA)
        pygame.draw.rect(refl, (28, 50, 88, 70), (0, 0, 30, 70))
        pygame.draw.rect(refl, (28, 50, 88, 70), (lw - 30, 0, 30, 70))
        self.screen.blit(refl, (lx, water_y + 18 + int(3 * math.sin(t * 1.4))))
        # Ground
        pygame.draw.rect(self.screen, (22, 52, 30), (0, self.height - 75, self.width, 75))
        pygame.draw.rect(self.screen, (16, 40, 22), (0, self.height - 50, self.width, 50))

    # ── Screens ───────────────────────────────────────────────────────────────

    def _draw_menu(self, mp):
        self._draw_bg()
        ov = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 105))
        self.screen.blit(ov, (0, 0))

        cx = self.width // 2

        # Logo
        shadow = self.fnt_xl.render("LOCK & DAM", True, (8, 16, 50))
        title  = self.fnt_xl.render("LOCK & DAM", True, (210, 228, 255))
        self.screen.blit(shadow, (cx - title.get_width() // 2 + 4, 144))
        self.screen.blit(title,  (cx - title.get_width() // 2,     140))
        sub = self.fnt_md.render("A Waterway Operations Simulation", True, (145, 175, 220))
        self.screen.blit(sub, (cx - sub.get_width() // 2, 252))

        # Buttons
        bw, bh, gap = 290, 54, 14
        bx = cx - bw // 2
        btns = [
            ('new_game',  'New Game',  370),
            ('load_game', 'Load Game', 370 + (bh + gap)),
            ('save_game', 'Save Game', 370 + (bh + gap) * 2),
            ('quit',      'Quit',      370 + (bh + gap) * 3),
        ]
        self.hover = None
        for bid, label, by in btns:
            rect = pygame.Rect(bx, by, bw, bh)
            hov  = rect.collidepoint(mp)
            if hov:
                self.hover = bid
            unavail = bid == 'load_game' and not self._any_saves()
            self._button(rect, label, hov and not unavail,
                         color=(30, 40, 70) if unavail else (45, 75, 155))

        # "Saved" confirmation banner
        if self._save_notif > 0:
            sv = self.fnt_sm.render("Game saved.", True, (130, 215, 130))
            self.screen.blit(sv, (cx - sv.get_width() // 2, 370 + (bh + gap) * 4 - 10))

        ver = self.fnt_sm.render("v0.1  —  [ESC] to return from any stage", True, (70, 88, 125))
        self.screen.blit(ver, (cx - ver.get_width() // 2, self.height - 28))

    def _draw_stage_select(self, mp):
        self._draw_bg()
        ov = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 130))
        self.screen.blit(ov, (0, 0))

        cx = self.width // 2
        hdr = self.fnt_lg.render("Choose Your Role", True, (205, 220, 255))
        self.screen.blit(hdr, (cx - hdr.get_width() // 2, 48))

        cw, ch = 248, 300
        total  = len(self.STAGES) * cw + (len(self.STAGES) - 1) * 18
        sx     = cx - total // 2
        self.hover = None

        for i, stage in enumerate(self.STAGES):
            cx_ = sx + i * (cw + 18)
            cy_ = 130
            rect = pygame.Rect(cx_, cy_, cw, ch)
            avail   = stage['available'] or self.dev_mode
            hov     = rect.collidepoint(mp) and avail
            if hov:
                self.hover = ('stage', i)
            col = stage['color']

            # Card
            card = pygame.Surface((cw, ch), pygame.SRCALPHA)
            card.fill((*col, 195 if avail else 110))
            self.screen.blit(card, (cx_, cy_))
            border_col = (220, 232, 255) if hov else tuple(max(0, c - 30) for c in col)
            pygame.draw.rect(self.screen, border_col, rect, 2, border_radius=5)

            # Title
            tc = (255, 255, 255) if avail else (130, 130, 150)
            ts = self.fnt_md.render(stage['title'], True, tc)
            self.screen.blit(ts, (cx_ + cw // 2 - ts.get_width() // 2, cy_ + 18))

            # Icon area
            icon = pygame.Rect(cx_ + 54, cy_ + 58, 140, 110)
            pygame.draw.rect(self.screen, tuple(max(0, c - 40) for c in col), icon, border_radius=8)
            if not avail:
                cs = self.fnt_sm.render("Coming Soon", True, (175, 175, 195))
                self.screen.blit(cs, (cx_ + cw // 2 - cs.get_width() // 2, cy_ + 105))

            # Description
            for li, line in enumerate(stage['desc']):
                ds = self.fnt_sm.render(line, True, tc)
                self.screen.blit(ds, (cx_ + cw // 2 - ds.get_width() // 2, cy_ + 186 + li * 19))

            # Play button
            if avail:
                pr = pygame.Rect(cx_ + 38, cy_ + ch - 50, cw - 76, 36)
                self._button(pr, "Play", hov, color=col, fnt=self.fnt_sm)

        # Back
        br = pygame.Rect(28, self.height - 55, 115, 38)
        bhov = br.collidepoint(mp)
        if bhov:
            self.hover = 'back'
        self._button(br, "← Back", bhov, color=(42, 48, 68))

    def _draw_load_select(self, mp):
        self._draw_bg()
        ov = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 140))
        self.screen.blit(ov, (0, 0))

        cx  = self.width // 2
        hdr = self.fnt_lg.render("Load Game", True, (205, 220, 255))
        self.screen.blit(hdr, (cx - hdr.get_width() // 2, 48))

        self.hover = None
        y = 125
        any_saves = False

        # ── Campaign save ──────────────────────────────────────────────────
        if os.path.exists(self.CAMPAIGN_SAVE):
            any_saves = True
            try:
                saved  = load_campaign(self.CAMPAIGN_SAVE)
                stage_label = next(
                    (s['title'] for s in self.STAGES
                     if s['id'] == saved['active_stage_id']), 'Unknown')
                total_earned = sum(p.get('total_earnings', 0.0)
                                   for p in saved['progressions'].values())
                total_debt   = saved['debt']
                bal  = total_earned - total_debt
                desc = (f"Stage: {stage_label}   "
                        f"Earned: ${total_earned:,.0f}   "
                        f"Balance: {'−' if bal < 0 else '+'}${abs(bal):,.0f}")
            except Exception:
                desc = "Campaign save (unreadable)"
            sl = self.fnt_md.render("Campaign Progress", True, (220, 230, 160))
            self.screen.blit(sl, (cx - 310, y)); y += 30
            rr  = pygame.Rect(cx - 310, y, 620, 42)
            hov = rr.collidepoint(mp)
            if hov:
                self.hover = 'load_campaign'
            self._button(rr, desc, hov, color=(45, 85, 50), fnt=self.fnt_sm)
            y += 56

        # ── Simulation mid-game saves ──────────────────────────────────────
        for stage in self.STAGES:
            saves = self._saves_for(stage['id'])
            if not saves:
                continue
            any_saves = True
            sl = self.fnt_md.render(stage['title'], True, (155, 185, 235))
            self.screen.blit(sl, (cx - 310, y))
            y += 30
            for path in saves:
                name = os.path.basename(path).replace('.json', '')
                try:
                    with open(path) as f:
                        d = json.load(f)
                    gt = d.get('game_time', 0)
                    h_, m_ = int(gt), int((gt * 60) % 60)
                    desc = f"Score: {d.get('score','?')}   {h_:02d}:{m_:02d}"
                except Exception:
                    desc = "Unreadable"
                rr = pygame.Rect(cx - 310, y, 620, 38)
                hov = rr.collidepoint(mp)
                if hov:
                    self.hover = ('load', stage['id'], path)
                self._button(rr, f"{name}   —   {desc}", hov,
                             color=stage['color'], fnt=self.fnt_sm)
                y += 46

        if not any_saves:
            msg = self.fnt_md.render("No save files found.", True, (150, 162, 195))
            self.screen.blit(msg, (cx - msg.get_width() // 2, 300))

        br = pygame.Rect(28, self.height - 55, 115, 38)
        bhov = br.collidepoint(mp)
        if bhov:
            self.hover = 'back'
        self._button(br, "← Back", bhov, color=(42, 48, 68))

    # ── Story / briefing / debrief screens ───────────────────────────────────

    def _draw_story(self, mp):
        """Text-card intro sequence. Returns True when the story is finished."""
        story = self.STORIES[self.active_stage_id]
        card  = story[self.story_card]
        self._draw_bg()
        ov = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 160))
        self.screen.blit(ov, (0, 0))

        cx = self.width // 2
        y  = 180

        if card.get('location'):
            loc = self.fnt_lg.render(card['location'], True, (160, 185, 230))
            self.screen.blit(loc, (cx - loc.get_width() // 2, y))
            y += 52
        if card.get('clock'):
            clk = self.fnt_md.render(card['clock'], True, (200, 200, 160))
            self.screen.blit(clk, (cx - clk.get_width() // 2, y))
            y += 50

        for line in card['lines']:
            if not line:
                y += 14
                continue
            italic = line.startswith('"') or line.startswith(' ')
            col    = (220, 215, 195) if italic else (195, 210, 235)
            s = self.fnt_md.render(line, True, col)
            self.screen.blit(s, (cx - s.get_width() // 2, y))
            y += 34

        # CTA / advance hint
        cta_text = card.get('cta', 'Press SPACE to continue')
        pulse = int(200 + 55 * math.sin(self.bg_time * 2.5))
        cta_p = self.fnt_sm.render(cta_text, True, (pulse, pulse, pulse))
        self.screen.blit(cta_p, (cx - cta_p.get_width() // 2, self.height - 60))

        # Card counter dots
        for i, _ in enumerate(story):
            col = (200, 210, 240) if i == self.story_card else (60, 70, 100)
            pygame.draw.circle(self.screen, col, (cx - (len(story) - 1) * 10 + i * 20, self.height - 28), 4)

    def _draw_shift_briefing(self, mp):
        prog  = self.progressions[self.active_stage_id]
        phase = prog['phase']
        num   = prog['shift_num']
        clean = prog['clean_shifts']
        is_night = phase == 'nights'

        self._draw_bg()
        ov = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 145))
        self.screen.blit(ov, (0, 0))

        cx = self.width // 2
        phase_label = "Night Shift" if is_night else "Day Shift"
        col_h = (160, 195, 255) if is_night else (255, 230, 140)

        hdr = self.fnt_lg.render(f"{phase_label}  —  Shift {num}", True, col_h)
        self.screen.blit(hdr, (cx - hdr.get_width() // 2, 140))

        start_t = "8:00 PM" if is_night else "8:00 AM"
        end_t   = "8:00 AM" if is_night else "8:00 PM"
        sub = self.fnt_md.render(f"{start_t}  →  {end_t}  (12 hours)", True, (190, 200, 220))
        self.screen.blit(sub, (cx - sub.get_width() // 2, 210))

        # Progress pips
        pip_y = 285
        for i in range(5):
            done  = i < clean
            c_pip = (80, 200, 100) if done else (55, 60, 80)
            pygame.draw.rect(self.screen, c_pip,
                             pygame.Rect(cx - 130 + i * 60, pip_y, 44, 22), border_radius=4)
            lp = self.fnt_sm.render("✓" if done else str(i + 1), True, (220, 230, 220))
            self.screen.blit(lp, (cx - 130 + i * 60 + 22 - lp.get_width() // 2, pip_y + 3))
        next_stage  = self._next_stage_title(self.active_stage_id)
        if clean == 4 and is_night:
            pip_msg = "Promotion to days next!"
        elif clean == 4 and not is_night and next_stage:
            pip_msg = f"Advance to {next_stage} next!"
        else:
            pip_msg = "Complete all 5 without incidents to advance."
        prog_label = self.fnt_sm.render(
            f"Clean shifts: {clean}/5  —  {pip_msg}", True, (160, 175, 210))
        self.screen.blit(prog_label, (cx - prog_label.get_width() // 2, pip_y + 34))

        # Stage-specific reminders
        tips = self.STAGE_TIPS.get(self.active_stage_id, [])
        for i, tip in enumerate(tips):
            t = self.fnt_sm.render(tip, True, (130, 145, 175))
            self.screen.blit(t, (cx - t.get_width() // 2, 370 + i * 24))

        br = pygame.Rect(cx - 120, 500, 240, 52)
        hov = br.collidepoint(mp)
        self.hover = 'begin_shift' if hov else None
        self._button(br, "Begin Shift", hov,
                     color=(35, 60, 140) if is_night else (140, 110, 30))

        if self.dev_mode:
            dev_hint = self.fnt_sm.render("[DEV]  S = skip shift instantly", True, (255, 100, 255))
            self.screen.blit(dev_hint, (cx - dev_hint.get_width() // 2, 572))

    def _draw_shift_debrief(self, mp):
        d        = self.debrief_data
        is_clean = d['incidents'] == 0
        prog     = self.progressions[self.active_stage_id]

        self._draw_bg()
        ov = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 155))
        self.screen.blit(ov, (0, 0))

        cx = self.width // 2

        hdr_text = "Shift Complete" if d['completed'] else "Shift Ended"
        hdr_col  = (120, 230, 130) if is_clean else (230, 130, 80)
        hdr = self.fnt_lg.render(hdr_text, True, hdr_col)
        self.screen.blit(hdr, (cx - hdr.get_width() // 2, 130))

        stats = [
            (f"Boats passed:   {d['score']}",                       (200, 215, 240)),
            (f"Incidents:      {d['incidents']}",                   (200, 215, 240)),
            (f"Clean shifts:   {prog['clean_shifts']} / 5",         (200, 215, 240)),
        ]
        for i, (s, col) in enumerate(stats):
            st = self.fnt_md.render(s, True, col)
            self.screen.blit(st, (cx - st.get_width() // 2, 210 + i * 36))

        # Pay summary
        wages   = d.get('wages',          0.0)
        bonuses = d.get('bonuses',        0.0)
        earned  = d.get('shift_earnings', 0.0)
        total   = d.get('total_earnings', 0.0)
        debt    = d.get('debt', self.debt)
        balance = total - debt
        bal_col = (120, 230, 130) if balance >= 0 else (230, 130, 80)

        pay_rows = [
            (f"Wages:    ${wages:.2f}",            (190, 210, 160)),
            (f"Bonuses:  ${bonuses:.2f}",           (190, 210, 160)),
            (f"Shift pay: ${earned:.2f}",           (220, 230, 180)),
            (f"Total earned: ${total:,.2f}  /  ${debt:,.0f} debt",  (200, 200, 200)),
            (f"Balance: {'−' if balance < 0 else '+'}${abs(balance):,.2f}", bal_col),
        ]
        for i, (s, col) in enumerate(pay_rows):
            ps = self.fnt_sm.render(s, True, col)
            self.screen.blit(ps, (cx - ps.get_width() // 2, 332 + i * 22))

        # Narrative line
        next_stage = self._next_stage_title(self.active_stage_id)
        if d.get('promoted_to_days'):
            msg = "Five clean nights. You're moving to days."
        elif d.get('advanced') and next_stage:
            msg = f"Five clean days. Time to move up — {next_stage} is next."
        elif d.get('advanced'):
            msg = "Five clean days. You've mastered this role."
        elif is_clean:
            msg = f"Good shift. {5 - prog['clean_shifts']} more clean shifts to go."
        else:
            msg = "Incidents on the log. This shift won't count toward promotion."
        msg_s = self.fnt_sm.render(msg, True, (210, 205, 180))
        self.screen.blit(msg_s, (cx - msg_s.get_width() // 2, 450))

        br = pygame.Rect(cx - 130, 490, 260, 48)
        hov = br.collidepoint(mp)
        self.hover = 'next_shift' if hov else None
        btn_label = "Continue →" if not d.get('advanced') else "Next Stage →"
        self._button(br, btn_label, hov, color=(40, 80, 40) if is_clean else (80, 50, 30))

    # ── Launch & save ─────────────────────────────────────────────────────────

    def _next_save_path(self, stage_id):
        existing = self._saves_for(stage_id)
        idx = len(existing) + 1
        return os.path.join(self.SAVE_DIR, f'{stage_id}_{idx:03d}.json')

    def _launch_operator_shift(self):
        """Configure and run one operator shift based on current progression."""
        prog     = self.progressions['operator']
        is_night = prog['phase'] == 'nights'
        start    = 20.0 if is_night else 8.0   # 8 PM nights, 8 AM days

        # Compute current week (7 shifts per week) and reset ship log if a new
        # week has started since the last recorded week in the log.
        current_week = (prog['shift_num'] - 1) // 7
        ship_log = prog.get('ship_log', {'week': 0, 'ships': {}})
        if ship_log.get('week', 0) < current_week:
            ship_log = {'week': current_week, 'ships': {}}

        vis = LockDamVisualizer(
            shift_duration=12.0,
            shift_start_time=start,
            cfg_time_scale=2.0,   # 2 game-hrs/real-min → 6 real minutes per shift
            dev_mode=self.dev_mode,
            ship_log=ship_log,
        )
        # Attach display labels for the HUD
        vis._shift_phase_label = "Night" if is_night else "Day"
        vis._shift_num_label   = f"{prog['shift_num']}"
        vis._shift_clean_label = f"({prog['clean_shifts']}/5 clean)"

        result = vis.run()

        if result == 'quit':
            return 'quit'

        # Persist updated ship sighting log back into campaign progression
        prog['ship_log'] = vis.ship_log

        # Compute shift earnings
        wages   = LockDamVisualizer.HOURLY_WAGE * vis.shift_hours_elapsed
        bonuses = LockDamVisualizer.BOAT_BONUS  * vis.score
        shift_earnings = wages + bonuses
        prog['total_earnings'] += shift_earnings

        # Build debrief data
        self.debrief_data = {
            'completed':        result == 'shift_complete',
            'incidents':        vis.incident_count,
            'score':            vis.score,
            'promoted_to_days': False,
            'advanced':         False,
            'wages':            wages,
            'bonuses':          bonuses,
            'shift_earnings':   shift_earnings,
            'total_earnings':   prog['total_earnings'],
            'debt':             self.debt,
        }

        if result == 'shift_complete':
            prog['shift_num'] += 1
            if vis.incident_count == 0:
                prog['clean_shifts'] += 1
                if prog['clean_shifts'] >= 5:
                    if is_night:
                        prog['phase']        = 'days'
                        prog['clean_shifts'] = 0
                        prog['shift_num']    = 1
                        self.debrief_data['promoted_to_days'] = True
                    else:
                        self.debrief_data['advanced'] = True

        # Auto-save mid-career state
        if result == 'menu':
            vis.save_to_file(self._next_save_path('operator'))

        self.screen_name = 'debrief'
        return result

    def _launch_deckhand_shift(self):
        """Configure and run one deck hand shift based on current progression."""
        prog     = self.progressions['deckhand']
        is_night = prog['phase'] == 'nights'
        start    = 20.0 if is_night else 6.0

        # 50 % chance to carry over open-door / empty-barge state from last shift
        carry = prog.get('_cargo_state')
        cargo_start = None
        if carry and random.random() < 0.5:
            cargo_start = carry

        vis = DeckHandSimulation(
            shift_duration=12.0,
            shift_start_time=start,
            cfg_time_scale=2.0,
            dev_mode=self.dev_mode,
            first_shift=(prog['shift_num'] == 1),
            cargo_start_state=cargo_start,
        )
        vis._shift_phase_label = "Night" if is_night else "Day"
        vis._shift_num_label   = f"{prog['shift_num']}"
        vis._shift_clean_label = f"({prog['clean_shifts']}/5 clean)"

        result = vis.run()

        if result == 'quit':
            return 'quit'

        # Persist cargo state if any barge ended with doors open and empty
        end_state = vis.cargo_end_state
        if any(e['door_open'] >= 1.0 and e['empty'] for e in end_state):
            prog['_cargo_state'] = end_state
        else:
            prog['_cargo_state'] = None

        wages   = DeckHandSimulation.HOURLY_WAGE * vis.shift_hours_elapsed
        bonuses = DeckHandSimulation.TASK_BONUS  * vis.score
        shift_earnings = wages + bonuses
        prog['total_earnings'] += shift_earnings

        self.debrief_data = {
            'completed':        result == 'shift_complete',
            'incidents':        vis.incident_count,
            'score':            vis.score,
            'promoted_to_days': False,
            'advanced':         False,
            'wages':            wages,
            'bonuses':          bonuses,
            'shift_earnings':   shift_earnings,
            'total_earnings':   prog['total_earnings'],
            'debt':             self.debt,
        }

        if result == 'shift_complete':
            prog['shift_num'] += 1
            if vis.incident_count == 0:
                prog['clean_shifts'] += 1
                if prog['clean_shifts'] >= 5:
                    if is_night:
                        prog['phase']        = 'days'
                        prog['clean_shifts'] = 0
                        prog['shift_num']    = 1
                        self.debrief_data['promoted_to_days'] = True
                    else:
                        self.debrief_data['advanced'] = True

        self.screen_name = 'debrief'
        return result

    def _launch_engineer_shift(self):
        """Configure and run one engineer shift based on current progression."""
        prog     = self.progressions['engineer']
        is_night = prog['phase'] == 'nights'
        start    = 20.0 if is_night else 6.0
        vis = EngineerSimulation(
            shift_duration=12.0,
            shift_start_time=start,
            cfg_time_scale=2.0,
            dev_mode=self.dev_mode,
        )

        result = vis.run()

        if result == 'quit':
            return 'quit'

        wages          = EngineerSimulation.HOURLY_WAGE * vis.shift_hours_elapsed
        bonuses        = EngineerSimulation.TASK_BONUS  * vis.score
        shift_earnings = wages + bonuses
        prog['total_earnings'] += shift_earnings

        self.debrief_data = {
            'completed':        result == 'shift_complete',
            'incidents':        vis.incident_count,
            'score':            vis.score,
            'promoted_to_days': False,
            'advanced':         False,
            'wages':            wages,
            'bonuses':          bonuses,
            'shift_earnings':   shift_earnings,
            'total_earnings':   prog['total_earnings'],
            'debt':             self.debt,
        }

        if result == 'shift_complete':
            prog['shift_num'] += 1
            if vis.incident_count == 0:
                prog['clean_shifts'] += 1
                if prog['clean_shifts'] >= 5:
                    if is_night:
                        prog['phase']        = 'days'
                        prog['clean_shifts'] = 0
                        prog['shift_num']    = 1
                        self.debrief_data['promoted_to_days'] = True
                    else:
                        self.debrief_data['advanced'] = True

        self.screen_name = 'debrief'
        return result

    def _launch_captain_shift(self):
        """Configure and run one captain (towboat pilot) shift."""
        prog     = self.progressions['captain']
        is_night = prog['phase'] == 'nights'
        start    = 20.0 if is_night else 9.0   # day shifts start at 9 AM

        vis = PilotGame(
            shift_duration=12.0,
            shift_start_time=start,
            dev_mode=self.dev_mode,
        )
        vis._shift_phase_label = "Night" if is_night else "Day"
        vis._shift_num_label   = f"{prog['shift_num']}"
        vis._shift_clean_label = f"({prog['clean_shifts']}/5 clean)"

        result = vis.run()

        if result == 'quit':
            return 'quit'

        wages          = PilotGame.HOURLY_WAGE * vis.shift_hours_elapsed
        bonuses        = PilotGame.DOCK_BONUS  * vis.score
        shift_earnings = wages + bonuses
        prog['total_earnings'] += shift_earnings

        self.debrief_data = {
            'completed':        result == 'shift_complete',
            'incidents':        vis.incident_count,
            'score':            vis.score,
            'promoted_to_days': False,
            'advanced':         False,
            'wages':            wages,
            'bonuses':          bonuses,
            'shift_earnings':   shift_earnings,
            'total_earnings':   prog['total_earnings'],
            'debt':             self.debt,
        }

        if result == 'shift_complete':
            prog['shift_num'] += 1
            if vis.incident_count == 0:
                prog['clean_shifts'] += 1
                if prog['clean_shifts'] >= 5:
                    if is_night:
                        prog['phase']        = 'days'
                        prog['clean_shifts'] = 0
                        prog['shift_num']    = 1
                        self.debrief_data['promoted_to_days'] = True
                    else:
                        self.debrief_data['advanced'] = True

        self.screen_name = 'debrief'
        return result

    def _launch_placeholder_shift(self, stage_id):
        """Stub for stages not yet implemented — shows a debrief immediately."""
        prog = self.progressions[stage_id]
        self.debrief_data = {
            'completed': False, 'incidents': 0, 'score': 0,
            'promoted_to_days': False, 'advanced': False,
            'wages': 0.0, 'bonuses': 0.0, 'shift_earnings': 0.0,
            'total_earnings': prog['total_earnings'],
            'debt': self.debt,
        }
        self.screen_name = 'debrief'
        return 'menu'

    def _next_stage_title(self, stage_id):
        """Return the title of the next stage, or None if this is the last."""
        for i, s in enumerate(self.STAGES):
            if s['id'] == stage_id and i + 1 < len(self.STAGES):
                return self.STAGES[i + 1]['title']
        return None

    def _dispatch_shift(self, stage_id):
        """Route a 'begin shift' click to the correct launch method."""
        if stage_id == 'operator':
            return self._launch_operator_shift()
        elif stage_id == 'deckhand':
            return self._launch_deckhand_shift()
        elif stage_id == 'engineer':
            return self._launch_engineer_shift()
        elif stage_id == 'captain':
            return self._launch_captain_shift()
        else:
            return self._launch_placeholder_shift(stage_id)

    def _skip_shift_dev(self):
        """Dev mode: instantly complete the current shift as if it were clean."""
        prog     = self.progressions[self.active_stage_id]
        is_night = prog['phase'] == 'nights'
        wages    = LockDamVisualizer.HOURLY_WAGE * 12.0  # full 12h shift
        prog['total_earnings'] += wages
        self.debrief_data = {
            'completed': True, 'incidents': 0, 'score': 0,
            'promoted_to_days': False, 'advanced': False,
            'wages':          wages,
            'bonuses':        0.0,
            'shift_earnings': wages,
            'total_earnings': prog['total_earnings'],
            'debt':           prog['debt'],
        }
        prog['shift_num'] += 1
        prog['clean_shifts'] += 1
        if prog['clean_shifts'] >= 5:
            if is_night:
                prog['phase']        = 'days'
                prog['clean_shifts'] = 0
                prog['shift_num']    = 1
                self.debrief_data['promoted_to_days'] = True
            else:
                self.debrief_data['advanced'] = True
        self.screen_name = 'debrief'

    # ── Event handling ────────────────────────────────────────────────────────

    def _click(self, mp):
        if self.screen_name == 'menu':
            self._draw_menu(mp)
            if self.hover == 'new_game':
                self.screen_name = 'stage_select'
            elif self.hover == 'load_game' and self._any_saves():
                self.screen_name = 'load_select'
            elif self.hover == 'save_game':
                self.save_campaign_state()
            elif self.hover == 'quit':
                pygame.quit()
                sys.exit()

        elif self.screen_name == 'stage_select':
            self._draw_stage_select(mp)
            if self.hover == 'back':
                self.screen_name = 'menu'
            elif isinstance(self.hover, tuple) and self.hover[0] == 'stage':
                stage = self.STAGES[self.hover[1]]
                avail = stage['available'] or self.dev_mode
                if avail:
                    self.active_stage_id = stage['id']
                    prog = self.progressions[self.active_stage_id]
                    story = self.STORIES.get(self.active_stage_id, [])
                    if story and not prog['story_seen']:
                        self.story_card = 0
                        self.screen_name = 'story'
                    else:
                        self.screen_name = 'briefing'

        elif self.screen_name == 'story':
            pass  # handled by keydown

        elif self.screen_name == 'briefing':
            self._draw_shift_briefing(mp)
            if self.hover == 'begin_shift':
                result = self._dispatch_shift(self.active_stage_id)
                if result == 'quit':
                    pygame.quit()
                    sys.exit()

        elif self.screen_name == 'debrief':
            self._draw_shift_debrief(mp)
            if self.hover == 'next_shift':
                if self.debrief_data and self.debrief_data.get('advanced'):
                    self.screen_name = 'stage_select'
                else:
                    self.screen_name = 'briefing'

        elif self.screen_name == 'load_select':
            self._draw_load_select(mp)
            if self.hover == 'back':
                self.screen_name = 'menu'
            elif self.hover == 'load_campaign':
                try:
                    saved = load_campaign(self.CAMPAIGN_SAVE)
                    self.active_stage_id = saved['active_stage_id']
                    self.progressions    = saved['progressions']
                    self.debt            = saved['debt']
                except Exception:
                    pass
                self.screen_name = 'stage_select'
            elif isinstance(self.hover, tuple) and self.hover[0] == 'load':
                _, _sid, path = self.hover
                vis = LockDamVisualizer()
                vis.load_from_file(path)
                result = vis.run()
                if result == 'quit':
                    pygame.quit()
                    sys.exit()
                self.screen_name = 'menu'

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        while True:
            self.bg_time += 1 / 60
            mp = pygame.mouse.get_pos()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self._click(mp)
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        if self.screen_name in ('stage_select', 'load_select', 'briefing'):
                            self.screen_name = 'menu'
                        elif self.screen_name == 'debrief':
                            self.screen_name = 'menu'
                    elif self.dev_mode and event.key == pygame.K_s:
                        if self.screen_name == 'briefing':
                            self._skip_shift_dev()
                    elif event.key == pygame.K_SPACE:
                        if self.screen_name == 'story':
                            self.story_card += 1
                            story = self.STORIES.get(self.active_stage_id, [])
                            if self.story_card >= len(story):
                                self.progressions[self.active_stage_id]['story_seen'] = True
                                self.screen_name = 'briefing'

            if self.screen_name == 'menu':
                self._draw_menu(mp)
            elif self.screen_name == 'stage_select':
                self._draw_stage_select(mp)
            elif self.screen_name == 'story':
                self._draw_story(mp)
            elif self.screen_name == 'briefing':
                self._draw_shift_briefing(mp)
            elif self.screen_name == 'debrief':
                self._draw_shift_debrief(mp)
            elif self.screen_name == 'load_select':
                self._draw_load_select(mp)

            if self._save_notif > 0:
                self._save_notif -= 1 / 60

            pygame.display.flip()
            self.clock.tick(60)


if __name__ == "__main__":
    import datetime
    ap = argparse.ArgumentParser()
    ap.add_argument('--dev', action='store_true', help='Enable developer mode')
    args = ap.parse_args()
    if args.dev:
        from assets import enable_debug_logging
        enable_debug_logging()

        # Mirror all DEBUG output to a timestamped log file in logs/
        os.makedirs('logs', exist_ok=True)
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        log_path = os.path.join('logs', f'dev_{stamp}.log')
        fh = logging.FileHandler(log_path, encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter('%(asctime)s  %(name)s %(levelname)s  %(message)s'))
        logging.getLogger().addHandler(fh)
        print(f"[dev] logging to {log_path}")

    GameEngine(dev_mode=args.dev).run()