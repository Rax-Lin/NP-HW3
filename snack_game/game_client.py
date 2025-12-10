import socket
import argparse
import threading
import sys
import tkinter as tk

CELL_SIZE = 20
BG_COLOR = "#000000"
P1_COLOR = "#00ff00"
P2_COLOR = "#0000ff"
APPLE_COLOR = "#ff0000"

state_lock = threading.Lock()
board_width = 30
board_height = 20
apple = None
snake1 = []
snake2 = []
p1_alive = True
p2_alive = True
p1_score = 0
p2_score = 0
player_id = None
game_over = False
winner = 0

running = True
game_started = False


def parse_state(line: str):
    global apple, snake1, snake2, p1_alive, p2_alive, p1_score, p2_score

    try:
        head_part, body1_part, body2_part = line.split("|")
        head_tokens = head_part.strip().split()

        ax = int(head_tokens[1])
        ay = int(head_tokens[2])
        p1a = int(head_tokens[3])
        p2a = int(head_tokens[4])
        s1 = int(head_tokens[5])
        s2 = int(head_tokens[6])

        apple = (ax, ay)
        p1_alive = (p1a == 1)
        p2_alive = (p2a == 1)
        p1_score = s1
        p2_score = s2

        def parse_body(part):
            part = part.strip()
            if part == "":
                return []
            segments = part.split(";")
            body = []
            for seg in segments:
                seg = seg.strip()
                if seg == "":
                    continue
                x_str, y_str = seg.split(",")
                body.append((int(x_str), int(y_str)))
            return body

        snake1 = parse_body(body1_part)
        snake2 = parse_body(body2_part)

    except Exception:
        pass


def network_thread(sock):
    global board_width, board_height, player_id, game_over, winner, running, game_started

    buffer = ""
    try:
        while running:
            data = sock.recv(1024)
            if not data:
                break
            buffer += data.decode()

            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                parts = line.split()
                cmd = parts[0]

                with state_lock:
                    if cmd == "START" and len(parts) >= 3:
                        board_width = int(parts[1])
                        board_height = int(parts[2])
                        game_started = True

                    elif cmd == "PLAYER_ID":
                        player_id = int(parts[1])

                    elif cmd == "STATE":
                        parse_state(line)

                    elif cmd == "GAME_OVER":
                        winner = int(parts[1])
                        game_over = True

                    elif cmd == "MSG":
                        print("[Server MSG]", " ".join(parts[1:]))

    except Exception:
        pass
    finally:
        running = False
        try:
            sock.close()
        except:
            pass


def draw_game(canvas, score_label, status_label):
    with state_lock:
        w = board_width
        h = board_height
        a = apple
        s1 = list(snake1)
        s2 = list(snake2)
        alive1 = p1_alive
        alive2 = p2_alive
        sc1 = p1_score
        sc2 = p2_score
        over = game_over
        win = winner
        pid = player_id
        started = game_started

    canvas.delete("all")
    canvas.config(width=w * CELL_SIZE, height=h * CELL_SIZE)

    canvas.create_rectangle(0, 0, w * CELL_SIZE, h * CELL_SIZE,
                            fill=BG_COLOR, outline=BG_COLOR)

    if not started:
        status_label.config(text="Waiting to start...")
        canvas.after(100, draw_game, canvas, score_label, status_label)
        return

    # 畫蘋果
    if a is not None:
        ax, ay = a
        x0 = ax * CELL_SIZE
        y0 = ay * CELL_SIZE
        canvas.create_oval(
            x0 + 3, y0 + 3,
            x0 + CELL_SIZE - 3, y0 + CELL_SIZE - 3,
            fill=APPLE_COLOR, outline=""
        )

    # 畫玩家蛇
    for idx, body in enumerate([s1, s2]):
        color = P1_COLOR if idx == 0 else P2_COLOR
        for i, (x, y) in enumerate(body):
            x0 = x * CELL_SIZE
            y0 = y * CELL_SIZE
            if i == 0:
                canvas.create_rectangle(x0, y0, x0 + CELL_SIZE, y0 + CELL_SIZE,
                                        fill=color)
            else:
                canvas.create_rectangle(
                    x0 + 2, y0 + 2,
                    x0 + CELL_SIZE - 2, y0 + CELL_SIZE - 2,
                    fill=color)

    score_label.config(text=f"P1 Score: {sc1}   P2 Score: {sc2}")

    status = ""
    if pid:
        status += f"You are Player {pid}.  "

    if over:
        if win == 0:
            status += "Draw"
        elif win == pid:
            status += "You Win!"
        else:
            status += "You Lose."
    else:
        status += "Game Running..."

    status_label.config(text=status)

    canvas.after(100, draw_game, canvas, score_label, status_label)


def key_handler(event, sock):
    if not game_started:
        return

    key = event.keysym
    dir_map = {
        "Up": "UP",
        "Down": "DOWN",
        "Left": "LEFT",
        "Right": "RIGHT",
    }
    if key in dir_map:
        try:
            sock.sendall(f"DIR {dir_map[key]}\n".encode())
        except:
            pass


def start_game(sock, btn):
    btn.config(state="disabled")
    try:
        sock.sendall(b"READY\n")
    except:
        pass


def on_close(root, sock):
    global running
    running = False
    try:
        sock.sendall(b"QUIT\n")
    except:
        pass
    try:
        sock.close()
    except:
        pass
    root.destroy()
    sys.exit(0)


def start_game_client(ip, port, room_id):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((ip, port))

    t = threading.Thread(target=network_thread, args=(sock,), daemon=True)
    t.start()

    root = tk.Tk()
    root.title("Two Player Snake")

    score_label = tk.Label(root, text="Scores", font=("Arial", 14))
    score_label.pack()

    status_label = tk.Label(root, text="Waiting...", font=("Arial", 12))
    status_label.pack()

    start_btn = tk.Button(root, text="Start Game",
                          font=("Arial", 14),
                          command=lambda: start_game(sock, start_btn))
    start_btn.pack(pady=5)

    canvas = tk.Canvas(root, width=board_width * CELL_SIZE,
                       height=board_height * CELL_SIZE)
    canvas.pack()

    root.bind("<KeyPress>", lambda e: key_handler(e, sock))

    root.protocol("WM_DELETE_WINDOW", lambda: on_close(root, sock))

    draw_game(canvas, score_label, status_label)

    root.mainloop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server_ip", required=True)
    parser.add_argument("--server_port", required=True)
    parser.add_argument("--room_id", required=True)
    args = parser.parse_args()

    start_game_client(args.server_ip, int(args.server_port), args.room_id)
