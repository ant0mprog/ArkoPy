"""Тесты физики арканоида — без терминала: python -m unittest discover -s tests"""

import curses
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import arkanoid as ark


def make_world(width=80, height=24, seed=1, **kwargs) -> ark.World:
    kwargs.setdefault("powerups", False)
    return ark.new_world(width, height, ark.Config(seed=seed, **kwargs))


def free_ball(world: ark.World, x: int, y: int, vx: int = 1, vy: int = -1) -> ark.Ball:
    for ball in world.balls:
        ball.dead = True
    ball = ark.Ball(x=x, y=y, vx=vx, vy=vy, stuck=False)
    world.balls = [ball]
    return ball


class PhysicsTest(unittest.TestCase):
    def test_ball_stays_inside_arena(self):
        world = make_world(seed=7)
        for _ in range(20000):
            world.launch()          # после потери жизни шарик снова на ракетке
            ark.advance(world, 1 / 60)
            for ball in world.balls:
                self.assertGreaterEqual(ball.x, world.left)
                self.assertLessEqual(ball.x, world.field_right)
                self.assertGreaterEqual(ball.y, world.ceiling)
                self.assertLessEqual(ball.y, world.floor_y)
            if world.over:
                break
        else:
            self.fail("за 5,5 минуты игры не закончилась ни одна жизнь")

    def test_ball_never_gets_a_vertical_course(self):
        """Регрессия: |vx| == 0 давал вечный размен и бесконечные очки."""
        for seed in range(20):
            world = make_world(seed=seed)
            for _ in range(3000):
                world.launch()
                for ball in world.balls:
                    if ball.stuck:
                        continue
                    self.assertLessEqual(abs(ball.vx), world.max_vx)
                    self.assertGreaterEqual(abs(ball.vx), 1, "шарик встал вертикально")
                    self.assertIn(ball.vy, (-1, 1))
                ark.advance(world, 1 / 60)

    def test_paddle_angle_depends_on_hit_spot(self):
        """Центр ракетки — пологий угол, край — самый крутой, нуля не бывает."""
        world = make_world()
        center = world.paddle_x + world.paddle_width // 2

        def bounce(offset: int, vx: int = 1) -> int:
            ball = free_ball(world, center + offset, world.paddle_y - 1, vx=vx, vy=1)
            return ark.paddle_bounce(world, ball)

        self.assertEqual(bounce(-world.paddle_width // 2), -world.max_vx)
        self.assertEqual(bounce(world.paddle_width // 2), world.max_vx)
        self.assertEqual(bounce(0, vx=-1), -1)                 # в центр — угол как был
        self.assertEqual(bounce(0, vx=-world.max_vx), -world.max_vx)
        self.assertNotEqual(bounce(1), 0)
        for offset in range(-4, 5):
            magnitude = abs(bounce(offset))
            self.assertGreaterEqual(magnitude, world.min_vx)
            self.assertLessEqual(magnitude, world.max_vx)

    def test_fast_ball_is_caught_by_paddle(self):
        """Отскок проверяется пересечением линии, а не совпадением строки."""
        world = make_world()
        world.speed = 3 * world.cfg.fps        # 3 клетки за кадр — точно больше одной
        ball = free_ball(world, world.paddle_x + 3, world.paddle_y - 2, vx=1, vy=1)
        for _ in range(400):
            ark.advance(world, 1 / 60)
            if ball.vy < 0:
                break
        self.assertLess(ball.vy, 0, "шарик пролетел ракетку")
        self.assertFalse(ball.dead)

    def test_arena_fills_terminal(self):
        """Поле = размер терминала (минус строка счёта и подсказки)."""
        for width, height in ((40, 14), (80, 24), (120, 40), (200, 60)):
            world = make_world(width, height)
            self.assertGreaterEqual(world.arena.inner_width, min(width - 2, ark.ARENA_MIN_WIDTH))
            self.assertEqual(world.left, world.arena.inner_left)
            self.assertEqual(world.field_right, width - 2)
            self.assertEqual(world.arena.right, width - 1)
            self.assertEqual(world.paddle_y, height - 3)
            self.assertLess(world.brick_top, world.paddle_y)

    def test_arena_width_can_be_capped(self):
        """--arena-width: поле уже терминала, если игрок хочет короткие уровни."""
        cfg = ark.Config(seed=1, max_arena_width=40)
        world = ark.new_world(160, 40, cfg)
        self.assertEqual(world.arena.inner_width, 40)
        self.assertLess(world.arena.left, world.arena.right)
        self.assertEqual(world.bricks[0] and len(world.bricks[0]), 40)
        ark.resize(world, 90, 30)
        self.assertEqual(world.arena.inner_width, 40)

    def test_wider_arena_clears_slower_but_finite(self):
        """Скорость и толщина стены растут с полем: уровень конечен везде."""
        times = {}
        for size in ((40, 14), (80, 24), (200, 60)):
            world = ark.new_world(*size, ark.Config(seed=3, lives=99, powerups=False))
            for _ in range(60 * 400):
                ark.aim_ai_paddle(world)
                if world.balls and world.balls[0].stuck:
                    world.launch()
                if "level" in ark.advance(world, 1 / 60):
                    times[size] = _ / 60
                    break
            else:
                self.fail(f"{size}: уровень не пробит за 400 с")
        self.assertLess(times[(40, 14)], times[(200, 60)] * 3)

    def test_every_brick_column_is_reachable(self):
        """Регрессия: кирпичи в крайних колонках были недостижимы — уровень
        нельзя было пройти (софт-лок)."""
        for width, height in ((80, 24), (40, 14), (120, 50), (200, 60), (60, 20)):
            for level in range(1, 8):
                world = make_world(width, height)
                world.level = level
                world.speed = world.level_speed(level)
                world.reset_level()
                cols = {world.brick_left + c for row in world.bricks for c, hp in enumerate(row) if hp}
                self.assertTrue(cols, f"{width}x{height} ур.{level}: нет ни одного кирпича")
                self.assertTrue(
                    all(world.left <= x <= world.field_right for x in cols),
                    f"{width}x{height} ур.{level}: кирпичи вне поля",
                )
                self.assertTrue(world.bricks_left())

    def test_level_is_clearable_on_any_terminal_size(self):
        """Стена считается из размера поля: уровень проходится и на 40x14,
        и на 200x60 за сопоставимое время (иначе игра непобедима)."""
        for width, height in ((40, 14), (58, 16), (80, 24), (100, 30), (120, 40), (200, 60)):
            world = make_world(width, height, seed=3, lives=99)   # меряем чистое время пробоя
            step = 1 / 60
            limit = 60 * 320        # на широком поле уровень объективно длиннее
            cleared = False
            for frame in range(limit):
                world.launch()
                ark.aim_ai_paddle(world)
                events = ark.advance(world, step)
                if "level" in events:
                    cleared = True
                    break
                if world.over:
                    break
            self.assertTrue(cleared, f"{width}x{height}: уровень не пробит за 200 с")

    def test_ball_reaches_extreme_columns_and_bounces(self):
        """Крайние колонки у самих стенок достижимы: на них тоже висят кирпичи."""
        world = make_world()
        y = world.paddle_y - 3
        ball = free_ball(world, world.left + 1, y, vx=-1, vy=1)
        events: list[str] = []
        self.assertTrue(ark.move_x(world, ball, events))
        self.assertEqual(ball.x, world.left)
        self.assertFalse(ark.move_x(world, ball, events), "дальше уже стенка")
        self.assertEqual((ball.vx, ball.x), (1, world.left))

        ball = free_ball(world, world.field_right - 1, y, vx=1, vy=-1)
        self.assertTrue(ark.move_x(world, ball, events))
        self.assertEqual(ball.x, world.field_right)
        self.assertFalse(ark.move_x(world, ball, events))
        self.assertEqual((ball.vx, ball.x), (-1, world.field_right))

    def brick_neighbourhood(self, world):
        """Первый кирпич верхнего ряда и соседняя с ним пустая клетка."""
        row = world.bricks[0]
        col = next(i for i, hp in enumerate(row) if hp)
        step = 1 if col + 1 < len(row) and not row[col + 1] else -1
        return world.brick_left + col, world.brick_left + col + step

    def test_destroyed_brick_does_not_bounce_ball(self):
        world = make_world()
        brick_x, start_x = self.brick_neighbourhood(world)
        ball = free_ball(world, start_x, world.brick_top, vx=1 if brick_x > start_x else -1, vy=1)
        self.assertEqual(ark.brick_hp(world, brick_x, ball.y), 1)
        events: list[str] = []
        ark.move_x(world, ball, events)
        self.assertEqual(ball.vx, 1 if brick_x > start_x else -1, "разбитый кирпич должен пропускать шарик")
        self.assertEqual(ball.x, brick_x)
        self.assertIn("brick_break", events)

    def test_hard_brick_bounces_and_survives(self):
        world = make_world()
        brick_x, start_x = self.brick_neighbourhood(world)
        world.bricks[0][brick_x - world.brick_left] = 3
        direction = 1 if brick_x > start_x else -1
        ball = free_ball(world, start_x, world.brick_top, vx=direction, vy=1)
        events: list[str] = []
        ark.move_x(world, ball, events)
        self.assertEqual(ball.vx, -direction, "крепкий кирпич обязан отбить шарик")
        self.assertEqual(ball.x, start_x)
        self.assertEqual(world.bricks[0][brick_x - world.brick_left], 2)
        self.assertIn("brick", events)

    def test_level_progression(self):
        world = make_world()
        world.bricks = [[0] * len(row) for row in world.bricks]
        events = ark.advance(world, 1 / 60)
        self.assertIn("level", events)
        self.assertEqual(world.level, 2)
        self.assertTrue(world.bricks_left())
        self.assertGreater(world.speed, world.cfg.ball_speed)

    def test_missing_ball_costs_life_then_game_over(self):
        world = make_world()
        ball = free_ball(world, world.left + 5, world.floor_y - 1, vx=1, vy=1)
        world.lives = 1
        for _ in range(200):
            events = ark.advance(world, 1 / 60)
            if world.over:
                break
            ball = world.balls[0]
            ball.x = world.left + 5
            ball.y = world.floor_y - 1
            ball.vx, ball.vy, ball.acc = 1, 1, 0.99
        self.assertTrue(world.over)
        self.assertIn("over", events)

    def test_powerups(self):
        world = make_world(powerups=True)
        base_width = world.paddle_width
        lives = world.lives

        ark.apply_powerup(world, "E", [])
        self.assertEqual(world.paddle_width, base_width + 2)

        ark.apply_powerup(world, "L", [])
        self.assertEqual(world.lives, lives + 1)

        ark.apply_powerup(world, "S", [])
        self.assertLess(world.ball_speed_now, world.speed)

        world.effects.clear()
        ark.apply_powerup(world, "M", [])  # один прилипший шарик — новых не будет
        self.assertEqual(len(world.balls), 1)
        world.launch()
        ark.apply_powerup(world, "M", [])
        self.assertEqual(len(world.balls), 2)

        for _ in range(int(ark.Config().fps * 13)):
            ark.advance(world, 1 / 60)
        self.assertEqual(world.paddle_width, base_width)

    def test_paddle_cannot_leave_arena(self):
        world = make_world()
        world.paddle_dir = -1
        for _ in range(2000):
            ark.advance(world, 1 / 60)
        self.assertEqual(world.paddle_x, world.left)
        world.paddle_dir = 1
        for _ in range(4000):
            ark.advance(world, 1 / 60)
        self.assertLessEqual(world.paddle_x + world.paddle_width - 1, world.field_right)

    def test_resize_rebuilds_arena(self):
        world = make_world(80, 24)
        ark.resize(world, 45, 15)
        self.assertEqual((world.width, world.height), (45, 15))
        self.assertLessEqual(world.arena.right, 44)
        self.assertLess(world.paddle_y, world.floor_y)
        self.assertTrue(world.bricks_left())
        self.assertEqual(len(world.balls), 1)
        self.assertTrue(world.balls[0].stuck)

    def test_record_file_is_optional(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nest" / "score.json"
            self.assertEqual(ark.load_record(path), 0)
            ark.save_record(path, 1234)
            self.assertEqual(ark.load_record(path), 1234)
            path.write_text("не число")
            self.assertEqual(ark.load_record(path), 0)


class PaddleMotionTest(unittest.TestCase):
    """Ракетка должна ехать плавно (с разгоном и торможением) и вставать точно."""

    def setUp(self):
        self.world = make_world(80, 24)
        self.dt = 1 / 60
        self.world.paddle_pos = float(self.world.paddle_x)
        self.world.paddle_cmd = self.world.paddle_pos
        self.world.paddle_vel = 0.0

    def drive(self, frames: int) -> list[float]:
        path = []
        for _ in range(frames):
            ark.follow_paddle_command(self.world, self.dt)
            path.append(self.world.paddle_pos)
        return path

    def test_tap_moves_exactly_one_cell_and_stops(self):
        start = self.world.paddle_pos
        self.world.paddle_cmd = start + ark.PADDLE_KEY_STEP
        self.drive(20)
        self.assertAlmostEqual(self.world.paddle_pos, start + 1, places=9)
        self.assertEqual(self.world.paddle_vel, 0.0)

    def test_ten_taps_land_on_the_tenth_cell(self):
        start = self.world.paddle_pos
        for _ in range(10):
            self.world.paddle_cmd += ark.PADDLE_KEY_STEP
            self.drive(2)                    # два кадра между тапами: автоповтор
        self.assertAlmostEqual(self.world.paddle_pos, start + 10, places=9)

    def test_start_is_not_a_jump(self):
        """Первый кадр медленнее второго: ракета разгоняется, а не телепортируется."""
        self.world.paddle_cmd = self.world.paddle_pos + 30
        path = self.drive(12)
        steps = [path[0] - self.world.paddle_pos] + [b - a for a, b in zip(path, path[1:])]
        self.assertLess(steps[0], steps[1])
        self.assertLess(steps[1], steps[-1])          # разгон до полки
        self.assertLessEqual(max(steps), self.world.paddle_speed * self.dt + 1e-9)

    def test_brakes_exactly_on_target_without_overshoot(self):
        target = self.world.paddle_pos + 25
        self.world.paddle_vel = self.world.paddle_speed    # летим на полном ходу
        self.world.paddle_cmd = target
        overshoot = 0.0
        for _ in range(200):
            ark.follow_paddle_command(self.world, self.dt)
            overshoot = max(overshoot, self.world.paddle_pos - target)
        self.assertLessEqual(overshoot, 1e-9, "ракета проскочила цель")
        self.assertAlmostEqual(self.world.paddle_pos, target, places=9)
        self.assertEqual(self.world.paddle_vel, 0.0)

    def test_no_jitter_around_the_target(self):
        self.world.paddle_cmd = self.world.paddle_pos + 7.5
        self.drive(120)
        settled = self.world.paddle_pos
        self.drive(300)
        self.assertAlmostEqual(self.world.paddle_pos, settled, places=9)

    def start_from_left_wall(self):
        world = self.world
        world.paddle_pos = world.paddle_min
        world.paddle_cmd = world.paddle_min
        world.paddle_vel = 0.0

    def test_holding_key_reaches_full_speed(self):
        self.start_from_left_wall()
        per_frame = []
        previous = self.world.paddle_pos
        for _ in range(20):                                     # 20 кадров удержания
            self.world.paddle_cmd += self.world.paddle_speed * self.dt
            ark.follow_paddle_command(self.world, self.dt)
            per_frame.append(self.world.paddle_pos - previous)
            previous = self.world.paddle_pos
        self.assertLess(per_frame[0], per_frame[-1], "должен быть разгон")
        self.assertAlmostEqual(per_frame[-1], self.world.paddle_speed * self.dt, places=6)

    def test_release_glides_to_a_stop_instead_of_jerking(self):
        """Отпущенная клавиша: ракета дотормаживает и встаёт, без возврата назад."""
        world = self.world
        self.start_from_left_wall()
        world.paddle_dir = 1
        for _ in range(20):                       # держим клавишу — разгон и полка
            ark.move_paddle(world, self.dt)
        self.assertGreater(world.paddle_vel, 0.0, "ракета должна быть в ходу")

        speed_at_release = world.paddle_vel
        release_pos = world.paddle_pos
        world.paddle_dir = 0                      # отпустили
        path = []
        for _ in range(80):
            ark.move_paddle(world, self.dt)
            path.append(world.paddle_pos)

        glide = path[-1] - release_pos
        self.assertGreater(glide, 0.0, "ракета должна проскользить, а не рубить ход")
        self.assertLessEqual(glide, speed_at_release**2 / (2 * world.paddle_accel) + 0.05)
        self.assertEqual(world.paddle_vel, 0.0)
        self.assertTrue(all(b >= a - 1e-9 for a, b in zip(path, path[1:])),
                        "ракета не должна разворачиваться назад после отпускания")

    def test_paddle_stays_inside_arena_while_running(self):
        world = self.world
        for direction in (-1, 1):
            world.paddle_vel = 0.0
            for _ in range(600):
                world.paddle_cmd = float(direction * 1000)
                ark.follow_paddle_command(world, self.dt)
            self.assertGreaterEqual(world.paddle_pos, world.paddle_min)
            self.assertLessEqual(world.paddle_pos, world.paddle_max)
            self.assertEqual(world.paddle_vel, 0.0)


class KeyRepeatTest(unittest.TestCase):
    """Тап и удержание различаются по интервалу автоповтора терминала."""

    def simulate(self, presses, seconds=2.0, world=None):
        """Прогон кадров так же, как main-loop: dir из трекера, физика шаг за шагом."""
        world = world or make_world(80, 24)
        tracker = ark.KeyRepeatTracker()
        dt = 1 / 60
        frames = int(seconds * 60)
        sent = list(presses)
        for frame in range(frames):
            now = frame * dt
            while sent and sent[0][0] <= now:
                moment, direction = sent.pop(0)             # (момент, направление)
                if not tracker.press(direction, now):        # тап: ровно клетка
                    world.paddle_cmd = float(ark.clamp(
                        world.paddle_cmd + direction * ark.PADDLE_KEY_STEP,
                        world.paddle_min, world.paddle_max))
            world.paddle_dir = tracker.active_direction(now)
            ark.move_paddle(world, dt)
        return world, tracker

    def repeat_stream(self, direction, hz, seconds, start=0.0):
        step = 1 / hz
        moments, moment = [], start
        while moment <= seconds:
            moments.append((moment, direction))
            moment += step
        return moments

    def test_single_tap_moves_exactly_one_cell(self):
        world = make_world(80, 24)
        world.paddle_pos = world.paddle_min
        world.paddle_cmd = world.paddle_min
        start = world.paddle_pos
        # одно нажатие и тишина 1 с — регрессия на «уехала на 20 клеток от тапа»
        world, _ = self.simulate([(0.0, 1)], seconds=1.0, world=world)
        self.assertAlmostEqual(world.paddle_pos, start + ark.PADDLE_KEY_STEP, places=6)
        self.assertEqual(world.paddle_vel, 0.0)

    def test_ten_single_taps_land_on_tenth_cell(self):
        world = make_world(80, 24)
        world.paddle_pos = world.paddle_min
        world.paddle_cmd = world.paddle_min
        start = world.paddle_pos
        presses = [(i * 0.5, 1) for i in range(10)]           # редкие тапы, не повтор
        world, _ = self.simulate(presses, seconds=5.5, world=world)
        self.assertAlmostEqual(world.paddle_pos, start + 10, places=6)

    def test_hold_at_30hz_gives_continuous_motion(self):
        world = make_world(80, 24)
        world.paddle_pos = world.paddle_min
        world.paddle_cmd = world.paddle_min
        world, tracker = self.simulate(self.repeat_stream(1, 30, 1.0), seconds=1.0, world=world)
        self.assertAlmostEqual(tracker.gap, 1 / 30, places=4)
        # за секунду удержания ракета должна проехать почти всё поле
        self.assertGreater(world.paddle_pos, world.paddle_max - world.paddle_width,
                           "удержание клавиши должно давать сплошной ход")

    def test_hold_on_slow_terminal_does_not_stutter(self):
        """Автоповтор 6 Гц (SSH): окно удержания подстраивается, провалов нет."""
        world = make_world(80, 24)
        world.paddle_pos = world.paddle_min
        world.paddle_cmd = world.paddle_min
        dt = 1 / 60
        tracker = ark.KeyRepeatTracker()
        world.paddle_dir = 0
        steps = []
        previous = world.paddle_pos
        for frame in range(40):                              # 0.66 с удержания
            now = frame * dt
            if frame % 10 == 0:                              # событие каждые 10 кадров
                tracker.press(1, now)
            world.paddle_dir = tracker.active_direction(now)
            ark.move_paddle(world, dt)
            steps.append(world.paddle_pos - previous)
            previous = world.paddle_pos
        self.assertGreater(tracker.gap, 0.12, "должен выучить медленный автоповтор")
        stopped = sum(1 for s in steps[12:] if s <= 1e-9)
        self.assertEqual(stopped, 0, f"ракета встала {stopped} кадров при удержании (дёргается)")

    def test_release_is_detected_and_paddle_brakes(self):
        tracker = ark.KeyRepeatTracker(initial_gap=0.05)
        tracker.press(1, 0.0)
        tracker.press(1, 0.05)
        self.assertTrue(tracker.holding, "второе событие в ритме — это удержание")
        self.assertEqual(tracker.active_direction(0.06), 1)
        self.assertEqual(tracker.active_direction(0.05 + 0.05 * ark.HOLD_TOLERANCE + 0.01), 0)

    def test_change_of_direction_is_a_new_tap(self):
        tracker = ark.KeyRepeatTracker(initial_gap=0.03)
        tracker.press(1, 0.0)
        self.assertTrue(tracker.press(1, 0.03))
        self.assertFalse(tracker.press(-1, 0.06), "смена направления — не повтор")
        self.assertEqual(tracker.direction, -1)


class KeyDecoderTest(unittest.TestCase):
    """Стрелки должны работать и на терминалах без application cursor mode."""

    def decode(self, sequence: bytes) -> list[int]:
        decoder = ark.KeyDecoder()
        return [key for key in (decoder.feed(byte) for byte in sequence) if key is not None]

    def test_both_cursor_forms_decode(self):
        for sequence in (b"\x1b[C", b"\x1bOC"):
            self.assertEqual(self.decode(sequence), [curses.KEY_RIGHT], sequence)
        for sequence in (b"\x1b[D", b"\x1bOD"):
            self.assertEqual(self.decode(sequence), [curses.KEY_LEFT], sequence)

    def test_modified_and_home_end(self):
        self.assertEqual(self.decode(b"\x1b[1;5C"), [curses.KEY_RIGHT])     # Ctrl+Right
        self.assertEqual(self.decode(b"\x1b[H"), [ark.KEY_HOME])
        self.assertEqual(self.decode(b"\x1bOF"), [ark.KEY_END])

    def test_plain_keys_pass_through_and_stray_bytes_are_swallowed(self):
        self.assertEqual(self.decode(b"q"), [ord("q")])
        self.assertEqual(self.decode(b" "), [ord(" ")])
        self.assertEqual(self.decode(b"\x1b"), [], "одинокий ESC не должен никуда вести")
        self.assertEqual(self.decode(b"\x1b[<0;42;12M"), [], "мышиный мусор не должен становиться буквой M")

    def test_two_sequences_back_to_back(self):
        self.assertEqual(self.decode(b"\x1b[C\x1b[D"), [curses.KEY_RIGHT, curses.KEY_LEFT])
        self.assertEqual(self.decode(b"\x1b[Cq"), [curses.KEY_RIGHT, ord("q")])

    def test_reset_drops_partial_sequence(self):
        decoder = ark.KeyDecoder()
        decoder.feed(27)
        decoder.feed(ord("["))
        decoder.reset()
        self.assertEqual(decoder.feed(ord("C")), ord("C"), "после reset буфер чист")


class CursesCompatTest(unittest.TestCase):
    """Сборки curses бывают без мыши и без цвета — падать посреди игры нельзя."""

    def test_missing_functions_resolve_to_none(self):
        self.assertIsNone(ark._curses_func("такой_функции_в_curses_нет"))
        self.assertIsNone(ark._curses_func("error"))          # класс исключения — не функция
        self.assertTrue(callable(ark._curses_func("initscr")))

    def test_mouse_capability_flags_are_consistent(self):
        self.assertEqual(ark.HAS_MOUSE, bool(ark.MOUSE_MASK and ark.GET_MOUSE and ark.MOUSE_EVENTS))
        self.assertIsInstance(ark.KEY_MOUSE, int)

    def test_colors_available_never_raises(self):
        self.assertIn(ark.colors_available(), (True, False))

    def test_curses_failure_covers_attribute_error(self):
        # именно AttributeError ронял игру на сборках без curses.getmouse
        self.assertIn(AttributeError, ark.CURSES_FAILURE)
        self.assertIn(ValueError, ark.CURSES_FAILURE)


class ScorePathTest(unittest.TestCase):
    def test_score_file_is_expanded(self):
        """Регрессия: «~» без expanduser создавал папку с тильдой в cwd."""
        with tempfile.TemporaryDirectory() as home:
            with mock.patch.dict(os.environ, {"HOME": home, "ARKANOID_SCORE": "~/scores/arkanoid.json"}):
                path = ark.score_file_from_env()
                self.assertNotIn("~", str(path))
                self.assertTrue(path.is_absolute())
                ark.save_record(path, 7)
                self.assertEqual(ark.load_record(path), 7)
                self.assertTrue(ark.Path(home, "scores/arkanoid.json").exists())

        with mock.patch.dict(os.environ, {"ARKANOID_SCORE": ""}):
            self.assertTrue(str(ark.score_file_from_env()).endswith("arkanoid/score.json"))

        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                ark.save_record(ark.Path("~/x.json"), 1)
                self.assertFalse(ark.Path(tmp, "~").exists(), "тильда не должна становиться папкой")
            finally:
                os.chdir(cwd)


class SmokeTest(unittest.TestCase):
    def test_smoke_report_is_clean(self):
        self.assertEqual(ark.run_smoke(60, ark.Config(seed=5)), 0)


if __name__ == "__main__":
    unittest.main()
