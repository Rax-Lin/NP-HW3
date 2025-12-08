import socket
import threading
import json
import os
import shutil
import subprocess
import zipfile
import tempfile
import time

# ========= 檔案路徑設定 =========
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR       = os.path.dirname(BASE_DIR)
DEV_DIR        = os.path.join(ROOT_DIR, "developer_client")

# 與 developer_server 共用的遊戲資料與上傳檔案（直接讀 developer_client 資料夾）
DB_FILE        = os.path.join(DEV_DIR, "database.json")
UPLOAD_DIR     = os.path.join(DEV_DIR, "uploaded_games")
PLAYER_FILE    = os.path.join(BASE_DIR, "players.json")

# data of the server
ROOM_FILE      = os.path.join(BASE_DIR, "rooms.json")             # room list
PLAY_FILE      = os.path.join(BASE_DIR, "play_history.json")      # 玩家玩過哪些遊戲
CHAT_FILE      = os.path.join(BASE_DIR, "room_chats.json")        # chat records

os.makedirs(UPLOAD_DIR, exist_ok=True)

# ========= Plugin definition（PL1） =========
# 在這裡定義所有可用的 Plugin
AVAILABLE_PLUGINS = [
    {
        "id": "room_chat",
        "name": "Room Chat Plugin",
        "description": "在房間內提供簡單的文字群組聊天功能",
        "version": "1.0"
    }
]


# ========= load/save JSON =========
def load_json(path, default):
    """
    小工具：安全載入 JSON 檔案
    若檔案不存在則回傳 default
    """
    if not os.path.exists(path):
        return default
    with open(path, "r") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)


def load_db():
    # 遊戲資料庫，與 Developer 共用
    return load_json(DB_FILE, {"developers": {}, "games": {}})


def save_db(db):
    save_json(DB_FILE, db)


def load_rooms():
    return load_json(ROOM_FILE, {"rooms": []})


def save_rooms(rooms):
    save_json(ROOM_FILE, rooms)


def load_players():
    return load_json(PLAYER_FILE, {"players": {}})


def save_players(p):
    save_json(PLAYER_FILE, p)


# ========================== 玩家帳號相關 ==========================
def handle_player_register(req, conn):
    name = req.get("name")
    pwd  = req.get("password")
    if not name or not pwd:
        conn.sendall(json.dumps({"status":"error","message":"missing fields"}).encode())
        return
    players = load_players()
    if name in players["players"]:
        conn.sendall(json.dumps({"status":"error","message":"account exists"}).encode())
        return
    # 註冊後直接視為已登入，方便首次使用 -> same as the developer server change
    players["players"][name] = {"password": pwd, "online": True, "last_seen": time.time()}
    save_players(players)
    conn.sendall(json.dumps({"status":"ok","message":"registered and logged in"}).encode())


def handle_player_login(req, conn):
    name = req.get("name")
    pwd  = req.get("password")
    players = load_players()
    info = players["players"].get(name)
    if not info or info.get("password") != pwd:
        conn.sendall(json.dumps({"status":"error","message":"invalid credentials"}).encode())
        return
    # 允許覆蓋舊 session，若之前異常未登出也能重新登入
    info["online"] = True
    info["last_seen"] = time.time()
    save_players(players)
    conn.sendall(json.dumps({"status":"ok","message":"login success"}).encode())


def handle_player_logout(req, conn):
    name = req.get("name")
    players = load_players()
    if name in players["players"]:
        players["players"][name]["online"] = False
        players["players"][name]["last_seen"] = 0
        save_players(players)
    conn.sendall(json.dumps({"status":"ok","message":"logout"}).encode())


def handle_list_players(conn):
    players = load_players()
    online = [p for p, info in players["players"].items() if info.get("online")]
    conn.sendall(json.dumps({"status":"ok","players": online}).encode())


def require_player_online(player):
    players = load_players()
    info = players["players"].get(player)
    if info and info.get("online"):
        info["last_seen"] = time.time()
        save_players(players)
        return True
    return False


