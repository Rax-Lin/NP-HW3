# game_client.py
import socket
import argparse
import threading
import sys
import os

game_over = threading.Event()

def listen_thread(sock):
    """專門負責聽 server 的訊息"""
    while True:
        try:
            msg = sock.recv(1024).decode().strip()
        except:
            print("Disconnected from server.")
            sys.exit(0)

        if not msg:
            continue

        
        if msg.startswith("PLAYER_"):
            print(f"\n🎉 {msg} 🎉")
            print("End Game, exiting...")
            game_over.set()
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except:
                pass
            os._exit(0)
        else:
            print(msg)

def start_game_client(server_ip, server_port, room_id):
    print(f"[GameClient] Connecting to Game Server {server_ip}:{server_port} (room {room_id})...")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((server_ip, server_port))

    threading.Thread(target=listen_thread, args=(sock,), daemon=True).start()

    # 主迴圈：等待使用者輸入 guess
    while not game_over.is_set():
        try:
            msg = input()
        except EOFError:
            break
        try:
            sock.sendall(msg.encode())
        except:
            print("❌ Server closed.")
            break

    try:
        sock.close()
    except:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server_ip", required=True)
    parser.add_argument("--server_port", required=True)
    parser.add_argument("--room_id", required=True)
    args = parser.parse_args()

    start_game_client(args.server_ip, int(args.server_port), args.room_id)
