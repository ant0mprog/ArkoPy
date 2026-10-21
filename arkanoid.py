"""
Вторая версия простой текстовой игры в стиле Arkanoid.

Запуск:
    python arkanoid.py

Управление:
    ← → — движение ракетки
    s   — включить/выключить звук
    q   — выход
"""

import curses
import random

# Настройки игры
INITIAL_MOVE_INTERVAL = 5   # сколько кадров ждать перед шагом шарика
MIN_MOVE_INTERVAL = 3       # максимальная скорость шарика
FRAME_DELAY_MS = 35         # задержка между кадрами, мс
PADDLE_WIDTH = 5            # ширина ракетки
PADDLE_STEP = 2             # насколько клеток двигать ракетку за нажатие
START_LIVES = 3             # количество жизней
BRICK_ROWS = 3              # количество рядов кирпичей
BRICK_Y_OFFSET = 2          # первый ряд кирпичей по вертикали
BRICK_X_OFFSET = 1          # первый ряд кирпичей по горизонтали


def safe_addstr(win, y, x, text):
    """
    Безопасно выводит строку в окно curses.
    Если строка выходит за границы экрана, она обрезается.
    """
    if not text:
        return

    max_y, max_x = win.getmaxyx()

    if y < 0 or y >= max_y or x < 0 or x >= max_x:
        return

    text = text[:max_x - x]

    try:
        win.addstr(y, x, text)
    except curses.error:
        pass


def play_sound(stdscr, kind, enabled):
    """
    Простые звуковые эффекты через curses.beep().
    kind:
        paddle — отскок от ракетки
        brick  — попадание по кирпичу
        wall   — отскок от стены
        life   — потеря жизни
        level  — переход на новый уровень
    """
    if not enabled:
        return

    try:
        if kind == "life":
            curses.beep()
            curses.flash()
        elif kind == "level":
            curses.beep()
            curses.flash()
        else:
            curses.beep()
    except curses.error:
        pass


