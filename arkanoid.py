#!/usr/bin/env python3
"""
Текстовый арканоид на curses (версия 3).

Запуск:
    python arkanoid.py
    python arkanoid.py --fps 60 --lives 5 --seed 42 --no-sound
    python arkanoid.py --arena-width 60   # поле уже терминала -> уровни короче
    python arkanoid.py --smoke 30         # проверка физики без терминала

Поле по умолчанию занимает весь терминал: скорость шарика, ширина ракетки и
толщина стены считаются из размеров окна (формулу и обоснование смотри в
README).

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
# Поле занимает весь терминал: только что не хватает на минимальную игру.
ARENA_MIN_WIDTH = 14    # внутренних колонок
ARENA_MIN_HEIGHT = 9    # внутренних строк
# От этой диагонали арены масштабируется скорость и толщина стены:
# базовый терминал 80x24 (арена ~40x16), всё остальное — пропорционально.
REFERENCE_DIAGONAL = 43.0
SPEED_SCALE = (0.85, 5.0)     # границы масштаба скорости
MIN_REACTION_SECONDS = 0.35   # за сколько секунд шарик должен пролетать высоту поля
# Законы жанра (замерены на симуляции): время пробоя стены это
# ~0.5 * ширина_поля * ряды * плотность, и почти не зависит от скорости шарика
# (быстрее шарик — чаще подлёты, но и кирпичей на уровне больше). Значит
# толщину и густоту стены надо считать из размера поля, иначе на 200x60
# уровень превращается в пятиминутное перебирание кирпичей.
LEVEL_SECONDS = 80.0        # целевое время пробоя стены; на очень широких полях
LEVEL_GROWTH = 0.25         # floor уровня меньше не станет — см. заметку ниже
MAX_VX = 2                  # классический предел угла: дальше шарик не перехватить ракеткой

# Время пробоя уровня (замерено и выведено):
#
#       время ≈ ширина_поля * прочность_кирпича * (2 * высота_поля / скорость)
#
# Ряды и густота кладки на него НЕ влияют: за один подлёт шарик проходит по
# клетке в каждом ряду, и сколько из них окажутся кирпичами — столько он и
# выбьет; произведение «кирпичей» и «шанса попасть» как раз сворачивается в
# ширину поля. Поэтому толщина стены — это про сложность и внешний вид, а
# скорость шарика — про темп игры (см. --speed и --arena-width).
PADDLE_WIDTH_DIVISOR = 12     # ширина ракетки от ширины поля

# --- Скорости (клеток в секунду) -------------------------------------------
BALL_SPEED = 18.0       # базовая скорость шарика
BALL_SPEED_PER_LEVEL = 1.5
BALL_SPEED_MAX = 34.0
PADDLE_TO_BALL = 2.6    # запас по скорости ракетки относительно шарика (у шарика |vx| до 2)
POWERUP_SPEED = 7.0
MAX_STEPS_PER_FRAME = 4  # страховка от «телепорта» при просадке FPS

STALL_SECONDS = 5.0     # столько секунд без кирпича считаем «залипанием» и рулим к кирпичам

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
    ("#%#%#", "#...#", "#####"),
    ("&.#.%", "#.#.#", "%.###", "#...#"),
    ("#####", "#%#%#", "&.#.#", ".....", "#.#.#"),
    ("#.&.#", "%%#%#", "#.#.#", "&.#.%", "....."),
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
    def fit(cls, width: int, height: int, max_width: int | None = None) -> "Arena":
        """
        Арена во весь терминал: минус строка счёта, минус подсказки внизу.

        max_width нужен тем, кто играет на огромном терминале, но не хочет
        длинных уровней: время пробоя пропорционально ширине поля.
        """
        inner_w = max(ARENA_MIN_WIDTH, width - 2)
        if max_width:
            inner_w = min(inner_w, max(ARENA_MIN_WIDTH, max_width))
        inner_h = max(ARENA_MIN_HEIGHT, height - 4)

        left = max(0, (width - inner_w) // 2 - 1)
        right = min(width - 1, left + inner_w + 1)
        top = 1
        bottom = min(height - 1, top + inner_h + 1)
        return cls(left=left, right=right, top=top, bottom=bottom)

    @property
    def diagonal(self) -> float:
        return (self.inner_width**2 + self.play_rows**2) ** 0.5

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
    level_seconds: float = LEVEL_SECONDS
    max_arena_width: int | None = None   # None = во весь терминал
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
    brick_rows: int = 1
    brick_cols: int = 1
    brick_left: int = 1
    balls: list[Ball] = field(default_factory=list)
    powerups: list[PowerUp] = field(default_factory=list)

    paddle_pos: float = 0.0              # положение ракетки (вещественное — плавный ход)
    paddle_target: float | None = None   # цель от мыши
    paddle_dir: int = 0                  # -1 / 0 / 1 при удержании клавиши

    combo: int = 0
    speed: float = BALL_SPEED
    level_seconds: float = LEVEL_SECONDS
    effects: dict[str, float] = field(default_factory=dict)
    since_brick: float = 0.0

    def __post_init__(self) -> None:
        if self.cfg.seed is not None:
            self.rng = random.Random(self.cfg.seed)
        self.lives = self.cfg.lives
        self.arena = Arena.fit(self.width, self.height, self.cfg.max_arena_width)
        self.level_seconds = self.cfg.level_seconds
        self.speed = self.level_speed(self.level)
        self.brick_rows, self.brick_cols, self.brick_left, _keep, _max_hp = self.brick_layout()
        self.bricks = []
        self.reset_level()
        self.paddle_pos = float(
            self.arena.inner_left + max(0, (self.arena.inner_width - self.paddle_width) // 2)
        )
        self.spawn_ball()

    # --- геометрия ---------------------------------------------------------
    @property
    def paddle_x(self) -> int:
        return int(round(self.paddle_pos))

    @property
    def size_scale(self) -> float:
        """Во сколько раз эта арена больше базовой (40x16).

        Скорость шарика и ширина ракетки масштабируются от него, иначе на
        терминале 200x60 шарик ползает, а на 50x14 — непотопляемо быстр.
        """
        raw = self.arena.diagonal / REFERENCE_DIAGONAL
        return max(SPEED_SCALE[0], min(SPEED_SCALE[1], raw))

    def level_speed(self, level: int) -> float:
        """
        Скорость шарика: базовый масштаб от размера поля, но на широких полях
        ещё и разгон, чтобы «прочёсывание» успевало за бюджет уровня. Выше
        MIN_REACTION_SECONDS не прыгаем — дальше реакция игрока не успевает.
        """
        base = (self.cfg.ball_speed + BALL_SPEED_PER_LEVEL * (level - 1)) * self.size_scale
        field = max(1, self.arena.inner_width) * 2 * max(1, self.arena.play_rows)
        needed = field / max(1.0, self.level_seconds)
        capable = max(1, self.arena.play_rows) / MIN_REACTION_SECONDS
        return max(base, min(needed, capable))

    @property
    def paddle_speed(self) -> float:
        """Ракетка успевает за шариком: запас PADDLE_TO_BALL к его скорости."""
        return PADDLE_TO_BALL * self.speed

    @property
    def max_vx(self) -> int:
        """
        Самый крутой горизонтальный угол шарика (в клетках на один ряд).

        Больше двух нельзя: горизонтальная скорость шарика становится выше
        скорости ракетки, и её нечем отбить — проверено симуляцией, при |vx| = 4
        «игрок» теряет по 90 жизней в минуту.
        """
        return MAX_VX

    @property
    def min_vx(self) -> int:
        return 1

    @property
    def sweep_seconds(self) -> float:
        """Время одного полного «прочёсывания» поля: width * (2*height/speed)."""
        return max(1, self.arena.inner_width) * 2 * max(1, self.arena.play_rows) / max(1.0, self.speed)

    @property
    def estimated_level_seconds(self) -> float:
        """Сколько секунд займёт пробой стены: одно «прочёсывание» поля на прочность."""
        hp = [value for row in self.bricks for value in row if value]
        strength = sum(hp) / len(hp) if hp else 1
        return strength * self.sweep_seconds

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
        base = max(self.cfg.paddle_width, round(self.arena.inner_width / PADDLE_WIDTH_DIVISOR))
        return base + (2 if self.effects.get("E", 0) > 0 else 0)

    @property
    def ball_speed_now(self) -> float:
        factor = 0.6 if self.effects.get("S", 0) > 0 else 1.0
        return self.speed * factor

    # --- уровни ------------------------------------------------------------
    def brick_layout(self) -> tuple[int, int, int, float]:
        """
        Ряды, колонки, отступ и плотность кладки текущего уровня.

        Стена всегда во всю ширину поля — так она выглядит правильно на любом
        терминале. А «объём» уровня считается из размеров поля: время чистки
        это занятые колонки, делённые на подлёты в секунду. Поэтому на 40x14
        кладка глухая, а на 200x60 — дырявая, зато уровень везде проходится
        за одно и то же время.
        """
        inner_w = self.arena.inner_width
        max_rows = max(1, (self.arena.play_rows - 3) // 2)

        # Ряды и плотность — внешний вид и сложность: сквозь дыру в стене шарик
        # летит дальше, поэтому время уровня держится ~sweep_seconds и от толщины
        # стены почти не зависит. А вот крепкий кирпич (%) дорогой: каждый его
        # уровень прочности стоит отдельного подлёта, так что максимум прочности
        # ограничиваем по бюджету времени.
        rows = max(1, min(max_rows, 1 + self.level // 2))
        keep = min(1.0, 0.6 + 0.13 * (self.level - 1))

        budget = self.level_seconds * (1 + LEVEL_GROWTH * (self.level - 1)) / self.sweep_seconds
        max_hp = 3 if budget >= 2.6 else 2 if budget >= 1.4 else 1
        return rows, inner_w, self.arena.inner_left, keep, max_hp

    def reset_level(self) -> None:
        """Собрать кирпичи заново (размер окна мог измениться)."""
        self.brick_rows, self.brick_cols, self.brick_left, keep, max_hp = self.brick_layout()
        layout = LEVELS[(self.level - 1) % len(LEVELS)]
        self.bricks = []
        for r in range(self.brick_rows):
            pattern = layout[r % len(layout)]
            row = [min(max_hp, BRICK_HP_BY_CHAR.get(pattern[c % len(pattern)], 0)) for c in range(self.brick_cols)]
            self.bricks.append(thin_row(row, keep, r))

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
                ball.vx = self.rng.choice((-1, 1)) * self.max_vx
                ball.vy = -1
                launched = True
        return launched

    def next_level(self) -> None:
        self.level += 1
        self.speed = self.level_speed(self.level)
        self.balls = []
        self.powerups = []
        self.reset_level()
        self.spawn_ball()


def new_world(width: int, height: int, cfg: Config) -> World:
    return World(width=width, height=height, cfg=cfg)


def thin_row(row: list[int], keep: float, row_index: int) -> list[int]:
    """
    Оставить в ряду примерно долю `keep` кирпичей, равномерно и вразнобой.

    Сдвиг фазы по номеру ряда даёт «кирпичную» кладку, а не вертикальные полосы.
    """
    if keep >= 1.0:
        return row

    count = max(1, round(len(row) * keep))
    step = len(row) / count
    wanted = {int(col * step + step / 2 + row_index * step / 2) % len(row) for col in range(count)}
    return [hp if col in wanted else 0 for col, hp in enumerate(row)]


# ---------------------------------------------------------------------------
# Физика. Чистые функции: аргументы — World и dt, результат — список событий.
# ---------------------------------------------------------------------------
Event = str


def brick_row_col(world: World, x: int, y: int) -> tuple[int, int] | None:
    """Индекс ряда/колонки кирпича по координатам поля (или None)."""
    row = y - world.brick_top
    col = x - world.brick_left
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
    half = max(1, world.paddle_width // 2)
    offset = ball.x - (world.paddle_x + world.paddle_width // 2)
    span = max(1, world.max_vx)

    if offset == 0:                               # точно в центр — угол не трогаем
        return ball.vx or 1

    magnitude = span if abs(offset) >= half else 1 + round(abs(offset) / half * (span - 1))
    magnitude = max(world.min_vx, min(span, magnitude))
    return magnitude * (1 if offset > 0 else -1)


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
        step = world.paddle_speed * dt
        world.paddle_pos += max(-step, min(step, delta))
    else:
        world.paddle_pos += world.paddle_dir * world.paddle_speed * dt

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


def nearest_brick_column(world: World, x: int) -> int | None:
    """Ближайшая колонка с целым кирпичом — куда стоит довернуть шарик."""
    best: tuple[int, int] | None = None
    for row in world.bricks:
        for col, hp in enumerate(row):
            if hp > 0:
                candidate = world.brick_left + col
                distance = abs(candidate - x)
                if best is None or distance < best[0]:
                    best = (distance, candidate)
    return best[1] if best else None


def anti_stall(world: World, dt: float, events: list[Event]) -> None:
    """
    Подстраховка: если шарик долго летает впустую, доворачиваем его к кирпичам.

    Без этого последние кирпичи превращаются в лотерею — на широком поле
    шарик может десятки секунд носиться между пустыми колонками (и знакомая
    по-настоящемуму арканоиду «орбита» тоже никуда не денется). Знак vx менять
    мало — траектория просто отразится зеркально, поэтому целимся в конкретную
    колонку и попутно меняем наклон (|vx| 1 <-> 2).
    """
    world.since_brick += dt
    if world.since_brick < STALL_SECONDS:
        return
    world.since_brick = 0.0
    for ball in world.balls:
        if ball.stuck or ball.dead:
            continue
        target = nearest_brick_column(world, ball.x)
        if target is None:
            return
        if abs(target - ball.x) <= 1:
            ball.vy = -1                       # уже над ним — идём вверх
        else:
            step = 1 if abs(ball.vx) >= world.max_vx else world.max_vx
            ball.vx = step * (1 if target > ball.x else -1)
        events.append("nudge")
        return


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
    world.arena = Arena.fit(width, height, world.cfg.max_arena_width)
    world.speed = world.level_speed(world.level)
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
                    self.put(y, world.brick_left + col_index, self.glyph["brick"].get(hp, "#"),
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
def aim_ai_paddle(world: World) -> None:
    """
    Болван игрока для тестов: догоняет шарик ракеткой. Идеальный — зато
    проверяет худший случай: ракетка не помогает шарику «собирать» кирпичи,
    и вся надежда на анти-залипание.
    """
    if not world.balls:
        return
    ball = world.balls[0]
    world.paddle_target = ball.x - world.paddle_width / 2


def run_smoke(seconds: float, cfg: Config, width: int = 80, height: int = 24) -> int:
    """
    Инварианты, зафиксированные по мотивам багов прошлой версии:

      1. шарик не покидает поле;
      2. у летящего шарика |vx| ∈ {1, 2} (нет «столба» вверх-вниз с бесконечными очками);
      3. ракетка не выезжает за границы;
      4. игра реально прогрессирует (кирпичи разбиваются, жизни теряются).
    """
    world = new_world(width, height, cfg)
    step = 1.0 / cfg.fps
    frames = int(seconds * cfg.fps)
    broken = 0
    levels = 0
    lives_lost = 0
    problems: list[str] = []

    for frame in range(frames):
        aim_ai_paddle(world)
        if world.balls and world.balls[0].stuck:
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
        f"прогон {seconds:.0f} с на {width}x{height} (арена {world.arena.inner_width}x{world.arena.play_rows}, "
        f"стена {world.brick_cols}x{world.brick_rows}, скорость {world.speed:.0f}, "
        f"пробой ~{world.estimated_level_seconds:.0f} с): "
        f"очков {world.score}, разбито {broken}, уровней пройдено {levels}, жизней потеряно {lives_lost}"
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
    parser.add_argument("--size", metavar="WxH", default=None,
                        help="размер поля для --smoke (по умолчанию 80x24)")
    parser.add_argument("--level-seconds", type=float, default=Config.level_seconds,
                        help="целевое время пробоя стены (на широких полях есть физический минимум)")
    parser.add_argument("--arena-width", type=int, default=None, metavar="N",
                        help="ограничить ширину поля N колонками (по умолчанию — весь терминал); "
                             "уже поле — короче уровни")
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
        level_seconds=max(20.0, args.level_seconds),
        max_arena_width=args.arena_width,
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


def parse_size(text: str | None) -> tuple[int, int]:
    """Размер '120x40' для --smoke; по умолчанию 80x24."""
    if not text:
        return 80, 24
    try:
        width, _, height = text.lower().partition("x")
        return max(20, int(width)), max(12, int(height))
    except ValueError:
        raise SystemExit("--size нужен вида 120x40")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = config_from_args(args)

    if args.smoke is not None:
        width, height = parse_size(args.size)
        return run_smoke(args.smoke, cfg, width, height)

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
