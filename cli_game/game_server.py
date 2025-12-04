# game_server.py
import socket
import threading
import argparse
import random
import time

players = []
secret_number = random.randint(1, 100)
turn = 0   # 0 or 1
lock = threading.Lock()
game_over = threading.Event()

def broadcast(msg):
    """把訊息送給所有玩家"""
    for p in players:
        try:
            p.sendall((msg + "\n").encode())
        except:
            pass

def handle_player(conn, idx):
    global turn, secret_number

    conn.sendall(b"Welcome! Please wait for another player...\n")

    # 等到兩位都加入
    while len(players) < 2:
        time.sleep(0.05)

    conn.sendall(f"Both players joined! Secret number generated.\n".encode())

    # 遊戲主迴圈
    last_seen_turn = None
    while not game_over.is_set():
        if turn == idx:
            conn.sendall(b"YOUR_TURN(Enter 1-100) :")
            guess = conn.recv(1024).decode().strip()
            if not guess:
                break
            if not guess.isdigit():
                conn.sendall(b"INVALID\n")
                continue

            guess = int(guess)
            if guess == secret_number:
                broadcast(f"PLAYER_{idx+1}_WIN")
                game_over.set()
                break
            elif guess < secret_number:
                broadcast(f"->{guess} guess is LOW\n")
            else:
                broadcast(f"->{guess} guess is HIGH\n")

            # 換人
            with lock:
                last_seen_turn = turn
                turn = 1 - turn
        else:
            if( last_seen_turn != turn ):
                conn.sendall(b"WAIT your opponent and drink a cup of tea\n")
                last_seen_turn = turn
            time.sleep(0.1)

    if game_over.is_set():
        try:
            conn.sendall(b"GAME_OVER\n")
        except:
            pass

    conn.close()


def start_game_server(port, room_id):
    print(f"[GameServer] Starting on port {port} (Room {room_id})")
    print(f"[GameServer] Secret number = {secret_number}")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("0.0.0.0", port))
    server.listen(2)

    print("[GameServer] Waiting for 2 players...")

    # waiting for 2 players entered
    threads = []
    for i in range(2):
        conn, addr = server.accept()
        print(f"[GameServer] Player {i+1} connected:", addr)
        players.append(conn)
        t = threading.Thread(target=handle_player, args=(conn, i))
        t.start()
        threads.append(t)

    # 等待遊戲執行完（兩個 thread 都結束）
    for t in threads:
        t.join()

    print("[GameServer] Game Finished")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--room_id", type=int, required=True)
    args = parser.parse_args()

    start_game_server(args.port, args.room_id)