def handle_player_heartbeat(req, conn):
    name = req.get("name")
    players = load_players()
    info = players["players"].get(name)
    if info and info.get("online"):
        info["last_seen"] = time.time()
        save_players(players)
        conn.sendall(json.dumps({"status":"ok"}).encode())
    else:
        conn.sendall(json.dumps({"status":"error","message":"not logged in"}).encode())


def find_player_room(rooms, player):
    """
    回傳玩家所在的房間物件，若不在任何房間回傳 None
    """
    for r in rooms["rooms"]:
        if player in r.get("players", []):
            return r
    return None


def cleanup_player_in_rooms(rooms, player):
    """
    移除玩家在所有房間中的紀錄，若房間變空則刪除。
    回傳 (updated_rooms, removed_any)
    """
    removed = False
    new_rooms = []
    for r in rooms["rooms"]:
        if player in r.get("players", []):
            removed = True
            r["players"] = [p for p in r["players"] if p != player]
        if r.get("players"):
            new_rooms.append(r) # save the room only if not empty, (may be someone else still inside)
    if removed:
        rooms["rooms"] = new_rooms
    return rooms, removed


def save_rooms(rooms):
    save_json(ROOM_FILE, rooms)


def load_play_history():
    # play_history , check if the player has played this game before（P4）
    return load_json(PLAY_FILE, {"records": []})


def save_play_history(ph):
    save_json(PLAY_FILE, ph)


def load_chats():
    # room_chats 格式：{"rooms": {"1": [ {player,message}, ... ] } }
    return load_json(CHAT_FILE, {"rooms": {}})


def save_chats(chats):
    save_json(CHAT_FILE, chats)


def clear_chat_room(room_id):
    chats = load_chats()
    room_key = str(room_id)
    if room_key in chats["rooms"]:
        del chats["rooms"][room_key]
        save_chats(chats)


# ========= P1：取得商城遊戲列表（include rating） =========
def handle_get_games(conn):
    db = load_db()

    game_list = []
    for key, info in db["games"].items():
        # 可能舊資料沒有 ratings 欄位，所以用 get
        ratings = info.get("ratings", [])
        if ratings:
            avg_score = sum(r["score"] for r in ratings) / len(ratings)
        else:
            avg_score = None

        latest_version = sorted(info["versions"].keys())[-1]

        game_list.append({
            "game_key": key,                  # 唯一 ID（developer_gameName）
            "name": info["name"],
            "developer": info["developer"],
            "description": info["description"],
            "latest_version": latest_version,
            "avg_score": avg_score,
            "rating_count": len(ratings)
        })

    response = {"status": "ok", "games": game_list}
    conn.sendall(json.dumps(response).encode())


# ========= P2：download game =========
def handle_download(req, conn):
    """
    req 內容：
    {
        "action": "download_game",
        "game_key": "...",
        "version": "...",
        "player": "PlayerName"
    }
    """
    game_key = req["game_key"]
    version  = req["version"]
    player   = req["player"]

    if not require_player_online(player):
        conn.sendall(json.dumps({"status":"error","message":"player not logged in"}).encode())
        return

    db = load_db()
    if game_key not in db["games"]:
        conn.sendall(json.dumps({"status": "error", "message": "game not found"}).encode())
        return

    # 找對應版本的檔案路徑
    version_info = db["games"][game_key]["versions"].get(version)
    if not version_info:
        conn.sendall(json.dumps({"status": "error", "message": "version not exists"}).encode())
        return

    src_path = version_info["file_path"]
    if not os.path.isabs(src_path):
        src_path = os.path.join(DEV_DIR, src_path)
    if not os.path.exists(src_path):
        conn.sendall(json.dumps({"status": "error", "message": "game file missing"}).encode())
        return

    # 玩家下載目的地（-> 每位玩家一個資料夾）
    dst_dir = os.path.join(ROOT_DIR, "player_client", "downloads", player)
    os.makedirs(dst_dir, exist_ok=True)
    dst_path = os.path.join(dst_dir, os.path.basename(src_path))

    shutil.copy(src_path, dst_path)

    conn.sendall(json.dumps({"status": "ok", "message": "download success"}).encode())


