# Three-player Attack/Reflect game server
# Rules:
# - Each round, every player chooses: ATTACK <target> or REFLECT <target>
# - If A attacks B and B does NOT reflect at A, B dies.
# - If A and B attack each other, both die.
# - If B reflects at A while A (and only A) attacks B, A dies and B survives.
# - If multiple attackers hit B and B reflects at one of them, that reflected attacker dies; B still dies to the other attack.
# - As soon as someone dies, round ends. Survivors get 1 point.
# - Game ends when有唯一最高分且該分數 >= 3；若最高分平手則繼續。
import socket
import threading
import argparse
import json
import time
import socket
game_over = threading.Event()

ROUND_POINTS = 1
WIN_SCORE = 3
ACTION_TIMEOUT = 10  # seconds to wait for a player's action before auto-picking


def recv_json(conn):
    data = conn.recv(4096)
    if not data:
        return None
    try:
        # 支援多行 JSON
        lines = data.decode().strip().splitlines()
        if not lines:
            return None
        return json.loads(lines[-1])
    except:
        return None


class GameServer:
    def __init__(self, port, room_id):
        self.port = port
        self.room_id = room_id
        self.players = []  # list of (name, conn)
        self.lock = threading.Lock()
        self.scores = {}

    def broadcast(self, payload):
        msg = (json.dumps(payload) + "\n").encode()
        dead = []
        for i, (n, c) in enumerate(self.players):
            try:
                c.sendall(msg)
            except:
                dead.append(i)
        # 清除斷線玩家
        if dead:
            for idx in reversed(dead):
                _, conn = self.players[idx]
                try:
                    conn.close()
                except:
                    pass
                del self.players[idx]

    def handle_player(self, conn, addr):
        # 收玩家名稱
        conn.sendall(b'{"msg":"WELCOME","room":' + str(self.room_id).encode() + b"}\n")
        data = recv_json(conn)
        if not data or "name" not in data:
            conn.close()
            return
        name = data["name"]
        with self.lock:
            self.players.append((name, conn))
            self.scores.setdefault(name, 0)
        print(f"[ThreeGame] {name} joined from {addr}")
        # 等待遊戲結束（不再讀取 conn，避免吃掉後續行為封包）
        while not game_over.is_set():
            time.sleep(0.1)
        try:
            conn.close()
        except:
            pass

    def collect_actions(self):
        actions = {}
        # 提示選擇
        self.broadcast({"prompt": "CHOOSE", "hint": "A <target> or R <target>"})

        pending = {p: c for p, c in self.players}
        last_wait_broadcast = 0

        while pending:
            for name, conn in list(pending.items()):
                try:
                    conn.settimeout(1)
                    act = recv_json(conn)
                except Exception:
                    act = None
                finally:
                    try:
                        conn.settimeout(None)
                    except:
                        pass

                if act:
                    t = act.get("type", "").lower()
                    target = act.get("target")
                    valid_targets = [x[0] for x in self.players if x[0] != name]
                    if t not in ("attack", "reflect") or target not in valid_targets:
                        actions[name] = {"type": "attack", "target": name}
                    else:
                        actions[name] = {"type": t, "target": target}
                    pending.pop(name, None)
                else:
                    # 若連線已斷，避免永遠等待：給預設動作並移除
                    try:
                        peek = conn.recv(1, socket.MSG_PEEK)
                    except Exception:
                        peek = b""
                    if peek == b"":
                        actions[name] = {"type": "attack", "target": name}
                        pending.pop(name, None)
            # 若尚有人未回應，稍等再試並廣播等待名單
            if pending:
                now = time.time()
                if now - last_wait_broadcast >= 1:
                    self.broadcast({
                        "msg": "WAITING",
                        "pending": list(pending.keys())
                    })
                    last_wait_broadcast = now
                try:
                    time.sleep(0.1)
                except:
                    pass
        return actions

    def resolve_round(self, actions):
        attackers = {}
        reflects = {}
        for p, act in actions.items():
            if act["type"] == "attack":
                attackers.setdefault(act["target"], []).append(p)
            else:
                reflects[p] = act["target"]

        eliminated = set()

        for target, atk_list in attackers.items():
            if target in eliminated:
                continue
            if target in reflects:
                ref_to = reflects[target]
                if len(atk_list) == 1 and atk_list[0] == ref_to:
                    # 成功反彈單一攻擊者
                    eliminated.add(ref_to)
                else:
                    # 反彈錯/多重攻擊，目標死亡；若反彈對其中一個攻擊者，該攻擊者也死
                    eliminated.add(target)
                    if ref_to in atk_list:
                        eliminated.add(ref_to)
            else:
                eliminated.add(target)

        survivors = [p for p, _ in self.players if p not in eliminated]
        for p in survivors:
            self.scores[p] += ROUND_POINTS

        return eliminated, survivors, actions

    def has_winner(self):
        if not self.scores:
            return None
        max_score = max(self.scores.values())
        top = [p for p, s in self.scores.items() if s == max_score]
        if max_score >= WIN_SCORE and len(top) == 1:
            return top[0], max_score
        return None

    def run(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("0.0.0.0", self.port))
        srv.listen(3)
        print(f"[ThreeGame] Room {self.room_id} listening on {self.port}")

        # 接三位玩家
        threads = []
        for _ in range(3):
            conn, addr = srv.accept()
            t = threading.Thread(target=self.handle_player, args=(conn, addr))
            t.start()
            threads.append(t)

        # 等待所有人加入
        while True:
            with self.lock:
                if len(self.players) >= 3:
                    break

        self.broadcast({"msg": "START", "players": [p for p, _ in self.players]})

        while True:
            actions = self.collect_actions()
            eliminated, survivors, acts = self.resolve_round(actions)
            self.broadcast({"msg": "ROUND_END", "eliminated": list(eliminated), "survivors": survivors, "scores": self.scores, "actions": acts})
            # 若沒有人被淘汰，避免卡住，直接進下一輪
            if not eliminated:
                self.broadcast({"msg": "NEXT_ROUND"})
                continue
            winner = self.has_winner()
            if winner:
                name, score = winner
                self.broadcast({"msg": "GAME_END", "winner": name, "score": score})
                game_over.set()
                break
            else:
                self.broadcast({"msg": "NEXT_ROUND"})

        for t in threads:
            t.join()
        game_over.set()
        srv.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--room_id", type=int, required=True)
    args = parser.parse_args()
    GameServer(args.port, args.room_id).run()
