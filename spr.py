#!/usr/bin/env python3
"""
spr.py — ракетка арканоид на экране: интерактивная модель её движения.

Ракетку видно, она рисуется в терминале (curses, без зависимостей) и слушает
клавиатуру. Все четыре параметра движения задаются при запуске:

    1. пауза перед началом движения   --pause      секунды
    2. скорость движения              --speed      клеток/с
    3. ускорение при удержании клавиши --accel     клеток/с²
    4. максимальная скорость          --max-speed  клеток/с

Запуск:

    python3 spr.py                                  # параметры по умолчанию
    python3 spr.py 0.05 30 120 90                    # те же четыре позиционно
    python3 spr.py --pause 0.2 --speed 20 --accel 0 --max-speed 20   # без разгона
    python3 spr.py 0 40 200 120             # --pause 0: поехала в кадре нажатия
    python3 spr.py --pause 0 --exact-tap    # тот же ноль, но тап = ровно клетка
    python3 spr.py --fps 30 --width 14               # реже кадры, ракетка шире
    python3 spr.py --trace 1.2                      # покадровая лента без терминала
    python3 spr.py --check                          # инварианты модели; !=0 = сломано
    python3 spr.py --help                           # полный список параметров

Порядок позиционных аргументов тот же, что у флагов: пауза, скорость,
ускорение, максимум. Флаг перекрывает позиционный. Значения, не названные ни
там, ни там, берутся по умолчанию (они показаны в --help).

Единицы: время — секунды, скорость — клеток/с, ускорение — клеток/с². Клетка =
колонка терминала, как в arkanoid.py, поэтому параметры переносятся в игру
один-в-один по масштабу поля.

Модель движения ракетки
-----------------------

    нажали (пауза идёт)     тяги нет — это единственная задержка, и задаёт её
                            только --pause
    пауза истекла           тяга открывается СРАЗУ: v = min(Vmax, V + a·t),
                            разгон до полки = (Vmax-V)/a
    тап или удержание?      решает терминал уже на ходу: пришёл автоповтор —
                            газ остаётся; промолчал окно подтверждения
                            (1.7 интервала автоповтора) — ракета тормозит в
                            клетку тапа (а если клетка уже проедена — там, где
                            её честно остановит тормоз)
    отпустили               v -= a_t·t; ракетка проезжает тормозной путь
                            v²/(2·a_t) и встаёт
    Home/End                то же, что удержание, но целью стоит клетка у
                            стенки и потолок — Vmax, а не V

Здесь V = --speed, a = --accel, Vmax = --max-speed, a_t = --brake.

Задержка = --pause и больше ничего. Модель не ждёт «подтверждения удержания» и
не решает «тап это или нет» до первого движения: при --pause 0 ракета едет в
том же кадре, в котором принято нажатие (остаток — сетка кадров показа,
~1/fps: без timestamps от терминала дальше не уехать).

Чем за это плачено: одиночное нажатие при --pause 0 проезжает НЕ ровно клетку,
а клетку плюс то, что ракетка успела за окно подтверждения
(≈ V·1.7/repeat + v²/(2·a_t)). События «клавишу отпустили» в терминале нет, так
что узнать про тап раньше нечем. Нужна именно «ровно клетка» — зовите
--exact-tap: тогда перед стартом ракета дожидается подтверждения, и задержка
становится max(--pause, окно подтверждения).

Отклик у хода мгновенный: с места ракетка сразу получает V (это аркадная
модель — нажал, и она едет), а ускорение — это НАД v, то, насколько ход
разгоняется, если клавишу держать. Поэтому --accel 0 — не «сломанный» режим, а
классическая схема без разгона: всё время ровно V. Единственное место, где
скорость меняется скачком, — этот отклик 0 -> V; разворот (встречное нажатие)
гасится тормозом плавно, 1.5*a_t.

Пауза (--pause) — это мёртвое время между нажатием и началом движения: команда
принята, тяги ещё нет. Она включается на КАЖДОЕ новое нажатие (как старая
задержка автоповтора в X11), поэтому --pause 0.2 означает «ракетка трогается
через 200 мс после нажатия». Если нужно просто не дать себе дёргать ракетку в
первые секунды показа, есть отдельная --ready — блокировка ввода на старте.

Автоповтор при этом паузу НЕ взводит: иначе при --pause больше интервала
повтора (33 мс на X11, ~120 мс по SSH) ракетка не тронулась бы никогда.

Автоповтор клавиш в терминале — единственное, чем отличается «тап» от
«удержания» (события «клавишу отпустили» не бывает), поэтому здесь тот же
KeyRepeatTracker, что в arkanoid.py, — но с двумя поправками, без которых
ломалось удержание после серии частых нажатий:

  * «чаще выученного» — это тоже удержание. Автоповтор не бывает слишком частым,
    а сетка кадров рвёт его на куски (60 fps + 30 Гц = интервалы 16.7/33/50 мс);
    старая нижняя граница окна объявляла такие повторы новыми тапами;
  * интервал учим медианой короткого окна, а не односторонней EMA: три быстрых
    тапа больше не задирают окно так, что настоящие повторы в него перестают
    попадать (проверяется правилом `repeat` в --check).

Управление:

    ← → (или h l, или стрелки в русской раскладке)  тап = клетка, держать = разгон
    Home / End            ракетка к левой / правой стенке
    Space                 встать в центр поля
    + / -                 скорость движения (V) ±5 клеток/с наживо
    [ / ]                 ускорение (a) в 1.5 раза наживо
    , / .                 максимальная скорость (Vmax) ±15 клеток/с
    o / 0                 пауза перед началом движения ±0.02 с
    r                     сброс: в центр, след и метрики с нуля, пауза ещё раз
    p                     заморозить показ (кадр стоит, клавиши читаются)
    Ctrl-L                перерисовать экран после мусора в терминале
    q                     выход

Полезное на экране: клетка-«призрак» (куда ракетка едет по адресу), след
последних позиций, проекция «встанет в» (куда ракетка докатится по инерции),
шкала скорости, лента |v| по кадрам и ЗАМЕРЕННЫЕ время до начала движения,
разгон до Vmax и пик скорости — рядом с тем, что было задано.

Коды выхода: 0 — вышли по q, 1 — терминал не годится, 2 — нет интерактивного
терминала, при --check ненулевой код — нарушен хотя бы один инвариант.

Соседние файлы: arkanoid.py — сама игра (там движение уже встроено), speed.py —
безголовый полигон того же алгоритма игры. spr.py — про НАСТРОЙКУ четырёх
параметров глазами: их задаёшь в командной строке, щёлкаешь клавишами и сразу
видишь, как едет ракетка.
"""
from __future__ import annotations

import argparse
import curses
import locale
import math
import os
import random
import statistics
import sys
import time
from collections import deque
from dataclasses import dataclass, field, replace

# --- Совместимость со сборками curses --------------------------------------
# На Windows (windows-curses), в сборочных терминах и в нетипичных сборках
# части функций модуля просто нет; вызов даёт AttributeError посреди кадра, а
# except curses.error его не ловит. Достаём один раз и работаем через заглушки.
def _curses_func(name: str):
    func = getattr(curses, name, None)
    return func if callable(func) and not isinstance(func, type) else None


USE_DEFAULT_COLORS = _curses_func("use_default_colors")
# На разных терминалах curses умудряется кидать и ValueError, и AttributeError.
CURSES_FAILURE = (curses.error, ValueError, AttributeError)
KEY_HOME = getattr(curses, "KEY_HOME", -101)
KEY_END = getattr(curses, "KEY_END", -102)

# --- Автоповтор терминала ---------------------------------------------------
DEFAULT_REPEAT_GAP = 1 / 30
REPEAT_GAP_LIMIT = (0.015, 0.20)   # правдоподобный интервал автоповтора
REPEAT_SLOW_EDGE = 2.2             # x заученного: медленнее — уже новый тап
REPEAT_HISTORY = 5                 # по скольким интервалам учимся (медиана)
HOLD_TOLERANCE = 1.7               # через столько интервалов «повтор кончился»
ENVELOPE_REPEAT = (6.0, 60.0)      # Гц автоповтора, на которых модель ввода
ENVELOPE_FPS = (15, 120)           # рассчитана (вне её честнее предупреждение)

# --- Параметры движения по умолчанию ---------------------------------------
DEFAULT_PAUSE = 0.05      # с: мёртвое время между нажатием и началом движения
DEFAULT_SPEED = 30.0      # клеток/с: с какой скорости ход начинается
DEFAULT_ACCEL = 120.0     # клеток/с²: насколько быстрее он делается при удержании
DEFAULT_MAX_SPEED = 90.0  # клеток/с: потолок разгона
BRAKE_RATE = 21.0         # 1/с: торможение = BRAKE_RATE * V (тот же PADDLE_BRAKE)
REVERSE_RATE = 1.5        # x торможение: встречное торможение при смене направления
BRAKE_RATE_FLOOR = 30.0   # клеток/с²: ниже этого ракета не тормозит даже на V=0

TAP_STEP = 1.0            # клеток за тап
SNAP_PATH = 0.005         # остаток пути меньше этого — ноль
SNAP_SPEED = 0.02         # скорость меньше этого — ноль
MAX_CATCHUP = 4           # кадров догона за один проход цикла (защита от «телепорта»)

PHASE_IDLE = "покой"
PHASE_WAIT = "пауза"
PHASE_RUN = "разгон"
PHASE_TAP = "тап"
PHASE_GONE = "адрес"
PHASE_BRAKE = "торможение"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# ---------------------------------------------------------------------------
# Параметры: ровно то, что приходит из командной строки
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Motion:
    """Четыре параметра движения плюс производное торможение.

    Значения осмысленны в конверте 15-120 fps: на грубой сетке кадров один шаг
    проносит далеко, и ракета физически не может встать короче, чем
    0.5 * Vmax * dt (это видно по метрике «остаток» в --check).
    """

    pause: float = DEFAULT_PAUSE        # с, мёртвое время перед началом движения
    speed: float = DEFAULT_SPEED        # клеток/с, базовая скорость
    accel: float = DEFAULT_ACCEL        # клеток/с², прирост при удержании
    max_speed: float = DEFAULT_MAX_SPEED  # клеток/с, потолок
    brake: float | None = None          # клеток/с²; None -> BRAKE_RATE * speed
    tap_step: float = TAP_STEP          # клеток за тап
    exact_tap: bool = False             # ждать подтверждения удержания до старта

    def confirm_window(self, repeat_gap: float) -> float:
        """Сколько нужно молчать автоповтору, чтобы нажатие стало тапом.

        Это окно — не наша задержка, а физика терминала: событие «клавишу
        отпустили» приходит только как отсутствие повторов. --pause 0 разгоняет
        ракетку, не дожидаясь его; --exact-tap дожидается его ради «ровно клетки».
        """
        return max(repeat_gap, DEFAULT_REPEAT_GAP) * HOLD_TOLERANCE

    @property
    def dec(self) -> float:
        """Торможение, клеток/с²: по умолчанию 21/с от базовой скорости."""
        return self.brake if self.brake is not None else max(
            BRAKE_RATE_FLOOR, BRAKE_RATE * self.speed)

    def brake_like(self, target: float, vel: float) -> float:
        """Вдоль хода — обычный тормоз, навстречу ходу — встречный, злее."""
        return self.dec * (REVERSE_RATE if target * vel < 0 else 1.0)

    @property
    def shelf_time(self) -> float:
        """Сколько нужно удержания на полной тяге, от V до Vmax."""
        return (self.max_speed - self.speed) / self.accel if self.accel > 0 else 0.0

    def braking_distance(self, vel: float) -> float:
        """Тормозной путь с текущей скорости, клеток."""
        return vel * vel / (2 * self.dec)

    def capped(self) -> tuple[Motion, str | None]:
        """Привести к согласованному набору; вернуть предупреждение, если правим."""
        notes: list[str] = []
        pause = max(0.0, self.pause)
        speed = max(0.5, self.speed)
        accel = max(0.0, self.accel)
        max_speed = max(speed, self.max_speed)
        brake = None if self.brake is None else max(1.0, self.brake)
        if 0 < accel < 1.0:
            notes.append(f"ускорение {self.accel:g} кл/с² почти незаметно — разгон за "
                         f"{self.shelf_time:.0f} с; a=0 означает ход сразу с V")
        if max_speed != self.max_speed:
            notes.append(f"максимум {self.max_speed:g} не может быть меньше скорости — "
                         f"взяли {max_speed:g}")
        if speed != self.speed:
            notes.append(f"скорость {self.speed:g} слишком мала — взяли {speed:g}")
        if brake is not None and brake != self.brake:
            notes.append(f"торможение {self.brake:g} слишком слабое — взяли {brake:g}")
        return replace(self, pause=pause, speed=speed, accel=accel,
                       max_speed=max_speed, brake=brake), (
            "; ".join(notes) if notes else None)


