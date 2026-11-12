#!/usr/bin/env python3
"""
Текстовый арканоид на curses (версия 3).

Запуск:
    python arkanoid.py
    python arkanoid.py --fps 60 --lives 5 --seed 42 --no-sound
    python arkanoid.py --smoke 30     # проверка физики без терминала

Управление:
    ← →  (или h/l) — движение ракетки, удержание работает
    Пробел         — запустить / поймать шарик
    Мышь           — ракетка следует за курсором
    p              — пауза
    s              — звук вкл/выкл
    r              — начать заново
    q              — выход

Физика (функции advance/step_ball) намеренно отделена от curses: её можно
тестировать и прогонять без терминала — см. --smoke и tests/test_physics.py.
"""

from __future__ import annotations

import argparse
import curses
import locale
import os
import random
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

# --- Арена -----------------------------------------------------------------
# Поле сознательно ограничено по размеру: на терминале 200x60 «арканоид»
# превращается в бесконечное блуждание шарика, и уровень нельзя пройти.
ARENA_MAX_WIDTH = 40    # внутренняя ширина поля
ARENA_MAX_HEIGHT = 16   # внутренняя высота поля

# --- Скорости (клеток в секунду) -------------------------------------------
BALL_SPEED = 18.0       # базовая скорость шарика
BALL_SPEED_PER_LEVEL = 1.5
BALL_SPEED_MAX = 34.0
PADDLE_SPEED = 34.0
POWERUP_SPEED = 7.0
MAX_STEPS_PER_FRAME = 4  # страховка от «телепорта» при просадке FPS

STALL_SECONDS = 12.0    # если кирпичей нет так долго — слегка рулим шариком

# --- Начисление очков -------------------------------------------------------
POINTS_BRICK = 10
POINTS_COMBO = 2
COMBO_MAX = 10

# --- Внешний вид ------------------------------------------------------------
# Символы кирпича по остаточной прочности (1..3)
BRICK_GLYPHS = {1: "▒", 2: "▓", 3: "█"}
BRICK_HP_BY_CHAR = {"#": 1, "%": 2, "&": 3}

FALLBACK_GLYPHS = {
    "brick": {1: "#", 2: "#", 3: "#"},
    "ball": "O",
    "paddle": "=",
    "wall_h": "-",
    "wall_v": "|",
}

# Карты уровней: '.' — пусто, '#', '%', '&' — кирпичи с прочностью 1..3.
# Строки тайлятся по ширине окна, поэтому уровень годится для любого терминала.
LEVELS = [
    ("#####", "#.#.#"),
    ("#%#%#", "#.%.#", "#####"),
    ("&.%.#", "#.&.%", "%.#.&", "....."),
    ("#####", "%%%%%", "&.#.&", ".....", "#.#.#"),
    ("&.&.&", "%%%%%", "#.#.#", "&%&#%", "....."),
]

# Вид бонусов: код -> (символ на поле, расшифровка для README)
POWERUPS = {
    "E": ("E", "ракетка шире"),
    "S": ("S", "замедление шарика"),
    "L": ("L", "+1 жизнь"),
    "M": ("M", "ещё один шарик"),
}
POWERUP_CHANCE = 0.12