# ========= P3：create room =========
def handle_create_room(req, conn):
    """
    req:
    {
        "action": "create_room",
        "player": "PlayerName",
        "game_key": "...",
        "version": "..."
    }
    """
    player   = req["player"]
    game_key = req["game_key"]
    version  = req["version"]

    if not require_player_online(player):
        conn.sendall(json.dumps({"status":"error","message":"player not logged in"}).encode())
        return

    db = load_db()
    if game_key not in db["games"]:
        conn.sendall(json.dumps({"status":"error","message":"game not found"}).encode())
        return

    game = db["games"][game_key]
    version_info = game["versions"].get(version)
    if not version_info:
        conn.sendall(json.dumps({"status":"error","message":"version not exists"}).encode())
        return

    zip_path = version_info["file_path"]
    if not os.path.isabs(zip_path):
        zip_path = os.path.join(DEV_DIR, zip_path)
    if not os.path.exists(zip_path):
        conn.sendall(json.dumps({"status":"error","message":"game zip missing on server"}).encode())
        return

    rooms = load_rooms()
    rooms, _ = cleanup_player_in_rooms(rooms, player)
    # 儲存清理後的 rooms，避免殘留
    save_rooms(rooms)
    if find_player_room(rooms, player):
        conn.sendall(json.dumps({"status":"error","message":"leave current room first"}).encode())
        return

    # 分配最小可用房號（從 1 開始）
    existing_ids = sorted(r["room_id"] for r in rooms["rooms"]) # for fear that room ids are not continuous
    new_room_id = 1
    for rid in existing_ids: # find the hole, then we can reuse the id
        if rid == new_room_id:
            new_room_id += 1
        elif rid > new_room_id:
            break

    new_room = {
        "room_id": new_room_id,
        "game": game_key,
        "version": version,
        "creator": player,
        "players": [player],
        "server_port": 7000 + new_room_id,  # 先保留埠號，真正啟動在 start_room
        "started": False
    }

    rooms["rooms"].append(new_room)
    save_rooms(rooms)

    # record play_history（for P4 ）
    ph = load_play_history()
    ph["records"].append({
        "player": player,
        "game_key": game_key
    })
    save_play_history(ph)

    conn.sendall(json.dumps({
        "status":  "ok",
        "message": "room created",
        "room":    new_room
    }).encode())



# ========= P4：get the information of game =========
def handle_get_game_detail(req, conn):
    """
    req 內容：
    {
        "action": "get_game_detail",
        "game_key": "..."
    }
    """
    game_key = req["game_key"]
    db = load_db()

    if game_key not in db["games"]:
        conn.sendall(json.dumps({"status": "error", "message": "game not found"}).encode())
        return

    info = db["games"][game_key]
    ratings = info.get("ratings", [])
    if ratings:
        avg_score = sum(r["score"] for r in ratings) / len(ratings)
    else:
        avg_score = None

    # 只回傳前幾則留言即可（避免太多）
    preview_comments = ratings[-5:]

    res = {
        "status": "ok",
        "game_key": game_key,
        "name": info["name"],
        "developer": info["developer"],
        "description": info["description"],
        "avg_score": avg_score,
        "rating_count": len(ratings),
        "comments": preview_comments
    }
    conn.sendall(json.dumps(res).encode())


# ========= P4：submit rating =========
def handle_submit_rating(req, conn):
    """
    req 內容：
    {
        "action": "submit_rating",
        "player": "PlayerName",
        "game_key": "...",
        "score": 1~5,
        "comment": "..."
    }
    """
    player   = req["player"]
    game_key = req["game_key"]
    score    = req["score"]
    comment  = req.get("comment", "")

    if not require_player_online(player):
        conn.sendall(json.dumps({"status": "error", "message": "player not logged in"}).encode())
        return

    # check score range
    if not (1 <= score <= 5): # five rating review
        conn.sendall(json.dumps({"status": "error", "message": "score must be 1~5"}).encode())
        return

    db = load_db()
    if game_key not in db["games"]:
        conn.sendall(json.dumps({"status": "error", "message": "game not found"}).encode())
        return

    # check if the player has played this game before（依照 play_history）
    ph = load_play_history()
    played = any((r["player"] == player and r["game_key"] == game_key) for r in ph["records"])
    if not played:
        conn.sendall(json.dumps({"status": "error", "message": "you have not played this game"}).encode())
        return

    # write rating
    game = db["games"][game_key]
    if "ratings" not in game:
        game["ratings"] = []
    game["ratings"].append({
        "player": player,
        "score": score,
        "comment": comment
    })

    save_db(db)

    conn.sendall(json.dumps({"status": "ok", "message": "rating submitted"}).encode())