# ---------------------------------------------------------------------------
# Ракетка: состояние и шаг физики (без curses — это можно гонять headless)
# ---------------------------------------------------------------------------
@dataclass
class Paddle:
    """Состояние ракетки и один шаг интегрирования.

    Единица позиции — клетка (колонка), pos хранится вещественным: ракета едет
    плавно, а рисуется в ближайшей клетке (см. x).
    """

    motion: Motion = field(default_factory=Motion)
    min_x: float = 0.0             # куда может встать ЛЕВЫЙ край ракетки
    max_x: float = 10.0
    pos: float = 0.0
    vel: float = 0.0               # клеток/с, со знаком
    width: int = 10                # клеток, только для отрисовки и границ

    # --- ввод ---
    key: int = 0                   # направление последней серии нажатий
    holding: bool = False          # автоповтор живой = клавишу держат
    wait: float = 0.0              # остаток паузы перед началом движения
    pending: float = 0.0           # окно подтверждения удержания (--pause 0)
    tap_target: float | None = None  # клетка тапа «на всякий случай»
    confirm_gap: float = DEFAULT_REPEAT_GAP  # выученный интервал автоповтора

    # --- фаза ---
    phase: str = PHASE_IDLE
    target: float | None = None    # адрес (тап, Home/End)
    run_t: float = 0.0             # сколько секунд тяга уже открыта
    boost: bool = False            # разрешён ли разгон выше V (у Home/End)

    # --- часы и метрики ---
    time: float = 0.0
    press_at: float | None = None  # когда приняли команду (замер задержки)
    move_at: float | None = None   # когда она сдвинула ракетку
    shelf_at: float | None = None  # когда дошли до Vmax
    shelf_lag: float | None = None # замеренное время разгона до полки (серия)
    peak: float = 0.0              # |v|max за серию
    vel_frame: float = 0.0         # скорость на начала кадра (для средней)
    trail: deque = field(default_factory=lambda: deque(maxlen=64))

    def __post_init__(self) -> None:
        if not self.trail:
            self.trail = deque([self.x] * self.trail.maxlen, maxlen=self.trail.maxlen)

    # --- клетка ---
    @property
    def x(self) -> int:
        """floor(pos + 0.5), а не round(): round округляет к чётному, и ракета
        на полуклетке рисовалась бы то там, то тут."""
        return int(math.floor(self.pos + 0.5))

    @property
    def stop_at(self) -> float:
        """Клетка, где ракета встанет, если начать тормозить прямо сейчас."""
        glide = self.motion.braking_distance(self.vel)
        return float(clamp(self.pos + math.copysign(glide, self.vel), self.min_x, self.max_x))

    # --- приём ввода ---
    def press(self, direction: int, repeat: bool, now: float | None = None) -> None:
        """Нажатие клавиши движения. repeat=True — это автоповтор, то есть держат.

        Начало серии взводит паузу: команда принята, а тяги нет ещё --pause
        секунд (при --pause 0 мёртвого времени не остается вовсе, и тяга
        открывается этим же кадром). Автоповтор паузу НЕ взводит — иначе при
        --pause больше интервала повтора ракета бы не тронулась никогда.

        Заодно начало серии обнуляет метрики (press_at/move_at/shelf_*): «замер
        задержки» всегда относится к последней нажатой серии, а не к первой.
        """
        if direction == 0:
            return
        if not repeat or self.key != direction:
            self.press_at = self.time if now is None else now
            self.move_at = None        # замер задержки считаем заново для серии
            self.shelf_at = None
            self.shelf_lag = None
            self.target = None
            window = self.motion.confirm_window(self.confirm_gap)
            wait = max(self.motion.pause, window) if self.motion.exact_tap \
                else self.motion.pause
            if wait > 0.0:
                self.phase = PHASE_WAIT
                self.wait = wait
                self.pending = 0.0
                self.tap_target = None
            else:
                # --pause 0: мёртвого времени нет вовсе — тяга сразу, а «тап это
                # был или удержание» решается по ходу: повтор подтвердит газ,
                # молчание терминала отправит тормозить в клетку тапа. Ждать
                # подтверждения, стоя на месте, смысл был бы только ценой
                # задержки в один-два интервала автоповтора.
                self.pending = self.motion.confirm_window(self.confirm_gap)
                self.tap_target = self._anchor(direction)
                self.phase = PHASE_RUN
                self.run_t = 0.0
                self.boost = True
        self.key = direction
        if repeat:
            self.holding = True

    def _anchor(self, direction: int) -> float:
        """Клетка тапа: tap_step от той, что игрок ВИДИТ (с учётом начатых)."""
        anchor = float(self.x)
        if (self.pos - anchor) * direction > 0.0:
            anchor = self.pos          # начатые полклетки засчитаны, отката нет
        return float(clamp(anchor + direction * self.motion.tap_step,
                           self.min_x, self.max_x))

    def go_to(self, position: float, boost: bool = True) -> None:
        """Адрес: клетка, до которой ракета обязана доехать (Home/End, центр)."""
        self.key = 0
        self.holding = False
        self.target = float(clamp(position, self.min_x, self.max_x))
        self.boost = boost
        self.run_t = 0.0
        self.phase = PHASE_GONE
        self.pending = 0.0
        self.tap_target = None
        self.press_at = self.time
        self.move_at = None            # метрики серии — с этого нажатия
        self.shelf_at = None
        self.shelf_lag = None

    def set_holding(self, holding: bool) -> None:
        """Вызывается каждый кадр: автоповтор ещё идёт или уже нет."""
        if not holding and self.holding:
            self.holding = False            # газ убрали -> BRAKE на следующем шаге
        elif holding and self.key:
            self.holding = True

    def reset(self, pos: float | None = None) -> None:
        """В центр (или в pos), след и метрики серии — с нуля."""
        center = (self.min_x + self.max_x) / 2.0 if pos is None else float(pos)
        self.pos = center
        self.vel = 0.0
        self.key = 0
        self.holding = False
        self.wait = 0.0
        self.phase = PHASE_IDLE
        self.target = None
        self.pending = 0.0
        self.tap_target = None
        self.boost = False
        self.run_t = 0.0
        self.press_at = self.move_at = self.shelf_at = None
        self.shelf_lag = None
        self.peak = 0.0
        self.trail = deque([int(math.floor(center + 0.5))] * self.trail.maxlen,
                           maxlen=self.trail.maxlen)

    # --- шаг физики ---
    def step(self, dt: float) -> None:
        """Один кадр. dt — секунды; состояние обновляется целиком здесь.

        Часов модели (self.time) идут впереди шага, поэтому press_at — это
        момент приёма команды, а move_at/shelf_at — конец кадра, в котором
        движение началось/достигнуто Vmax: замеренная задержка на кадр больше
        задания, и это честно (терминал тоже не может сдвинуть ракету раньше
        следующего кадра).
        """
        if dt <= 0.0:
            return
        m = self.motion
        self.time += dt
        self.vel_frame = self.vel

        if self.holding and self.key and self.phase in (PHASE_IDLE, PHASE_BRAKE, PHASE_TAP):
            # Клавишу всё ещё держат, а режима нет: тап уже отыгран или торможение
            # началось раньше, чем трекер понял, что повторы не кончились.
            self.phase = PHASE_RUN
            self.run_t = 0.0
            self.boost = True
            self.pending = 0.0
            self.tap_target = None
            self.target = None

        if self.phase == PHASE_WAIT:
            # Команда есть, тяги нет. Если ракета уже катилась КУДА ЖЕ, она
            # катится дальше, а не встаёт колом: пауза перед началом нового
            # нажатия не должна торить то, что уже едет. Встречная команда,
            # наоборот, начинает гаситься сразу.
            self.wait -= dt
            if self.wait > 0.0:
                self._coast(dt, keep=self._keeping())
            else:
                # Пауза кончилась посреди кадра: до этого момента ещё катимся
                # по-старому, после — уже с тягой. Кадр при этом считается ровно
                # один раз (иначе ракета скачет на два шага за кадр).
                passed = dt + self.wait        # часть кадра, прошедшая под паузой
                if 0.0 < passed < dt:
                    self._coast(passed, keep=self._keeping())
                    rest = dt - passed
                else:
                    rest = dt                  # пауза кончилась до начала кадра
                self.wait = 0.0
                self._start()
                self._thrust(rest)
        elif self.phase == PHASE_RUN:
            if self.pending > 0.0:
                # Газ открыт первым нажатием (--pause 0), а тап это или удержание
                # терминал ещё не подтвердил. Ждём окно подтверждения, НЕ глуша
                # тягу: именно здесь раньше пропадал разгон — ракета успевала
                # проехать клетку, встать и дождаться повтора с нулевой скорости.
                if self.holding:
                    # повтор подтвердил удержание — тяга продолжается, а не
                    # заводится заново со следующего кадра
                    self.pending = 0.0
                    self.tap_target = None
                    self._run(dt)
                else:
                    self.pending -= dt
                    if self.pending > 0.0:
                        self._run(dt)
                    else:
                        self.pending = 0.0
                        self._settle_tap()
                        self._thrust(dt)
            elif not self.holding:
                # газ убрали: тормозим уже в этом кадре, без паузы на целый кадр
                self.phase = PHASE_BRAKE
                self._coast(dt)
                if self.vel == 0.0:
                    self.phase = PHASE_IDLE
            else:
                self._run(dt)
        elif self.phase in (PHASE_TAP, PHASE_GONE):
            if self.holding and self.key:
                # автоповтор подоспел уже после тапа: это удержание, уходим на газ
                self.phase = PHASE_RUN
                self.run_t = 0.0
                self.boost = True
                self.target = None
                self._run(dt)
            else:
                self._address(dt, boost=self.phase == PHASE_GONE)
        elif self.phase == PHASE_BRAKE:
            self._coast(dt)
            if self.vel == 0.0:
                self.phase = PHASE_IDLE
        else:
            self.vel = 0.0

        self._wall()
        if self.move_at is None and abs(self.vel) > SNAP_SPEED:
            self.move_at = self.time
        self.peak = max(self.peak, abs(self.vel))
        if abs(self.vel) >= m.max_speed - 1e-6:
            if self.shelf_at is None:
                self.shelf_at = self.time
                if self.move_at is not None:
                    # запоминаем разгон серии: полка могла быть пройдена между
                    # кадрами, а следующим кадром ниже Vmax уже не будет
                    self.shelf_lag = self.time - self.move_at
        else:
            self.shelf_at = None
        self.trail.append(self.x)

    def _settle_tap(self) -> None:
        """Окно подтверждения истекло, повтор так и не пришёл — это был тап.

        В клетку тапа ещё можно встаться без удара (скорость не выше базовой и
        впереди целый тормозной путь) — едем в неё по кривой прибытия. Если за
        время окна ракета уже улетела дальше — честно тормозим там, где едем:
        врать про «ровно клетку» ценой мгновенной остановки не будем.
        """
        target, self.tap_target = self.tap_target, None
        ahead = (target - self.pos) * self.key if target is not None else -1.0
        if target is None or ahead <= SNAP_PATH:
            # клетку тапа уже проехали — разворачиваться назад не будем, честно
            # тормозим там, где едем
            self.phase = PHASE_BRAKE
            return
        self.target = target
        self.boost = False
        self.phase = PHASE_TAP

    def _keeping(self) -> bool:
        """Катится ли ракета в ту же сторону, куда зовёт новая команда."""
        return bool(self.key) and self.key * self.vel > 0.0

    def _thrust(self, dt: float) -> None:
        """Дотянуть кадр, в котором пауза истекла посередине."""
        if dt <= 0.0:
            return
        if self.phase == PHASE_RUN:
            self._run(dt)
        elif self.phase in (PHASE_TAP, PHASE_GONE):
            self._address(dt, boost=self.phase == PHASE_GONE)
        elif self.phase == PHASE_BRAKE:
            self._coast(dt)
            if self.vel == 0.0:
                self.phase = PHASE_IDLE

    def _start(self) -> None:
        """Пауза (--pause) истекла: тяга открывается сразу, а тап это был или
        удержание — решает терминал, молчанием или повтором.

        Прежняя логика («повтора нет ⇒ это тап ⇒ тормозим в клетку») при паузе
        короче окна подтверждения успевала проехать клетку и встать: разгон
        включался только с первым автоповтором, и это выглядело как задержка
        после нажатия. Дожидаться подтверждения до движения — значит добавить
        к задержке ещё и окно автоповтора, чего --pause не просил; это отдельный
        режим --exact-tap.
        """
        if self.holding and self.key:
            self.phase = PHASE_RUN
            self.run_t = 0.0
            self.boost = True
            self.target = None
            return
        if self.motion.exact_tap:
            self.target = self._anchor(self.key)
            self.boost = False
            self.pending = 0.0
            self.tap_target = None
            self.phase = PHASE_TAP
            return
        self.tap_target = self._anchor(self.key)
        self.pending = self.motion.confirm_window(self.confirm_gap)
        self.phase = PHASE_RUN
        self.run_t = 0.0
        self.boost = True
        self.target = None

    def _run(self, dt: float) -> None:
        """Удержание. Отклик — ход сразу с V, дальше |v| растёт с a до Vmax.

        То есть v(t) = min(Vmax, V + a·t) от момента, когда тяга открылась, и
        время до полки ровно (Vmax-V)/a — ровно то, что обещают параметры.
        Единственный скачок скорости здесь — переход 0 -> V на старте хода
        (аркадная модель: нажал — едет; в arkanoid.py тот же скачок гасится
        очень жёстким ускорением).
        """
        m = self.motion
        base = min(m.speed, m.max_speed)
        if self.vel * self.key < 0.0:
            # Команда против хода: сначала гасим встречным тормозом до нуля, а
            # разгон включится со следующего кадра — через ноль не прыгаем.
            drop = min(abs(self.vel), m.brake_like(self.key * base, self.vel) * dt)
            self.vel = 0.0 if drop >= abs(self.vel) - 1e-12 else self.vel - math.copysign(drop, self.vel)
            self._integrate(dt)
            return
        self.run_t += dt
        grown = base if self.vel == 0.0 else math.copysign(
            min(m.max_speed, abs(self.vel) + m.accel * dt), self.key)
        # ниже базовой скорости газ не держит (отклик), выше полки не пускает потолок
        self.vel = math.copysign(clamp(abs(grown), base, m.max_speed), self.key)
        self._integrate(dt)

    def _address(self, dt: float, boost: bool) -> None:
        """Едем в адрес. Кривая прибытия v=sqrt(2*a_t*d) гарантирует, что до
        цели хватает торможения, то есть клетка не проскакивается."""
        m = self.motion
        target = self.target if self.target is not None else self.pos
        distance = target - self.pos
        if abs(distance) <= SNAP_PATH and abs(self.vel) <= SNAP_SPEED:
            self.pos = target
            self.vel = 0.0
            self.phase = PHASE_IDLE
            self.target = None
            return
        arrival = math.copysign(math.sqrt(2.0 * m.dec * abs(distance)), distance)
        if boost:
            self.run_t += dt
            base = min(m.speed, m.max_speed)
            current = base if self.vel == 0.0 else math.copysign(
                min(m.max_speed, abs(self.vel) + m.accel * dt), self.key or (1 if distance > 0 else -1))
            limit = clamp(abs(current), 0.0, m.max_speed)
            wanted = math.copysign(min(limit, abs(arrival)), distance)
            self.vel = wanted
        else:
            # Тап — это адрес, а не газ: ускорение к нему не относится, ракета
            # идёт по кривой прибытия (иначе клетка ехала бы полсекунды). Если
            # скорости уже выше кривой (прилетели с газом), снижаемся не прыжком,
            # а тормозом: иначе остановка ощущается как удар.
            wanted = math.copysign(min(min(m.speed, m.max_speed), abs(arrival)), distance)
            if abs(wanted) < abs(self.vel):
                drop = min(abs(self.vel) - abs(wanted), m.dec * dt)
                self.vel = math.copysign(abs(self.vel) - drop, self.vel)
            else:
                self.vel = wanted
        self._integrate(dt)
        if (target - self.pos) * distance <= 0.0:
            self.pos = target                    # цель пройдена — встаём на ней
            self.vel = 0.0
            self.phase = PHASE_IDLE
            self.target = None

    def _coast(self, dt: float, keep: bool = False) -> None:
        """Только торможение: газ убран (или его и не было).

        keep=True — катимся с прежней скоростью (пауза перед началом движения
        попутной команды). Просадка скорости здесь — это и есть тот «сбой»,
        который видно, если терминал переклассифицировал удержание.
        """
        if self.vel:
            if not keep:
                drop = min(abs(self.vel), self.motion.dec * dt)
                self.vel -= math.copysign(drop, self.vel)
            self._integrate(dt)
        if self.vel == 0.0 and self.phase != PHASE_WAIT:
            self.phase = PHASE_IDLE

    def _integrate(self, dt: float) -> None:
        """Путь за кадр по СРЕДНЕЙ скорости кадра (как в arkanoid.py).

        Схема «взял новую скорость и ешь ею весь кадр» на грубой сетке кадров
        обнуляла торможение: гашение 30 -> 0 за кадр давало нулевой путь, и
        тап недоедал половину клетки. Кадр может делиться пополам (пауза
        истекла в его середине), поэтому `vel_frame` обновляется на каждом
        вызове — вторая половина считает уже свою среднюю.
        """
        self.pos += 0.5 * (self.vel_frame + self.vel) * dt
        self.vel_frame = self.vel

    def _wall(self) -> None:
        """Стенка: адрес у неё считается выполненным, газа это не отменяет."""
        if self.pos < self.min_x or self.pos > self.max_x:
            self.pos = float(clamp(self.pos, self.min_x, self.max_x))
            self.vel = 0.0
            if self.phase in (PHASE_TAP, PHASE_GONE):
                self.target = None
                self.phase = PHASE_RUN if (self.holding and self.key) else PHASE_IDLE