@dataclass
class Arena:
    """
    Рамка игрового поля, вписанная в размер терминала.

    top/bottom — строки стенок, внутри между ними играют шарик, ракетка
    и кирпичи. Под нижней стенкой — строка с подсказкой.
    """

    left: int = 0
    right: int = 10
    top: int = 1
    bottom: int = 10

    @classmethod
    def fit(cls, width: int, height: int) -> "Arena":
        inner_w = max(14, min(width - 2, ARENA_MAX_WIDTH))
        inner_h = max(9, min(height - 4, ARENA_MAX_HEIGHT))

        left = max(0, (width - inner_w) // 2 - 1)
        right = min(width - 1, left + inner_w + 1)
        top = 1 + max(0, (height - 4 - inner_h) // 2)
        bottom = min(height - 1, top + inner_h + 1)
        return cls(left=left, right=right, top=top, bottom=bottom)

    @property
    def inner_left(self) -> int:
        return self.left + 1

    @property
    def inner_right(self) -> int:
        return max(self.left + 2, self.right - 1)

    @property
    def inner_width(self) -> int:
        return max(1, self.inner_right - self.inner_left + 1)

    @property
    def play_rows(self) -> int:
        return max(3, self.bottom - self.top - 1)

    @property
    def ceiling(self) -> int:
        """Самая верхняя строка, куда заходит шарик."""
        return self.top + 1

    @property
    def brick_top(self) -> int:
        """Первый ряд кирпичей: на строку ниже «потолка», чтобы было где отскочить."""
        return self.top + 2

    @property
    def paddle_y(self) -> int:
        return self.bottom - 1

    @property
    def floor_y(self) -> int:
        """Шарик дошёл до нижней стенки — жизнь потеряна."""
        return self.bottom

    @property
    def hint_y(self) -> int:
        return self.bottom + 1


@dataclass
class Config:
    """Все настраиваемые правила игры в одном месте."""

    fps: int = 60
    lives: int = 3
    paddle_width: int = 7
    ball_speed: float = BALL_SPEED
    sound: bool = True
    color: bool = True
    powerups: bool = True
    seed: int | None = None   # None — случайное зерно
    highscore_file: Path = Path(
        os.environ.get("ARKANOID_SCORE", "~/.local/share/arkanoid/score.json")
    )


@dataclass
class Ball:
    """Шарик: целая клетка + накопитель дробного движения."""

    x: int
    y: int
    vx: int = 0
    vy: int = -1
    acc: float = 0.0
    stuck: bool = True   # прилип к ракетке до запуска
    dead: bool = False


@dataclass
class PowerUp:
    x: int
    y: float
    kind: str


@dataclass
class World:
    """Всё состояние игры. Не знает ничего про curses."""

    width: int
    height: int
    cfg: Config
    arena: Arena = field(default_factory=Arena)
    rng: random.Random = field(default_factory=random.Random)

    score: int = 0
    lives: int = 3
    level: int = 1
    over: bool = False

    bricks: list[list[int]] = field(default_factory=list)
    balls: list[Ball] = field(default_factory=list)
    powerups: list[PowerUp] = field(default_factory=list)

    paddle_pos: float = 0.0              # положение ракетки (вещественное — плавный ход)
    paddle_target: float | None = None   # цель от мыши
    paddle_dir: int = 0                  # -1 / 0 / 1 при удержании клавиши

    combo: int = 0
    speed: float = BALL_SPEED
    effects: dict[str, float] = field(default_factory=dict)
    since_brick: float = 0.0

    def __post_init__(self) -> None:
        if self.cfg.seed is not None:
            self.rng = random.Random(self.cfg.seed)
        self.lives = self.cfg.lives
        self.speed = self.cfg.ball_speed
        self.arena = Arena.fit(self.width, self.height)
        self.paddle_pos = float(self.arena.inner_left + (self.arena.inner_width - self.cfg.paddle_width) // 2)
        self.reset_level()
        self.spawn_ball()

    # --- геометрия ---------------------------------------------------------
    @property
    def paddle_x(self) -> int:
        return int(round(self.paddle_pos))

    @property
    def paddle_y(self) -> int:
        return self.arena.paddle_y

    @property
    def floor_y(self) -> int:
        """Строка, за которой шарик считается пропущенным."""
        return self.arena.floor_y

    @property
    def ceiling(self) -> int:
        return self.arena.ceiling

    @property
    def left(self) -> int:
        return self.arena.inner_left

    @property
    def brick_top(self) -> int:
        return self.arena.brick_top

    @property
    def field_right(self) -> int:
        return self.arena.inner_right

    @property
    def paddle_width(self) -> int:
        return self.cfg.paddle_width + (2 if self.effects.get("E", 0) > 0 else 0)

    @property
    def ball_speed_now(self) -> float:
        factor = 0.6 if self.effects.get("S", 0) > 0 else 1.0
        return self.speed * factor

    # --- уровни ------------------------------------------------------------
    def reset_level(self) -> None:
        """Собирать кирпичи заново (размер окна может отличаться от прошлого)."""
        rows, cols = self.brick_grid_size()
        layout = LEVELS[(self.level - 1) % len(LEVELS)]
        self.bricks = []
        for r in range(rows):
            pattern = layout[r % len(layout)]
            self.bricks.append(
                [BRICK_HP_BY_CHAR.get(pattern[c % len(pattern)], 0) for c in range(cols)]
            )

    def brick_grid_size(self) -> tuple[int, int]:
        # Ряды тайлятся сверху вниз, поэтому уровень можно «развернуть» на любую
        # высоту: чем выше уровень, тем толще стена (и тем быстрее шарик).
        rows = min(2 + self.level // 2, (self.arena.play_rows - 3) // 2)
        return max(1, rows), self.arena.inner_width

    def bricks_left(self) -> bool:
        return any(cell for row in self.bricks for cell in row)

    # --- шарики ------------------------------------------------------------
    def spawn_ball(self) -> Ball:
        ball = Ball(x=0, y=0, stuck=True)
        self.balls.append(ball)
        self.place_stuck(ball)
        return ball

    def place_stuck(self, ball: Ball) -> None:
        ball.stuck = True
        ball.vx, ball.vy = 0, -1
        ball.acc = 0.0
        ball.dead = False
        ball.x = min(max(self.paddle_x + self.paddle_width // 2, self.left), self.field_right)
        ball.y = max(self.ceiling + 1, self.paddle_y - 1)

    def launch(self) -> bool:
        """Запуск прилипшего шарика. False — если на поле нет прилипшего."""
        launched = False
        for ball in self.balls:
            if ball.stuck:
                ball.stuck = False
                ball.vx = self.rng.choice((-1, 1))
                ball.vy = -1
                launched = True
        return launched

    def next_level(self) -> None:
        self.level += 1
        self.speed = min(BALL_SPEED_MAX, self.cfg.ball_speed + BALL_SPEED_PER_LEVEL * (self.level - 1))
        self.balls = []
        self.powerups = []
        self.reset_level()
        self.spawn_ball()


def new_world(width: int, height: int, cfg: Config) -> World:
    return World(width=width, height=height, cfg=cfg)


# ---------------------------------------------------------------------------
# Физика. Чистые функции: аргументы — World и dt, результат — список событий.
# ---------------------------------------------------------------------------
Event = str


def brick_row_col(world: World, x: int, y: int) -> tuple[int, int] | None:
    """Индекс ряда/колонки кирпича по координатам поля (или None)."""
    row = y - world.brick_top
    col = x - world.left
    if 0 <= row < len(world.bricks) and 0 <= col < len(world.bricks[row]):
        return row, col
    return None


def brick_hp(world: World, x: int, y: int) -> int:
    """Прочность кирпича в клетке (0 — клетка пуста)."""
    pos = brick_row_col(world, x, y)
    return world.bricks[pos[0]][pos[1]] if pos else 0


def damage_brick(world: World, x: int, y: int, events: list[Event]) -> bool | None:
    """
    Снять единицу прочности с кирпича в клетке (x, y).

    None  — кирпича там нет;
    False — треснул, но держится (шарик отскакивает);
    True  — разбит (шарик летит дальше — сквозь выбитую брешь).
    """
    pos = brick_row_col(world, x, y)
    if pos is None or world.bricks[pos[0]][pos[1]] <= 0:
        return None

    row, col = pos
    world.bricks[row][col] -= 1
    world.combo += 1
    world.since_brick = 0.0

    if world.bricks[row][col] == 0:
        world.score += POINTS_BRICK + POINTS_COMBO * min(world.combo, COMBO_MAX)
        maybe_drop_powerup(world, x, y)
        events.append("brick_break")
        return True

    world.score += 2
    events.append("brick")
    return False


def on_paddle(world: World, x: int) -> bool:
    return world.paddle_x <= x <= world.paddle_x + world.paddle_width - 1


def paddle_bounce(world: World, ball: Ball) -> int:
    """
    Новый vx после удара о ракетку: |vx| ∈ {1, 2}.

    Край ракетки даёт крутой («быстрый») угол, центр — пологий. Нулевого vx
    нет намеренно: вертикальный «столб» в одной колонке — это вечный размен
    и бесконечные очки (баг прошлой версии). А два разных угла ломают
    периодическую траекторию, в которую шарик иначе залетает надолго.
    """
    half = max(1, world.paddle_width // 2 - 1)
    offset = ball.x - (world.paddle_x + world.paddle_width // 2)

    if abs(offset) >= half:
        return (2 if abs(offset) >= half + 1 else 1) * (1 if offset > 0 else -1)
    if abs(ball.vx) == 1:
        return ball.vx
    return 1 if ball.vx > 0 else -1


def move_x(world: World, ball: Ball, events: list[Event]) -> bool:
    """
    Сдвиг по X на vx клеток, но строго по одной клетке за проверку — иначе
    быстрая «двойная» скорость проскакивала бы колонку кирпичей насквозь.

    False — был отскок, шаг по Y в этом ходе пропускаем.
    """
    for _ in range(abs(ball.vx)):
        nx = ball.x + (1 if ball.vx > 0 else -1)

        # Мяч может стоять ровно у стенки (это же крайний столбец кирпичей),
        # поэтому отскок — только если следующая клетка ВЫХОДИТ за поле.
        # Раньше условие было «<= left», и крайние столбцы кирпичей
        # оказывались недостижимы: уровень нельзя было пройти.
        if nx < world.left or nx > world.field_right:
            ball.vx = -ball.vx
            events.append("wall")
            return False
        if damage_brick(world, nx, ball.y, events) is False:
            ball.vx = -ball.vx
            return False
        ball.x = nx

    return True


def move_y(world: World, ball: Ball, events: list[Event]) -> None:
    ny = ball.y + ball.vy

    if ny <= world.ceiling:
        ball.y = world.ceiling
        ball.vy = -ball.vy
        events.append("wall")
        return

    # Удар о ракетку: проверка «пересёк линию», а не «оказался ровно на строке»,
    # чтобы быстрый шарик не пролетал сквозь ракетку.
    if ball.vy > 0 and ny >= world.paddle_y and ball.y < world.paddle_y:
        if on_paddle(world, ball.x):
            ball.y = world.paddle_y
            ball.vy = -1
            ball.vx = paddle_bounce(world, ball)
            world.combo = 0
            events.append("paddle")
            return

    if damage_brick(world, ball.x, ny, events) is False:
        # Работает в обе стороны: на картах с проходами шарик успевает
        # залезть под кирпичи и прилететь в них сверху.
        ball.vy = -ball.vy
        return

    ball.y = ny

    if ball.y >= world.floor_y:
        ball.dead = True
        events.append("life")


def step_ball(world: World, ball: Ball, dt: float, events: list[Event]) -> None:
    if ball.stuck:
        world.place_stuck(ball)
        return

    ball.acc += world.ball_speed_now * dt
    for _ in range(MAX_STEPS_PER_FRAME):
        if ball.acc < 1.0:
            break
        ball.acc -= 1.0
        if move_x(world, ball, events) and not ball.dead:
            move_y(world, ball, events)
        if ball.dead:
            return
    ball.acc = min(ball.acc, 1.0)


def maybe_drop_powerup(world: World, x: int, y: int) -> None:
    if not world.cfg.powerups or world.rng.random() >= POWERUP_CHANCE:
        return
    world.powerups.append(
        PowerUp(x=x, y=float(y), kind=world.rng.choice(sorted(POWERUPS)))
    )


def apply_powerup(world: World, kind: str, events: list[Event]) -> None:
    events.append("powerup")
    if kind == "E":
        world.effects["E"] = 12.0
    elif kind == "S":
        world.effects["S"] = 8.0
    elif kind == "L":
        world.lives += 1
    elif kind == "M":
        # Зеркальный шарик от каждого летящего, но не больше трёх на поле.
        extra: list[Ball] = []
        for ball in world.balls:
            if not ball.stuck and len(world.balls) + len(extra) < 3:
                extra.append(Ball(x=ball.x, y=ball.y, vx=-ball.vx, vy=ball.vy, stuck=False))
        world.balls.extend(extra)


def step_powerups(world: World, dt: float, events: list[Event]) -> None:
    alive: list[PowerUp] = []
    for item in world.powerups:
        item.y += POWERUP_SPEED * dt
        row = int(item.y)
        if row >= world.paddle_y and on_paddle(world, item.x):
            apply_powerup(world, item.kind, events)
            continue
        if row < world.floor_y:
            alive.append(item)
    world.powerups = alive


def move_paddle(world: World, dt: float) -> None:
    """Ракетка: удержание клавиши или плавное следование за мышью."""
    if world.paddle_target is not None:
        delta = world.paddle_target - world.paddle_pos
        step = PADDLE_SPEED * dt
        world.paddle_pos += max(-step, min(step, delta))
    else:
        world.paddle_pos += world.paddle_dir * PADDLE_SPEED * dt

    world.paddle_pos = float(
        clamp(world.paddle_pos, world.left, max(world.left, world.field_right - world.paddle_width + 1))
    )


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def tick_effects(world: World, dt: float) -> None:
    for kind in list(world.effects):
        world.effects[kind] -= dt
        if world.effects[kind] <= 0:
            del world.effects[kind]


def anti_stall(world: World, dt: float, events: list[Event]) -> None:
    """
    Если шарик долго не трогает кирпичи — меняем ему наклон.

    Знак vx менять мало: траектория отражается зеркально и тот же цикл
    повторяется. А вот переход 1 <-> 2 меняет наклон и выводит шарик
    из «орбиты» между пустыми колонками.
    """
    world.since_brick += dt
    if world.since_brick < STALL_SECONDS:
        return
    world.since_brick = 0.0
    for ball in world.balls:
        if not ball.stuck and not ball.dead:
            ball.vx = (1 if abs(ball.vx) == 2 else 2) * world.rng.choice((-1, 1))
            events.append("nudge")
            break


def advance(world: World, dt: float) -> list[Event]:
    """Продвинуть мир на dt секунд и вернуть список событий."""
    events: list[Event] = []
    if world.over:
        return events

    tick_effects(world, dt)
    move_paddle(world, dt)

    for ball in list(world.balls):
        step_ball(world, ball, dt, events)

    step_powerups(world, dt, events)

    alive = [ball for ball in world.balls if not ball.dead]
    if len(alive) != len(world.balls):
        world.balls = alive

    if not world.balls:
        world.lives -= 1
        world.combo = 0
        if world.lives <= 0:
            world.over = True
            events.append("over")
        else:
            world.spawn_ball()

    if not world.bricks_left():
        events.append("level")
        world.next_level()

    anti_stall(world, dt, events)
    return events


def resize(world: World, width: int, height: int) -> None:
    """Пересобрать мир под новый размер терминала (ключ curses.KEY_RESIZE)."""
    if (width, height) == (world.width, world.height):
        return

    world.width, world.height = width, height
    world.arena = Arena.fit(width, height)
    world.paddle_pos = float(
        clamp(world.paddle_pos, world.left, max(world.left, world.field_right - world.paddle_width + 1))
    )
    world.reset_level()
    world.powerups = []
    world.balls = []
    world.spawn_ball()


# ---------------------------------------------------------------------------
# Звук
# ---------------------------------------------------------------------------
class Sound:
    """
    Озвучка через curses.beep()/flash().

    beep() дёргается не чаще SOUND_COOLDOWN секунд, иначе быстрый шарик
    превращает терминал в непрерывную сирену. flash() — только для потери жизни.
    """

    SOUNDS = {
        "paddle": "beep",
        "brick": "beep",
        "brick_break": "beep",
        "wall": "beep",
        "powerup": "beep",
        "level": "beep",
        "nudge": "beep",
        "life": "flash",
        "over": "flash",
    }

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._last = 0.0

    def play(self, events: list[Event]) -> None:
        if not self.enabled or not events:
            return
        kind = "flash" if any(self.SOUNDS.get(e) == "flash" for e in events) else "beep"
        now = time.monotonic()
        if kind == "beep" and now - self._last < 0.04:
            return
        self._last = now
        try:
            if kind == "flash":
                curses.flash()
            curses.beep()
        except curses.error:
            pass


# ---------------------------------------------------------------------------
# Отрисовка
# ---------------------------------------------------------------------------
HINT = "← → / h l — ракетка · Пробел — пуск/ловля · p — пауза · s — звук · r — заново · q — выход"
POWERUP_HINT = "бонусы: E шире · S тормоз · L жизнь · M мульти"


class Renderer:
    """
    покадровый буфер + вывод только изменившихся клеток.

    Это убирает мерцание (в прошлой версии каждый кадр шёл erase() и полная
    перерисовка) и заметно сокращает объём вывода в терминал.
    """

    def __init__(self, scr, color: bool = True) -> None:
        self.scr = scr
        self.unicode = _utf8_term()
        self.glyph = {
            "brick": BRICK_GLYPHS if self.unicode else FALLBACK_GLYPHS["brick"],
            "ball": "●" if self.unicode else FALLBACK_GLYPHS["ball"],
            "paddle": "▬" if self.unicode else FALLBACK_GLYPHS["paddle"],
            "wall_v": "│" if self.unicode else FALLBACK_GLYPHS["wall_v"],
            "wall_h": "─" if self.unicode else FALLBACK_GLYPHS["wall_h"],
            "life": "♥" if self.unicode else "o",
        }
        self.attr = self._init_attrs(color)
        self.resize(*scr.getmaxyx())

    @staticmethod
    def _init_attrs(color: bool) -> dict[str, int]:
        attrs = {
            "brick": {1: curses.A_NORMAL, 2: curses.A_DIM, 3: curses.A_BOLD},
            "ball": curses.A_BOLD,
            "paddle": curses.A_BOLD,
            "wall": curses.A_DIM,
            "hud": curses.A_BOLD,
            "powerup": curses.A_BOLD,
            "msg": curses.A_BOLD,
            "dim": curses.A_DIM,
            "over": curses.A_BOLD,
        }
        if not color or not curses.has_colors():
            return attrs

        try:
            curses.start_color()
            curses.use_default_colors()
        except curses.error:
            return attrs

        if curses.COLORS < 8:
            return attrs

        brick_colors = {
            1: curses.COLOR_YELLOW,
            2: curses.COLOR_MAGENTA,
            3: curses.COLOR_CYAN,
        }
        single_colors = {
            "ball": curses.COLOR_WHITE,
            "paddle": curses.COLOR_GREEN,
            "wall": curses.COLOR_BLUE,
            "hud": curses.COLOR_CYAN,
            "powerup": curses.COLOR_RED,
            "msg": curses.COLOR_YELLOW,
            "dim": -1,
            "over": curses.COLOR_RED,
        }

        index = 1
        for hp, colour in brick_colors.items():
            try:
                curses.init_pair(index, colour, -1)
            except curses.error:
                continue
            attrs["brick"][hp] |= curses.color_pair(index)
            index += 1

        for name, colour in single_colors.items():
            try:
                curses.init_pair(index, colour, -1)
            except curses.error:
                continue
            attrs[name] |= curses.color_pair(index)
            index += 1

        return attrs

    # --- буфер кадров ------------------------------------------------------
    def resize(self, height: int, width: int) -> None:
        self.h, self.w = height, width
        self.blank = [(" ", 0)] * max(0, width)
        self.cells = [list(self.blank) for _ in range(max(0, height))]
        self.prev = [list(self.blank) for _ in range(max(0, height))]

    def begin(self) -> None:
        for row in self.cells:
            row[:] = self.blank

    def put(self, y: int, x: int, text: str, attr: int = 0) -> None:
        if not text or not (0 <= y < self.h):
            return
        row = self.cells[y]
        for offset, ch in enumerate(text):
            col = x + offset
            if 0 <= col < self.w:
                row[col] = (ch, attr)

    def put_centered(self, y: int, text: str, attr: int = 0) -> None:
        self.put(y, (self.w - len(text)) // 2, text, attr)

    def flush(self) -> None:
        for y, (row, old) in enumerate(zip(self.cells, self.prev)):
            run_start = 0
            while run_start < self.w:
                ch, attr = row[run_start]
                end = run_start + 1
                while end < self.w and row[end] == (ch, attr):
                    end += 1
                if row[run_start:end] != old[run_start:end]:
                    try:
                        self.scr.addstr(y, run_start, "".join(c for c, _ in row[run_start:end]), attr)
                    except curses.error:
                        pass  # правый нижний угол curses не умеет
                run_start = end
        self.prev, self.cells = self.cells, self.prev

    # --- содержимое кадра --------------------------------------------------
    def draw(self, world: World, *, record: int, paused: bool, message: str = "",
             message_until: float = 0.0) -> None:
        now = time.monotonic()
        self.begin()

        lives = self.glyph["life"] * max(0, min(world.lives, 8))
        hud = f" Счёт {world.score}  Рекорд {max(record, world.score)}  {lives}  Уровень {world.level} "
        self.put(0, 0, hud, self.attr["hud"])

        for y in range(world.arena.top, world.floor_y + 1):
            self.put(y, world.arena.left, self.glyph["wall_v"], self.attr["wall"])
            self.put(y, world.arena.right, self.glyph["wall_v"], self.attr["wall"])
        self.put(world.floor_y, world.arena.left, self.glyph["wall_h"] * (world.arena.right - world.arena.left + 1),
                 self.attr["wall"])
        self.put(world.arena.top, world.arena.left,
                 self.glyph["wall_h"] * (world.arena.right - world.arena.left + 1), self.attr["wall"])

        for row_index, row in enumerate(world.bricks):
            y = world.brick_top + row_index
            for col_index, hp in enumerate(row):
                if hp > 0:
                    self.put(y, world.left + col_index, self.glyph["brick"].get(hp, "#"),
                             self.attr["brick"].get(hp, self.attr["brick"][1]))

        for item in world.powerups:
            sign = POWERUPS.get(item.kind, ("?", ""))[0]
            self.put(int(item.y), item.x, sign, self.attr["powerup"])

        self.put(world.paddle_y, world.paddle_x, self.glyph["paddle"] * world.paddle_width,
                 self.attr["paddle"])

        for ball in world.balls:
            self.put(ball.y, ball.x, self.glyph["ball"], self.attr["ball"])

        hint = HINT
        self.put(world.arena.hint_y, 0, hint[: world.width - 1], self.attr["dim"])
        legend_y = world.arena.hint_y + 1
        if legend_y < world.height:
            self.put(legend_y, 0, POWERUP_HINT[: world.width - 1], self.attr["dim"])

        if world.effects:
            signs = " ".join(f"{k}:{int(round(v))}s" for k, v in sorted(world.effects.items()))
            self.put(1, world.width - len(signs) - 2, signs, self.attr["powerup"])
        if message and now < message_until:
            self.put_centered(world.paddle_y - 3, f" {message} ", self.attr["msg"])

        if paused and not world.over:
            self.overlay(["ПАУЗА", "p — продолжить"])
        elif world.over:
            self.overlay(
                [
                    "ИГРА ОКОНЧЕНА",
                    f"Счёт {world.score}   Рекорд {max(record, world.score)}   Уровень {world.level}",
                    "r — заново    q — выход",
                ]
            )

        self.flush()

    def overlay(self, lines: list[str]) -> None:
        """Полупрозрачная плашка по центру поверх поля."""
        if not lines:
            return
        width = max(len(line) for line in lines) + 4
        top = max(2, (self.h - len(lines)) // 2 - 1)
        if self.h < 8 or self.w < width + 2:
            return
        for index, line in enumerate(lines):
            y = top + index
            self.put(y, (self.w - width) // 2, " " * width, curses.A_REVERSE)
            self.put_centered(y, line, curses.A_REVERSE | self.attr["msg" if index == 0 else "over"])


def _utf8_term() -> bool:
    """Рисуем «красивые» символы только если терминал точно в UTF-8."""
    encoding = (locale.getpreferredencoding(False) or "").lower()
    return "utf" in encoding


# ---------------------------------------------------------------------------
# Рекорды
# ---------------------------------------------------------------------------
def load_record(path: Path) -> int:
    try:
        return int(path.read_text().strip() or 0)
    except (OSError, ValueError):
        return 0


def save_record(path: Path, value: int) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(value))
    except OSError:
        pass  # рекорд — не критично


# ---------------------------------------------------------------------------
# Игра: ввод, цикл, размеры терминала
# ---------------------------------------------------------------------------
HOLD_SECONDS = 0.15   # «удержание» клавиши: автоповтор продлевает это окно
MIN_HEIGHT = 14
MIN_WIDTH = 40


class Game:
    def __init__(self, stdscr, cfg: Config) -> None:
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        stdscr.keypad(True)
        stdscr.nodelay(True)
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        except curses.error:
            pass

        self.scr = stdscr
        self.cfg = cfg
        self.renderer = Renderer(stdscr, cfg.color)
        self.sound = Sound(cfg.sound)
        height, width = stdscr.getmaxyx()
        self.world = new_world(width, height, cfg)
        self.record = load_record(cfg.highscore_file)
        self.paused = False
        self.record_dirty = False
        self.message = "Пробел — запустить шарик"
        self.message_until = time.monotonic() + 3.0
        self.hold_until = 0.0
        self.mouse_until = 0.0

    # --- главный цикл ------------------------------------------------------
    def run(self) -> None:
        step = 1.0 / self.cfg.fps
        previous = time.monotonic()
        accumulator = 0.0

        while True:
            if not self.handle_input():
                break

            now = time.monotonic()
            if now > self.hold_until:
                self.world.paddle_dir = 0
            if now > self.mouse_until:
                self.world.paddle_target = None

            frame_dt = min(now - previous, 0.25)  # просадка не должна телепортировать шарик
            previous = now

            if not self.paused and not self.world.over:
                accumulator += frame_dt
                events: list[Event] = []
                while accumulator >= step:
                    accumulator -= step
                    events.extend(advance(self.world, step))
                    if self.world.over:
                        accumulator = 0.0
                        break
                self.sound.play(events)
                self.react(events)
            else:
                accumulator = 0.0

            if self.world.score > self.record:
                self.record = self.world.score
                self.record_dirty = True
            if self.world.over and self.record_dirty:
                save_record(self.cfg.highscore_file, self.record)
                self.record_dirty = False

            self.renderer.draw(
                self.world,
                record=self.record,
                paused=self.paused,
                message=self.message,
                message_until=self.message_until,
            )

            spent = time.monotonic() - now
            remaining = int((step - spent) * 1000)
            if remaining > 0:
                curses.napms(remaining)

        save_record(self.cfg.highscore_file, self.record)

    def react(self, events: list[Event]) -> None:
        now = time.monotonic()
        if "level" in events:
            self.say(f"Уровень {self.world.level}", 2.0)
        elif "powerup" in events:
            self.say("Бонус подхвачен", 1.2)
        elif "life" in events and not self.world.over:
            self.say(f"Мимо! Жизней: {self.world.lives}", 1.8)

    def say(self, text: str, seconds: float) -> None:
        self.message = text
        self.message_until = time.monotonic() + seconds

    # --- ввод --------------------------------------------------------------
    def handle_input(self) -> bool:
        """Обработка всех нажатых клавиш. False — пора выходить."""
        while True:
            key = self.scr.getch()
            if key == -1:
                return True
            if not self.handle_key(key):
                return False

    def handle_key(self, key: int) -> bool:
        now = time.monotonic()
        world = self.world

        # Esc намеренно не выход: в некоторых терминалах это часть
        # последовательности стрелок, и выход получился бы случайным.
        if key in (ord("q"), ord("Q"), ord("й"), ord("Й")):
            return False

        if key == curses.KEY_RESIZE:
            self.handle_resize()
            return True

        if key == curses.KEY_MOUSE:
            self.handle_mouse()
            return True

        if key in (curses.KEY_LEFT, ord("h"), ord("а"), ord("H"), ord("А")):
            world.paddle_dir = -1
            world.paddle_target = None
            self.hold_until = now + HOLD_SECONDS
        elif key in (curses.KEY_RIGHT, ord("l"), ord("д"), ord("L"), ord("Д")):
            world.paddle_dir = 1
            world.paddle_target = None
            self.hold_until = now + HOLD_SECONDS
        elif key in (ord("s"), ord("ы"), ord("S"), ord("Ы")):
            self.sound.enabled = not self.sound.enabled
            self.say(f"Звук: {'вкл' if self.sound.enabled else 'выкл'}", 1.2)
        elif key in (ord("p"), ord("з"), ord("P"), ord("З")):
            self.paused = not self.paused
        elif key in (ord("r"), ord("к"), ord("R"), ord("К")):
            self.restart()
        elif key in (ord(" "), curses.KEY_ENTER, 10, 13):
            if world.launch():
                self.say("", 0.0)
        return True

    def handle_mouse(self) -> None:
        try:
            event = curses.getmouse()
        except curses.error:
            return
        if event.x > 0:
            self.world.paddle_target = float(event.x - self.world.paddle_width // 2)
            self.world.paddle_dir = 0
            self.mouse_until = time.monotonic() + 2.0
            if event.bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED):
                self.world.launch()

    def handle_resize(self) -> None:
        height, width = self.scr.getmaxyx()
        self.renderer.resize(height, width)
        resize(self.world, width, height)
        if height < MIN_HEIGHT or width < MIN_WIDTH:
            self.say(f"Тесно: нужно минимум {MIN_WIDTH}x{MIN_HEIGHT}", 3.0)

    def restart(self) -> None:
        height, width = self.scr.getmaxyx()
        self.world = new_world(width, height, self.cfg)
        self.paused = False
        self.say("Новая игра", 1.5)


# ---------------------------------------------------------------------------
# Прогон физики без терминала: python arkanoid.py --smoke 30
# ---------------------------------------------------------------------------
def run_smoke(seconds: float, cfg: Config) -> int:
    """
    Инварианты, зафиксированные по мотивам багов прошлой версии:

      1. шарик не покидает поле;
      2. у летящего шарика |vx| ∈ {1, 2} (нет «столба» вверх-вниз с бесконечными очками);
      3. ракетка не выезжает за границы;
      4. игра реально прогрессирует (кирпичи разбиваются, жизни теряются).
    """
    world = new_world(80, 24, cfg)
    step = 1.0 / cfg.fps
    frames = int(seconds * cfg.fps)
    broken = 0
    levels = 0
    lives_lost = 0
    problems: list[str] = []

    for frame in range(frames):
        ball = world.balls[0] if world.balls else None
        if ball is not None:
            # неидеальный «игрок»: наводит ракетку с запаздыванием
            world.paddle_target = ball.x - world.paddle_width / 2
            if ball.stuck:
                world.launch()
        events = advance(world, step)
        broken += events.count("brick_break")
        levels += events.count("level")
        lives_lost += events.count("life")

        for ball in world.balls:
            if not world.left <= ball.x <= world.field_right or not world.ceiling <= ball.y <= world.floor_y:
                problems.append(f"кадр {frame}: шарик вне поля ({ball.x},{ball.y})")
            if not ball.stuck and abs(ball.vx) not in (1, 2):
                problems.append(f"кадр {frame}: у шарика неверный vx={ball.vx} в x={ball.x}")
        if not world.left <= world.paddle_x <= world.field_right - world.paddle_width + 1:
            problems.append(f"кадр {frame}: ракетка за границей x={world.paddle_x}")

        if world.over:
            # новая партия без того же зерна, иначе прогон зациклится
            world = new_world(world.width, world.height, replace(cfg, seed=None))

    print(
        f"прогон {seconds:.0f} с ({frames} шагов): очков {world.score}, разбито {broken}, "
        f"уровней пройдено {levels}, жизней потеряно {lives_lost}"
    )
    for problem in problems[:10]:
        print("ПРОБЛЕМА:", problem)
    if broken < frames // 200:
        problems.append("кирпичи почти не разрушаются — игра стоит")
    if levels == 0 and seconds >= 120:
        print("ПРЕДУПРЕЖДЕНИЕ: за прогон не пройден ни один уровень")

    return 1 if problems else 0


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Текстовый арканоид на curses")
    parser.add_argument("--fps", type=int, default=60, help="кадров в секунду (по умолчанию 60)")
    parser.add_argument("--lives", type=int, default=Config.lives, help="число жизней")
    parser.add_argument("--speed", type=float, default=BALL_SPEED, help="скорость шарика, клеток/с")
    parser.add_argument("--seed", type=int, default=None, help="зерно ГСЧ для повторяемости")
    parser.add_argument("--no-sound", action="store_true", help="без звука")
    parser.add_argument("--no-color", action="store_true", help="монохромный режим")
    parser.add_argument("--no-powerups", action="store_true", help="без бонусов")
    parser.add_argument(
        "--smoke", type=float, metavar="SECONDS", default=None,
        help="прогнать физику без терминала и проверить инварианты",
    )
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> Config:
    return Config(
        fps=max(10, args.fps),
        lives=max(1, args.lives),
        ball_speed=max(4.0, args.speed),
        sound=not args.no_sound,
        color=not args.no_color,
        powerups=not args.no_powerups,
        seed=args.seed,
    )


def run_game(stdscr, cfg: Config) -> None:
    height, width = stdscr.getmaxyx()
    if height < MIN_HEIGHT or width < MIN_WIDTH:
        stdscr.nodelay(False)
        text = f"Терминал слишком мал: {width}x{height}, нужно минимум {MIN_WIDTH}x{MIN_HEIGHT}."
        try:
            stdscr.addstr(0, 0, text[: max(0, width - 1)])
            stdscr.getch()
        except curses.error:
            pass
        return

    Game(stdscr, cfg).run()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = config_from_args(args)

    if args.smoke is not None:
        return run_smoke(args.smoke, cfg)

    # Без этой строки при LANG=C curses рисует кириллицу пробелами (проверено в pty).
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    os.environ.setdefault("ESCDELAY", "25")

    if not (os.isatty(0) and os.isatty(1)):
        print("arkanoid: нужен интерактивный терминал (для проверки физики есть --smoke).")
        return 2

    try:
        curses.wrapper(run_game, cfg)
    except KeyboardInterrupt:
        pass
    except curses.error as exc:
        print(f"arkanoid: терминал не подходит для curses ({exc}). TERM={os.environ.get('TERM')!r}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
