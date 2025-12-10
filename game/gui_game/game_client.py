# Simple Tkinter GUI client for Rock-Paper-Scissors
import socket
import threading
import argparse
import tkinter as tk
from tkinter import messagebox


class GameClientGUI:
    def __init__(self, server_ip, server_port, room_id):
        self.server_ip = server_ip
        self.server_port = server_port
        self.room_id = room_id
        self.sock = None
        self.root = tk.Tk()
        self.root.title(f"RPS - Room {room_id}")
        self.messages = tk.StringVar(value="connecting...")
        tk.Label(self.root, textvariable=self.messages, justify="left", anchor="w", font=("Helvetica", 16)).pack(fill="both", padx=20, pady=20)
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=15)
        for text in ["Rock", "Scissors", "Paper"]:
            tk.Button(
                btn_frame,
                text=text,
                width=40,          # 放大按鈕寬度
                height=3,          # 放大按鈕高度
                font=("Helvetica", 16),
                command=lambda t=text: self.send_choice(t)
            ).pack(side="left", padx=10)

    def start(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.server_ip, self.server_port))
        except OSError as e:
            messagebox.showerror("connection failed", str(e))
            return
        threading.Thread(target=self.listen_loop, daemon=True).start()
        self.root.mainloop()

    def append_msg(self, text):
        current = self.messages.get()
        self.messages.set((current + "\n" if current else "") + text)

    def listen_loop(self):
        try:
            while True:
                data = self.sock.recv(1024).decode().strip()
                if not data:
                    break
                for line in data.splitlines():
                    if line.startswith("FINAL"):
                        self.append_msg(line)
                        messagebox.showinfo("Result", line)
                        self.root.quit()
                        return
                    elif line.startswith("RESULT"):
                        self.append_msg(line)
                    elif line == "CHOOSE":
                        self.append_msg("choose：Rock/Scissors/Paper")
                    elif line == "WAIT":
                        self.append_msg("wait your opponent...")
                    elif line == "INVALID":
                        self.append_msg("not effective input, please choose again")
                    elif line == "START":
                        self.append_msg("game start ! make your choice")
                    elif line == "GAME_OVER":
                        self.root.quit()
                        return
                    else:
                        self.append_msg(line)
        finally:
            try:
                self.sock.close()
            except:
                pass

    def send_choice(self, choice_text):
        if not self.sock:
            return
        mapping = {"Rock": "rock", "Scissors": "scissors", "Paper": "paper"}
        choice = mapping.get(choice_text, "")
        try:
            self.sock.sendall(choice.encode())
        except OSError as e:
            messagebox.showerror("submission failed", str(e))
            return


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server_ip", required=True)
    parser.add_argument("--server_port", required=True)
    parser.add_argument("--room_id", required=True)
    args = parser.parse_args()
    gui = GameClientGUI(args.server_ip, int(args.server_port), args.room_id)
    gui.start()
