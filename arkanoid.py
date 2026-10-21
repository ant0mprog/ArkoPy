"""
Простая текстовая игра в стиле Arkanoid.

Запуск:
    python arkanoid.py

Управление:
    ← → — движение ракетки
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


def new_ball(width):
    """
    Создаёт новый шарик в случайной позиции сверху.
    Возвращает: x, y, vx
    """
    x = random.randint(1, max(1, width - 2))
    vx = random.choice([-1, 0, 1])

    # Если шарик появился у стены, не даём ему сразу "уйти" за стену
    if x <= 1 and vx < 0:
        vx = 1
    if x >= width - 2 and vx > 0:
        vx = -1

    return x, 1, vx


def main(stdscr):
    # Скрываем курсор
    curses.curs_set(0)

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

    # Позиция ракетки
    paddle_x = (width - PADDLE_WIDTH) // 2
    paddle_y = height - 2

    # Позиция шарика
    ball_x, ball_y, ball_vx = new_ball(width)

    # Скорость шарика: чем меньше move_interval, тем быстрее шарик
    move_interval = INITIAL_MOVE_INTERVAL
    frame = 0

    game_over = False

    while True:
        # --- Обработка ввода ---
        while True:
            key = stdscr.getch()

            if key == -1:
                break

            if key in (ord("q"), ord("Q")):
                return

            if key == curses.KEY_LEFT:
                paddle_x = max(0, paddle_x - PADDLE_STEP)

            elif key == curses.KEY_RIGHT:
                paddle_x = min(width - PADDLE_WIDTH, paddle_x + PADDLE_STEP)

        # --- Обновление шарика ---
        frame += 1

        if frame >= move_interval:
            frame = 0

            ball_x += ball_vx
            ball_y += 1

            # Отскок от боковых стен
            if ball_x <= 1:
                ball_x = 1
                ball_vx = 1
            elif ball_x >= width - 2:
                ball_x = width - 2
                ball_vx = -1

            # Проверка: шарик пойман ракеткой
            if ball_y == paddle_y and paddle_x <= ball_x <= paddle_x + PADDLE_WIDTH - 1:
                score += 1

                # Постепенное ускорение шарика
                move_interval = max(MIN_MOVE_INTERVAL, move_interval - 1)

                # Новый шарик
                ball_x, ball_y, ball_vx = new_ball(width)

            # Проверка: шарик пропущен
            elif ball_y >= height - 1:
                lives -= 1

                if lives <= 0:
                    game_over = True
                    break

                # Новый шарик после потери жизни
                ball_x, ball_y, ball_vx = new_ball(width)

        # --- Отрисовка кадра ---
        stdscr.erase()

        # Счёт и жизни
        safe_addstr(stdscr, 0, 0, f"Счёт: {score}  Жизни: {lives}")

        # Подсказка по управлению
        safe_addstr(stdscr, height - 1, 0, "← → — движение, q — выход")

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
    curses.wrapper(main)
