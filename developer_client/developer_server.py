import socket
import threading
import json
import os
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "database.json")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploaded_games")

os.makedirs(UPLOAD_DIR, exist_ok=True)

# ==========================
# DB 載入/儲存
# ==========================
def load_db():
    if not os.path.exists(DB_FILE):
        # developers: {name: {"password": "...", "online": False}}
        return {"developers": {}, "games": {}}
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db(db):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=4)


# ==========================
# D1：upload new game
# # ==========================
def handle_upload_game(data, conn, db):
    """
    上架新遊戲：
    - 若該 game_key 尚未存在 => 建立新遊戲
    - 若已存在 => 視為「補上初始版本」，通常 D2 用 update_game
      會比較合理；這裡仍允許覆蓋，以防使用者一開始就用 upload。
    """
    developer   = data["developer"]
    game_name   = data["game_name"]
    version     = data["version"]
    description = data["description"]

    game_key = f"{developer}_{game_name}"
    # 必須 login
    if developer not in db["developers"] or not db["developers"][developer].get("online"):
        conn.sendall(json.dumps({"status":"error","message":"developer not logged in"}).encode())
        return
    # create new game entry if not exists
    if game_key not in db["games"]:
        db["games"][game_key] = {
            "developer": developer,
            "name": game_name,
            "description": description,
            "active": True,
            "versions": {},
            "ratings": []
        }
    else:
        # if game exists
        db["games"][game_key]["description"] = description 
        db["games"][game_key]["active"] = True

    # new version 的 zip 檔案路徑
    file_path = f"{UPLOAD_DIR}{game_key}_{version}.zip"
    db["games"][game_key]["versions"][version] = {
        "file_path": file_path
    }

    # 實際接收檔案資料
    sentinel = b"<END>"
    buffer = b""
    with open(file_path, "wb") as f:
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buffer += chunk

            idx = buffer.find(sentinel)
            if idx != -1:
                # 找到結尾標記，寫入標記前的資料即可
                f.write(buffer[:idx])
                buffer = b""
                break

            # 未找到結尾，保留最後 len(sentinel) - 1 bytes 以防標記斷在 chunk 之間
            if len(buffer) > len(sentinel):
                f.write(buffer[:-len(sentinel)])
                buffer = buffer[-len(sentinel):]

        # 若未找到結尾但連線結束，把剩餘 buffer 寫入
        if buffer:
            f.write(buffer)

    save_db(db)

    response = {"status": "ok", "message": "Game uploaded successfully"}
    conn.sendall(json.dumps(response).encode())


# ==========================
# D2：update game version
# ==========================
def handle_update_game(data, conn, db):
    """
    更新遊戲版本：
    - 只能更新自己（developer）擁有的遊戲
    - 新增一個新的 version entry，並存 zip 檔
    """
    developer = data["developer"]
    game_key  = data["game_key"]  # 直接用 developer_client 傳回來的 key
    version   = data["version"]

    # 權限檢查
    if developer not in db["developers"] or not db["developers"][developer].get("online"):
        conn.sendall(json.dumps({"status":"error","message":"developer not logged in"}).encode())
        return
    if game_key not in db["games"]:
        conn.sendall(json.dumps({"status":"error","message":"game not found"}).encode())
        return

    game = db["games"][game_key]
    if game["developer"] != developer:
        conn.sendall(json.dumps({"status":"error","message":"no permission to update this game"}).encode())
        return

    # 準備接新版本檔案
    file_path = f"{UPLOAD_DIR}{game_key}_{version}.zip"
    game["versions"][version] = {
        "file_path": file_path
    }
    game["active"] = True  # ensure the game is active when updated

    sentinel = b"<END>"
    buffer = b""
    with open(file_path, "wb") as f:
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buffer += chunk

            idx = buffer.find(sentinel)
            if idx != -1:
                f.write(buffer[:idx])
                buffer = b""
                break

            if len(buffer) > len(sentinel):
                f.write(buffer[:-len(sentinel)])
                buffer = buffer[-len(sentinel):]

        if buffer:
            f.write(buffer)

    save_db(db)
    conn.sendall(json.dumps({"status":"ok","message":"Game updated successfully"}).encode())


# ==========================
# D3：remove game
# ==========================
def handle_remove_game(data, conn, db):
    """
    下架遊戲：
    - 不直接刪資料，改成 active=False
    - 方便之後做「重新上架」或保留歷史評價
    """
    developer = data["developer"] # get developer name to confirm the request
    game_key  = data["game_key"]

    if developer not in db["developers"] or not db["developers"][developer].get("online"):
        conn.sendall(json.dumps({"status":"error","message":"developer not logged in"}).encode())
        return

    if game_key not in db["games"]:
        conn.sendall(json.dumps({"status":"error","message":"game not found"}).encode())
        return

    game = db["games"][game_key]
    if game["developer"] != developer: # not developer , shouldn't remove the game
        conn.sendall(json.dumps({"status":"error","message":"no permission to remove this game"}).encode())
        return

    game["active"] = False
    save_db(db)
    conn.sendall(json.dumps({"status":"ok","message":"Game removed (inactive)"}).encode())