# ---------------------------------------------------------------------------
# Автоповтор клавиш: тап и удержание различаются только по интервалу
# (та же схема, что в arkanoid.py/speed.py, включая пакет кодов в одном кадре)
# ---------------------------------------------------------------------------
class KeyRepeatTracker:
    """
    Отличает одиночный тап от удержания — по интервалу автоповтора.

    Правила и почему именно так:

      * медленнее выученного окна (REPEAT_SLOW_EDGE) или правдоподобного
        предела (REPEAT_GAP_LIMIT[1]) — новая серия, то есть тап;
      * чаще — всегда тот же газ. Верхней частоты у автоповтора нет, а сетка
        кадров дробит интервалы: на 60 fps при 30 Гц приходят 16.7 / 33 / 50 мс.
        Прежняя версия требовала и нижнюю границу (>= 0.45 заученного) и училась
        только внутри неё: серия частых тапов задирала заученный интервал,
        настоящие повторы оказывались «реже допустимого», их объявляло новыми
        тапами, и удержание разваливалось на подскоки без разгона — а обратной
        дороги у обучения не было вовсе. Найден и исправлен по жалобе:
        «после тройного быстрого нажатия ракетка больше не разгоняется».
      * интервал учим медианой короткого окна — она устойчива к тапам и к
        пакетам кодов и быстро перестраивается, когда автоповтор изменился.
    """

    def __init__(self, initial_gap: float = DEFAULT_REPEAT_GAP) -> None:
        self.gap = initial_gap
        self.direction = 0
        self.pressed_at: float | None = None
        self.holding = False
        self.samples: deque[float] = deque(maxlen=REPEAT_HISTORY)

    def press(self, direction: int, now: float) -> bool:
        """True — это повтор (клавишу держат), False — начало новой серии (тап)."""
        interval = None
        if not self.direction or direction != self.direction or self.pressed_at is None:
            self.holding = False                      # новая серия: считаем тапом
        else:
            interval = now - self.pressed_at
            # Удержанием считается ВСЁ, что не медленнее правдоподобного
            # автоповтора. «Слишком частый» интервал — это тоже газ: сетка
            # кадров рвёт поток на части (60 fps и 30 Гц дают 16.7 / 33 / 50 мс),
            # а old-окно с нижней границей объявляло такие повторы новыми тапами
            # — удержание рассыпалось (см. докстринг класса и --check repeat).
            self.holding = interval <= min(REPEAT_GAP_LIMIT[1],
                                           self.gap * REPEAT_SLOW_EDGE)
        self.direction = direction
        self.pressed_at = now
        if interval is not None and REPEAT_GAP_LIMIT[0] <= interval <= REPEAT_GAP_LIMIT[1]:
            self._learn(interval)
        return self.holding

    def _learn(self, interval: float) -> None:
        """Выучиваем интервал автоповтора медианой последних REPEAT_HISTORY.

        Медиана, а не EMA: серия из трёх частых тапов (интервалы в разы длиннее
        автоповтора) не тянет окно вверх, а настоящий автоповтор медленного
        терминала всё равно за пару нажатий находит себя. Пакеты кодов с одним
        временем (интервал ~0) в выборку не попадают — они ничего не доказывают.
        """
        self.samples.append(interval)
        self.gap = clamp(statistics.median(self.samples), *REPEAT_GAP_LIMIT)

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
        self.samples.clear()


# ---------------------------------------------------------------------------
# Escape-последовательности, которые curses не распознал сам
# ---------------------------------------------------------------------------
class KeyDecoder:
    """
    При nodelay(True) ncurses не ждёт хвоста последовательности, и если
    terminfo не содержит kcuf=\\e[C (xterm-256color), вместо KEY_RIGHT приходит
    набор байтов 27, 91, 67. Собираем сами, иначе стрелок просто нет.
    """

    ESC = 27
    LENGTH_LIMIT = 12
    SHORT = {b"[C": curses.KEY_RIGHT, b"OC": curses.KEY_RIGHT,
             b"[D": curses.KEY_LEFT, b"OD": curses.KEY_LEFT,
             b"[A": curses.KEY_UP, b"OA": curses.KEY_UP,
             b"[B": curses.KEY_DOWN, b"OB": curses.KEY_DOWN,
             b"[H": KEY_HOME, b"OH": KEY_HOME, b"[F": KEY_END, b"OF": KEY_END}
    LAST = {ord("C"): curses.KEY_RIGHT, ord("D"): curses.KEY_LEFT,
            ord("A"): curses.KEY_UP, ord("B"): curses.KEY_DOWN,
            ord("H"): KEY_HOME, ord("F"): KEY_END}
    PREFIXES = (b"[", b"O")

    def __init__(self) -> None:
        self.buffer = bytearray()

    def feed(self, code: int) -> int | None:
        if not self.buffer:
            if code == self.ESC:
                self.buffer.append(self.ESC)
                return None
            return code
        self.buffer.append(code & 0xFF)
        raw = bytes(self.buffer[1:])
        if raw in self.SHORT:
            self.reset()
            return self.SHORT[raw]
        if len(self.buffer) > self.LENGTH_LIMIT:
            self.reset()
            return None
        if raw[:1] in self.PREFIXES and raw[-1:] and raw[-1] in self.LAST:
            key = self.LAST[raw[-1]]
            self.reset()
            return key
        return None

    def reset(self) -> None:
        self.buffer.clear()


# ---------------------------------------------------------------------------
# Геометрия показа: поле, линейка, ракетка
# ---------------------------------------------------------------------------
MIN_WIDTH = 44
MIN_HEIGHT = 15
BAR_WIDTH = 22
SPARK_CHARS = "▁▂▃▄▅▆▇█"