# ========= 房間列表 / 加入 / 離開 / 刪除 =========
def handle_list_rooms(conn):
    rooms = load_rooms()
    conn.sendall(json.dumps({
        "status": "ok",
        "rooms": rooms["rooms"]
    }).encode())


def handle_join_room(req, conn):
    """
    req: {action:"join_room", player:"...", room_id":int}
    """
    player = req["player"]
    room_id = int(req["room_id"])

    if not require_player_online(player):
        conn.sendall(json.dumps({"status":"error","message":"player not logged in"}).encode())
        return

    rooms = load_rooms()
    rooms, _ = cleanup_player_in_rooms(rooms, player)
    save_rooms(rooms)
    if find_player_room(rooms, player):
        conn.sendall(json.dumps({"status": "error", "message": "leave current room first"}).encode())
        return

    target = None
    for r in rooms["rooms"]:
        if r["room_id"] == room_id:
            target = r
            break
    if not target:
        conn.sendall(json.dumps({"status":"error","message":"room not found"}).encode())
        return

    if player not in target["players"]:
        target["players"].append(player)
        save_rooms(rooms)

    # 記錄 play history
    ph = load_play_history()
    ph["records"].append({"player": player, "game_key": target["game"]})
    save_play_history(ph)

    conn.sendall(json.dumps({"status":"ok","room":target}).encode())


def cleanup_room_after_game(room_id):
    """
    Debug : 
    遊戲的 child process 結束後，將房間移除，避免下局被卡在 started 狀態
    """
    rooms = load_rooms()
    rooms["rooms"] = [r for r in rooms["rooms"] if r["room_id"] != room_id]
    save_rooms(rooms)
    clear_chat_room(room_id)
    print(f"[Lobby] Room {room_id} cleaned after game finished")


def handle_start_room(req, conn):
    """
    req: {action:"start_room", player:"...", room_id":int}
    只有 creator 可以啟動，且需要至少 2 位玩家
    """
    player = req["player"]
    if not require_player_online(player):
        conn.sendall(json.dumps({"status":"error","message":"player not logged in"}).encode())
        return
    room_id = int(req["room_id"])

    rooms = load_rooms()
    target = None
    for r in rooms["rooms"]:
        if r["room_id"] == room_id:
            target = r
            break
    if not target:
        conn.sendall(json.dumps({"status":"error","message":"room not found"}).encode())
        return
    if target.get("creator") != player:
        conn.sendall(json.dumps({"status":"error","message":"only creator can start"}).encode())
        return
    if target.get("started"):
        conn.sendall(json.dumps({"status":"ok","message":"already started","room":target}).encode())
        return
    if len(target.get("players", [])) < 2:
        conn.sendall(json.dumps({"status":"error","message":"need at least 2 players"}).encode())
        return

    # 準備啟動 game server
    db = load_db()
    game_key = target["game"]
    version = target["version"]
    version_info = db["games"][game_key]["versions"].get(version)
    if not version_info:
        conn.sendall(json.dumps({"status":"error","message":"version not exists"}).encode())
        return
    zip_path = version_info["file_path"]
    if not os.path.isabs(zip_path):
        zip_path = os.path.join(DEV_DIR, zip_path)
    if not os.path.exists(zip_path):
        conn.sendall(json.dumps({"status":"error","message":"game zip missing on server"}).encode())
        return

    result = start_game_server(game_key, version, zip_path, room_id)
    if result is None:
        conn.sendall(json.dumps({"status":"error","message":"failed to start game server"}).encode())
        return
    server_port, proc = result

    target["server_port"] = server_port
    target["started"] = True
    save_rooms(rooms)

    # 背景等待 game server 結束後清理房間，避免卡住
    threading.Thread(target=lambda p, rid: (p.wait(), cleanup_room_after_game(rid)),
                     args=(proc, room_id), daemon=True).start()

    conn.sendall(json.dumps({"status":"ok","message":"game started","room":target}).encode())