# ==========================
# see the game list（for D2 / D3）
# ==========================
def handle_list_my_games(data, conn, db):
    """
    回傳該 developer 擁有的所有遊戲（包含 active / inactive）
    """
    developer = data["developer"]
    if developer not in db["developers"] or not db["developers"][developer].get("online"):
        conn.sendall(json.dumps({"status":"error","message":"developer not logged in"}).encode())
        return

    my_games = []
    for key, info in db["games"].items():
        if info["developer"] == developer:
            latest_version = sorted(info["versions"].keys())[-1] if info["versions"] else None
            my_games.append({
                "game_key": key,
                "name": info["name"],
                "description": info["description"],
                "active": info.get("active", True),
                "latest_version": latest_version
            })

    conn.sendall(json.dumps({"status":"ok","games":my_games}).encode())


# ==========================
# the handler of each client connection
# ==========================
def client_thread(conn, addr):
    print(f"[Developer Server] Client connected:", addr)

    # 每個 connection 開始時載入最新 DB
    db = load_db()

    while True:
        # 先讀取前 4 bytes 的長度，再讀完整 JSON meta，避免 meta 和檔案黏在同一個 recv
        header = conn.recv(4)
        if not header:
            break
        meta_len = int.from_bytes(header, "big")
        meta_bytes = b""
        while len(meta_bytes) < meta_len:
            chunk = conn.recv(meta_len - len(meta_bytes))
            if not chunk:
                break
            meta_bytes += chunk
        if len(meta_bytes) != meta_len:
            break

        try:
            data = json.loads(meta_bytes.decode())
        except json.JSONDecodeError:
            continue

        action = data.get("action")

        if action == "register":
            name = data.get("name")
            pwd  = data.get("password")
            if not name or not pwd:
                conn.sendall(json.dumps({"status":"error","message":"missing fields"}).encode())
                continue
            if name in db["developers"]:
                conn.sendall(json.dumps({"status":"error","message":"account exists"}).encode())
                continue
            # update state as login after registeration ，方便首次使用
            db["developers"][name] = {"password": pwd, "online": True, "last_seen": time.time()}
            save_db(db)
            conn.sendall(json.dumps({"status":"ok","message":"registered and logged in"}).encode())
        elif action == "login":
            name = data.get("name")
            pwd  = data.get("password")
            dev = db["developers"].get(name)
            if not dev or dev.get("password") != pwd:
                conn.sendall(json.dumps({"status":"error","message":"invalid credentials"}).encode())
                continue
            # 允許覆蓋舊 session，避免異常斷線卡在線
            dev["online"] = True
            dev["last_seen"] = time.time()
            save_db(db)
            conn.sendall(json.dumps({"status":"ok","message":"login success"}).encode())
        elif action == "logout":
            name = data.get("name")
            dev = db["developers"].get(name)
            if dev:
                dev["online"] = False
                dev["last_seen"] = 0
                save_db(db)
            conn.sendall(json.dumps({"status":"ok","message":"logout"}).encode())
        elif action == "heartbeat":
            name = data.get("name")
            dev = db["developers"].get(name)
            if dev and dev.get("online"):
                dev["last_seen"] = time.time()
                save_db(db)
            conn.sendall(json.dumps({"status":"ok"}).encode())
        elif action == "upload_game":
            handle_upload_game(data, conn, db)
        elif action == "list_my_games":
            handle_list_my_games(data, conn, db)
        elif action == "update_game":
            handle_update_game(data, conn, db)
        elif action == "remove_game":
            handle_remove_game(data, conn, db)

    conn.close()


# ==========================
# Server 主迴圈
# ==========================
def find_available_port(start_port=5050, max_port=6000):
    """
    從 start_port 開始向後尋找可用 port，找到就返回 socket 與 port。
    """
    for port in range(start_port, max_port + 1):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("0.0.0.0", port))
            s.listen(5)
            return s, port
        except OSError:
            s.close()
            continue
    raise RuntimeError("No available port found in range")


def start_server():
    server, port = find_available_port()

    print(f"Hello I am developer server, I'm running on port {port}...")

    def expire_loop():
        while True:
            time.sleep(30)
            db = load_db()
            now = time.time()
            changed = False
            for dev in db["developers"].values():
                last = dev.get("last_seen", 0)
                if dev.get("online") and now - last > 60:
                    dev["online"] = False
                    changed = True
            if changed:
                save_db(db)

    threading.Thread(target=expire_loop, daemon=True).start()

    while True:
        conn, addr = server.accept()
        threading.Thread(target=client_thread, args=(conn, addr)).start()


if __name__ == "__main__":
    start_server()