@dataclass(frozen=True)
class View:
    """Куда что рисовать. Пересчитывается при старте и на KEY_RESIZE."""

    width: int = 80
    height: int = 24
    motion: Motion = field(default_factory=Motion)
    paddle_width: int = 0          # 0 — авто от ширины поля
    fps: int = 60

    @property
    def inner(self) -> int:
        return max(14, self.width - 2)

    @property
    def wall_left(self) -> int:
        return max(0, (self.width - self.inner) // 2 - 1)

    @property
    def wall_right(self) -> int:
        return min(self.width - 1, self.wall_left + self.inner + 1)

    @property
    def left(self) -> float:
        return float(self.wall_left + 1)

    @property
    def right(self) -> float:
        return float(max(self.wall_left + 2, self.wall_right - 1))

    @property
    def paddle_cells(self) -> int:
        if self.paddle_width:
            return int(clamp(self.paddle_width, 3, max(3, int(self.right - self.left) - 2)))
        return int(clamp(round(self.inner / 12), 6, 20))

    def bounds(self) -> tuple[float, float]:
        low = self.left
        return low, max(low, self.right - self.paddle_cells + 1)

    def centered(self) -> float:
        low, high = self.bounds()
        return float(clamp((low + high) / 2.0, low, high))

    # строки
    row_top = 1
    row_ruler = 2
    row_air = 3
    row_paddle = 4
    row_track = 5
    row_bottom = 6
    row_hud = 7


def _utf8_term() -> bool:
    """Красивые символы — только если НЕИСПАРТИМНАЯ кодировка терминала UTF-8.

    getpreferredencoding() для этого не годится: на Python 3.7+ PEP 538
    докоэрсит C-локаль в C.UTF-8, и функция ответит «utf-8» даже когда
    LC_ALL=C, — curses тогда молча съест и псевдографику, и кириллицу. Смотрим
    на CODESET уже после locale.setlocale(LC_ALL, "").
    """
    try:
        encoding = locale.nl_langinfo(locale.CODESET) or ""
    except (AttributeError, ValueError, locale.Error):
        encoding = locale.getpreferredencoding(False) or ""
    return "utf" in encoding.lower()


class Canvas:
    """Постраничный буфер + побайтовый diff: ни мерцания, ни лишних write()."""

    def __init__(self, screen, color: bool = True) -> None:
        self.scr = screen
        self.color = color
        self.h = self.w = 0
        self.blank: list[tuple[str, int]] = []
        self.cells: list[list[tuple[str, int]]] = []
        self.prev: list[list[tuple[str, int]]] = []
        self.glyph = ({"paddle": "█", "edge_l": "▐", "edge_r": "▌", "ghost": "░",
                       "mark": "▴", "stop": "▾", "wall_v": "│", "wall_h": "─",
                       "corner": "┬", "arrow_l": "←", "arrow_r": "→", "spark": SPARK_CHARS,
                       "bar_empty": "░", "dot": "·"}
                      if _utf8_term() else
                      {"paddle": "#", "edge_l": "[", "edge_r": "]", "ghost": "-",
                       "mark": "^", "stop": "v", "wall_v": "|", "wall_h": "-",
                       "corner": "+", "arrow_l": "<", "arrow_r": ">", "spark": ".,-~=!#",
                       "bar_empty": ".", "dot": "."})
        self.attr = {
            "paddle": curses.A_REVERSE if not self.color else curses.A_BOLD,
            "wall": 0, "dim": curses.A_DIM, "hud": curses.A_BOLD,
            "target": curses.A_BOLD, "warn": curses.A_BOLD, "title": curses.A_BOLD,
        }
        self.resize(*screen.getmaxyx())

    def init_colors(self) -> None:
        if not self.color or not curses.has_colors():
            return
        if USE_DEFAULT_COLORS is not None:
            try:
                USE_DEFAULT_COLORS()
            except CURSES_FAILURE:
                pass
        pairs = {"wall": (curses.COLOR_BLUE, -1), "paddle": (curses.COLOR_GREEN, -1),
                 "target": (curses.COLOR_YELLOW, -1), "dim": (curses.COLOR_BLUE, -1),
                 "hud": (curses.COLOR_CYAN, -1), "warn": (curses.COLOR_MAGENTA, -1),
                 "title": (curses.COLOR_CYAN, -1)}
        self.attr = {}
        for index, (name, (fg, bg)) in enumerate(pairs.items(), start=1):
            try:
                curses.init_pair(index, fg, bg)
                base = curses.color_pair(index)
            except CURSES_FAILURE:
                base = 0
            bold = curses.A_DIM if name == "dim" else base | curses.A_BOLD
            self.attr[name] = bold
        self.attr["paddle"] = self.attr["paddle"] | curses.A_REVERSE   # зелёная плашка

    def resize(self, height: int, width: int) -> None:
        self.h, self.w = height, width
        self.blank = [(" ", 0)] * max(0, width)
        self.cells = [list(self.blank) for _ in range(max(0, height))]
        self.prev = [list(self.blank) for _ in range(max(0, height))]

    def begin(self) -> None:
        for row in self.cells:
            row[:] = self.blank

    def forget(self) -> None:
        for row in self.prev:
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
            start = 0
            while start < self.w:
                cell = row[start]
                end = start + 1
                while end < self.w and row[end] == cell:
                    end += 1
                if row[start:end] != old[start:end]:
                    try:
                        self.scr.addstr(y, start, "".join(c for c, _ in row[start:end]), cell[1])
                    except CURSES_FAILURE:
                        pass      # в правый нижний угол curses писать не умеет
                start = end
        self.prev, self.cells = self.cells, self.prev


# ---------------------------------------------------------------------------
# Что показывать: производные величины, снятые с состояния ракетки
# ---------------------------------------------------------------------------
@dataclass
class Readout:
    phase: str
    vel: float
    shelf: float          # доля полки (0..1) от Vmax
    cell: int
    step: float           # клеток за последний кадр
    start_lag: float | None
    expect_lag: float           # сколько задержки заказано (с точным тапом — окно)
    shelf_time: float | None
    peak: float                 # |v|max за серию
    stop_cell: float
    brake_path: float
    repeat_hz: float
    frame_ms: float


def readout(paddle: Paddle, gap: float, frame_ms: float, step: float) -> Readout:
    m = paddle.motion
    lag = (paddle.move_at - paddle.press_at) if (paddle.move_at is not None
                                                 and paddle.press_at is not None) else None
    shelf = paddle.shelf_lag
    return Readout(
        phase=paddle.phase,
        vel=paddle.vel,
        shelf=abs(paddle.vel) / m.max_speed if m.max_speed else 0.0,
        cell=paddle.x,
        step=paddle.vel * step,
        start_lag=lag,
        expect_lag=max(m.pause, m.confirm_window(gap)) if m.exact_tap else m.pause,
        shelf_time=shelf,
        peak=paddle.peak,
        stop_cell=paddle.stop_at,
        brake_path=m.braking_distance(paddle.vel or m.max_speed),
        repeat_hz=1.0 / gap if gap else 0.0,
        frame_ms=frame_ms,
    )


def sparkline(values: list[float], size: int, glyphs: str = SPARK_CHARS) -> str:
    """Лента |v| за последние size кадров, нормированная на Vmax."""
    if size <= 0:
        return ""
    out = []
    for value in values[-size:]:
        index = int(clamp(value, 0.0, 1.0) * (len(glyphs) - 1) + 0.5)
        out.append(glyphs[min(index, len(glyphs) - 1)])
    return "".join(out)


def speed_bar(vel: float, max_speed: float, size: int, filled: str = "█",
              empty: str = "░", left: str = "←", right: str = "→") -> str:
    ratio = clamp(abs(vel) / max_speed, 0.0, 1.0) if max_speed else 0.0
    filled_cells = int(round(ratio * size))
    head = right if vel > 1e-9 else (left if vel < -1e-9 else " ")
    return f"{head}[" + filled * filled_cells + empty * (size - filled_cells) + "]"


# ---------------------------------------------------------------------------
# Отрисовка кадра
# ---------------------------------------------------------------------------
HINT_MOVE = (" ← → / h l — тап = клетка, держать = разгон · Home/End — к стенке · "
             "Space — центр")
HINT_KEYS = (" +/− скорость V · [ ] ускорение a · , . максимум Vmax · o 0 пауза · "
             "r сброс · p показ · q выход")
FORMULA = (" модель: нажал → [пауза] → тяга сразу: v = min(Vmax, V + a·t) → отпустил: "
           "торможение v²/(2·a_t) · тап тормозит в свою клетку; ровно клетка — --exact-tap")


def draw(can: Canvas, view: View, paddle: Paddle, ro: Readout, m: Motion, *,
         vels: list[float] | None = None, frozen: bool = False, ready_left: float = 0.0,
         message: str = "", message_until: float = 0.0) -> None:
    now = time.monotonic()
    g = can.glyph
    can.begin()

    inner_left, inner_right = int(view.left), int(view.right)
    title = " арканоид · модель хода ракетки "
    params = (f"пауза {m.pause * 1000:3.0f} мс · V {m.speed:g} · a {m.accel:g} · "
              f"Vmax {m.max_speed:g} · {view.fps} fps")
    can.put(0, 0, title, can.attr["title"])
    can.put(0, max(len(title) + 1, can.w - len(params) - 1), params, can.attr["warn"])

    # поле
    for row in range(view.row_top, view.row_bottom + 1):
        can.put(row, view.wall_left, g["wall_v"], can.attr["wall"])
        can.put(row, view.wall_right, g["wall_v"], can.attr["wall"])
    can.put(view.row_top, view.wall_left + 1, g["wall_h"] * (inner_right - inner_left + 1),
            can.attr["wall"])
    can.put(view.row_bottom, view.wall_left + 1, g["wall_h"] * (inner_right - inner_left + 1),
            can.attr["wall"])

    # линейка колонок: цифры, каждая десятая жирнее
    for col in range(inner_left, inner_right + 1):
        digit = str(col % 10)
        can.put(view.row_ruler, col, digit,
                can.attr["hud"] if col % 10 == 0 else can.attr["dim"])

    # след: куда ракета заглядывала в последних кадрах
    recent = list(paddle.trail)[-24:]
    half = view.paddle_cells // 2
    for age, cell in enumerate(reversed(recent)):
        glyph = "▓" if age <= 3 else ("▒" if age <= 8 else "░")
        if g["paddle"] == "#":
            glyph = ":" if age <= 8 else "."
        can.put(view.row_air, cell + half, glyph, can.attr["dim"])

    # призрак адреса (куда едем по тапу / Home / End)
    if paddle.target is not None:
        tx = int(math.floor(paddle.target + 0.5))
        can.put(view.row_paddle, tx, g["ghost"] * view.paddle_cells, can.attr["target"])

    # ракетка
    x = paddle.x
    w = max(3, view.paddle_cells)
    body = g["paddle"] * w if g["paddle"] == "#" else \
        g["edge_l"] + g["paddle"] * (w - 2) + g["edge_r"]
    can.put(view.row_paddle, x, body, can.attr["paddle"])
    if paddle.key and (paddle.holding or paddle.phase in (PHASE_WAIT, PHASE_RUN, PHASE_TAP)):
        arrow = g["arrow_r"] if paddle.key > 0 else g["arrow_l"]
        column = x + w + 1 if paddle.key > 0 else x - 2
        can.put(view.row_paddle, column, arrow * 2,
                can.attr["hud"] if paddle.holding else can.attr["dim"])

    # дорожка: центр ракетки и клетка, где она встанет по инерции
    can.put(view.row_track, inner_left, g["wall_h"] * (inner_right - inner_left + 1),
            can.attr["dim"])
    can.put(view.row_track, x + w // 2, g["mark"], can.attr["paddle"])
    if abs(paddle.vel) > 1e-6:
        can.put(view.row_track, int(math.floor(paddle.stop_at + 0.5)) + w // 2,
                g["stop"], can.attr["target"])

    # HUD
    shelf_pct = int(round(ro.shelf * 100))
    tail = (f"встанет в {ro.stop_cell:5.1f} (путь {ro.brake_path:4.1f} кл)"
            if abs(ro.vel) > 1e-6 else
            f"встанет в {ro.stop_cell:5.1f}")
    phase_name = "газ?" if (paddle.phase == PHASE_RUN and paddle.pending > 0.0) else ro.phase
    line1 = (f" {phase_name:<9} v {ro.vel:+6.1f} кл/с ({shelf_pct:3d}% полки)   "
             f"x {ro.cell:<4}   шаг {abs(ro.step):4.2f} кл/кадр   {tail}")
    can.put(view.row_hud, 0, line1, can.attr["hud"])

    size = min(BAR_WIDTH, max(6, can.w // 4))
    strip = max(8, min(can.w - size * 2 - 34, 40))
    bar = speed_bar(ro.vel, m.max_speed, size, g["paddle"], g["bar_empty"],
                    g["arrow_l"], g["arrow_r"])
    tail = sparkline(vels or [], strip, g["spark"])
    line2 = f" {bar} {ro.vel:+6.1f} / {m.max_speed:g} кл/с · |v| за {strip} кадров {tail}"
    can.put(view.row_hud + 1, 0, line2[: can.w - 1], can.attr["hud"])

    line3 = (f" задано:  пауза {m.pause:.3f} с · V {m.speed:g} · a {m.accel:g} · "
             f"Vmax {m.max_speed:g} кл/с · тормоз {m.dec:g} кл/с² · "
             f"пик серии {ro.peak:.1f} кл/с")
    can.put(view.row_hud + 2, 0, line3[: can.w - 1], can.attr["dim"])

    lag = "   —  " if ro.start_lag is None else f"{ro.start_lag * 1000:4.0f} мс"
    got = "   —  " if ro.shelf_time is None else f"{ro.shelf_time * 1000:4.0f} мс"
    line4 = (f" замерено: тронулась через {lag} (надо {m.pause * 1000:.0f}) · "
             f"до Vmax {got} (расчёт {m.shelf_time * 1000:.0f}) · "
             f"повтор {ro.repeat_hz:3.0f} Гц · кадр {ro.frame_ms:4.1f} мс")
    can.put(view.row_hud + 3, 0, line4[: can.w - 1], can.attr["dim"])

    can.put(view.row_hud + 5, 0, HINT_MOVE[: can.w - 1], can.attr["dim"])
    can.put(view.row_hud + 6, 0, HINT_KEYS[: can.w - 1], can.attr["dim"])
    can.put(view.row_hud + 7, 0, FORMULA[: can.w - 1], can.attr["warn"])

    if ready_left > 0.0:
        can.put_centered(view.row_paddle - 1, f" приготовьтесь: {ready_left:4.1f} с ",
                         can.attr["warn"])
    elif message and now < message_until:
        can.put_centered(view.row_paddle - 1, f" {message} ", can.attr["warn"])
    if frozen:
        can.put_centered(view.row_bottom - 1, " ПОКАЗ ОСТАНОВЛЕН · p — продолжить ",
                         can.attr["warn"])
    can.flush()


# ---------------------------------------------------------------------------
# Живой цикл: curses + клавиатура
# ---------------------------------------------------------------------------
LEFT_KEYS = (curses.KEY_LEFT, ord("h"), ord("H"), ord("р"), ord("Р"), ord("ф"), ord("Ф"))
RIGHT_KEYS = (curses.KEY_RIGHT, ord("l"), ord("L"), ord("д"), ord("Д"), ord("в"), ord("В"))


class App:
    def __init__(self, stdscr, view: View, motion: Motion, ready: float = 0.0,
                 color: bool = True, repeat_hz: float = 30.0) -> None:
        try:
            curses.curs_set(0)
        except CURSES_FAILURE:
            pass
        stdscr.keypad(True)
        stdscr.nodelay(True)
        self.scr = stdscr
        self.view = view
        self.motion = motion
        self.color = color
        self.can = Canvas(stdscr, color)
        if color:
            self.can.init_colors()
        low, high = view.bounds()
        self.paddle = Paddle(motion=motion, min_x=low, max_x=high,
                             width=view.paddle_cells)
        self.paddle.reset(view.centered())
        self.keys = KeyDecoder()
        self.repeat = KeyRepeatTracker(1.0 / max(5.0, repeat_hz))
        self.frozen = False
        self.ready_seconds = max(0.0, ready)
        self.ready_until = time.monotonic() + self.ready_seconds
        self.message = ""
        self.message_until = 0.0
        self.forced = False
        self.vels: deque[float] = deque(maxlen=512)
        self.frame_ms = 1000.0 / max(1, view.fps)

    # --- цикл --------------------------------------------------------------
    def run(self) -> None:
        step = 1.0 / max(1, self.view.fps)
        previous = time.monotonic()
        accumulator = 0.0
        while True:
            if not self.handle_input():
                break
            now = time.monotonic()
            ready_left = max(0.0, self.ready_until - now)
            held = 0 if ready_left > 0.0 else self.repeat.active_direction(now)
            self.paddle.set_holding(bool(held) and held == self.paddle.key)
            self.paddle.confirm_gap = self.repeat.gap   # окно = выученный автоповтор

            frame = min(now - previous, 0.25)
            previous = now
            if not self.frozen and ready_left <= 0.0:
                accumulator += frame
                guard = 0
                while accumulator >= step and guard < MAX_CATCHUP:
                    accumulator -= step
                    guard += 1
                    self.paddle.step(step)
                    self.vels.append(abs(self.paddle.vel))
                if guard == MAX_CATCHUP:
                    accumulator = 0.0

            if self.forced:
                self.forced = False
                try:
                    self.scr.erase()
                except CURSES_FAILURE:
                    pass
                self.can.forget()

            ro = readout(self.paddle, self.repeat.gap, self.frame_ms, step)
            ceiling = self.motion.max_speed or 1.0
            draw(self.can, self.view, self.paddle, ro, self.motion,
                 vels=[v / ceiling for v in self.vels],
                 frozen=self.frozen, ready_left=ready_left,
                 message=self.message, message_until=self.message_until)

            spent = time.monotonic() - now
            rest = int((step - spent) * 1000)
            if rest > 0:
                curses.napms(rest)

    # --- ввод --------------------------------------------------------------
    def handle_input(self) -> bool:
        while True:
            code = self.scr.getch()
            if code == -1:
                self.keys.reset()
                return True
            key = self.keys.feed(code)
            if key is None:
                continue
            if not self.handle_key(key):
                return False

    def say(self, text: str, seconds: float = 1.2) -> None:
        self.message = text
        self.message_until = time.monotonic() + seconds

    def set_motion(self, **changes) -> None:
        self.motion = replace(self.motion, **changes)
        fixed, note = self.motion.capped()
        self.motion = fixed
        self.paddle.motion = fixed
        self.view = replace(self.view, motion=fixed)
        if note:
            self.say(note, 2.5)

    def handle_key(self, key: int) -> bool:
        now = time.monotonic()
        locked = now < self.ready_until      # --ready: ввод движения ещё не открыт
        # Esc — не выход: в терминале это начало хвоста последовательности.
        if key in (ord("q"), ord("Q"), ord("й"), ord("Й")):
            return False
        if key == curses.KEY_RESIZE:
            self.handle_resize()
            return True
        if key in (12, 18):            # Ctrl-L / Ctrl-R
            self.forced = True
            return True
        if key in LEFT_KEYS:
            self.nudge(-1, locked)
        elif key in RIGHT_KEYS:
            self.nudge(1, locked)
        elif key == KEY_HOME:
            if not locked:
                self.paddle.go_to(self.paddle.min_x)
        elif key == KEY_END:
            if not locked:
                self.paddle.go_to(self.paddle.max_x)
        elif key in (ord(" "), curses.KEY_ENTER, 10, 13):
            if not locked:
                self.paddle.go_to(self.view.centered())
        elif key in (ord("r"), ord("к"), ord("R"), ord("К")):
            self.paddle.reset(self.view.centered())
            self.repeat.reset()
            self.vels.clear()
            self.ready_until = now + self.ready_seconds
            self.say("сброс: ракетка в центре")
        elif key in (ord("p"), ord("з"), ord("P"), ord("З")):
            self.frozen = not self.frozen
        elif key in (ord("+"), ord("=")):
            self.set_motion(speed=self.motion.speed + 5.0)
            self.say(f"скорость {self.motion.speed:g} кл/с")
        elif key in (ord("-"), ord("_")):
            self.set_motion(speed=self.motion.speed - 5.0)
            self.say(f"скорость {self.motion.speed:g} кл/с")
        elif key == ord("]"):
            self.set_motion(accel=max(0.0, self.motion.accel * 1.5))
            self.say(f"ускорение {self.motion.accel:g} кл/с²")
        elif key == ord("["):
            self.set_motion(accel=self.motion.accel / 1.5)
            self.say(f"ускорение {self.motion.accel:g} кл/с²")
        elif key == ord("."):
            self.set_motion(max_speed=self.motion.max_speed + 15.0)
            self.say(f"максимум {self.motion.max_speed:g} кл/с")
        elif key == ord(","):
            self.set_motion(max_speed=self.motion.max_speed - 15.0)
            self.say(f"максимум {self.motion.max_speed:g} кл/с")
        elif key in (ord("o"), ord("O"), ord("щ"), ord("Щ")):
            self.set_motion(pause=max(0.0, self.motion.pause - 0.02))
            self.say(f"пауза {self.motion.pause * 1000:.0f} мс")
        elif key in (ord("0"), ord(")")):
            self.set_motion(pause=self.motion.pause + 0.02)
            self.say(f"пауза {self.motion.pause * 1000:.0f} мс")
        return True

    def nudge(self, direction: int, locked: bool = False) -> None:
        """Нажатие клавиши хода: трекер решает, тап это или автоповтор.

        Во время --ready это не нажатие вовсе: не кормим ни трекер (иначе он
        выучит несуществующую серию), ни ракетку.
        """
        if locked:
            return
        repeat = self.repeat.press(direction, time.monotonic())
        self.paddle.press(direction, repeat, self.paddle.time)

    def handle_resize(self) -> None:
        height, width = self.scr.getmaxyx()
        self.can.resize(height, width)
        self.view = replace(self.view, width=width, height=height)
        low, high = self.view.bounds()
        if height < MIN_HEIGHT or width < MIN_WIDTH:
            self.say(f"тесно: нужно минимум {MIN_WIDTH}x{MIN_HEIGHT}", 3.5)
        self.paddle.min_x, self.paddle.max_x = low, high
        self.paddle.width = self.view.paddle_cells
        inside = clamp(self.paddle.pos, low, high)
        if inside != self.paddle.pos:
            self.paddle.pos = inside
            self.paddle.vel = 0.0
            self.paddle.target = None
            if self.paddle.phase in (PHASE_TAP, PHASE_GONE):
                self.paddle.phase = PHASE_IDLE


def run_app(stdscr, view: View, motion: Motion, ready: float, color: bool,
            repeat_hz: float) -> None:
    height, width = stdscr.getmaxyx()
    if height < MIN_HEIGHT or width < MIN_WIDTH:
        stdscr.nodelay(False)
        text = f"spr: терминал {width}x{height}, нужно минимум {MIN_WIDTH}x{MIN_HEIGHT}."
        try:
            stdscr.addstr(0, 0, text[: max(0, width - 1)])
            stdscr.getch()
        except CURSES_FAILURE:
            pass
        return
    view = replace(view, width=width, height=height)
    App(stdscr, view, motion, ready=ready, color=color, repeat_hz=repeat_hz).run()


# ---------------------------------------------------------------------------
# Головые прогоны: --trace (лента кадров) и --check (инварианты). Без curses,
# поэтому модель можно смотреть и в CI. Клавиши подаются через тот же
# KeyRepeatTracker, что и в живом цикле, так что headless — это не «упрощённая
# версия», а тот же путь ввода.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Frame:
    t: float
    phase: str
    vel: float
    pos: float
    held: int


class Rig:
    """Полигон: подаёт таймлайн нажатий и крутит paddle.step с шагом 1/fps."""

    def __init__(self, motion: Motion, fps: float = 60.0, bounds: tuple[float, float] = (0.0, 60.0),
                 width: int = 10, repeat_hz: float = 30.0) -> None:
        self.motion = motion
        self.fps = fps
        self.step = 1.0 / fps
        self.paddle = Paddle(motion=motion, min_x=bounds[0], max_x=bounds[1], width=width)
        self.paddle.pos = self.paddle.min_x + 5.0
        self.tracker = KeyRepeatTracker(1.0 / max(5.0, repeat_hz))
        self.repeat_hz = repeat_hz
        self.frames: list[Frame] = []

    @staticmethod
    def hold_events(t0: float, seconds: float, direction: int, repeat_hz: float) -> list[tuple[float, int]]:
        """Таймлайн удержания: первое нажатие, потом автоповтор с частотой терминала."""
        gap = 1.0 / max(5.0, repeat_hz)
        out = [(t0, direction)]
        t = t0 + gap
        while t < t0 + seconds - 1e-9:
            out.append((t, direction))
            t += gap
        return out

    @staticmethod
    def tap_events(t0: float, direction: int) -> list[tuple[float, int]]:
        return [(t0, direction)]

    def run(self, keys: list[tuple[float, int]], seconds: float,
            extra: list[tuple[float, str, float]] | None = None,
            start: float | None = None) -> list[Frame]:
        """keys — [(время, направление)], extra — [(время, 'home'/'end'/'center', 0)]."""
        keys = sorted(keys)
        extra = sorted(extra or [])
        self.paddle.reset(self.paddle.min_x + 5.0 if start is None else start)
        self.tracker.reset()
        self.frames = []
        ki = xi = 0
        t = 0.0
        self.frames.append(Frame(t=0.0, phase=self.paddle.phase, vel=0.0,
                                 pos=self.paddle.pos, held=0))
        steps = int(round(seconds / self.step))
        for _ in range(steps + 1):
            while ki < len(keys) and keys[ki][0] <= t + 1e-9:
                _, direction = keys[ki]
                repeat = self.tracker.press(direction, t)
                self.paddle.press(direction, repeat, t)
                ki += 1
            while xi < len(extra) and extra[xi][0] <= t + 1e-9:
                _, kind, _v = extra[xi]
                if kind == "home":
                    self.paddle.go_to(self.paddle.min_x)
                elif kind == "end":
                    self.paddle.go_to(self.paddle.max_x)
                elif kind == "center":
                    self.paddle.go_to((self.paddle.min_x + self.paddle.max_x) / 2.0)
                xi += 1
            held = self.tracker.active_direction(t)
            self.paddle.set_holding(bool(held) and held == self.paddle.key)
            # окно подтверждения удержания живёт ровно столько, сколько выученный
            # автоповтор: на медленном терминале оно вчетверо длиннее
            self.paddle.confirm_gap = self.tracker.gap
            self.paddle.step(self.step)
            # метка кадра — его конец: состояние соответствует именно этому моменту,
            # иначе «ракета сдвинулась во время паузы» на грубой сетке кадров
            self.frames.append(Frame(t=t + self.step, phase=self.paddle.phase,
                                     vel=self.paddle.vel, pos=self.paddle.pos,
                                     held=self.paddle.key if self.paddle.holding else 0))
            t += self.step
        return self.frames


def start_of_motion(frames: list[Frame], t0: float) -> float | None:
    """Первый кадр после нажатия, в котором ракета СДВИНУЛАСЬ.

    По позиции, а не по скорости: на грубой сетке кадров тап успевает проехать
    клетку и погаситься внутри одного кадра, и скорость между кадрами не видна.
    """
    if not frames:
        return None
    start = frames[0].pos
    for frame in frames:
        if frame.t >= t0 and abs(frame.pos - start) > 1e-9:
            return frame.t
    return None


def trace(motion: Motion, seconds: float, fps: float, repeat_hz: float,
          bounds: tuple[float, float], width: int) -> int:
    """Удержание вправо на seconds, потом отпускание — и вся лента кадров."""
    t_press = 0.02
    keys = Rig.hold_events(t_press, seconds, 1, repeat_hz)
    rig = Rig(motion, fps=fps, bounds=bounds, width=width, repeat_hz=repeat_hz)
    frames = rig.run(keys, seconds + 1.0)
    gap = 1.0 / max(5.0, repeat_hz)
    print(f"# spr.py --trace: удержание → {seconds:g} с, затем отпускание")
    print(f"# пауза {motion.pause * 1000:.0f} мс · V {motion.speed:g} · a {motion.accel:g} · "
          f"Vmax {motion.max_speed:g} · торможение {motion.dec:g} кл/с² · {fps:g} fps · "
          f"автоповтор {repeat_hz:g} Гц")
    print(f"{'t, с':>7} {'фаза':<11} {'v, кл/с':>9} {'x, кл':>8} "
          f"{'шаг, кл/кадр':>13} {'после нажатия, мс':>18}")
    keep = max(1, math.ceil(len(frames) / 220))
    shown_t, shown_pos = frames[0].t, frames[0].pos
    for index, frame in enumerate(frames):
        if index % keep:
            continue
        span = max(1e-9, frame.t - shown_t)
        step_cells = (frame.pos - shown_pos) / span / fps if index else 0.0
        since = "" if frame.t < t_press else f"{(frame.t - t_press) * 1000:18.0f}"
        print(f"{frame.t:7.3f} {frame.phase:<11} {frame.vel:9.2f} {frame.pos:8.3f} "
              f"{step_cells:13.3f}{since}")
        shown_t, shown_pos = frame.t, frame.pos
    print_summary(motion, frames, t_press, fps)
    return 0


def print_summary(motion: Motion, frames: list[Frame], t_press: float, fps: float) -> None:
    moved = start_of_motion(frames, t_press)
    peak = max((abs(f.vel) for f in frames), default=0.0)
    last = frames[-1] if frames else None
    travelled = (max((f.pos for f in frames), default=0.0)
                 - min((f.pos for f in frames), default=0.0))
    lag = f"{(moved - t_press) * 1000:6.1f} мс" if moved else "    не тронулась"
    print()
    print(f" тронулась через {lag} (задано {motion.pause * 1000:.0f} мс; сверху — до двух"
          f" кадров сетки, ≤ {2000.0 / fps:.0f} мс)")
    print(f" пик скорости   {peak:6.1f} кл/с (полка {motion.max_speed:g})")
    print(f" разгон до полки расчётно {motion.shelf_time * 1000:6.1f} мс при непрерывном удержании")
    print(f" пройдено       {travelled:6.2f} кл за всю ленту")
    if last:
        print(f" финал: фаза {last.phase}, v {last.vel:+.3f} кл/с, x {last.pos:.3f}")


# --- инварианты -------------------------------------------------------------
@dataclass(frozen=True)
class Rule:
    key: str
    title: str
    check: object          # (motion, fps, repeat_hz, bounds, width) -> bool | str


CONFIRM_RULES = ("полка недостижима: автоповтор вне конверта 6-60 Гц",)


def _hold(motion, fps, repeat_hz, bounds, width, seconds, t_press=0.02,
          direction=1) -> tuple[list[Frame], float]:
    """Удержание и всё, что после него.

    Держим минимум столько, чтобы пауза и разгон до полки успели случиться:
    иначе на --pause 5 сценарий закончился бы, не начавшись. Возвращает
    (кадры, момент, когда клавишу отпустили).
    """
    hold = max(seconds, motion.pause + motion.shelf_time + 0.5)
    # хвост после отпускания — не меньше, чем нужно на полную остановку с Vmax
    tail = max(1.5, motion.max_speed / motion.dec + 0.5)
    rig = Rig(motion, fps=fps, bounds=bounds, width=width, repeat_hz=repeat_hz)
    keys = Rig.hold_events(t_press, hold, direction, repeat_hz)
    return rig.run(keys, t_press + hold + motion.pause + tail), t_press + hold


def _tap(motion, fps, repeat_hz, bounds, width, direction=1,
         t_press=0.02) -> tuple[list[Frame], Rig]:
    rig = Rig(motion, fps=fps, bounds=bounds, width=width, repeat_hz=repeat_hz)
    return rig.run(Rig.tap_events(t_press, direction), t_press + motion.pause + 2.5), rig


def rule_pause(motion, fps, repeat_hz, bounds, width) -> bool:
    """Пока пауза не истекла, ракета не сдвинулась ни на шаг."""
    frames, _rig = _tap(motion, fps, repeat_hz, bounds, width)
    t_press, start = 0.02, frames[0].pos
    for frame in frames:
        if frame.t < t_press + motion.pause - 1e-9:
            if abs(frame.pos - start) > 1e-9:
                return False
        elif abs(frame.pos - start) > 1e-9:
            return True
    return motion.pause > 0 and abs(frames[-1].pos - start) <= 1e-9


def rule_start_lag(motion, fps, repeat_hz, bounds, width) -> bool | str:
    """Задержка старта = заказанная --pause (плюс окно, если взят --exact-tap)."""
    frames, _rig = _tap(motion, fps, repeat_hz, bounds, width)
    moved = start_of_motion(frames, 0.02)
    if moved is None:
        return "не тронулась"
    want = motion.pause
    if motion.exact_tap:
        want = max(want, motion.confirm_window(1.0 / max(5.0, repeat_hz)))
    lag = moved - 0.02
    # плюс до двух кадров: нажатие приходит в середине кадра, а сдвиг виден
    # только на следующем
    if want - 1e-9 <= lag <= want + 2.5 / fps:
        return True
    return f"ждём {lag * 1000:.0f} мс, заказано {want * 1000:.0f} мс"


def rule_tap_cell(motion, fps, repeat_hz, bounds, width) -> bool | str:
    """Тап = ровно TAP_STEP клетка и старт в том же кадре, что нажатие.

    При --pause 0 (мгновенный отклик) «ровно клетка» физически недоступна: мы
    узнаём, что это был тап, только когда автоповтор промолчит окно
    подтверждения, — ракета к этому моменту уже едет. Тогда требование
    ослабляется до «не меньше клетки и не дальше честной остановки», зато
    задержка старта обязана быть нулевой. Точный тап при --pause 0 — это
    --exact-tap (см. rule_exact_tap).
    """
    if not ENVELOPE_REPEAT[0] <= repeat_hz <= ENVELOPE_REPEAT[1]:
        return True        # за пределом конверта тап неотличим от удержания
    base = min(motion.speed, motion.max_speed)
    for direction in (-1, 1):
        frames, rig = _tap(motion, fps, repeat_hz, bounds, width, direction)
        # окно, за которое терминал успел бы подтвердить удержание (выученный
        # интервал — не идеальный 1/repeat_hz: сетка кадров его квантует); пока
        # окно открыто, тяга работает и скорость успевает подрасти
        window = HOLD_TOLERANCE * max(rig.tracker.gap, 1.0 / max(5.0, repeat_hz))
        v_end = min(motion.max_speed, base + motion.accel * window)
        limit = (motion.tap_step + 0.5 * (base + v_end) * window
                 + motion.braking_distance(v_end) + 2.0 * v_end / fps)
        start = frames[0].pos
        finish = frames[-1].pos
        shift = abs(finish - start)
        if not motion.exact_tap:
            floor = motion.tap_step - max(0.05, 2.0 * v_end / fps)
            if not floor <= shift <= limit:
                return (f"направление {direction}: сдвиг {shift:.2f} кл, "
                        f"ожидалось {floor:.2f}…{limit:.2f}")
            moved = start_of_motion(frames, 0.02)
            want = motion.pause
            if moved is None or moved - 0.02 > want + 2.5 / fps:
                return (f"направление {direction}: тап стартует через "
                        f"{(moved - 0.02) * 1000 if moved else -1:.0f} мс при паузе "
                        f"{want * 1000:.0f} мс")
            continue
        if abs(shift - motion.tap_step) > 0.02:
            return f"направление {direction}: сдвиг {finish - start:+.3f} кл"
        whole = abs(motion.tap_step - round(motion.tap_step)) <= 1e-9
        if whole and abs(finish - round(finish)) > 0.02:
            return f"направление {direction}: встала не на клетку ({finish:.3f})"
    return True


def rule_exact_tap(motion, fps, repeat_hz, bounds, width) -> bool | str:
    """--exact-tap возвращает «ровно клетку» даже при --pause 0 — ценой окна."""
    if not ENVELOPE_REPEAT[0] <= repeat_hz <= ENVELOPE_REPEAT[1]:
        return True        # за пределом конверта автоповтор либо не выучивается,
                           # либо неотличим от тапов — правило пропускаем

    m = replace(motion, pause=0.0, exact_tap=True)
    window = m.confirm_window(1.0 / max(5.0, repeat_hz))
    for direction in (-1, 1):
        frames, _rig = _tap(m, fps, repeat_hz, bounds, width, direction)
        shift = abs(frames[-1].pos - frames[0].pos)
        if abs(shift - m.tap_step) > 0.02:
            return f"направление {direction}: сдвиг {shift:.2f} вместо {m.tap_step:g} кл"
        moved = start_of_motion(frames, 0.02)
        if moved is None:
            return "не тронулась"
        if not window - 1e-9 <= moved - 0.02 <= window + 2.5 / fps:
            return (f"старт через {(moved - 0.02) * 1000:.0f} мс, "
                    f"окно подтверждения {window * 1000:.0f} мс")
    return True


def rule_no_dip(motion, fps, repeat_hz, bounds, width) -> bool | str:
    """От нажатия до подтверждения удержания скорость не проседает.

    Регрессия «нажал — ракета подскочила, встала и только потом поехала»:
    раньше при --pause 0 модель сначала выбирала тап, успевала проехать клетку,
    тормозила, а газ включался лишь с первым автоповтором (замер: ноль
    скорости к моменту подтверждения и разгон на 63 мс позже нажатия).
    """
    if not ENVELOPE_REPEAT[0] <= repeat_hz <= ENVELOPE_REPEAT[1]:
        return True        # за пределом конверта автоповтор либо не выучивается,
                           # либо неотличим от тапов — правило пропускаем

    for pause in sorted({0.0, motion.pause}):
        m = replace(motion, pause=pause, exact_tap=False)
        rig = Rig(m, fps=fps, bounds=bounds, width=width, repeat_hz=repeat_hz)
        hold = max(0.4, pause + m.shelf_time + 0.5)
        frames = rig.run(Rig.hold_events(0.02, hold, 1, repeat_hz), pause + hold + 0.5)
        seen = [f for f in frames if f.t >= 0.02]
        start = next((i for i, f in enumerate(seen) if abs(f.vel) > SNAP_SPEED), None)
        if start is None:
            return f"pause={pause:g}: не тронулась"
        done = next((i for i, f in enumerate(seen) if f.held and i >= start), None)
        window = seen[start:(done + 1) if done is not None else len(seen)]
        if any(f.phase == PHASE_BRAKE for f in window):
            continue        # трекер успел объявить отпускание: это дребезг
                            # автоповтора, а не потеря тяги
        for a, b in zip(window, window[1:]):
            if abs(b.vel) < abs(a.vel) - 1e-9:
                return (f"pause={pause:g}: провал {abs(a.vel):.1f} → {abs(b.vel):.1f} кл/с "
                        f"до подтверждения удержания")
    return True


def rule_max_speed(motion, fps, repeat_hz, bounds, width) -> bool:
    frames, _ = _hold(motion, fps, repeat_hz, bounds, width, 3.0)
    return all(abs(f.vel) <= motion.max_speed + 1e-6 for f in frames)


def rule_shelf(motion, fps, repeat_hz, bounds, width) -> bool | str:
    """Время разгона до Vmax совпадает с (Vmax-V)/a с точностью до пары кадров."""
    if not ENVELOPE_REPEAT[0] <= repeat_hz <= ENVELOPE_REPEAT[1]:
        return True        # за пределом конверта автоповтор либо не выучивается,
                           # либо неотличим от тапов — правило пропускаем
    if motion.accel <= 0:
        return True
    frames, _ = _hold(motion, fps, repeat_hz, bounds, width, 3.0)
    # отсчёт от первого кадра с тягой: тап до подтверждения удержания тоже
    # сдвигает ракетку, но разгоном не является
    began = next((f.t for f in frames if f.phase == PHASE_RUN), None)
    hit = next((f.t for f in frames if began is not None and f.t >= began
                and abs(f.vel) >= motion.max_speed - 1e-6), None)
    if hit is None or began is None:
        return "полки не дождались"
    got, want = hit - began, motion.shelf_time
    if not want - 1e-9 <= got <= want + 3.0 / fps:
        return f"{got * 1000:.0f} мс вместо {want * 1000:.0f} мс"
    return True


def rule_release_stops(motion, fps, repeat_hz, bounds, width) -> bool | str:
    """Отпустил — встала; проехала не дальше тормозного пути + шаг кадра."""
    if not ENVELOPE_REPEAT[0] <= repeat_hz <= ENVELOPE_REPEAT[1]:
        return True        # за пределом конверта автоповтор либо не выучивается,
                           # либо неотличим от тапов — правило пропускаем

    frames, _ = _hold(motion, fps, repeat_hz, bounds, width, 1.0)
    # отсчёт от последнего кадра с тягой: трекер на грубой сетке кадров может
    # объявить отпускание раньше, чем кончится сценарий, а очень жёсткий тормоз
    # успевает встать за кадр, и кадров PHASE_BRAKE не бывает вовсе
    gas = [i for i, f in enumerate(frames) if f.phase == PHASE_RUN]
    if not gas:
        return "газ так и не открылся"
    after = frames[gas[-1]:]
    peak = abs(after[0].vel)
    if abs(after[-1].vel) > SNAP_SPEED:
        return f"скорость в конце {after[-1].vel:+.2f} кл/с"
    roll = max(f.pos for f in after) - min(f.pos for f in after)
    allowed = motion.braking_distance(peak) + peak / fps + 0.05
    if roll > allowed:
        return f"проехала {roll:.2f} кл при тормозном пути {allowed:.2f}"
    return True


def rule_no_teleport(motion, fps, repeat_hz, bounds, width) -> bool | str:
    """За кадр ракета не прыгает дальше, чем Vmax/fps (плюс кривая прибытия)."""
    if not ENVELOPE_REPEAT[0] <= repeat_hz <= ENVELOPE_REPEAT[1]:
        return True        # за пределом конверта автоповтор либо не выучивается,
                           # либо неотличим от тапов — правило пропускаем

    frames, _ = _hold(motion, fps, repeat_hz, bounds, width, 2.0)
    worst = 0.0
    for a, b in zip(frames, frames[1:]):
        worst = max(worst, abs(b.pos - a.pos))
    limit = motion.max_speed / fps + 1e-6
    if worst > limit:
        return f"шаг {worst:.3f} кл > {limit:.3f} кл"
    return True


def rule_reversal(motion, fps, repeat_hz, bounds, width) -> bool | str:
    """Разворот без рывков: внутри фазы |dv| <= max(a, 1.5*a_t) за кадр.

    Скачки разрешены только там, где модель меняет режим: старт хода сразу с V
    (отклик, см. _run и тап по кривой прибытия) и удар о стенку. Рывок внутри
    фазы — это то, что игрок чувствует как «дёргание».
    """
    rig = Rig(motion, fps=fps, bounds=bounds, width=width, repeat_hz=repeat_hz)
    keys = Rig.hold_events(0.02, 1.0, 1, repeat_hz) + Rig.hold_events(1.2, 0.5, -1, repeat_hz)
    frames = rig.run(keys, 2.5, start=(bounds[0] + bounds[1]) / 2.0)
    rate = max(motion.accel, motion.dec * REVERSE_RATE) / fps + 1e-6
    base = min(motion.speed, motion.max_speed)
    for a, b in zip(frames, frames[1:]):
        if abs(b.vel - a.vel) <= rate:
            continue
        # Смена режима — это отклик модели, а не рывок привода: старт хода с V
        # (в том числе с кривой прибытия у тапа) и удар о стенку скачут всегда.
        if a.phase != b.phase:
            continue
        if abs(a.vel) <= 1e-9 and abs(b.vel) <= base + 1e-9:
            continue
        against = min(abs(a.pos - bounds[0]), abs(a.pos - bounds[1]),
                      abs(b.pos - bounds[0]), abs(b.pos - bounds[1])) <= 1e-6
        if not against:
            return (f"скачок v на {abs(b.vel - a.vel):.1f} кл/с за кадр при t={b.t:.3f} "
                    f"(фаза {b.phase}), разрешено {rate:.1f}")
    return True


def rule_field(motion, fps, repeat_hz, bounds, width) -> bool | str:
    """Ракета не покидает поле ни при каком сочетании нажатий."""
    rng = random.Random(20260713)
    narrow = (0.0, float(max(12, width * 3)))          # тесное поле: стенки близко
    rig = Rig(motion, fps=fps, bounds=narrow, width=width, repeat_hz=repeat_hz)
    keys: list[tuple[float, int]] = []
    t = 0.0
    while t < 12.0:
        keys.append((round(t, 4), rng.choice((-1, 1))))
        if rng.random() < 0.55:
            keys += Rig.hold_events(round(t, 4), rng.uniform(0.1, 1.2), keys[-1][1], repeat_hz)
        t += rng.uniform(0.03, 0.5)
    frames = rig.run(keys, 14.0,
                     extra=[(3.0, "end", 0.0), (7.0, "home", 0.0), (10.0, "center", 0.0)])
    low, high = narrow
    for frame in frames:
        if not (low - 1e-6 <= frame.pos <= high + 1e-6):
            return f"x {frame.pos:.3f} вне поля [{low:g}..{high:g}]"
        if not math.isfinite(frame.vel):
            return "скорость стала нечисловой"
    if abs(frames[-1].vel) > SNAP_SPEED:
        return "после 14 с хаоса ракета всё ещё едет"
    return True


def rule_accel_zero(motion, fps, repeat_hz, bounds, width) -> bool | str:
    """Без ускорения ход идёт ровно с V и не разгоняется."""
    if not ENVELOPE_REPEAT[0] <= repeat_hz <= ENVELOPE_REPEAT[1]:
        return True        # за пределом конверта автоповтор либо не выучивается,
                           # либо неотличим от тапов — правило пропускаем

    calm = replace(motion, accel=0.0, max_speed=motion.speed)
    frames, _ = _hold(calm, fps, repeat_hz, bounds, width, 1.0)
    inside = [abs(f.vel) for f in frames if f.phase == PHASE_RUN]
    if len(inside) < 5:
        return "разгон не начался"
    steady = statistics.median(inside)
    if abs(steady - calm.speed) > 1e-6:
        return f"полка {steady:.3f} вместо {calm.speed:g} кл/с"
    return True


def rule_pause_zero(motion, fps, repeat_hz, bounds, width) -> bool | str:
    """--pause 0: ракета трогается и набирает тягу в первом же кадре."""
    calm = replace(motion, pause=0.0, exact_tap=False)
    rig = Rig(calm, fps=fps, bounds=bounds, width=width, repeat_hz=repeat_hz)
    frames = rig.run(Rig.hold_events(0.02, 0.3, 1, repeat_hz), 0.8)
    moved = start_of_motion(frames, 0.02)
    if moved is None:
        return "не тронулась"
    if moved - 0.02 > 2.5 / fps:
        return f"ждём {(moved - 0.02) * 1000:.0f} мс при кадре {1000.0 / fps:.0f} мс"
    began = next((f.t for f in frames if f.phase == PHASE_RUN), None)
    if began is None or began - 0.02 > 2.5 / fps:
        return "разгон начинается позже первого кадра"
    return True


def rule_hold_after_taps(motion, fps, repeat_hz, bounds, width) -> bool | str:
    """Регрессия «после тройного быстрого нажатия удержание не разгоняется».

    Три частых тапа (интервалы заметно больше автоповтора), потом нормальное
    удержание. Раньше тапы задирали выученный интервал, настоящие повторы
    переставали попадать в окно (нижняя граница!), каждая ложная «новая серия»
    взводила паузу и гасила скорость — разгон до Vmax не получался никогда.
    """
    if not ENVELOPE_REPEAT[0] <= repeat_hz <= ENVELOPE_REPEAT[1]:
        return True        # за пределом конверта автоповтор либо не выучивается,
                           # либо неотличим от тапов — правило пропускаем

    real = 1.0 / max(5.0, repeat_hz)
    tap_gap = min(0.40, max(real * REPEAT_SLOW_EDGE + 0.02, 0.06))
    if tap_gap >= 0.40:
        return True              # на совсем медленном автоповторе тап неотличим
    hold_from = 3 * tap_gap + motion.pause + 0.5
    rig = Rig(motion, fps=fps, bounds=bounds, width=width, repeat_hz=repeat_hz)
    keys = [(round(0.02 + i * tap_gap, 4), 1) for i in range(3)]
    keys += Rig.hold_events(hold_from, max(2.0, motion.shelf_time + 1.0), 1, repeat_hz)
    frames = rig.run(keys, hold_from + motion.pause + 3.5)
    peak = max(abs(f.vel) for f in frames)
    if peak < motion.max_speed - 1e-6:
        return f"пик {peak:.1f} кл/с вместо полки {motion.max_speed:g}"
    # срывом считаем только потерю газа внутри удержания: сами тапы теперь тоже
    # открывают тягу (мгновенный отклик), и каждое следующее нажатие — законная
    # новая серия, а не потеря газа
    late = [f for f in frames if f.t >= hold_from]
    began = next((i for i, f in enumerate(late) if f.phase == PHASE_RUN), None)
    gas = late[began:] if began is not None else []
    stalls = sum(1 for a, b in zip(gas, gas[1:])
                 if a.phase == PHASE_RUN and b.phase == PHASE_WAIT)
    if stalls:
        return f"{stalls} срыва удержания в паузу"
    learned = rig.tracker.gap
    if not real * 0.4 <= learned <= max(real * 3.0, 2.0 / fps):
        return f"выучен интервал {learned * 1000:.0f} мс при автоповторе {real * 1000:.0f} мс"
    return True


def rule_slow_terminal(motion, fps, repeat_hz, bounds, width) -> bool | str:
    """Медленный автоповтор (SSH, ~8 Гц) всё равно узнаётся как удержание."""
    if not ENVELOPE_REPEAT[0] <= repeat_hz <= ENVELOPE_REPEAT[1]:
        return True        # за пределом конверта автоповтор либо не выучивается,
                           # либо неотличим от тапов — правило пропускаем

    slow = 8.0
    hold = max(1.5, motion.pause + motion.shelf_time + 1.0)
    rig = Rig(motion, fps=fps, bounds=bounds, width=width, repeat_hz=slow)
    frames = rig.run(Rig.hold_events(0.02, hold, 1, slow), motion.pause + hold + 2.0)
    peak = max(abs(f.vel) for f in frames)
    if peak < motion.max_speed - 1e-6:
        return f"на 8 Гц автоповтора пик {peak:.1f} вместо {motion.max_speed:g}"
    if not 0.05 <= rig.tracker.gap <= 0.25:
        return f"выучен интервал {rig.tracker.gap * 1000:.0f} мс"
    return True


def rule_pause_in_flight(motion, fps, repeat_hz, bounds, width) -> bool | str:
    """Пауза перед началом движения: попутный ход сохраняет, встречный гасит.

    Модель вызвана напрямую, без трекера: момент «нажали, когда уже катились»
    через автоповтор не воспроизводится надёжно (он зависит от сетки кадров),
    а проверяем мы именно шаг физики.
    """
    rig = Rig(motion, fps=fps, bounds=(0.0, 20000.0), width=width, repeat_hz=repeat_hz)
    paddle = rig.paddle
    step = rig.step

    def ride(first: int, then: int) -> tuple[float, int, float]:
        """Разгон в одну сторону, потом новое нажатие (свежая пауза) в другую.

        Возвращает скорость на входе в паузу, число её кадров и минимальную
        скорость ВНУТРИ паузы: кадр, где она кончилась, не считаем — там уже
        начинается другой режим и скорость меняется по его закону.
        """
        paddle.reset((paddle.min_x + paddle.max_x) / 2.0)
        paddle.press(first, False, paddle.time)
        ramp = motion.pause + 0.5 + motion.shelf_time
        for _ in range(max(2, int(round(ramp / step)))):
            paddle.holding = True
            paddle.step(step)
        entry = abs(paddle.vel)
        paddle.press(then, False, paddle.time)     # новая серия = пауза взведена
        paddle.holding = False                     # как в живом цикле: повторов нет
        frames = 0
        low = entry
        while paddle.phase == PHASE_WAIT:
            paddle.step(step)
            if paddle.phase == PHASE_WAIT:
                frames += 1
                low = min(low, abs(paddle.vel))
            else:
                break
        return entry, frames, low

    if motion.pause <= 1.0 / fps:
        return True            # пауза короче кадра: проверить нечего
    entry, held, low = ride(1, 1)              # попутно: катимся дальше
    if entry < 1.0:
        return f"не разогнались для замера ({entry:.1f} кл/с)"
    if held == 0:
        return "пауза не продлилась ни одного кадра"
    if low < entry - 1e-9:
        return f"попутная пауза погасила ход с {entry:.1f} до {low:.1f} кл/с"
    entry, held, low = ride(1, -1)             # навстречу: гасится сразу
    if held and low >= entry - 1e-9:
        return f"встречная пауза не погасила ход ({entry:.1f} → {low:.1f} кл/с)"
    return True


RULES = [
    Rule("pause", "во время паузы ракета стоит", rule_pause),
    Rule("lag", "пауза выдержана ровно (задание + кадр)", rule_start_lag),
    Rule("tap", "тап = ровно tap_step, при целом шаге — на клетку", rule_tap_cell),
    Rule("vmax", "скорость не превышает Vmax", rule_max_speed),
    Rule("shelf", "разгон до Vmax = (Vmax-V)/a", rule_shelf),
    Rule("release", "после отпускания встала на тормозном пути", rule_release_stops),
    Rule("step", "шаг за кадр не больше Vmax/fps", rule_no_teleport),
    Rule("reverse", "внутри фазы скорость меняется плавно", rule_reversal),
    Rule("field", "ракета в поле при случайных нажатиях", rule_field),
    Rule("accel0", "a=0 → ход строго с V", rule_accel_zero),
    Rule("pause0", "пауза=0 → движение в первом кадре", rule_pause_zero),
    Rule("repeat", "частые тапы не ломают следующее удержание", rule_hold_after_taps),
    Rule("slowterm", "медленный автоповтор (8 Гц) узнаётся", rule_slow_terminal),
    Rule("flight", "пауза в полёте: попутный ход бережёт, встречный гасит",
         rule_pause_in_flight),
    Rule("nodip", "между нажатием и подтверждением удержания нет провала v",
         rule_no_dip),
    Rule("exacttap", "--exact-tap: ровно клетка и при --pause 0", rule_exact_tap),
]


def check(motion: Motion, fps: float, repeat_hz: float, size: tuple[int, int]) -> int:
    bounds = (0.0, 4000.0)     # простор, чтобы правила о скорости не упирались в стенку
    width = int(clamp(round(size[0] / 12), 6, 20))
    print(f"spr.py --check: V {motion.speed:g} · a {motion.accel:g} · Vmax {motion.max_speed:g} · "
          f"пауза {motion.pause * 1000:.0f} мс · {fps:g} fps · {size[0]}x{size[1]}")
    failed = 0
    for rule in RULES:
        try:
            verdict = rule.check(motion, fps, repeat_hz, bounds, width)
        except Exception as exc:                     # падение правила — тоже провал
            verdict = f"{type(exc).__name__}: {exc}"
        ok = verdict is True
        if isinstance(verdict, bool) and not ok:
            verdict = "см. модель"
        print(f" [{'ok ' if ok else 'МИМО'}] {rule.title}" + ("" if ok else f" — {verdict}"))
        failed += 0 if ok else 1
    if not ENVELOPE_FPS[0] <= fps <= ENVELOPE_FPS[1]:
        print(" [!]    вне конверта 15-120 fps: инварианты могут ломаться из-за сетки кадров")
    if not ENVELOPE_REPEAT[0] <= repeat_hz <= ENVELOPE_REPEAT[1]:
        print(f" [!]    вне конверта {ENVELOPE_REPEAT[0]:g}-{ENVELOPE_REPEAT[1]:g} Гц: "
              f"автоповтор неотличим от тапов, правила про подтверждение пропущены")
    print(f" вердикт: {'модель держится' if not failed else f'{failed} правил(о) нарушено'}")
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# Командная строка
# ---------------------------------------------------------------------------
EPILOG = """параметры движения (позиционно — в том же порядке):

  1) пауза перед началом движения, с      --pause       (по умолчанию 0.05)
  2) скорость движения, клеток/с          --speed       (по умолчанию 30)
  3) ускорение при удержании клавиши,     --accel       (по умолчанию 120)
                                            клеток/с²
  4) максимальная скорость, клеток/с      --max-speed   (по умолчанию 90)

примеры:

  python3 spr.py                          # параметры по умолчанию
  python3 spr.py 0.1 25 60 75             # те же четыре числа позиционно
  python3 spr.py --pause 0.25 --speed 40  # длинная задержка, потом быстрый ход
  python3 spr.py 0 40 200 120             # --pause 0: старт в кадре нажатия
  python3 spr.py --accel 0 --speed 55     # без разгона: всё время 55 кл/с
  python3 spr.py --pause 0 --exact-tap    # мгновенный ноль + тап ровно клетка
  python3 spr.py --trace 0.8 --fps 30     # лента кадров удержания, без терминала
  python3 spr.py --check                  # 16 инвариантов модели, !=0 = сломано

задержка старта — только --pause: тяга открывается в тот же кадр, что нажатие,
а «тап это или удержание» терминал подтверждает уже на ходу (окно = 1.7
интервала автоповтора). --exact-tap дожидается этого окна ДО движения и зато
гарантирует «тап = ровно клетка»; с ним задержка = max(--pause, окно).

торможение при отпускании по умолчанию = 21/с от скорости движения
(отношение из arkanoid.py); его тоже можно задать: --brake 400.
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="spr.py",
        description="Ракетка арканоид: показать и настроить движение (curses, без зависимостей)",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # четыре параметра позиционно ...
    parser.add_argument("pos_pause", nargs="?", type=float, default=None, metavar="ПАУЗА",
                        help="пауза перед началом движения, с")
    parser.add_argument("pos_speed", nargs="?", type=float, default=None, metavar="СКОРОСТЬ",
                        help="скорость движения, клеток/с")
    parser.add_argument("pos_accel", nargs="?", type=float, default=None, metavar="УСКОРЕНИЕ",
                        help="ускорение при удержании клавиши, клеток/с²")
    parser.add_argument("pos_max", nargs="?", type=float, default=None, metavar="МАКСИМУМ",
                        help="максимальная скорость, клеток/с")
    # ... и теми же словами флагами (флаг перекрывает позиционную пару)
    parser.add_argument("--pause", type=float, default=None, dest="pause",
                        help=f"пауза перед началом движения, с (по умолчанию {DEFAULT_PAUSE})")
    parser.add_argument("--speed", type=float, default=None,
                        help=f"скорость движения, клеток/с (по умолчанию {DEFAULT_SPEED})")
    parser.add_argument("--accel", type=float, default=None,
                        help=f"ускорение при удержании клавиши, клеток/с² "
                             f"(по умолчанию {DEFAULT_ACCEL})")
    parser.add_argument("--max-speed", type=float, default=None, dest="max_speed",
                        help=f"максимальная скорость, клеток/с (по умолчанию {DEFAULT_MAX_SPEED})")
    parser.add_argument("--brake", type=float, default=None, metavar="A_T",
                        help="торможение при отпускании, клеток/с² "
                             "(по умолчанию 21/с от скорости)")
    parser.add_argument("--tap-step", type=float, default=TAP_STEP, metavar="N",
                        help=f"клеток за один тап (по умолчанию {TAP_STEP:g})")
    parser.add_argument("--exact-tap", action="store_true", dest="exact_tap",
                        help="тап = ровно клетка даже при --pause 0: ракета ждёт, "
                             "пока терминал подтвердит удержание (~1.7 интервала "
                             "автоповтора), и ценой этой задержки не проезжает лишнего")
    parser.add_argument("--ready", type=float, default=0.0, metavar="СЕК",
                        help="не давать управлять первые СЕК секунд показа "
                             "(по умолчанию 0)")
    parser.add_argument("--fps", type=int, default=60,
                        help="кадров в секунду показа (по умолчанию 60)")
    parser.add_argument("--width", type=int, default=0, metavar="N",
                        help="ширина ракетки в клетках (по умолчанию — поля/12)")
    parser.add_argument("--size", metavar="WxH", default=None,
                        help="поле для --trace/--check (по умолчанию 80x24)")
    parser.add_argument("--repeat-hz", type=float, default=30.0, metavar="ГЦ",
                        help="частота автоповтора клавиш в --trace/--check "
                             "(по умолчанию 30)")
    parser.add_argument("--no-color", action="store_true", help="монохромный показ")
    parser.add_argument("--trace", type=float, default=None, metavar="СЕК",
                        help="без терминала: раскадровать удержание вправо на СЕК секунд")
    parser.add_argument("--check", action="store_true",
                        help="без терминала: проверить инварианты модели")
    return parser.parse_args(argv)


def motion_from_args(args: argparse.Namespace) -> Motion:
    """Четыре числа из позиционных/флаговых аргументов -> Motion (с починкой)."""
    motion = Motion(
        pause=first(args.pause, args.pos_pause, DEFAULT_PAUSE),
        speed=first(args.speed, args.pos_speed, DEFAULT_SPEED),
        accel=first(args.accel, args.pos_accel, DEFAULT_ACCEL),
        max_speed=first(args.max_speed, args.pos_max, DEFAULT_MAX_SPEED),
        brake=args.brake,
        tap_step=max(0.25, args.tap_step),
        exact_tap=args.exact_tap,
    )
    return motion


def first(*values: float | None) -> float:
    for value in values:
        if value is not None:
            return float(value)
    raise ValueError("нет ни одного значения")


def parse_size(text: str | None) -> tuple[int, int]:
    if not text:
        return 80, 24
    try:
        width, _, height = text.lower().partition("x")
        return max(20, int(width)), max(10, int(height))
    except ValueError:
        raise SystemExit("--size нужен вида 100x30")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    motion, note = motion_from_args(args).capped()
    fps = float(clamp(args.fps, 5, 240))
    size = parse_size(args.size)

    if note:
        print(f"spr: {note}", file=sys.stderr)

    if args.trace is not None:
        bounds = (1.0, float(max(12, size[0] - 11)))
        width = args.width or int(clamp(round(size[0] / 12), 6, 20))
        return trace(motion, max(0.05, args.trace), fps, args.repeat_hz, bounds, width)

    if args.check:
        return check(motion, fps, args.repeat_hz, size)

    if not (os.isatty(0) and os.isatty(1)):
        print("spr: нужен интерактивный терминал (для проверки модели есть --trace и --check).")
        return 2

    # Без этой строки при LANG=C curses рисует кириллицу пробелами.
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    os.environ.setdefault("ESCDELAY", "25")
    if not _utf8_term():
        print("spr: терминал не в UTF-8 — русские подписи и псевдографика "
              "не отрисуются; позовите LANG=C.UTF-8 (или en_US.UTF-8).", file=sys.stderr)

    # Размер поля в живом режиме берётся у терминала; --width задаёт ракетку,
    # --size здесь только подсказывает стартовый масштаб, если терминал велик.
    view = View(width=size[0], height=size[1], motion=motion,
                paddle_width=args.width, fps=int(fps))
    try:
        curses.wrapper(run_app, view, motion, max(0.0, args.ready), not args.no_color,
                       args.repeat_hz)
    except KeyboardInterrupt:
        pass
    except CURSES_FAILURE as exc:
        print(f"spr: терминал не подходит для curses ({exc}). TERM={os.environ.get('TERM')!r}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