def handle_leave_room(req, conn):
    """
    req: {action:"leave_room", player:"..."}
    """
    player = req["player"]
    rooms = load_rooms()
    rooms, removed = cleanup_player_in_rooms(rooms, player)
    if not removed:
        conn.sendall(json.dumps({"status":"error","message":"not in any room"}).encode())
        return

    save_rooms(rooms)
    conn.sendall(json.dumps({"status":"ok","message":"left room"}).encode())


def handle_delete_room(req, conn):
    """
    req: {action:"delete_room", player:"...", room_id":int}
    只有 creator 可以刪除
    """
    player = req["player"]
    room_id = int(req["room_id"])
    rooms = load_rooms()
    # 找出符合房號且是自己建立的房間
    target = None
    for r in rooms["rooms"]:
        if r["room_id"] == room_id and r.get("creator") == player:
            target = r
            break
    if not target:
        # 若房號存在但不是自己建立，回報錯誤
        exists = any(r["room_id"] == room_id for r in rooms["rooms"])
        if exists:
            conn.sendall(json.dumps({"status":"error","message":"only creator can delete"}).encode())
        else:
            conn.sendall(json.dumps({"status":"error","message":"room not found"}).encode())
        return

    # 刪除所有同房號的記錄以清理重複
    rooms["rooms"] = [r for r in rooms["rooms"] if r["room_id"] != room_id]
    save_rooms(rooms)
    clear_chat_room(room_id)
    conn.sendall(json.dumps({"status":"ok","message":"room deleted"}).encode())


# PL1：Get Plugin list
def handle_get_plugins(conn):
    """
    Plugin 只是由 Lobby Server 提供可用清單；
    安裝/移除放在 Client 端做（每位玩家自己決定）
    """
    res = {
        "status": "ok",
        "plugins": AVAILABLE_PLUGINS
    }
    conn.sendall(json.dumps(res).encode())


# Chatting in the room (PL1)
def handle_room_chat_send(req, conn):
    """
    req:
    {
        "action": "room_chat_send",
        "room_id": 1,
        "player": "Alice",
        "message": "Hello"
    }
    """
    room_id = str(req["room_id"])
    player  = req["player"]
    message = req["message"]

    if not require_player_online(player):
        conn.sendall(json.dumps({"status":"error","message":"player not logged in"}).encode())
        return

    rooms = load_rooms()
    my_room = find_player_room(rooms, player)
    if not my_room:
        conn.sendall(json.dumps({"status":"error","message":"not in any room"}).encode())
        return
    if str(my_room["room_id"]) != room_id:
        conn.sendall(json.dumps({"status":"error","message":"room mismatch"}).encode())
        return

    chats = load_chats()
    key = str(my_room["room_id"])
    if key not in chats["rooms"]:
        chats["rooms"][key] = []
    chats["rooms"][key].append({
        "player": player,
        "message": message
    })
    save_chats(chats)

    conn.sendall(json.dumps({"status":"ok","message":"chat sent"}).encode())


# Get the chatting history
def handle_room_chat_fetch(req, conn):
    """
    req:
    {
        "action": "room_chat_fetch",
        "room_id": 1
    }
    """
    room_id = str(req["room_id"])
    player = req.get("player")

    if not require_player_online(player):
        conn.sendall(json.dumps({"status":"error","message":"player not logged in"}).encode())
        return

    rooms = load_rooms()
    my_room = find_player_room(rooms, player)
    if not my_room:
        conn.sendall(json.dumps({"status":"error","message":"not in any room"}).encode())
        return
    if str(my_room["room_id"]) != room_id:
        conn.sendall(json.dumps({"status":"error","message":"room mismatch"}).encode())
        return

    chats = load_chats()
    key = str(my_room["room_id"])
    msgs = chats["rooms"].get(key, [])

    conn.sendall(json.dumps({
        "status": "ok",
        "messages": msgs
    }).encode())


