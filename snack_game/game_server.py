import socket
import threading
import argparse
import random
import time

# 遊戲設定
BOARD_WIDTH = 30
BOARD_HEIGHT = 20
TICK_INTERVAL = 0.12  # 每一格移動時間（秒）

# 全域狀態
players = []          # [conn0, conn1]
player_dirs = ["LEFT", "RIGHT"]  # 玩家當前方向
player_next_dirs = ["LEFT", "RIGHT"]  # 玩家要求的下一步方向
player_alive = [True, True]
player_scores = [0, 0]

snakes = [[], []]     # 每條蛇是一個 [(x, y), ...]
apple = (0, 0)

lock = threading.Lock()
game_over = threading.Event()


def broadcast(msg: str):
    """把訊息送給所有玩家（加上換行）"""
    with lock:
        for conn in players:
            try:
                conn.sendall((msg + "\n").encode())
            except Exception:
                pass


def send_to_player(idx: int, msg: str):
    with lock:
        if 0 <= idx < len(players):
            try:
                players[idx].sendall((msg + "\n").encode())
            except Exception:
                pass


def place_new_apple():
    global apple
    occupied = set()
    for body in snakes:
        for x, y in body:
            occupied.add((x, y))
    while True:
        x = random.randint(0, BOARD_WIDTH - 1)
        y = random.randint(0, BOARD_HEIGHT - 1)
        if (x, y) not in occupied:
            apple = (x, y)
            break


def init_game():
    """初始化兩條蛇與蘋果"""
    global snakes, player_dirs, player_next_dirs, player_alive, player_scores

    mid_y = BOARD_HEIGHT // 2

    # Player 1 從左邊往右
    snakes[0] = [(5, mid_y), (4, mid_y), (3, mid_y)]
    # Player 2 從右邊往左
    snakes[1] = [(BOARD_WIDTH - 6, mid_y),
                 (BOARD_WIDTH - 5, mid_y),
                 (BOARD_WIDTH - 4, mid_y)]

    player_dirs = ["RIGHT", "LEFT"]
    player_next_dirs = ["RIGHT", "LEFT"]
    player_alive = [True, True]
    player_scores = [0, 0]

    place_new_apple()


def opposite_dir(d1, d2):
    return (d1 == "UP" and d2 == "DOWN") or \
           (d1 == "DOWN" and d2 == "UP") or \
           (d1 == "LEFT" and d2 == "RIGHT") or \
           (d1 == "RIGHT" and d2 == "LEFT")


def dir_to_delta(d):
    if d == "UP":
        return (0, -1)
    if d == "DOWN":
        return (0, 1)
    if d == "LEFT":
        return (-1, 0)
    if d == "RIGHT":
        return (1, 0)
    return (0, 0)


def handle_player(conn, idx):
    """
    負責接收某位玩家送來的控制訊息，如：
    DIR UP / DIR DOWN / DIR LEFT / DIR RIGHT / QUIT
    """
    buffer = ""
    try:
        conn.sendall(f"MSG You are Player {idx+1}\n".encode())
        conn.sendall("MSG Waiting for another player...\n".encode())
    except Exception:
        return

    while not game_over.is_set():
        try:
            data = conn.recv(1024)
        except Exception:
            break

        if not data:
            break

        buffer += data.decode()
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue

            parts = line.split()
            if parts[0] == "DIR" and len(parts) == 2:
                new_dir = parts[1].upper()
                if new_dir in ("UP", "DOWN", "LEFT", "RIGHT"):
                    with lock:
                        # 暫存玩家要求的方向，真正套用在 game_loop 裡
                        player_next_dirs[idx] = new_dir
            elif parts[0] == "QUIT":
                game_over.set()
                return
            # 其他訊息就忽略
    # 斷線或結束
    game_over.set()


