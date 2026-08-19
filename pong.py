#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PONG (1972) - full-screen remake for Windows 11.
Two players, Logitech F310 gamepads (X or D switch position both work).

Keys:  ESC quit | F11 / Alt+Enter windowed | P pause | R restart
       Player 1: W / S      Player 2: Up / Down
Pads:  left stick or D-pad. START (or SPACE) to serve.
"""

import array
import math
import random

import pygame

# ---------------------------------------------------------------- constants --
VW, VH = 640, 480                 # virtual (game) resolution, 4:3 like the original
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GREY = (110, 110, 110)

PADDLE_W, PADDLE_H = 10, 64
PADDLE_MARGIN = 28
PADDLE_SPEED = 430.0              # px/s in virtual units

BALL_SIZE = 10
BALL_SPEED_START = 300.0
BALL_SPEED_MAX = 820.0
BALL_SPEED_STEP = 22.0            # speed-up on every paddle hit
MAX_BOUNCE_ANGLE = math.radians(55)

WIN_SCORE = 11
SERVE_DELAY = 1.1                 # seconds between point and next serve
DEADZONE = 0.22

STATE_MENU, STATE_PLAY, STATE_OVER = 0, 1, 2

# ------------------------------------------------------------- 3x5 pixel font -
GLYPHS = {
    'A': ("010", "101", "111", "101", "101"),
    'B': ("110", "101", "110", "101", "110"),
    'C': ("011", "100", "100", "100", "011"),
    'D': ("110", "101", "101", "101", "110"),
    'E': ("111", "100", "110", "100", "111"),
    'F': ("111", "100", "110", "100", "100"),
    'G': ("011", "100", "101", "101", "011"),
    'H': ("101", "101", "111", "101", "101"),
    'I': ("111", "010", "010", "010", "111"),
    'J': ("001", "001", "001", "101", "010"),
    'K': ("101", "101", "110", "101", "101"),
    'L': ("100", "100", "100", "100", "111"),
    'M': ("101", "111", "111", "101", "101"),
    'N': ("101", "111", "111", "111", "101"),
    'O': ("010", "101", "101", "101", "010"),
    'P': ("110", "101", "110", "100", "100"),
    'Q': ("010", "101", "101", "111", "011"),
    'R': ("110", "101", "110", "101", "101"),
    'S': ("011", "100", "010", "001", "110"),
    'T': ("111", "010", "010", "010", "010"),
    'U': ("101", "101", "101", "101", "011"),
    'V': ("101", "101", "101", "101", "010"),
    'W': ("101", "101", "111", "111", "101"),
    'X': ("101", "101", "010", "101", "101"),
    'Y': ("101", "101", "010", "010", "010"),
    'Z': ("111", "001", "010", "100", "111"),
    '0': ("111", "101", "101", "101", "111"),
    '1': ("010", "110", "010", "010", "111"),
    '2': ("111", "001", "111", "100", "111"),
    '3': ("111", "001", "011", "001", "111"),
    '4': ("101", "101", "111", "001", "001"),
    '5': ("111", "100", "111", "001", "111"),
    '6': ("111", "100", "111", "101", "111"),
    '7': ("111", "001", "010", "010", "010"),
    '8': ("111", "101", "111", "101", "111"),
    '9': ("111", "101", "111", "001", "111"),
    ' ': ("000", "000", "000", "000", "000"),
    '-': ("000", "000", "111", "000", "000"),
    '.': ("000", "000", "000", "000", "010"),
    ':': ("000", "010", "000", "010", "000"),
    '/': ("001", "001", "010", "100", "100"),
}


def text_width(text, scale):
    return (len(text) * 4 - 1) * scale if text else 0


def draw_text(surf, text, x, y, scale=4, color=WHITE, center=False):
    """Blocky bitmap text - no external font files needed."""
    text = text.upper()
    if center:
        x -= text_width(text, scale) // 2
    for ch in text:
        rows = GLYPHS.get(ch, GLYPHS[' '])
        for ry, row in enumerate(rows):
            for rx, bit in enumerate(row):
                if bit == '1':
                    pygame.draw.rect(surf, color,
                                     (x + rx * scale, y + ry * scale, scale, scale))
        x += 4 * scale


# ------------------------------------------------------------------- sounds --
def make_beep(freq, ms, volume=0.35, sample_rate=44100):
    """Square wave, the way the 1972 cabinet sounded."""
    n = int(sample_rate * ms / 1000.0)
    period = max(2, int(sample_rate / freq))
    amp = int(32767 * volume)
    fade = max(1, int(n * 0.15))
    buf = array.array('h')
    for i in range(n):
        v = amp if (i % period) < period // 2 else -amp
        if i > n - fade:                       # short fade-out, avoids clicks
            v = int(v * (n - i) / fade)
        buf.append(v)
    return pygame.mixer.Sound(buffer=buf.tobytes())


class Sfx:
    def __init__(self):
        self.ok = False
        try:
            self.paddle = make_beep(480, 45)
            self.wall = make_beep(240, 35)
            self.score = make_beep(120, 220)
            self.ok = True
        except Exception:
            pass

    def play(self, name):
        if self.ok:
            try:
                getattr(self, name).play()
            except Exception:
                pass


# ------------------------------------------------------------------ players --
class Player:
    def __init__(self, side, up_keys, down_keys):
        self.side = side                       # 'L' or 'R'
        self.up_keys = up_keys
        self.down_keys = down_keys
        self.pad = None                        # pygame.joystick.Joystick or None
        self.cpu = False
        self.cpu_bias = 0.0                    # small aiming error, keeps the CPU beatable
        self.score = 0
        self.y = (VH - PADDLE_H) / 2.0
        self.x = PADDLE_MARGIN if side == 'L' else VW - PADDLE_MARGIN - PADDLE_W

    @property
    def rect(self):
        return pygame.Rect(int(self.x), int(self.y), PADDLE_W, PADDLE_H)

    def reset(self):
        self.y = (VH - PADDLE_H) / 2.0
        self.score = 0

    def axis(self, keys):
        """-1 = up, +1 = down."""
        v = 0.0
        if self.pad is not None:
            try:
                if self.pad.get_numaxes() > 1:
                    a = self.pad.get_axis(1)          # left stick Y (X and D mode)
                    if abs(a) > DEADZONE:
                        v = (abs(a) - DEADZONE) / (1 - DEADZONE) * (1 if a > 0 else -1)
                if v == 0.0 and self.pad.get_numhats() > 0:
                    hy = self.pad.get_hat(0)[1]       # D-pad
                    v = -float(hy)
            except Exception:
                self.pad = None
        if v == 0.0:
            if any(keys[k] for k in self.up_keys):
                v = -1.0
            elif any(keys[k] for k in self.down_keys):
                v = 1.0
        return max(-1.0, min(1.0, v))

    def update(self, dt, keys, ball):
        if self.cpu:
            target = ball.y + BALL_SIZE / 2 - PADDLE_H / 2
            if (self.side == 'R' and ball.vx < 0) or (self.side == 'L' and ball.vx > 0):
                target = (VH - PADDLE_H) / 2          # idle back to centre
            diff = target - self.y + self.cpu_bias
            v = max(-1.0, min(1.0, diff / 30.0)) * 0.86
        else:
            v = self.axis(keys)
        self.y += v * PADDLE_SPEED * dt
        self.y = max(0.0, min(VH - PADDLE_H, self.y))

    def rumble(self):
        if self.pad is not None:
            try:
                self.pad.rumble(0.0, 0.6, 90)         # F710 buzzes, F310 ignores it
            except Exception:
                pass


# --------------------------------------------------------------------- ball --
class Ball:
    def __init__(self):
        self.reset(random.choice((-1, 1)))

    def reset(self, direction):
        self.x = VW / 2 - BALL_SIZE / 2
        self.y = VH / 2 - BALL_SIZE / 2
        angle = random.uniform(-0.35, 0.35)
        self.speed = BALL_SPEED_START
        self.vx = math.cos(angle) * self.speed * direction
        self.vy = math.sin(angle) * self.speed

    @property
    def rect(self):
        return pygame.Rect(int(self.x), int(self.y), BALL_SIZE, BALL_SIZE)


# --------------------------------------------------------------------- game --
class Game:
    def __init__(self):
        pygame.mixer.pre_init(44100, -16, 1, 512)
        pygame.init()
        try:
            pygame.mixer.init(44100, -16, 1, 512)
        except Exception:
            pass
        pygame.display.set_caption("PONG")
        pygame.mouse.set_visible(False)

        self.fullscreen = True
        self.screen = self._make_screen()
        self.canvas = pygame.Surface((VW, VH))
        self.clock = pygame.time.Clock()
        self.sfx = Sfx()

        pygame.joystick.init()
        self.p1 = Player('L', (pygame.K_w,), (pygame.K_s,))
        self.p2 = Player('R', (pygame.K_UP,), (pygame.K_DOWN,))
        self.pads = []
        self.refresh_pads()

        self.ball = Ball()
        self.state = STATE_MENU
        self.serve_timer = 0.0
        self.paused = False
        self.two_players = True
        self.winner = None
        self.rally = 0

    # ---------------------------------------------------------------- video --
    def _make_screen(self):
        if self.fullscreen:
            return pygame.display.set_mode((0, 0), pygame.FULLSCREEN | pygame.DOUBLEBUF)
        return pygame.display.set_mode((960, 720), pygame.RESIZABLE | pygame.DOUBLEBUF)

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self.screen = self._make_screen()
        pygame.mouse.set_visible(not self.fullscreen)

    def present(self):
        sw, sh = self.screen.get_size()
        scale = min(sw / VW, sh / VH)
        w, h = int(VW * scale), int(VH * scale)
        self.screen.fill(BLACK)
        self.screen.blit(pygame.transform.scale(self.canvas, (w, h)),
                         ((sw - w) // 2, (sh - h) // 2))
        pygame.display.flip()

    # ---------------------------------------------------------------- input --
    def refresh_pads(self):
        for p in self.pads:
            try:
                p.quit()
            except Exception:
                pass
        self.pads = []
        for i in range(pygame.joystick.get_count()):
            try:
                j = pygame.joystick.Joystick(i)
                j.init()
                self.pads.append(j)
            except Exception:
                pass
        self.p1.pad = self.pads[0] if len(self.pads) > 0 else None
        self.p2.pad = self.pads[1] if len(self.pads) > 1 else None

    def pad_names(self):
        if not self.pads:
            return "NO GAMEPADS - KEYBOARD ONLY"
        return "GAMEPADS FOUND: %d" % len(self.pads)

    # ----------------------------------------------------------------- flow --
    def start(self, two_players):
        self.two_players = two_players
        self.p1.reset()
        self.p2.reset()
        self.p1.cpu = False
        self.p2.cpu = not two_players
        self.ball.reset(random.choice((-1, 1)))
        self.serve_timer = SERVE_DELAY
        self.rally = 0
        self.paused = False
        self.winner = None
        self.state = STATE_PLAY

    def point_to(self, player):
        player.score += 1
        self.sfx.play('score')
        self.rally = 0
        if player.score >= WIN_SCORE:
            self.winner = player
            self.state = STATE_OVER
        else:
            loser = self.p2 if player is self.p1 else self.p1
            self.ball.reset(-1 if loser is self.p1 else 1)
            self.serve_timer = SERVE_DELAY

    # --------------------------------------------------------------- update --
    def update(self, dt):
        keys = pygame.key.get_pressed()
        if self.state != STATE_PLAY or self.paused:
            return

        self.p1.update(dt, keys, self.ball)
        self.p2.update(dt, keys, self.ball)

        if self.serve_timer > 0:
            self.serve_timer -= dt
            return

        b = self.ball
        steps = max(1, int(max(abs(b.vx), abs(b.vy)) * dt / 4) + 1)
        sdt = dt / steps
        for _ in range(steps):
            b.x += b.vx * sdt
            b.y += b.vy * sdt

            if b.y <= 0:
                b.y = 0
                b.vy = abs(b.vy)
                self.sfx.play('wall')
            elif b.y + BALL_SIZE >= VH:
                b.y = VH - BALL_SIZE
                b.vy = -abs(b.vy)
                self.sfx.play('wall')

            for pl in (self.p1, self.p2):
                if not b.rect.colliderect(pl.rect):
                    continue
                moving_into = (b.vx < 0 and pl.side == 'L') or (b.vx > 0 and pl.side == 'R')
                if not moving_into:
                    continue
                offset = ((b.y + BALL_SIZE / 2) - (pl.y + PADDLE_H / 2)) / (PADDLE_H / 2)
                offset = max(-1.0, min(1.0, offset))
                angle = offset * MAX_BOUNCE_ANGLE
                b.speed = min(BALL_SPEED_MAX, b.speed + BALL_SPEED_STEP)
                direction = 1 if pl.side == 'L' else -1
                b.vx = math.cos(angle) * b.speed * direction
                b.vy = math.sin(angle) * b.speed
                b.x = (pl.x + PADDLE_W) if pl.side == 'L' else (pl.x - BALL_SIZE)
                self.rally += 1
                for other in (self.p1, self.p2):
                    other.cpu_bias = random.uniform(-14.0, 14.0)
                self.sfx.play('paddle')
                pl.rumble()

            if b.x + BALL_SIZE < 0:
                self.point_to(self.p2)
                return
            if b.x > VW:
                self.point_to(self.p1)
                return

    # ----------------------------------------------------------------- draw --
    def draw_court(self):
        c = self.canvas
        c.fill(BLACK)
        dash_h, gap = 14, 10
        y = 4
        while y < VH:
            pygame.draw.rect(c, WHITE, (VW // 2 - 3, y, 6, min(dash_h, VH - y)))
            y += dash_h + gap
        pygame.draw.rect(c, WHITE, self.p1.rect)
        pygame.draw.rect(c, WHITE, self.p2.rect)

    def draw_scores(self):
        draw_text(self.canvas, str(self.p1.score), VW // 2 - 70, 30, 8, WHITE, center=True)
        draw_text(self.canvas, str(self.p2.score), VW // 2 + 70, 30, 8, WHITE, center=True)

    def draw(self):
        c = self.canvas
        if self.state == STATE_MENU:
            c.fill(BLACK)
            draw_text(c, "PONG", VW // 2, 90, 10, WHITE, center=True)
            draw_text(c, "1 - ONE PLAYER VS CPU", VW // 2, 210, 3, WHITE, center=True)
            draw_text(c, "2 - TWO PLAYERS", VW // 2, 240, 3, WHITE, center=True)
            draw_text(c, "START OR SPACE TO PLAY", VW // 2, 290, 3, GREY, center=True)
            draw_text(c, self.pad_names(), VW // 2, 330, 3, GREY, center=True)
            draw_text(c, "P1 W/S   P2 UP/DOWN   ESC QUIT", VW // 2, 400, 2, GREY, center=True)
            draw_text(c, "F11 WINDOW   P PAUSE   R MENU", VW // 2, 425, 2, GREY, center=True)
        else:
            self.draw_court()
            self.draw_scores()
            pygame.draw.rect(c, WHITE, self.ball.rect)
            if self.state == STATE_OVER:
                who = "PLAYER 1" if self.winner is self.p1 else \
                      ("CPU" if self.winner.cpu else "PLAYER 2")
                draw_text(c, who + " WINS", VW // 2, VH // 2 - 40, 6, WHITE, center=True)
                draw_text(c, "SPACE OR START - AGAIN", VW // 2, VH // 2 + 20, 3, GREY, center=True)
                draw_text(c, "ESC - QUIT", VW // 2, VH // 2 + 50, 3, GREY, center=True)
            elif self.paused:
                draw_text(c, "PAUSE", VW // 2, VH // 2 - 20, 6, WHITE, center=True)
            elif self.serve_timer > 0:
                draw_text(c, "GET READY", VW // 2, VH - 70, 3, GREY, center=True)
        self.present()

    # ----------------------------------------------------------------- loop --
    def confirm_pressed(self, event):
        """SPACE / ENTER / A, B, START on a pad."""
        if event.type == pygame.KEYDOWN:
            return event.key in (pygame.K_SPACE, pygame.K_RETURN, pygame.K_KP_ENTER)
        if event.type == pygame.JOYBUTTONDOWN:
            return event.button in (0, 1, 6, 7, 9, 11)
        return False

    def run(self):
        running = True
        while running:
            dt = min(self.clock.tick(120) / 1000.0, 0.05)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type in (pygame.JOYDEVICEADDED, pygame.JOYDEVICEREMOVED):
                    self.refresh_pads()
                elif event.type == pygame.KEYDOWN:
                    alt = pygame.key.get_mods() & pygame.KMOD_ALT
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_F11 or (event.key == pygame.K_RETURN and alt):
                        self.toggle_fullscreen()
                        continue
                    elif event.key == pygame.K_p and self.state == STATE_PLAY:
                        self.paused = not self.paused
                    elif event.key == pygame.K_r:
                        self.state = STATE_MENU
                    elif event.key == pygame.K_1:
                        self.start(False)
                    elif event.key == pygame.K_2:
                        self.start(True)

                if self.confirm_pressed(event):
                    if self.state in (STATE_MENU, STATE_OVER):
                        self.start(self.two_players)
                    elif self.paused:
                        self.paused = False

            self.update(dt)
            self.draw()
        pygame.quit()


if __name__ == "__main__":
    try:
        Game().run()
    except Exception:
        pygame.quit()
        raise
