# Rock-Paper-Scissors server (GUI-friendly), first to 3 points
import socket
import threading
import argparse
import time

players = []
choices = [None, None]
scores = [0, 0]
lock = threading.Lock()
game_over = threading.Event()

VALID = {"rock", "paper", "scissors"}


def broadcast(msg: str):
    """Send a line to all connected players."""
    for p in players:
        try:
            p.sendall((msg + "\n").encode())
        except:
            pass


def decide(c1: str, c2: str) -> int:
    """Return 0 tie, 1 if player1 wins, 2 if player2 wins."""
    if c1 == c2:
        return 0
    wins = {("rock", "scissors"), ("scissors", "paper"), ("paper", "rock")}
    return 1 if (c1, c2) in wins else 2


def handle_player(conn: socket.socket, idx: int):
    conn.sendall(b"WELCOME\nWAITING_FOR_OTHERS\n")
    while len(players) < 2 and not game_over.is_set():
        time.sleep(0.05)

    conn.sendall(b"START\nCHOOSE\n")

    while not game_over.is_set():
        data = conn.recv(1024).decode().strip().lower()
        if not data:
            break
        if data not in VALID:
            conn.sendall(b"INVALID\nCHOOSE\n")
            continue

        send_wait = False
        with lock:
            choices[idx] = data
            if not all(choices):
                send_wait = True
            else:
                outcome = decide(choices[0], choices[1])
                if outcome == 0:
                    broadcast(f"RESULT TIE P1:{choices[0]} P2:{choices[1]} SCORE {scores[0]}-{scores[1]}")
                    choices[0] = None
                    choices[1] = None
                    broadcast("CHOOSE")
                else:
                    winner = outcome
                    scores[winner - 1] += 1
                    broadcast(f"RESULT WINNER P{winner} P1:{choices[0]} P2:{choices[1]} SCORE {scores[0]}-{scores[1]}")
                    choices[0] = None
                    choices[1] = None
                    if max(scores) >= 3:
                        broadcast(f"FINAL WINNER P{winner} SCORE {scores[0]}-{scores[1]}")
                        game_over.set()
                    else:
                        broadcast("CHOOSE")

        if game_over.is_set():
            break
        if send_wait:
            conn.sendall(b"WAIT\n")

    if game_over.is_set():
        try:
            conn.sendall(b"GAME_OVER\n")
        except:
            pass
    conn.close()


def start_game_server(port: int, room_id: int):
    print(f"[RPS GUI GameServer] port={port}, room={room_id}")
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("0.0.0.0", port))
    srv.listen(2)
    threads = []
    for i in range(2):
        conn, addr = srv.accept()
        print("Player", i + 1, "connected", addr)
        players.append(conn)
        t = threading.Thread(target=handle_player, args=(conn, i))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    print("[RPS GUI GameServer] finished")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--room_id", type=int, required=True)
    args = parser.parse_args()
    start_game_server(args.port, args.room_id)
