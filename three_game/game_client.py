# Three-player Attack/Reflect GUI client
import socket
import threading
import argparse
import json
import os
import random
import tkinter as tk
from tkinter import messagebox


class GameClientGUI:
    def __init__(self, server_ip, server_port, name):
        self.server_ip = server_ip
        self.server_port = server_port
        self.name = name or "Player"
        self.sock = None
        self.players = []
        self.other_players = []
        self.scores = {}
        self.selected_action = None
        self.selected_target = None
        self.locked = False

        self.root = tk.Tk()
        self.root.title(f"Attack/Reflect - {self.name}")

        self.msg_var = tk.StringVar(value="Connecting...")
        tk.Label(self.root, textvariable=self.msg_var, justify="left", anchor="w").pack(fill="x", padx=10, pady=5)

        self.score_var = tk.StringVar(value="")
        tk.Label(self.root, textvariable=self.score_var, justify="left", anchor="w", fg="blue").pack(fill="x", padx=10)

        # Action buttons
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=5)
        self.selected_action = tk.StringVar(value="attack")
        tk.Radiobutton(btn_frame, text="Attack", variable=self.selected_action, value="attack").pack(side="left", padx=5)
        tk.Radiobutton(btn_frame, text="Reflect", variable=self.selected_action, value="reflect").pack(side="left", padx=5)
        tk.Button(btn_frame, text="Confirm", command=self.send_choice, width=12).pack(side="left", padx=5)

        # Canvas for players
        self.canvas = tk.Canvas(self.root, width=500, height=220, bg="white")
        self.canvas.pack(padx=10, pady=10)
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.player_positions = {}  # name -> (x,y)
        self.player_items = {}      # name -> (circle_id, text_id)

    def connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.server_ip, self.server_port))
        except OSError as e:
            messagebox.showerror("Connection failed", str(e))
            return False
        # send name
        self.sock.sendall(json.dumps({"name": self.name}).encode())
        threading.Thread(target=self.listen_loop, daemon=True).start()
        return True

    def set_message(self, text):
        self.msg_var.set(text)

    def update_scores(self):
        if not self.scores:
            self.score_var.set("")
            return
        parts = [f"{p}: {s}" for p, s in self.scores.items()]
        self.score_var.set("Scores: " + " | ".join(parts))

    def layout_players(self):
        self.canvas.delete("all")
        self.player_items.clear()
        n = len(self.other_players)
        if n == 0:
            return
        # spread evenly on a circle
        cx, cy, r = 250, 110, 80
        import math
        for i, p in enumerate(self.other_players):
            angle = 2 * math.pi * i / n
            x = cx + r * math.cos(angle)
            y = cy + r * math.sin(angle)
            self.player_positions[p] = (x, y)
            self.draw_player(p)

    def draw_player(self, name):
        x, y = self.player_positions.get(name, (0, 0))
        selected = (name == self.selected_target)
        color = "red" if selected else "lightblue"
        circle = self.canvas.create_oval(x-35, y-35, x+35, y+35, fill=color, outline="black", width=3)
        text = self.canvas.create_text(x, y, text=name, font=("Helvetica", 14, "bold"))
        self.player_items[name] = (circle, text)

    def on_canvas_click(self, event):
        if self.locked:
            return
        # find clicked player
        for name, (x, y) in self.player_positions.items():
            if (event.x - x) ** 2 + (event.y - y) ** 2 <= 35 ** 2:
                self.selected_target = name
                self.redraw_players()
                self.set_message(f"Selected target: {name}")
                return

    def redraw_players(self):
        for name, (circle, _) in self.player_items.items():
            color = "red" if name == self.selected_target else "lightblue"
            self.canvas.itemconfig(circle, fill=color)

    def send_choice(self):
        if self.locked:
            return
        if not self.selected_target:
            messagebox.showwarning("No target", "Please select a target on canvas.")
            return
        choice = {"type": self.selected_action.get(), "target": self.selected_target}
        try:
            self.sock.sendall(json.dumps(choice).encode())
        except OSError as e:
            messagebox.showerror("Send failed", str(e))
            return
        self.locked = True
        self.set_message(f"Locked choice: {choice['type']} -> {choice['target']}")

    def listen_loop(self):
        try:
            while True:
                data = self.sock.recv(4096)
                if not data:
                    break
                lines = data.decode().strip().splitlines()
                for line in lines:
                    try:
                        msg = json.loads(line)
                    except:
                        continue
                    self.handle_msg(msg)
        finally:
            try:
                self.sock.close()
            except:
                pass
            self.root.quit()

    def handle_msg(self, msg):
        mtype = msg.get("msg")
        if mtype == "START":
            self.players = msg.get("players", [])
            self.other_players = [p for p in self.players if p != self.name]
            self.scores = {p: 0 for p in self.players}
            self.layout_players()
            self.update_scores()
            self.locked = False
            self.selected_target = None
            self.redraw_players()
            self.set_message("Game start! Choose target and attack/reflect, then Confirm.")
        elif mtype == "ROUND_END":
            self.scores.update(msg.get("scores", {}))
            self.update_scores()
            eliminated = msg.get("eliminated", [])
            surv = msg.get("survivors", [])
            acts = msg.get("actions", {})
            self.set_message(f"Eliminated: {eliminated} | Survivors: {surv}\nActions: {acts}")
        elif mtype == "NEXT_ROUND":
            self.locked = False
            self.selected_target = None
            self.redraw_players()
            self.set_message("Next round: select target and action, then Confirm.")
        elif mtype == "GAME_END":
            winner = msg.get("winner")
            score = msg.get("score")
            messagebox.showinfo("Game End", f"Winner: {winner} (score {score})")
            self.root.quit()
        else:
            # ignore
            pass

    def start(self):
        if self.connect():
            self.root.mainloop()
        # ensure process exits even if lingering threads
        os._exit(0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server_ip", required=True)
    parser.add_argument("--server_port", type=int, required=True)
    parser.add_argument("--room_id", required=False, help="ignored (for launcher compatibility)")
    parser.add_argument("--name", required=False, help="player name (optional)")
    args = parser.parse_args()
    player_name = args.name or os.environ.get("PLAYER_NAME") or f"Player{random.randint(1000,9999)}"
    gui = GameClientGUI(args.server_ip, args.server_port, player_name)
    gui.start()


if __name__ == "__main__":
    main()
