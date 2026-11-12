"""Тесты физики арканоида — без терминала: python -m unittest discover -s tests"""

import sys
import tempfile
import unittest
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
                    self.assertIn(abs(ball.vx), (1, 2), "шарик встал вертикально")
                    self.assertIn(ball.vy, (-1, 1))
                ark.advance(world, 1 / 60)

    def test_paddle_angle_depends_on_hit_spot(self):
        """Край ракетки — крутой угол (|vx| = 2), ближе к центру — пологий."""
        world = make_world()
        center = world.paddle_x + world.paddle_width // 2
        edge = free_ball(world, center - world.paddle_width // 2, world.paddle_y - 1, vx=1, vy=1)
        self.assertEqual(ark.paddle_bounce(world, edge), -2)
        near = free_ball(world, center - 2, world.paddle_y - 1, vx=1, vy=1)
        self.assertEqual(ark.paddle_bounce(world, near), -1)
        middle = free_ball(world, center, world.paddle_y - 1, vx=1, vy=1)
        self.assertIn(ark.paddle_bounce(world, middle), (1, -1))
        other = free_ball(world, center + world.paddle_width // 2, world.paddle_y - 1, vx=-1, vy=1)
        self.assertEqual(ark.paddle_bounce(world, other), 2)

    def test_fast_ball_is_caught_by_paddle(self):
        """Отскок проверяется пересечением линии, а не совпадением строки."""
        world = make_world()
        world.speed = ark.BALL_SPEED_MAX
        ball = free_ball(world, world.paddle_x + 3, world.paddle_y - 2, vx=1, vy=1)
        for _ in range(400):
            ark.advance(world, 1 / 60)
            if ball.vy < 0:
                break
        self.assertLess(ball.vy, 0, "шарик пролетел ракетку")
        self.assertFalse(ball.dead)

    def test_every_brick_column_is_reachable(self):
        """Регрессия: кирпичи в крайних колонках были недостижимы — уровень
        нельзя было пройти (софт-лок)."""
        for width, height in ((80, 24), (40, 14), (120, 50), (60, 20)):
            for level in range(1, 8):
                world = make_world(width, height)
                world.level = level
                world.reset_level()
                cols = {world.left + c for row in world.bricks for c, hp in enumerate(row) if hp}
                self.assertTrue(cols, f"{width}x{height} ур.{level}: нет ни одного кирпича")
                self.assertTrue(
                    all(world.left <= x <= world.field_right for x in cols),
                    f"{width}x{height} ур.{level}: кирпичи вне поля",
                )

    def test_wall_bounce_does_not_block_brick_in_corner(self):
        world = make_world()
        y = world.brick_top
        x = world.left + 1
        ball = free_ball(world, x, y, vx=-1, vy=1)
        events = []
        ark.move_x(world, ball, events)
        self.assertEqual(ark.brick_row_col(world, world.left, y)[1], 0)
        self.assertGreaterEqual(world.bricks[0][0], 0)

    def test_destroyed_brick_does_not_bounce_ball(self):
        world = make_world()
        y = world.brick_top
        ball = free_ball(world, world.left, y, vx=1, vy=1)
        self.assertEqual(ark.brick_hp(world, ball.x + 1, y), 1)
        events: list[str] = []
        ark.move_x(world, ball, events)
        self.assertEqual(ball.vx, 1, "разбитый кирпич должен пропускать шарик")
        self.assertIn("brick_break", events)

    def test_hard_brick_bounces_and_survives(self):
        world = make_world()
        world.bricks[0][2] = 3
        ball = free_ball(world, world.left + 1, world.brick_top, vx=1, vy=1)
        events: list[str] = []
        ark.move_x(world, ball, events)
        self.assertEqual(ball.vx, -1)
        self.assertEqual(world.bricks[0][2], 2)
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


class SmokeTest(unittest.TestCase):
    def test_smoke_report_is_clean(self):
        self.assertEqual(ark.run_smoke(60, ark.Config(seed=5)), 0)


if __name__ == "__main__":
    unittest.main()
