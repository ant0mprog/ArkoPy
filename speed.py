#!/usr/bin/env python3
"""
speed.py — движение ракетки, вынесенное из игры: полигон для обкатки алгоритма
управления. Только стандартная библиотека, никакого curses, шарика и кирпичей.

Зачем: алгоритм (разгон/торможение/разворот/удержание клавиши) хочется крутить
по десять раз на дугу, а `arkanoid.py` для этого слишком большой — там вместе с
ним меняется и всё остальное. Здесь ровно то же состояние и ровно те же ветки,
плюс прогон сценариев, метрики game feel и сторожевые проверки.

Запуск:

    python3 speed.py                      # отчёт по всем сценариям + вердикт
    python3 speed.py --check              # только инварианты; код выхода != 0 = сломано
    python3 speed.py --chart              # покадровая лента (позиция, шаг, скорость, рывок)
    python3 speed.py --film               # как это выглядит на поле, клетка за кадром
    python3 speed.py --scenario reversal  # один сценарий (tap, shelf, release, ...)
    python3 speed.py --variant legacy     # старая схема — с чем сравнивать
    python3 speed.py --size 120x40 --fps 30 --repeat 6      # другой терминал/автоповтор
    python3 speed.py --accel 16 --brake 21 --reverse 1.5    # прикинуть другие константы
    python3 speed.py --tune               # сетка констант и рейтинг по целевым метрикам
    python3 speed.py --golden g.json      # нет g.json — записать снимок метрик; есть — сверить
    python3 speed.py --scenarios          # список сценариев

Конверт, на котором правила имеют смысл: 20-120 fps и автоповтор 6-60 Гц.
Вне его --check печатает предупреждение: там нарушения объясняются сеткой
кадров (один кадр проносит дальше, чем ракетка успевает затормозить) или
принципиальной неразличимостью тапа и удержания, а не алгоритмом.

Что полигон уже нашёл (все три ещё НЕ в arkanoid.py — это список на перенос):

  1. Пакет кодов в одном кадре. Если fps игры ниже частоты автоповтора
     (--fps 24 при 30 Гц), несколько повторов приходят с одним временем,
     трекер читает интервал 0 как «слишком редко», объявляет новый тап и
     гасит удержание: за полсекунды удержания на 24 fps — 2 кадра без газа и
     3 обвала с полки (в полигоне после правки — 0 и 0). Лечение:
     интервал меньше четверти выученного — тот же газ (см. KeyRepeatTracker
     выше), а не новый тап.
  2. Полка достигается асимптотой. Когда разрешение скорости считается только
     из зазора команды, скорость сходится к Vmax бесконечно долго: на 120 fps
     разгон до 99% полки занимает 92 мс вместо 42 мс (на 60 и 90 fps разницы
     нет — поэтому в игре баг и не был виден). Лечение: открытый газ = требование
     полной скорости (ветка `if p.held and abs(distance) >= stopping`).
  3. На грубой сетке кадров зазор нельзя сжимать до тормозного пути: один кадр
     проносит дальше, сервопривод начинает «вгрызаться» в цель через
     предсказание прибытия, и полка срывается в пилообразные остановки.
     Лечение: ограничитель зазора stopping_room = max(тормозной путь,
     1.5 кадров хода), а метрики съезда мерить от min_stop_distance.

Перенос обратно в arkanoid.py (имена здесь короче, логика — слово в слово):

    Paddle.pos/cmd/vel/target/dir/held  ->  World.paddle_pos/_cmd/_vel/_target/_dir/_held
    Paddle.speed/accel/brake/x          ->  World.paddle_speed/paddle_accel/paddle_brake/paddle_x
    Paddle.brake_to(direction)          ->  World.paddle_decel(direction)
    Paddle.braking_distance/stop/stop_at->  World.paddle_braking_distance/paddle_stop
    Paddle.stopping_room                ->  World.paddle_stopping_room   (новое)
    Paddle.min_stop_distance            ->  World.paddle_min_stop_distance (новое)
    Paddle.dt                           ->  поле World.paddle_dt, обновляется в move_paddle
    Paddle.min_x/max_x                  ->  World.paddle_min/paddle_max
    move_paddle/tap_paddle/hold_paddle_command/glide_paddle_to_stop/
    follow_paddle_command/command_paddle_address/fit_paddle_to_field  -> те же имена
    KeyRepeatTracker                    -> уже есть в arkanoid.py (править press, не копировать)
    PADDLE_ACCEL/BRAKE/REVERSE/SNAP/KEY_STEP  -> константы верхнего уровня

После переноса обязательно сверить с игрой: `python3 -m unittest discover -s
tests` и `python3 arkanoid.py --smoke 60 --seed 42` — тут инварианты те же, но
шарик, отрисовка и мышь живут по своим правилам.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field, replace

# --- SYNC с arkanoid.py -----------------------------------------------------
# Всё, что влияет на движение. Правь здесь, а когда алгоритм устроит — переноси
# значения и функции обратно (карта имён в докстринге модуля).
BALL_SPEED = 18.0            # базовая скорость шарика (от неё масштабируется ракетка)
BALL_SPEED_PER_LEVEL = 1.5
REFERENCE_DIAGONAL = 43.0    # диагональ эталонной арены (~40x16)
SPEED_SCALE = (0.85, 5.0)    # границы масштаба скорости
MIN_REACTION_SECONDS = 0.35
LEVEL_SECONDS = 80.0
PADDLE_WIDTH_DIVISOR = 12
PADDLE_MIN_WIDTH = 7
ARENA_MIN_WIDTH = 14
ARENA_MIN_HEIGHT = 9
PADDLE_TO_BALL = 3.4         # максимум ракетки в скоростях шарика

PADDLE_ACCEL = 16.0          # 1/с: разгон (62 мс до полки)
PADDLE_BRAKE = 21.0          # 1/с: торможение вдоль хода
PADDLE_REVERSE = 1.5         # x PADDLE_BRAKE: встречное торможение (смена направления)
PADDLE_SNAP = 0.02           # остаток пути и скорость меньше этого считаются нулём
PADDLE_KEY_STEP = 1.0        # один тап = ровно одна клетка

DEFAULT_REPEAT_GAP = 1 / 30
REPEAT_GAP_LIMIT = (0.015, 0.20)
REPEAT_ACCEPT = (0.45, 2.2)
REPEAT_EMA = 0.5
HOLD_TOLERANCE = 1.7


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# ---------------------------------------------------------------------------
# Геометрия и скорость: минимум из Arena + World, нужной ракетке
# ---------------------------------------------------------------------------
@dataclass
class Field:
    """Поле и всё, из чего считается скорость ракетки (уровень 1, без бонусов)."""

    width: int = 80
    height: int = 24
    level: int = 1
    level_seconds: float = LEVEL_SECONDS
    wider: bool = False          # бонус E: ракета шире -> правый край уезжает

    @property
    def inner_width(self) -> int:
        inner_w = max(ARENA_MIN_WIDTH, self.width - 2)
        return inner_w

    @property
    def play_rows(self) -> int:
        """Строк игры: арена во весь терминал, минус строка счёта и подсказка."""
        inner_h = max(ARENA_MIN_HEIGHT, self.height - 4)
        bottom = min(self.height - 1, 1 + inner_h + 1)
        return max(3, bottom - 2)

    @property
    def diagonal(self) -> float:
        return (self.inner_width ** 2 + self.play_rows ** 2) ** 0.5

    @property
    def scale(self) -> float:
        return clamp(self.diagonal / REFERENCE_DIAGONAL, *SPEED_SCALE)

    @property
    def ball_speed(self) -> float:
        """Тот же максимум, что считает arkanoid: база от размера поля."""
        base = (BALL_SPEED + BALL_SPEED_PER_LEVEL * (self.level - 1)) * self.scale
        span = max(1, self.inner_width) * 2 * max(1, self.play_rows)
        needed = span / max(1.0, self.level_seconds)
        capable = max(1, self.play_rows) / MIN_REACTION_SECONDS
        return max(base, min(needed, capable))

    @property
    def paddle_width(self) -> int:
        base = max(PADDLE_MIN_WIDTH, round(self.inner_width / PADDLE_WIDTH_DIVISOR))
        return base + (2 if self.wider else 0)

    @property
    def left(self) -> float:
        """Внутренняя левая колонка (= World.left)."""
        wall = max(0, (self.width - self.inner_width) // 2 - 1)
        return float(wall + 1)

    @property
    def right(self) -> float:
        """Внутренняя правая колонка (= World.field_right)."""
        wall = max(0, (self.width - self.inner_width) // 2 - 1)
        return float(max(wall + 2, min(self.width - 1, wall + self.inner_width + 1) - 1))

    def bounds(self) -> tuple[float, float]:
        """Левая и правая граница левой клетки ракетки (= World.paddle_min/max)."""
        left = self.left
        right = max(left, self.right - self.paddle_width + 1)
        return left, right


@dataclass
class Paddle:
    """Состояние ракетки: те шесть полей, что есть в World, плюс геометрия поля."""

    field: Field = field(default_factory=Field)
    pos: float = 0.0             # где на самом деле (вещественное — плавный ход)
    cmd: float = 0.0             # командная позиция: куда просит игрок
    vel: float = 0.0             # клеток/с
    target: float | None = None  # цель от мыши (или болвана)
    dir: int = 0                 # удержание клавиши в этом кадре: -1 / 0 / 1
    held: int = 0                # кто владеет cmd: 0 — адрес, ±1 — газ удержания
    dt: float = 1 / 60           # длительность последнего шага (нужна «комнатной»
                                 # границе зазора на грубой сетке кадров)

    def __post_init__(self) -> None:
        # стартовая клетка — как в World.__post_init__, чтобы траектории совпадали
        start = float(self.field.left + max(0, (self.field.inner_width - self.field.paddle_width) // 2))
        low, high = self.field.bounds()
        self.pos = self.cmd = clamp(start, low, high)

    # --- клетка -------------------------------------------------------------
    @property
    def x(self) -> int:
        """floor(pos + 0.5), а не round(pos): round округляет к чётному, и
        ракета на полуклетке рисовалась бы на разных клетках."""
        return int(math.floor(self.pos + 0.5))

    # --- геометрия ----------------------------------------------------------
    @property
    def min_x(self) -> float:
        return self.field.bounds()[0]

    @property
    def max_x(self) -> float:
        return self.field.bounds()[1]

    # --- усилия -------------------------------------------------------------
    @property
    def speed(self) -> float:
        return PADDLE_TO_BALL * self.field.ball_speed

    @property
    def accel(self) -> float:
        return PADDLE_ACCEL * self.speed

    @property
    def brake(self) -> float:
        return PADDLE_BRAKE * self.speed

    def brake_to(self, direction: float) -> float:
        """Вдоль хода — обычный тормоз, навстречу ходу — встречный, злее."""
        return self.brake * (PADDLE_REVERSE if direction * self.vel < 0 else 1.0)

    @property
    def braking_distance(self) -> float:
        """Тормозной путь на полной скорости — главная «цена» инерции."""
        return self.speed ** 2 / (2 * self.brake)

    @property
    def stopping_room(self) -> float:
        """Расстояние, ближе которого команда удержания не встаёт.

        Это тормозной путь, но не меньше полутора кадров хода: на грубой сетке
        (30 fps, широкое поле) один кадр проносит дальше, чем ракетка успевает
        затормозить, и сервопривод начинает «вгрызаться» в цель через предсказание
        прибытия — полка срывается в пилообразные рывки.
        """
        return max(self.braking_distance, 1.5 * self.speed * self.dt)

    @property
    def min_stop_distance(self) -> float:
        """Короче этого ракетка не встанет ни при каких константах: один кадр
        проносит полпути при полном гашении скорости (0.5·Vmax·dt)."""
        return max(self.braking_distance, 0.5 * self.speed * self.dt)

    @property
    def stop(self) -> float:
        """Клетка, где ракетка встанет, если начать тормозить прямо сейчас."""
        return self.stop_at(self.pos, self.vel)

    def stop_at(self, pos: float, vel: float) -> float:
        """То же для произвольного состояния — нужно ленте и метрикам."""
        glide = self.braking_distance * (vel / self.speed) ** 2
        return float(clamp(pos + math.copysign(glide, vel), self.min_x, self.max_x))


# ---------------------------------------------------------------------------
# Автоповтор терминала: тап и удержание различаются только по интервалу
# (копия того, что уже работает в arkanoid.py, — менять при переносе не надо)
# ---------------------------------------------------------------------------
class KeyRepeatTracker:
    def __init__(self, initial_gap: float = DEFAULT_REPEAT_GAP) -> None:
        self.gap = initial_gap
        self.direction = 0
        self.pressed_at: float | None = None
        self.holding = False

    def press(self, direction: int, now: float) -> bool:
        if not self.direction or direction != self.direction or self.pressed_at is None:
            self.holding = False
        else:
            interval = now - self.pressed_at
            if interval < self.gap * REPEAT_ACCEPT[0]:
                # Пакет кодов в одном кадре: когда fps игры ниже частоты
                # автоповтора, несколько повторов приходят с одним временем.
                # Это то же удержание, а не новый тап — иначе движение
                # рассыпается в рывки (нашёл --check --fps 24).
                self.holding = True
                self.pressed_at = now
                return True
            if interval <= REPEAT_GAP_LIMIT[1] and interval >= self.gap * REPEAT_ACCEPT[0]:
                self.gap = min(REPEAT_GAP_LIMIT[1], max(REPEAT_GAP_LIMIT[0],
                                  self.gap * (1 - REPEAT_EMA) + interval * REPEAT_EMA))
                self.holding = True
            else:
                self.holding = False
        self.direction = direction
        self.pressed_at = now
        return self.holding

    def still_holding(self, now: float) -> bool:
        if not self.direction or self.pressed_at is None:
            return False
        return (now - self.pressed_at) <= self.gap * HOLD_TOLERANCE

    def active_direction(self, now: float) -> int:
        if not self.holding or not self.direction:
            return 0
        return self.direction if self.still_holding(now) else 0

    def reset(self) -> None:
        self.direction = 0
        self.pressed_at = None
        self.holding = False


# ---------------------------------------------------------------------------
# Алгоритм управления («new» — текущая схема arkanoid.py после правок)
# ---------------------------------------------------------------------------
def command_paddle_address(p: Paddle, position: float) -> None:
    """Адрес: клетку, названную игроком (тап, Home/End, курсор), нельзя отменить
    торможением — под неё ракета разворачивается. Поэтому адрес снимает газ."""
    p.held = 0
    p.cmd = float(clamp(position, p.min_x, p.max_x))


def fit_paddle_to_field(p: Paddle) -> None:
    """Границы могли сузиться (бонус «шире», resize) — возвращаем внутрь поля."""
    inside = float(clamp(p.pos, p.min_x, p.max_x))
    if inside != p.pos:
        p.pos = inside
        p.cmd = inside
        p.vel = 0.0


def tap_paddle(p: Paddle, direction: int, step: float = PADDLE_KEY_STEP) -> None:
    """Тап: ровно одна клетка от той, что игрок ВИДИТ (paddle.x)."""
    p.target = None
    anchor = float(p.x)
    if (p.pos - anchor) * direction > 0.0:
        anchor = p.pos          # начатые полклетки засчитаны, отката через цель нет
    command_paddle_address(p, anchor + direction * step)


def hold_paddle_command(p: Paddle, direction: int, dt: float) -> None:
    """Удержание — газ, а не адрес: команда впереди на кадр, но не дальше точки
    честной остановки. Вперёд убегает только по своему ходу: при смене направления
    целью владеет тап, начавший серию."""
    if direction * p.vel < 0.0:
        return
    p.held = direction
    ahead = p.cmd + direction * p.speed * dt
    limit = p.pos + direction * p.stopping_room
    p.cmd = min(ahead, limit) if direction > 0 else max(ahead, limit)


def glide_paddle_to_stop(p: Paddle, dt: float) -> None:
    """Ввода нет — чистое торможение вдоль движения; команда идёт за позицией."""
    if p.vel:
        carried = p.vel
        brake = -math.copysign(min(abs(carried), p.brake * dt), carried)
        p.vel += brake
        p.pos += (carried + p.vel) * 0.5 * dt        # путь по средней скорости кадра
        p.cmd = p.pos
        if p.pos < p.min_x or p.pos > p.max_x:
            p.pos = float(clamp(p.pos, p.min_x, p.max_x))
            p.vel = 0.0
    if p.vel == 0.0:
        p.cmd = p.pos


def follow_paddle_command(p: Paddle, dt: float) -> None:
    """Шаг разгона/торможения к cmd: право на скорость = «ещё успею встать в
    цель» (sqrt по тормозу), прирост скорости ограничен мотором или тормозом."""
    accel = p.accel
    brake = p.brake
    distance = p.cmd - p.pos
    stopping = p.vel ** 2 / (2 * brake)

    if abs(distance) <= PADDLE_SNAP and stopping <= PADDLE_SNAP:
        p.pos = p.cmd                       # встаём ровно на клетке
        p.vel = 0.0
        return

    allowed = math.copysign(math.sqrt(2.0 * brake * abs(distance)), distance)
    desired = allowed if abs(allowed) <= p.speed else math.copysign(p.speed, allowed)

    # Газ открыт и цель не ближе тормозного пути: просим полную скорость, а не
    # «насколько хватает зазора команды». С зазором-ограничением скорость
    # подползает к полке асимптотой (замер на 120 fps: 117 мс вместо 62 мс).
    if p.held and abs(distance) >= stopping:
        desired = math.copysign(p.speed, p.held)

    delta = desired - p.vel
    rate = p.brake_to(desired) if delta * p.vel < 0.0 else accel
    carried = p.vel
    p.vel += clamp(delta, -rate * dt, rate * dt)
    new_pos = p.pos + (carried + p.vel) * 0.5 * dt

    if distance * (p.cmd - new_pos) < 0 and distance * p.vel > 0:
        p.pos = p.cmd                       # предсказание прибытия: цель не проскакиваем
        p.vel = 0.0
    else:
        p.pos = new_pos

    if p.pos < p.min_x or p.pos > p.max_x:
        p.pos = float(clamp(p.pos, p.min_x, p.max_x))
        p.vel = 0.0
        p.cmd = p.pos


def move_paddle(p: Paddle, dt: float) -> None:
    """Диспетчер команды: мышь > газ удержания > газ убрали (тормозим) > адрес >
    торможение на месте."""
    p.dt = dt                     # «комнатная» граница зазора зависит от шага кадров
    was_held = p.held
    p.held = 0
    fit_paddle_to_field(p)

    if p.target is not None:
        command_paddle_address(p, p.target)
    elif p.dir:
        hold_paddle_command(p, p.dir, dt)
    elif was_held:
        glide_paddle_to_stop(p, dt)
        return
    elif abs(p.cmd - p.pos) <= PADDLE_SNAP:
        glide_paddle_to_stop(p, dt)
        return

    p.cmd = float(clamp(p.cmd, p.min_x, p.max_x))
    follow_paddle_command(p, dt)


# ---------------------------------------------------------------------------
# Алгоритм «legacy» — как было до правок веса/предсказуемости. Нужен как
# baseline: --variant legacy показывает, что именно стало хуже/лучше.
# ---------------------------------------------------------------------------
def legacy_tap(p: Paddle, direction: int, step: float = PADDLE_KEY_STEP) -> None:
    p.target = None
    p.cmd = float(clamp(p.cmd + direction * step, p.min_x, p.max_x))


def legacy_move(p: Paddle, dt: float) -> None:
    if p.target is not None:
        p.cmd = p.target
    elif p.dir:
        p.cmd += p.dir * p.speed * dt
    elif abs(p.cmd - p.pos) <= PADDLE_SNAP:
        if p.vel:
            carried = p.vel
            p.vel -= math.copysign(min(abs(carried), p.accel * dt), carried)
            p.pos += p.vel * dt
            if p.pos < p.min_x or p.pos > p.max_x:
                p.pos = float(clamp(p.pos, p.min_x, p.max_x))
                p.vel = 0.0
        if p.vel == 0.0:
            p.cmd = p.pos
        return

    p.cmd = float(clamp(p.cmd, p.min_x, p.max_x))
    accel = p.accel
    distance = p.cmd - p.pos
    stopping = p.vel ** 2 / (2 * accel)
    if abs(distance) <= PADDLE_SNAP and stopping <= PADDLE_SNAP:
        p.pos, p.vel = p.cmd, 0.0
        return
    allowed = math.copysign(math.sqrt(2.0 * accel * abs(distance)), distance)
    desired = allowed if abs(allowed) <= p.speed else math.copysign(p.speed, allowed)
    p.vel += clamp(desired - p.vel, -accel * dt, accel * dt)
    new_pos = p.pos + p.vel * dt
    if distance * (p.cmd - new_pos) < 0 and distance * p.vel > 0:
        p.pos, p.vel = p.cmd, 0.0
    else:
        p.pos = new_pos
    if p.pos < p.min_x or p.pos > p.max_x:
        p.pos = float(clamp(p.pos, p.min_x, p.max_x))
        p.vel = 0.0
        p.cmd = p.pos


ALGORITHMS = {
    "new": {"move": move_paddle, "tap": tap_paddle},
    "legacy": {"move": legacy_move, "tap": legacy_tap},
}


# ---------------------------------------------------------------------------
# Прогон: полная копия main-loop из игры (фиксированный шаг, dir из трекера,
# протухшая мышь), только вместо curses — расписание событий
# ---------------------------------------------------------------------------
@dataclass
class Frame:
    t: float
    pos: float
    vel: float
    x: int
    cmd: float
    dir: int = 0              # газ этого кадра (0 — клавиша не держат)
    acc: float = 0.0          # |Δv| этого кадра, клеток/с² (рывок)


class Rig:
    """Прогон ракетки по расписанию нажатий, как это делает Game.run."""

    def __init__(self, field: Field | None = None, fps: int = 60, variant: str = "new",
                 repeat_hz: float = 30.0, mouse_timeout: float = 2.0) -> None:
        self.p = Paddle(field or Field())
        self.dt = 1.0 / fps
        self.fps = fps
        self.move_fn = ALGORITHMS[variant]["move"]
        self.tap_fn = ALGORITHMS[variant]["tap"]
        self.repeat_hz = repeat_hz
        self.mouse_timeout = mouse_timeout
        self.tracker = KeyRepeatTracker()
        self.t = 0.0
        self.queue: list[tuple[float, str, float]] = []      # (момент, действие, параметр)
        self.trace: list[Frame] = []   # покадровая лента (см. --chart)
        self.taps: list[tuple[int, float, int]] = []   # (кадр, цель тапа, клетка в момент тапа)
        self.last_code_t = 0.0                      # когда терминал прислал последний код
        self.gas_frame: int | None = None           # первый кадр, где трекер дал удержание
        self.manual = False                         # True: dir задаёт сценарий, не трекер
        self.mouse_until = 0.0
        self.released_at: list[float] = []                   # отметки «газ сменился/убран»

    # --- расписание ---------------------------------------------------------
    def at(self, moment: float, action: str, arg: float = 0.0) -> "Rig":
        self.queue.append((moment, action, arg))
        self.queue.sort(key=lambda item: item[0])
        return self

    def now(self, action: str, arg: float = 0.0) -> "Rig":
        return self.at(self.t, action, arg)

    def tap_key(self, direction: int, at: float | None = None) -> "Rig":
        """Один код клавиши (трекер сам решит, тап это или автоповтор)."""
        return self.at(self.t if at is None else at, "key", float(direction))

    def hold(self, direction: int, seconds: float, at: float | None = None,
             hz: float | None = None, settle: float = 0.0, advance: bool = True) -> "Rig":
        """Нажать и держать: первый код + автоповтор терминала с частотой hz.

        Держание — это и время, которое нужно прокрутить: `seconds` удержания плюс
        `settle` на то, как трекер обнаружит отпускание (на 30 Гц это ~1.7 интервала).
        """
        start = self.t if at is None else at
        rate = hz or self.repeat_hz
        self.at(start, "key", float(direction))
        moment = start + 1.0 / rate
        while moment <= start + seconds + 1e-9:
            self.at(moment, "key", float(direction))
            moment += 1.0 / rate
        if advance and start >= self.t - 1e-12:
            return self.seconds(seconds + settle)
        return self

    def mouse(self, position: float, at: float | None = None) -> "Rig":
        """Курсор: как handle_mouse — цель выставлена, удержание снято."""
        self.manual = False
        self.p.dir = 0
        return self.at(self.t if at is None else at, "mouse", position)

    def key_home(self, at: float | None = None) -> "Rig":
        return self.at(self.t if at is None else at, "home", 0.0)

    def key_end(self, at: float | None = None) -> "Rig":
        return self.at(self.t if at is None else at, "end", 0.0)

    def gas(self, direction: int, frames: int) -> "Rig":
        """Держать клавишу, минуя трекер: чистая физика алгоритма.

        Трекер добавляет к движению свою латентность (тап и удержание различаются
        только по второму коду) — её меряют сценарии shelf/jitter/reversal, а
        разгон, съезд и разворот algoritma должен быть виден отдельно от неё.
        """
        self.manual = True
        for _ in range(frames):
            self.p.dir = direction
            self.step()
        return self

    def runway(self, fraction: float = 0.5) -> int:
        """Кадров, за которые ракета проедет fraction поля: сценариям нужен
        разбег, чтобы упираться в стенку не раньше, чем кончится приём."""
        p = self.p
        room = (p.max_x - p.min_x) * fraction
        return max(4, int(room / max(1e-9, p.speed * self.dt)))

    def widen(self, at: float | None = None) -> "Rig":
        """Бонус E: ракета шире, правый край поля уехал."""
        return self.at(self.t if at is None else at, "widen", 0.0)

    # --- шаги ---------------------------------------------------------------
    def frames(self, count: int) -> "Rig":
        for _ in range(count):
            self.step()
        return self

    def seconds(self, amount: float) -> "Rig":
        return self.frames(int(round(amount * self.fps)))

    def step(self) -> None:
        self.t += self.dt
        p = self.p
        while self.queue and self.queue[0][0] <= self.t + 1e-12:
            _, action, arg = self.queue.pop(0)
            if action == "key":
                self.last_code_t = self.t
                direction = int(arg)
                if p.dir and direction != p.dir:
                    self.released_at.append(self.t)      # серия сменилась — газ менялся
                if not self.tracker.press(direction, self.t):
                    cell_before = p.x                 # что игрок видит в этом кадре
                    self.tap_fn(p, direction)
                    self.taps.append((len(self.trace), p.cmd, cell_before))
            elif action == "mouse":
                p.target = float(arg)
                p.dir = 0
                self.mouse_until = self.t + self.mouse_timeout
            elif action == "home":
                self.tracker.reset()
                p.target = None
                command_paddle_address(p, p.min_x)
            elif action == "end":
                self.tracker.reset()
                p.target = None
                command_paddle_address(p, p.max_x)
            elif action == "widen":
                p.field = replace(p.field, wider=True)
                fit_paddle_to_field(p)

        previous_dir = p.dir
        if not self.manual:
            p.dir = self.tracker.active_direction(self.t)
        if p.dir and self.gas_frame is None:
            self.gas_frame = len(self.trace)     # с этого кадра начинается разгон
        if previous_dir and not p.dir:
            self.released_at.append(self.t)
        if self.mouse_until < self.t:
            p.target = None

        before = p.vel
        self.move_fn(p, self.dt)
        self.record(before)

    def record(self, before: float) -> None:
        p = self.p
        self.trace.append(Frame(t=self.t, pos=p.pos, vel=p.vel, x=p.x, cmd=p.cmd,
                                dir=p.dir, acc=abs(p.vel - before) / self.dt))

    def place(self, where: str = "left") -> "Rig":
        """Поставить ракетку и обнулить состояние: сценариям нужен разбег."""
        low, high = self.p.min_x, self.p.max_x
        self.p.pos = self.p.cmd = {"left": low, "right": high}.get(where, (low + high) / 2.0)
        self.p.vel = 0.0
        self.p.dt = self.dt
        self.p.target = None
        self.p.dir = 0
        self.p.held = 0
        self.tracker.reset()
        self.mouse_until = 0.0
        self.gas_frame = None
        self.manual = False
        return self

    # --- разборы ------------------------------------------------------------
    def positions(self) -> list[float]:
        return [f.pos for f in self.trace]

    def speeds(self) -> list[float]:
        return [f.vel for f in self.trace]

    def cells(self) -> list[int]:
        return [f.x for f in self.trace]

    def at_frame(self, index: int) -> Frame:
        return self.trace[min(index, len(self.trace) - 1)]

    def release_frame(self, start: int = 1) -> int | None:
        """Кадр, в котором игра объявила отпускание (был газ — стал ноль)."""
        for i in range(start, len(self.trace)):
            if self.trace[i].dir == 0 and self.trace[i - 1].dir != 0:
                return i
        return None

    def frames_until(self, predicate, start: int = 0) -> int | None:
        for i in range(start, len(self.trace)):
            if predicate(self.trace[i]):
                return i - start + 1
        return None


# ---------------------------------------------------------------------------
# Сценарии: короткие ситуации, в которых вес и предсказуемость видны числами
# ---------------------------------------------------------------------------
def _settle_frame(rig: Rig, start: int = 0, first: float | None = None) -> int:
    """Сколько кадров ракета реально ехала (последний кадр, в котором позиция
    изменилась). `first` — позиция до начала движения, без неё первый кадр
    движения не виден."""
    pos = ([first] if first is not None else []) + rig.positions()
    last = start
    for i in range(max(start, 1), len(pos)):
        if abs(pos[i] - pos[i - 1]) > 1e-12:
            last = i
    return last - start


def steps_total(steps: list[float]) -> float:
    return sum(steps)


def _steps(pos: list[float]) -> list[float]:
    return [b - a for a, b in zip(pos, pos[1:])]


def _max_step_after_peak(pos: list[float]) -> tuple[float, bool]:
    """Пронос (максимум вперёд от точки разворота) и признак отскока назад-вперёд."""
    peak = max(pos)
    tail = pos[pos.index(peak):]
    bounce = any(b > a + 1e-12 for a, b in zip(tail, tail[1:]))
    return peak - pos[0], bounce


def _stop_promised(rig: Rig, speed: float, at_pos: float) -> float:
    """Точка остановки, которую обещал Paddle.stop в момент отпускания."""
    return rig.p.stop_at(at_pos, speed)


def sc_tap(rig: Rig) -> dict:
    """Тап из покоя: ровно одна видимая клетка и чистая остановка."""
    rig.place()
    x0, p0 = rig.p.x, rig.p.pos
    rig.tap_key(1).frames(20)
    steps = _steps([p0] + rig.positions())
    settle = _settle_frame(rig, first=p0)
    return {"cell": rig.p.x - x0, "moved": steps_total(steps), "settle": settle,
            "settle_ms": settle * 1000.0 / rig.fps,
            "vel_rest": rig.p.vel, "max_acc_over_brake": max(f.acc for f in rig.trace) / rig.p.brake,
            "first_step": steps[0], "parabola_step": rig.p.accel * rig.dt ** 2 / 2.0,
            "ease_in": steps[0] < steps[1]}


def sc_taps(rig: Rig) -> dict:
    """Десять тапов с паузой 0.3 с (чаще терминал уже не отличить от удержания)."""
    rig.place()
    x0, p0 = rig.p.x, rig.p.pos
    cells = []
    for _ in range(10):
        rig.tap_key(1).seconds(max(0.3, 3.0 * rig.dt))     # тап и пауза «это не повтор»
        cells.append(rig.p.x - x0)                        # клетка после каждого тапа
    rig.frames(10)
    return {"cell": cells[-1], "moved": rig.p.pos - p0, "steps": cells,
            "one_cell_each": all(b - a == 1 for a, b in zip([0] + cells, cells)),
            "on_cell": abs(rig.p.pos - round(rig.p.pos)) < 1e-9, "vel_rest": rig.p.vel}


def sc_shelf(rig: Rig) -> dict:
    """Удержание: разгон до полки за вменяемое время, без скачка в первом кадре."""
    rig.place()
    rig.hold(1, rig.runway() * rig.dt + 0.05, settle=0.1)
    gas = rig.gas_frame or 0
    moving = rig.frames_until(lambda f: abs(f.vel) > 1e-9) or 1
    steps = _steps([rig.at_frame(gas).pos] + [f.pos for f in rig.trace[gas:]])
    ramp = rig.frames_until(lambda f: f.vel >= 0.99 * rig.p.speed, start=gas) or 999
    frame = rig.at_frame(gas + ramp - 1)
    return {"ramp_frames": ramp, "ramp_ms": ramp * 1000.0 / rig.fps,
            "moving_ms": moving * 1000.0 / rig.fps,
            "detect_ms": gas * 1000.0 / rig.fps,
            "shelf_shortfall": 1.0 - frame.vel / rig.p.speed,
            "shelf": rig.p.speed * rig.dt, "max_step": max(steps), "first_step": steps[0],
            "monotone": all(b >= a - 1e-12 for a, b in zip(steps[:ramp], steps[1:ramp])),
            "lead": frame.cmd - frame.pos, "lead_limit": rig.p.stopping_room}


def sc_release(rig: Rig) -> dict:
    """Отпустили клавишу: съезд ровно тормозной путь, тормозом, без возврата."""
    rig.place()
    rig.hold(1, rig.runway() * rig.dt, settle=0.25)      # коды кончились, время идёт
    detected = rig.release_frame() or len(rig.trace)
    at_release, speed_at_release = rig.trace[detected - 1].pos, rig.trace[detected - 1].vel
    promised = _stop_promised(rig, speed_at_release, at_release)
    rig.frames(40)
    tail = rig.trace[detected:]
    pos = [at_release] + [f.pos for f in tail]
    glide = pos[-1] - at_release
    return {"glide": glide, "ratio": glide / rig.p.min_stop_distance,
            "braking_distance": rig.p.braking_distance,
            "stop_room": rig.p.min_stop_distance,
            "detect_ms": (rig.trace[detected].t - rig.last_code_t) * 1000.0,
            "brake_frames": next((i + 1 for i, f in enumerate(tail) if f.vel == 0.0), 999),
            "stop_ms": speed_at_release / rig.p.brake * 1000.0,
            "max_acc_over_brake": max((f.acc for f in tail), default=0.0) / rig.p.brake,
            "monotone": all(step >= -1e-12 for step in _steps(pos)),
            "vel_rest": rig.p.vel, "stop_predict": abs(pos[-1] - promised)}


def sc_reversal(rig: Rig) -> dict:
    """Держали вправо, жмём влево и держим: встречный тормоз и разворот."""
    rig.place("mid")          # разбег нужен в обе стороны
    rig.hold(1, rig.runway(0.4) * rig.dt, settle=0)
    index, at, cell = len(rig.trace), rig.p.pos, rig.p.x
    launched = abs(rig.p.vel) / rig.p.speed          # с какой скорости начался разворот
    rig.tap_key(-1)
    window = max(rig.runway(0.4), int(0.5 * rig.fps))   # окно с запасом на латентность трекера
    rig.hold(-1, window * rig.dt, at=rig.t, settle=0, advance=False)
    rig.frames(window)
    tail_frames = rig.trace[index:]
    # кадр, в котором игра поняла, что держат НОВУЮ сторону (-1 = не поняла)
    gas2 = next((i for i, f in enumerate(tail_frames) if f.dir < 0), -1)
    detect_ms = gas2 * 1000.0 / rig.fps
    tail = [at] + [f.pos for f in tail_frames]
    overrun, bounce = _max_step_after_peak(tail)
    back = next((i + 1 for i, f in enumerate(tail_frames) if f.vel <= -0.99 * rig.p.speed), 999)
    return {"overrun": overrun, "ratio": overrun / rig.p.min_stop_distance,
            "reverse_frames": back,
            "reverse_ms": (back - max(gas2, 0)) * 1000.0 / rig.fps,
            "gas2_ms": detect_ms, "launched": launched,
            "max_acc_over_reverse": _braking_jerk(rig, tail_frames) / (rig.p.brake * PADDLE_REVERSE),
            "bounce": bounce, "moved_back": tail[-1] < at, "end_cell": rig.p.x - cell}


def sc_reversal_tap(rig: Rig) -> dict:
    """Встречный тап и отпустили: разворот и остановка ровно на клетке тапа."""
    rig.place("mid")        # и назад есть куда, и вперёд где разогнаться
    rig.hold(1, 0.3).frames(int(0.3 * rig.fps))
    rig.tap_key(-1).frames(1)
    frame, target, cell = rig.taps[-1]         # кадр тапа, его цель и видимая клетка
    index, at = frame, rig.trace[max(0, frame - 1)].pos
    rig.frames(60)
    tail = [at] + [f.pos for f in rig.trace[index:]]
    overrun, bounce = _max_step_after_peak(tail)
    return {"cell": rig.p.x - cell, "land_error": abs(tail[-1] - target),
            "vel_rest": rig.p.vel, "overrun": overrun,
            "overrun_ratio": overrun / rig.p.stopping_room, "bounce": bounce}


def _braking_jerk(rig: Rig, frames: list[Frame]) -> float:
    """Максимальное |Δv| пока ракета гасит ход (до пересечения нуля)."""
    worst = 0.0
    for f in frames:
        worst = max(worst, f.acc)
        if f.vel <= 0.0:
            break                       # дальше уже разгон в другую сторону
    return worst


def sc_physics(rig: Rig) -> dict:
    """Алгоритм без трекера: разгон, полка и съезд в чистом виде.

    KeyRepeatTracker добавляет к движению свою латентность (что это удержание,
    игра узнаёт только по второму коду), поэтому «вес» и «тормоза» меряются
    здесь, а распознавание ввода — в shelf/jitter/reversal.
    """
    rig.place()
    p0 = rig.p.pos
    rig.gas(1, rig.runway())
    ramp = rig.frames_until(lambda f: f.vel >= 0.99 * rig.p.speed) or 999
    steps = _steps([p0] + rig.positions())
    ramp_steps = steps[:ramp]
    shelf_frame = rig.at_frame(ramp - 1)
    index, at_release = len(rig.trace), rig.p.pos               # момент, когда газ убран
    lead, promised = rig.p.cmd - rig.p.pos, rig.p.stop          # что ракетка обещает
    rig.gas(0, 60)                                             # газ убран — торможение
    glide = rig.p.pos - at_release
    return {"ramp_frames": ramp, "ramp_ms": ramp * 1000.0 / rig.fps,
            "monotone": all(b >= a - 1e-12 for a, b in zip(ramp_steps, ramp_steps[1:])),
            "first_step": steps[0], "parabola_step": rig.p.accel * rig.dt ** 2 / 2.0,
            "shelf": rig.p.speed * rig.dt, "lead": lead,
            "lead_room": rig.p.stopping_room,
            "glide": glide, "ratio": glide / rig.p.min_stop_distance,
            "stop_room": rig.p.min_stop_distance,
            "stop_ms": shelf_frame.vel / rig.p.brake * 1000.0,
            "stop_predict": abs(rig.p.pos - promised), "vel_rest": rig.p.vel,
            "monotone_brake": all(abs(b) <= abs(a) + 1e-12
                                  for a, b in zip(_steps([at_release] + [f.pos for f in rig.trace[index:]]),
                                                  _steps([at_release] + [f.pos for f in rig.trace[index:]])[1:]))}


def sc_physics_reversal(rig: Rig) -> dict:
    """Разворот без трекера: встречный тап-адрес, затем газ в новую сторону."""
    rig.place("mid")        # разбег нужен в обе стороны
    rig.gas(1, rig.runway())
    index, at, cell = len(rig.trace), rig.p.pos, rig.p.x
    tap_paddle(rig.p, -1)
    rig.gas(-1, rig.runway())
    tail_frames = rig.trace[index:]
    tail = [at] + [f.pos for f in tail_frames]
    overrun, bounce = _max_step_after_peak(tail)
    back = next((i + 1 for i, f in enumerate(tail_frames) if f.vel <= -0.99 * rig.p.speed), 999)
    return {"overrun": overrun, "ratio": overrun / rig.p.min_stop_distance,
            "reverse_frames": back, "reverse_ms": back * 1000.0 / rig.fps,
            "max_acc_over_reverse": _braking_jerk(rig, tail_frames) / (rig.p.brake * PADDLE_REVERSE),
            "bounce": bounce, "moved_back": tail[-1] < at, "cell": rig.p.x - cell}


def sc_mouse(rig: Rig) -> dict:
    """Мышь: курсор резко позади на полном ходу, потом плавное слежение."""
    rig.place()
    rig.gas(1, rig.runway(0.4))                # разгон удержанием, без хвоста кодов
    index, at = len(rig.trace), rig.p.pos
    rig.mouse(rig.p.pos - 4).frames(40)
    overshoot = max(rig.trace[index:], key=lambda f: f.pos).pos - at
    error = abs(rig.p.pos - (at - 4))
    prev, jumps = rig.p.x, []
    for _ in range(30):
        rig.mouse(rig.p.pos + 3.0).frames(1)
        jumps.append(rig.p.x - prev)
        prev = rig.p.x
    return {"overshoot": overshoot, "overshoot_ratio": overshoot / rig.p.stopping_room,
            "cursor_error": error, "max_cell_step": max(jumps),
            "back_steps": sum(1 for jump in jumps if jump < 0),
            "step_limit": rig.p.speed * rig.dt + 1.0}


def sc_home_end(rig: Rig) -> dict:
    """Home/End: задать цель у стенки и доехать без перелёта."""
    rig.place()
    rig.key_end().frames(int(1.5 * rig.fps))
    right = rig.p.pos
    rig.key_home().frames(int(1.5 * rig.fps))
    return {"at_right": abs(right - rig.p.max_x), "at_left": abs(rig.p.pos - rig.p.min_x),
            "vel_rest": rig.p.vel, "crossed": right - rig.p.pos}


def sc_jitter(rig: Rig) -> dict:
    """Удержание на медленном автоповторе (SSH, 6 Гц) и на «быстром» терминале:
    когда серия распознана, скорость не должна проваливаться до отпускания."""
    rig.place()
    rig.hold(1, 0.4, hz=min(6.0, rig.repeat_hz), settle=0.05)
    shelf = rig.frames_until(lambda f: f.vel >= 0.99 * rig.p.speed) or 0
    released = rig.release_frame() or len(rig.trace)
    speeds = rig.speeds()[shelf:released]
    dips = sum(1 for a, b in zip(speeds, speeds[1:]) if abs(a) > 1e-9 and abs(b) < abs(a) - 1e-9)
    return {"stalled_frames": sum(1 for v in speeds if v == 0.0), "dip_frames": dips,
            "detect_frames": shelf, "learned_gap": rig.tracker.gap}


def sc_widen(rig: Rig) -> dict:
    """Бонус E у правой стенки: границы сузились — ракетка возвращается в поле."""
    rig.place()
    rig.key_end().frames(int(1.5 * rig.fps))
    rig.widen().frames(10)
    return {"outside": rig.p.pos - rig.p.max_x, "vel_rest": rig.p.vel,
            "width": rig.p.field.paddle_width}


def sc_rest(rig: Rig) -> dict:
    """Встала — и стоит: ни ползучих остатков, ни мигания клетки."""
    rig.place()
    rig.tap_key(1).seconds(0.3)
    rig.tap_key(1).seconds(0.3)
    pos, cell = rig.p.pos, rig.p.x
    rig.frames(600)
    return {"moved": abs(rig.p.pos - pos), "cell_flips": 0 if rig.p.x == cell else 1,
            "vel_rest": rig.p.vel}


SCENARIOS = {
    "tap": ("тап из покоя", sc_tap),
    "taps": ("10 тапов подряд (0.3 с)", sc_taps),
    "shelf": ("удержание: разгон и полка", sc_shelf),
    "release": ("отпускание: съезд и торможение", sc_release),
    "reversal": ("разворот с удержанием", sc_reversal),
    "reversal_tap": ("разворот одиночным тапом", sc_reversal_tap),
    "physics": ("алгоритм без трекера: разгон и съезд", sc_physics),
    "physics_reversal": ("алгоритм без трекера: разворот", sc_physics_reversal),
    "mouse": ("мышь: цель позади и слежение", sc_mouse),
    "home_end": ("Home / End через поле", sc_home_end),
    "jitter": ("медленный автоповтор 6 Гц", sc_jitter),
    "widen": ("бонус E у стенки", sc_widen),
    "rest": ("покой после остановки", sc_rest),
}


# ---------------------------------------------------------------------------
# Сторожевые правила: тот же набор инвариантов, что в tests/test_physics.py,
# но читаются числами отчёта. --tune использует их как целевую функцию.
# ---------------------------------------------------------------------------
@dataclass
class Rule:
    scenario: str
    key: str
    label: str
    ok: object                       # (значение, метрики) -> bool
    why: str = ""

    def check(self, metrics: dict) -> bool | None:
        if self.key not in metrics:
            return None
        try:
            return bool(self.ok(metrics[self.key], metrics))
        except TypeError:
            return None


CHECKS: list[Rule] = [
    # предсказуемость
    Rule("tap", "cell", "клеток на тап", lambda v, m: v == 1, "тап = ровно одна видимая клетка"),
    Rule("tap", "vel_rest", "скорость после тапа", lambda v, m: v == 0.0, "остановка обязана быть чистой"),
    Rule("tap", "settle_ms", "прибытие тапа, мс", lambda v, m: v <= max(50.0, 2.0 * m["frame_ms"] + 5),
         "дольше — тап кажется задумчивым"),
    Rule("taps", "on_cell", "после серии — целая клетка", lambda v, m: v, "цель живёт на сетке"),
    Rule("taps", "cell", "клеток после 10 тапов", lambda v, m: v == 10, "ошибка не накапливается"),
    Rule("taps", "one_cell_each", "каждый тап = клетка", lambda v, m: v, "по одному шагу на нажатие"),
    Rule("taps", "vel_rest", "скорость после серии", lambda v, m: v == 0.0),
    Rule("home_end", "at_left", "Home: зазор до стенки", lambda v, m: v <= 1e-9),
    Rule("home_end", "at_right", "End: зазор до стенки", lambda v, m: v <= 1e-9),
    Rule("mouse", "cursor_error", "ошибка курсора, клеток",
         lambda v, m: v <= max(0.5, 0.5 * m["frame_travel"])),
    Rule("mouse", "back_steps", "шагов назад при слежении", lambda v, m: v == 0, "дрожание"),
    Rule("mouse", "max_cell_step", "макс. скачок клетки", lambda v, m: v <= m["step_limit"]),
    Rule("widen", "outside", "вылезание за поле", lambda v, m: v <= 1e-12, "бонус E у стенки"),
    Rule("rest", "moved", "ползучесть в покое, клеток", lambda v, m: v == 0.0),
    Rule("rest", "cell_flips", "мигание клетки", lambda v, m: v == 0),
    # тактильность
    Rule("tap", "first_step", "первый кадр тапа", lambda v, m: v <= m["parabola_step"] * 1.001 + 1e-12,
         "старт не должен быть пинком (путь по средней скорости кадра)"),
    Rule("physics", "ramp_ms", "разгон до полки, мс",
         lambda v, m: 45.0 <= v <= max(110.0, 2.0 * m["frame_ms"]),
         "меньше — ракетка без веса, больше — вязнет"),
    Rule("physics", "monotone", "разгон монотонен", lambda v, m: v),
    Rule("physics", "first_step", "первый кадр разгона",
         lambda v, m: v <= m["parabola_step"] * 1.001 + 1e-12, "старт — пинок"),
    Rule("physics", "glide", "съезд, клеток", lambda v, m: v > 0.0, "ракетка рубила ход"),
    Rule("physics", "lead", "зазор опережения команды", lambda v, m: v <= m["lead_room"] + 1e-9,
         "команда убегает дальше точки остановки"),
    Rule("physics", "monotone_brake", "торможение только плавнее", lambda v, m: v),
    Rule("physics", "stop_predict", "ошибка обещания stop, клеток",
         lambda v, m: v <= max(0.5, 0.4 * m["frame_travel"]),
         "Paddle.stop обязан показывать реальное место остановки"),
    Rule("physics", "ratio", "съезд / достижимая дистанция", lambda v, m: 0.85 <= v <= 1.15),
    Rule("physics", "stop_ms", "время остановки, мс", lambda v, m: 38.0 <= v <= 62.0),
    Rule("physics", "vel_rest", "скорость после съезда", lambda v, m: v == 0.0),
    Rule("physics_reversal", "ratio", "пронос / достижимая дистанция", lambda v, m: v <= 1.0),
    Rule("physics_reversal", "reverse_ms", "разворот, мс",
         lambda v, m: v <= max(130.0, 2.5 * m["frame_ms"])),
    Rule("physics_reversal", "bounce", "отскок при развороте", lambda v, m: not v),
    Rule("physics_reversal", "moved_back", "поехала назад", lambda v, m: v),
    Rule("physics_reversal", "max_acc_over_reverse", "гашение / встречный тормоз",
         lambda v, m: v <= 1.02),
    Rule("shelf", "shelf_shortfall", "недобор до полки", lambda v, m: v <= 0.02),
    Rule("shelf", "lead", "зазор опережения команды", lambda v, m: v <= m["lead_limit"] + 1e-9,
         "команда удержания не должна убегать за точку остановки"),
    Rule("shelf", "detect_ms", "удержание распознано, мс", lambda v, m: v <= 200.0),
    Rule("release", "ratio", "съезд / дистанция остановки", lambda v, m: 0.85 <= v <= 1.15,
         "меньше — рубит ход, больше — катится сама"),
    Rule("release", "stop_ms", "время остановки, мс", lambda v, m: 38.0 <= v <= 62.0,
         "быстрее — удар, медленнее — резина"),
    Rule("release", "max_acc_over_brake", "макс. гашение / тормоз", lambda v, m: v <= 1.02,
         "удар об точку остановки"),
    Rule("release", "monotone", "съезд без возврата", lambda v, m: v),
    Rule("release", "vel_rest", "скорость после съезда", lambda v, m: v == 0.0),
    Rule("release", "stop_predict", "ошибка прогноза остановки, клеток",
         lambda v, m: v <= max(0.5, 0.4 * m["frame_travel"]),
         "игрок обязан знать, где ракетка встанет"),
    Rule("reversal", "ratio", "пронос / дистанция остановки", lambda v, m: v <= 1.0,
         "разворот инертен, но не безнаказанно"),
    Rule("reversal", "reverse_ms", "разворот до полной скорости, мс",
         lambda v, m: v <= max(130.0, 3.0 * m["frame_ms"]) or m["launched"] < 0.5,
         "разворот с полки не должен занимать дольше пары разгонов"),
    Rule("reversal", "bounce", "отскок при развороте", lambda v, m: not v),
    Rule("reversal", "moved_back", "ракетка поехала назад", lambda v, m: v,
         "встречное нажатие не должно проглатываться"),
    Rule("reversal", "max_acc_over_reverse", "макс. гашение / встречный тормоз", lambda v, m: v <= 1.02),
    Rule("reversal_tap", "cell", "клеток при встречном тапе", lambda v, m: v == -1),
    Rule("reversal_tap", "land_error", "ошибка приземления", lambda v, m: v <= 1e-9),
    Rule("reversal_tap", "bounce", "отскок при встречном тапе", lambda v, m: not v),
    Rule("jitter", "stalled_frames", "кадров стоя при удержании 6 Гц", lambda v, m: v == 0),
    Rule("jitter", "dip_frames", "провалов скорости", lambda v, m: v == 0),
]


def run_scenarios(field: Field, fps: int, variant: str = "new", repeat_hz: float = 30.0,
                  only: list[str] | None = None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for key, (_title, func) in SCENARIOS.items():
        if only and key not in only:
            continue
        rig = Rig(field, fps, variant=variant, repeat_hz=repeat_hz)
        metrics = func(rig)
        metrics["frame_ms"] = 1000.0 / fps          # правила считаются с учётом кадра
        metrics["frame_travel"] = PADDLE_TO_BALL * field.ball_speed / fps
        metrics["repeat_hz"] = rig.repeat_hz
        out[key] = metrics
    return out


def verdict(results: dict[str, dict]) -> list[tuple[Rule, bool | None]]:
    return [(rule, rule.check(results.get(rule.scenario, {}))) for rule in CHECKS]


# ---------------------------------------------------------------------------
# Отчёты
# ---------------------------------------------------------------------------
CONTEXT_KEYS = {"frame_ms", "frame_travel", "repeat_hz"}   # они в шапке отчёта


def fmt(value) -> str:
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, (list, tuple)):
        return "[" + " ".join(fmt(v) for v in value) + "]"
    return str(value)


def report(results: dict[str, dict], field: Field, fps: int, variant: str,
           repeat_hz: float = 30.0) -> None:
    marks = {(rule.scenario, rule.key): state for rule, state in verdict(results)}
    print(f"ракетка: поле {field.width}x{field.height} (игра {field.inner_width}x{field.play_rows}), "
          f"{fps} fps, автоповтор {repeat_hz:g} Гц, вариант '{variant}'")
    p = Paddle(field)
    print(f"Vmax={p.speed:.1f} кл/с ({p.speed / fps:.2f} кл/кадр), разгон={p.accel:.0f}, "
          f"тормоз={p.brake:.0f}, встречный={p.brake * PADDLE_REVERSE:.0f} кл/с², "
          f"тормозной путь={p.braking_distance:.2f} кл, кадр {1000.0 / fps:.1f} мс\n")
    for key, (title, _func) in SCENARIOS.items():
        if key not in results:
            continue
        print(f"{title}  [{key}]")
        for name, value in results[key].items():
            if name in CONTEXT_KEYS:
                continue
            state = marks.get((key, name))
            sign = {True: "ok ", False: "FAIL", None: "   "}[state]
            print(f"  {sign:<5}{name:20s} {fmt(value)}")
        print()


# «конверт», на котором правила имеют смысл: ниже — кадры длиннее клетки хода,
# медленнее 6 Гц автоповтор трекер принципиально не отличает от серии тапов
ENVELOPE = (20, 120, 6, 60)


def print_checks(results: dict[str, dict]) -> int:
    failed = 0
    fps = 1000.0 / next(iter(results.values()))["frame_ms"]
    repeat = next(iter(results.values()))["repeat_hz"]
    if not (ENVELOPE[0] <= fps <= ENVELOPE[1]) or not (ENVELOPE[2] <= repeat <= ENVELOPE[3]):
        print(f"внимание: {fps:.0f} fps / {repeat:.0f} Гц вне конверта "
              f"{ENVELOPE[0]}-{ENVELOPE[1]} fps и {ENVELOPE[2]}-{ENVELOPE[3]} Гц —"
              f" часть нарушений объясняется сеткой кадров, а не алгоритмом")
    for rule, state in verdict(results):
        if state is None:
            continue
        value = results[rule.scenario][rule.key]
        if state:
            print(f"  ok    {rule.scenario:13s} {rule.label:38s} {fmt(value)}")
        else:
            failed += 1
            print(f"  FAIL  {rule.scenario:13s} {rule.label:38s} {fmt(value)}"
                  f"   <- {rule.why or 'нарушен инвариант'}")
    print(f"\nправил: {len(CHECKS)}, нарушений: {failed}")
    return failed


CHART_SCENARIOS = ("tap", "shelf", "release", "reversal", "reversal_tap")


def chart(field: Field, fps: int, variant: str, key: str, frames: int, first: int = 0) -> None:
    rig = Rig(field, fps, variant=variant)
    SCENARIOS[key][1](rig)          # сценарий сам прогоняет ленту, берём её
    trace, p = rig.trace, rig.p
    print(f"\n{SCENARIOS[key][0]}  ({key}) — покадрово, вариант '{variant}'")
    print("  кадр      время   клетка    позиция      шаг   скорость   |dv|/тормоз  газ")
    previous = trace[0].pos if trace else 0.0
    shown = trace[first:first + frames]
    for i, f in enumerate(trace):
        if i >= first + frames:
            break
        step = f.pos - previous
        previous = f.pos
        if i < first:
            continue
        bar = int(min(1.0, abs(f.vel) / p.speed) * 18)
        print(f"  {i:>4d} {f.t * 1000:7.1f}мс {f.x:>7d} {f.pos:>11.4f} {step:>+9.3f} "
              f"{f.vel:>8.1f}  {f.acc / p.brake:>9.2f}   {'>' if f.dir > 0 else '<' if f.dir < 0 else '.'} "
              f"{'#' * bar}")


def film(field: Field, fps: int, variant: str, key: str, frames: int, first: int = 0) -> None:
    """Как это выглядит на поле: ракетка, её цель (│) и точка остановки (┆)."""
    rig = Rig(field, fps, variant=variant)
    SCENARIOS[key][1](rig)
    trace, p = rig.trace, rig.p
    span = max(p.field.inner_width, p.field.paddle_width + 12)
    span = min(span, 76)
    print(f"\n{SCENARIOS[key][0]} — глазами (окно {span} клеток, вариант '{variant}'); "
          f"█ ракетка, │ команда, ┆ где встанет")
    for i in range(first, min(first + frames, len(trace))):
        f = trace[i]
        left = int(clamp(f.x - span // 3, 0, max(0.0, p.field.inner_width - span)))
        row = ["·"] * span
        cmd_cell = int(math.floor(f.cmd + 0.5))
        if left <= cmd_cell < left + span:
            row[cmd_cell - left] = "│"
        for col in range(p.field.paddle_width):
            index = f.x - left + col
            if 0 <= index < span:
                row[index] = "█"
        stop_cell = int(math.floor(p.stop_at(f.pos, f.vel) + 0.5))
        if left <= stop_cell < left + span:
            row[stop_cell - left] = "┆"        # важнее ракетки: это обещание игроку
        arrow = "→" if f.vel > 1 else "←" if f.vel < -1 else " "
        print(f"  {i:>3d} {f.t * 1000:6.0f}мс │{''.join(row)}│ {arrow} v={f.vel:7.1f}")


# ---------------------------------------------------------------------------
# Подбор констант: сетка (разгон, тормоз, встречный) и рейтинг по правилам
# ---------------------------------------------------------------------------
TARGETS = (                       # (сценарий, метрика, идеал, вес)
    ("physics", "ramp_ms", 66.0, 1.0),           # вес старта
    ("physics", "stop_ms", 48.0, 0.7),           # остановка как решение
    ("physics", "ratio", 1.0, 1.0),              # съезд = дистанция остановки, ни кадром больше
    ("release", "max_acc_over_brake", 1.0, 0.5),
    ("physics_reversal", "reverse_ms", 95.0, 0.8),
    ("physics_reversal", "ratio", 0.66, 0.4),    # пронос заметно короче обычного съезда
    ("physics_reversal", "max_acc_over_reverse", 1.0, 0.3),
)


def apply_constants(accel: float | None = None, brake: float | None = None,
                    reverse: float | None = None, snap: float | None = None,
                    step: float | None = None, to_ball: float | None = None) -> None:
    """Покрутить константы, не трогая код алгоритма."""
    glob = globals()
    for name, value in (("PADDLE_ACCEL", accel), ("PADDLE_BRAKE", brake),
                        ("PADDLE_REVERSE", reverse), ("PADDLE_SNAP", snap),
                        ("PADDLE_KEY_STEP", step), ("PADDLE_TO_BALL", to_ball)):
        if value is not None:
            glob[name] = float(value)


def soft_score(results: dict[str, dict]) -> float:
    """Штраф за отклонение от целевых метрик; правила-инварианты считаются отдельно."""
    total = 0.0
    for key, metric, ideal, weight in TARGETS:
        value = results.get(key, {}).get(metric)
        if isinstance(value, (int, float)):
            total += weight * abs(value - ideal) / max(ideal, 1e-9)
    return 100.0 * total


def tune(field: Field, fps: int, variant: str, grid: list[float], brakes: list[float],
         reverse_grid: list[float], top: int, repeat_hz: float = 30.0) -> None:
    keys = ["tap", "physics", "physics_reversal", "release", "reversal", "reversal_tap", "mouse"]
    keep = (PADDLE_ACCEL, PADDLE_BRAKE, PADDLE_REVERSE)
    rows = []
    for accel in grid:
        for brake in brakes:
            if brake < accel - 6:                       # тормоз слабее мотора — не рассматриваем
                continue
            for reverse in reverse_grid:
                apply_constants(accel, brake, reverse)
                results = run_scenarios(field, fps, variant, repeat_hz, only=keys)
                broken = sum(1 for _rule, state in verdict(results) if state is False)
                rows.append((broken, soft_score(results), accel, brake, reverse))
    apply_constants(*keep)
    rows.sort(key=lambda row: (row[0], row[1]))
    print(f"\nподбор: {len(rows)} сочетаний (поле {field.width}x{field.height}, {fps} fps, '{variant}')")
    print(f"  {'наруш.':>6} {'штраф':>7}  разгон  тормоз  встречный   | текущие: "
          f"{keep[0]:g} / {keep[1]:g} / {keep[2]:g}")
    for broken, score, accel, brake, reverse in rows[:top]:
        mark = "  <- как сейчас" if (accel, brake, reverse) == keep else ""
        print(f"  {broken:>6} {score:>7.2f}  {accel:>6g}  {brake:>6g}  {reverse:>9g}{mark}")
    if rows and rows[0][0] == 0:
        best = rows[0]
        print(f"\n  ноль нарушений у {sum(1 for r in rows if r[0] == 0)} сочетаний; "
              f"ближайшее к идеалу: --accel {best[2]:g} --brake {best[3]:g} --reverse {best[4]:g}")


# ---------------------------------------------------------------------------
# Снимок метрик: записать один раз, потом сверять после каждой правки алгоритма
# ---------------------------------------------------------------------------
def golden(path: str, results: dict[str, dict], tolerance: float = 1e-6) -> int:
    try:
        previous = json.load(open(path, encoding="utf-8"))
    except FileNotFoundError:
        json.dump(results, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
        print(f"снимок метрик записан: {path}")
        return 0
    diffs = 0
    for key, metrics in results.items():
        for name, value in metrics.items():
            old = previous.get(key, {}).get(name)
            if isinstance(value, (int, float)) and isinstance(old, (int, float)):
                if abs(value - old) > tolerance:
                    diffs += 1
                    print(f"  изменилось: {key}.{name}: {fmt(old)} -> {fmt(value)}")
            elif old != value:
                diffs += 1
                print(f"  изменилось: {key}.{name}: {fmt(old)} -> {fmt(value)}")
    print(f"\nсверка со {path}: {'совпало' if diffs == 0 else f'{diffs} отличий'}")
    return diffs


def parse_size(text: str) -> tuple[int, int]:
    try:
        width, height = text.lower().split("x")
        return int(width), int(height)
    except ValueError:
        raise SystemExit(f"--size нужен вида 80x24, а не {text!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="полив движения ракетки (см. докстринг модуля)")
    parser.add_argument("--size", default="80x24", help="размер «терминала» WxH (80x24 = эталон)")
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--variant", choices=sorted(ALGORITHMS), default="new")
    parser.add_argument("--repeat", type=float, default=30.0, help="частота автоповтора клавиш, Гц")
    parser.add_argument("--scenario", default="all", help="список через запятую или all")
    parser.add_argument("--scenarios", action="store_true", help="показать сценарии и выйти")
    parser.add_argument("--check", action="store_true", help="только инварианты, код выхода = числа нарушений")
    parser.add_argument("--chart", action="store_true", help="покадровая лента")
    parser.add_argument("--film", action="store_true", help="лента клетки за кадром")
    parser.add_argument("--frames", type=int, default=16, help="кадров для --chart/--film")
    parser.add_argument("--from", dest="first", type=int, default=0, help="начать с кадра")
    parser.add_argument("--tune", action="store_true", help="сетка констант и рейтинг")
    parser.add_argument("--golden", metavar="FILE", help="записать или сверить снимок метрик")
    parser.add_argument("--accel", type=float), parser.add_argument("--brake", type=float)
    parser.add_argument("--reverse", type=float), parser.add_argument("--snap", type=float)
    parser.add_argument("--step", type=float), parser.add_argument("--to-ball", dest="to_ball", type=float)
    args = parser.parse_args(argv)

    apply_constants(args.accel, args.brake, args.reverse, args.snap, args.step, args.to_ball)
    width, height = parse_size(args.size)
    field = Field(width=width, height=height)

    if args.scenarios:
        for key, (title, _func) in SCENARIOS.items():
            print(f"  {key:14s} {title}")
        return 0

    only = None if args.scenario == "all" else [name.strip() for name in args.scenario.split(",")]
    unknown = [name for name in (only or []) if name not in SCENARIOS]
    if unknown:
        parser.error(f"неизвестный сценарий: {', '.join(unknown)} (см. --scenarios)")

    if args.tune:
        grid = [12.0, 14.0, 16.0, 18.0, 20.0, 22.0]        # разгон
        brakes = [14.0, 16.0, 18.0, 21.0, 24.0, 27.0]      # торможение
        tune(field, args.fps, args.variant, grid, brakes, [1.0, 1.25, 1.5, 1.75, 2.0], top=10,
             repeat_hz=args.repeat)
        return 0

    results = run_scenarios(field, args.fps, args.variant, args.repeat, only)

    if args.check:
        return 1 if print_checks(results) else 0
    if args.chart or args.film:
        keys = only or ["reversal"]
        for key in keys:
            (film if args.film else chart)(field, args.fps, args.variant, key, args.frames, args.first)
        return 0

    report(results, field, args.fps, args.variant, args.repeat)
    failed = print_checks(results)
    if args.golden:
        golden(args.golden, results)
    print("\nследующий шаг: --chart --scenario release|reversal, --film, --tune, "
          "--variant legacy для сравнения")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