# Important !!!!! : Main server loop
def handle_client(conn, addr):
    print(f"[Lobby] Connected by {addr}")

    while True:
        raw = conn.recv(4096)
        if not raw:
            break

        try:
            req = json.loads(raw.decode())
        except:
            continue

        action = req.get("action")

        if action == "player_register":
            handle_player_register(req, conn)
        elif action == "player_login":
            handle_player_login(req, conn)
        elif action == "player_logout":
            handle_player_logout(req, conn)
        elif action == "list_players":
            handle_list_players(conn)
        elif action == "player_heartbeat":
            handle_player_heartbeat(req, conn)
        elif action == "get_games":
            handle_get_games(conn)
        elif action == "download_game":
            handle_download(req, conn)
        elif action == "create_room":
            handle_create_room(req, conn)
        elif action == "list_rooms":
            handle_list_rooms(conn)
        elif action == "join_room":
            handle_join_room(req, conn)
        elif action == "leave_room":
            handle_leave_room(req, conn)
        elif action == "delete_room":
            handle_delete_room(req, conn)
        elif action == "start_room":
            handle_start_room(req, conn)
        elif action == "get_game_detail":
            handle_get_game_detail(req, conn)
        elif action == "submit_rating":
            handle_submit_rating(req, conn)
        elif action == "get_plugins":
            handle_get_plugins(conn)
        elif action == "room_chat_send":
            handle_room_chat_send(req, conn)
        elif action == "room_chat_fetch":
            handle_room_chat_fetch(req, conn)
        # 其他 action 可在此擴充

    conn.close()


def start_lobby():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("0.0.0.0", 6060))
    server.listen(5) # can be changed here if a lot of people want to connect in the same time

    print("[Lobby Server] Running on port 6060...")

    def expire_loop():
        while True:
            time.sleep(30)
            players = load_players()
            now = time.time()
            changed = False
            for info in players["players"].values():
                last = info.get("last_seen", 0)
                if info.get("online") and now - last > 60:
                    info["online"] = False
                    changed = True
            if changed:
                save_players(players)

    threading.Thread(target=expire_loop, daemon=True).start()

    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_client, args=(conn, addr)).start()

GAME_RUNTIME_DIR = os.path.join(BASE_DIR, "game_runtime")
os.makedirs(GAME_RUNTIME_DIR, exist_ok=True)


def ensure_game_extracted(game_key, version, zip_path):
    """
    確保某個遊戲版本已經被解壓縮到 server 端的 runtime 目錄。
    規則：
    - 解壓縮到 GAME_RUNTIME_DIR/{game_key}/{version}/
    - 假設裡面會有一個 game_server.py 可以被啟動
    """
    target_dir = os.path.join(GAME_RUNTIME_DIR, game_key, version)
    if os.path.exists(target_dir) and os.listdir(target_dir):
        # 已經解壓過
        return target_dir

    os.makedirs(target_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(target_dir)
    return target_dir


def start_game_server(game_key, version, zip_path, room_id):
    """
    啟動對應遊戲的 game server：
    - 解壓縮 zip (若尚未解壓)
    - 假設裡面有 game_server.py
    - 分配一個 TCP port（例如 7000 + room_id）
    - 用 subprocess.Popen 啟動：python game_server.py --port XXX --room_id XXX
    """
    runtime_dir = ensure_game_extracted(game_key, version, zip_path)
    server_script = os.path.join(runtime_dir, "game_server.py")

    if not os.path.exists(server_script):
        # record log for debug
        print(f"[WARN] game_server.py not found in {runtime_dir}")
        return None

    # 選一個可用的埠號（避免之前殘留占用）
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tmp:
        tmp.bind(("0.0.0.0", 0))
        port = tmp.getsockname()[1]

    # 實際啟動 game server (non-blocking)
    proc = subprocess.Popen(
        ["python", server_script, "--port", str(port), "--room_id", str(room_id)],
        cwd=runtime_dir
    )
    print(f"[Lobby] Launched game server pid={proc.pid} on port {port} (room {room_id})")

    return port, proc

if __name__ == "__main__":
    start_lobby()