def create_bricks(height, width):
    """
    Создаёт кирпичи сверху экрана.
    Каждый кирпич — одна клетка.
    """
    max_rows = max(1, (height - 4) // 2)
    rows = min(BRICK_ROWS, max_rows)
    cols = max(1, width - 2)

    return [[True for _ in range(cols)] for _ in range(rows)]


def new_ball(width):
    """
    Создаёт новый шарик в случайной позиции сверху.
    Возвращает: x, y, vx, vy
    """
    x = random.randint(1, max(1, width - 2))
    vx = random.choice([-1, 0, 1])

    # Если шарик появился у стены, не даём ему сразу "уйти" за стену
    if x <= 1 and vx < 0:
        vx = 1
    if x >= width - 2 and vx > 0:
        vx = -1

    return x, 1, vx, 1


def bricks_left(bricks):
    """
    Проверяет, остались ли ещё целые кирпичи.
    """
    return any(any(row) for row in bricks)


def hit_brick(ball_x, ball_y, bricks, old_y):
    """
    Проверяет, попал ли шарик в кирпич.
    Если попал — разрушает кирпич и возвращает тип столкновения:
        "down" — шарик летел вниз
        "up"   — шарик летел вверх
        "side" — шарик летел горизонтально
    """
    row = ball_y - BRICK_Y_OFFSET
    col = ball_x - BRICK_X_OFFSET

    if 0 <= row < len(bricks) and 0 <= col < len(bricks[row]) and bricks[row][col]:
        bricks[row][col] = False

        if old_y < ball_y:
            return "down"
        elif old_y > ball_y:
            return "up"
        else:
            return "side"

    return None


def main(stdscr):
    # Скрываем курсор
    try:
        curses.curs_set(0)
    except curses.error:
        pass

    # Включаем обработку специальных клавиш, например стрелок
    stdscr.keypad(True)

    # Не блокируем ввод: getch() вернёт -1, если клавиша не нажата
    stdscr.nodelay(True)

    height, width = stdscr.getmaxyx()

    # Проверка минимального размера терминала
    if height < 10 or width < 20:
        stdscr.nodelay(False)
        safe_addstr(stdscr, 0, 0, "Терминал слишком мал. Минимум 20x10.")
        stdscr.getch()
        return

    score = 0
    lives = START_LIVES
    level = 1
    sound_enabled = True

    # Позиция ракетки
    paddle_x = (width - PADDLE_WIDTH) // 2
    paddle_y = height - 2

    # Кирпичи
    bricks = create_bricks(height, width)

    # Позиция шарика
    ball_x, ball_y, ball_vx, ball_vy = new_ball(width)

    # Скорость шарика: чем меньше move_interval, тем быстрее шарик
    move_interval = INITIAL_MOVE_INTERVAL
    frame = 0

    while True:
        # --- Обработка ввода ---
        while True:
            key = stdscr.getch()

            if key == -1:
                break

            if key in (ord("q"), ord("Q")):
                return

            if key in (ord("s"), ord("S")):
                sound_enabled = not sound_enabled

            if key == curses.KEY_LEFT:
                paddle_x = max(0, paddle_x - PADDLE_STEP)

            elif key == curses.KEY_RIGHT:
                paddle_x = min(width - PADDLE_WIDTH, paddle_x + PADDLE_STEP)

        # --- Обновление шарика ---
        frame += 1

        if frame >= move_interval:
            frame = 0

            old_y = ball_y

            ball_x += ball_vx
            ball_y += ball_vy

            # Отскок от верхней стены
            if ball_y <= 1:
                ball_y = 1
                ball_vy = 1
                play_sound(stdscr, "wall", sound_enabled)

            # Отскок от боковых стен
            if ball_x <= 1:
                ball_x = 1
                ball_vx = 1
                play_sound(stdscr, "wall", sound_enabled)
            elif ball_x >= width - 2:
                ball_x = width - 2
                ball_vx = -1
                play_sound(stdscr, "wall", sound_enabled)

            # Проверка попадания по кирпичу
            brick_hit = hit_brick(ball_x, ball_y, bricks, old_y)

            if brick_hit:
                score += 10

                # Отскок от кирпича
                if brick_hit == "side":
                    ball_vx = -ball_vx
                else:
                    ball_vy = -ball_vy

                play_sound(stdscr, "brick", sound_enabled)

                # Если все кирпичи разрушены — новый уровень
                if not bricks_left(bricks):
                    level += 1
                    move_interval = max(MIN_MOVE_INTERVAL, move_interval - 1)
                    bricks = create_bricks(height, width)
                    ball_x, ball_y, ball_vx, ball_vy = new_ball(width)
                    play_sound(stdscr, "level", sound_enabled)

            # Проверка отскока от ракетки
            if (
                ball_vy > 0
                and ball_y == paddle_y
                and paddle_x <= ball_x <= paddle_x + PADDLE_WIDTH - 1
            ):
                score += 1

                # Направление отскока зависит от точки попадания по ракетке
                center = paddle_x + PADDLE_WIDTH // 2
                offset = ball_x - center

                if offset < -1:
                    ball_vx = -1
                elif offset > 1:
                    ball_vx = 1
                else:
                    ball_vx = 0

                ball_vy = -1
                play_sound(stdscr, "paddle", sound_enabled)

            # Проверка: шарик пропущен
            elif ball_y >= height - 1:
                lives -= 1
                play_sound(stdscr, "life", sound_enabled)

                if lives <= 0:
                    break

                # Новый шарик после потери жизни
                ball_x, ball_y, ball_vx, ball_vy = new_ball(width)

        # --- Отрисовка кадра ---
        stdscr.erase()

        # Счёт, жизни и уровень
        safe_addstr(stdscr, 0, 0, f"Счёт: {score}  Жизни: {lives}  Уровень: {level}")

        # Подсказка по управлению
        safe_addstr(stdscr, height - 1, 0, "← → — движение, s — звук, q — выход")

        # Кирпичи
        for row, brick_row in enumerate(bricks):
            y = BRICK_Y_OFFSET + row
            for col, alive in enumerate(brick_row):
                if alive:
                    safe_addstr(stdscr, y, BRICK_X_OFFSET + col, "#")

        # Ракетка
        safe_addstr(stdscr, paddle_y, paddle_x, "=" * PADDLE_WIDTH)

        # Шарик
        safe_addstr(stdscr, ball_y, ball_x, "O")

        stdscr.refresh()

        # Задержка между кадрами
        curses.napms(FRAME_DELAY_MS)

    # --- Экран окончания игры ---
    stdscr.erase()

    msg = f"Игра окончена! Счёт: {score}"
    msg_x = max(0, (width - len(msg)) // 2)
    safe_addstr(stdscr, height // 2, msg_x, msg)

    hint = "Нажмите любую клавишу"
    hint_x = max(0, (width - len(hint)) // 2)
    safe_addstr(stdscr, height // 2 + 1, hint_x, hint)

    stdscr.refresh()

    # Ждём нажатия любой клавиши
    stdscr.nodelay(False)
    stdscr.getch()


if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