def encode_state():
    """
    狀態格式：
    STATE apple_x apple_y p1_alive p2_alive p1_score p2_score | x1,y1;x2,y2;... | x1,y1;...
    """
    ax, ay = apple
    p1_alive = 1 if player_alive[0] else 0
    p2_alive = 1 if player_alive[1] else 0
    p1_score = player_scores[0]
    p2_score = player_scores[1]

    def body_to_str(body):
        return ";".join(f"{x},{y}" for x, y in body)

    p1_body = body_to_str(snakes[0])
    p2_body = body_to_str(snakes[1])

    return f"STATE {ax} {ay} {p1_alive} {p2_alive} {p1_score} {p2_score} | {p1_body} | {p2_body}"


def game_loop():
    """主遊戲迴圈：按照 TICK_INTERVAL 更新狀態並廣播給兩個 client"""
    broadcast(f"START {BOARD_WIDTH} {BOARD_HEIGHT}")
    init_game()

    # 告訴每個玩家自己的 ID（1 or 2）
    send_to_player(0, "PLAYER_ID 1")
    send_to_player(1, "PLAYER_ID 2")

    broadcast("MSG Game Start! Use arrow keys to control your snake.")

    while not game_over.is_set():
        time.sleep(TICK_INTERVAL)

        with lock:
            # 套用玩家要求的新方向（不能直接反向）
            for i in range(2):
                if player_alive[i]:
                    nd = player_next_dirs[i]
                    if not opposite_dir(player_dirs[i], nd):
                        player_dirs[i] = nd

            # 計算新頭位置
            new_heads = [None, None]
            for i in range(2):
                if not player_alive[i]:
                    continue
                dx, dy = dir_to_delta(player_dirs[i])
                hx, hy = snakes[i][0]
                nx, ny = hx + dx, hy + dy
                new_heads[i] = (nx, ny)

            # 檢查碰牆 / 自己 / 對手
            all_positions = set()
            for body in snakes:
                for pos in body:
                    all_positions.add(pos)

            for i in range(2):
                if not player_alive[i]:
                    continue
                nx, ny = new_heads[i]
                # 撞牆
                if nx < 0 or nx >= BOARD_WIDTH or ny < 0 or ny >= BOARD_HEIGHT:
                    player_alive[i] = False
                    continue
                # 撞自己或對手：看目前所有身體
                if (nx, ny) in all_positions:
                    player_alive[i] = False
                    continue

            # 更新蛇身與吃蘋果
            for i in range(2):
                if not player_alive[i]:
                    continue
                nx, ny = new_heads[i]
                snakes[i].insert(0, (nx, ny))  # 新頭塞前面
                if (nx, ny) == apple:
                    player_scores[i] += 1
                    place_new_apple()  # 吃到就長一格，不刪尾
                else:
                    snakes[i].pop()  # 沒吃到就維持長度

            # 檢查遊戲結束條件
            if not player_alive[0] and not player_alive[1]:
                winner = 0
                if player_scores[0] > player_scores[1]:
                    winner = 1
                elif player_scores[1] > player_scores[0]:
                    winner = 2
                broadcast(f"GAME_OVER {winner}")
                game_over.set()
                break
            elif not player_alive[0]:
                broadcast("GAME_OVER 2")
                game_over.set()
                break
            elif not player_alive[1]:
                broadcast("GAME_OVER 1")
                game_over.set()
                break

            # 廣播狀態
            state_line = encode_state()
            broadcast(state_line)

    broadcast("MSG Game finished.")
    time.sleep(0.5)


def start_game_server(port, room_id):
    print(f"[GameServer] Starting on port {port} (Room {room_id})")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", port))
    server.listen(2)

    print("[GameServer] Waiting for 2 players...")

    threads = []
    for i in range(2):
        conn, addr = server.accept()
        print(f"[GameServer] Player {i+1} connected from {addr}")
        players.append(conn)
        t = threading.Thread(target=handle_player, args=(conn, i), daemon=True)
        t.start()
        threads.append(t)

    print("[GameServer] Both players connected, starting game loop.")
    game_loop()

    # 收尾
    for conn in players:
        try:
            conn.close()
        except Exception:
            pass

    print("[GameServer] Game Finished")
    server.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--room_id", type=int, required=True)
    args = parser.parse_args()

    start_game_server(args.port, args.room_id)
