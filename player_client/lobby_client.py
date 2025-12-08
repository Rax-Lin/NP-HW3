import socket
import json
import os
import subprocess
import zipfile
import threading

LOBBY_IP   = "127.0.0.1"
LOBBY_PORT = 6060
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
HEARTBEAT_INTERVAL = 30 # seconds

# the record of installed plugins for each player
PLUGIN_FILE_TEMPLATE = "plugins_{player}.json"


# ========= socket 傳送工具 =========
def send_request(data):
    """
    封裝好與 Lobby Server 的一次性 Request/Response 互動：
    1. 建立 socket
    2. 傳送 JSON
    3. 接收回覆 JSON
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((LOBBY_IP, LOBBY_PORT))
    s.sendall(json.dumps(data).encode())
    raw = s.recv(4096)
    s.close()

    try:
        return json.loads(raw.decode())
    except:
        return None


def heartbeat_loop(player, stop_event):
    while not stop_event.wait(HEARTBEAT_INTERVAL):
        try:
            send_request({"action":"player_heartbeat","name":player})
        except:
            pass


# ========= Plugin 安裝紀錄（存在本地檔案） =========
def get_plugin_file(player):
    return PLUGIN_FILE_TEMPLATE.format(player=player)


def load_installed_plugins(player):
    """
    回傳該玩家已安裝的 Plugin ID set，例如 {"room_chat"}
    """
    path = get_plugin_file(player)
    if not os.path.exists(path):
        return set()
    with open(path, "r") as f:
        data = json.load(f)
    return set(data.get("installed", []))


def save_installed_plugins(player, plugin_ids):
    path = get_plugin_file(player)
    with open(path, "w") as f:
        json.dump({"installed": list(plugin_ids)}, f, indent=4)


# ========= 連線設定 =========
def configure_lobby_endpoint():
    """
    允許使用者在啟動時決定要連本機或遠端工作站。
    也支援環境變數：
    - LOBBY_IP：指定 IP，若存在將當成預設值
    - LOBBY_PORT：指定 Port，若存在則覆寫
    """
    global LOBBY_IP, LOBBY_PORT

    env_ip = os.environ.get("LOBBY_IP", LOBBY_IP)
    env_port = os.environ.get("LOBBY_PORT")
    if env_port and env_port.isdigit():
        LOBBY_PORT = int(env_port)

    print("=== Lobby 連線設定 ===")
    print(f"1. 本機 ({env_ip})")
    print("2. 自訂 IP")
    choice = input("選擇: ").strip()
    if choice == "2":
        ip = input("輸入 Lobby Server IP (例如 10.1.14.12 或 140.113.17.12): ").strip()
        if ip:
            LOBBY_IP = ip
    else:
        LOBBY_IP = env_ip
    print(f"➡ 使用 Lobby 位址 {LOBBY_IP}:{LOBBY_PORT}")


# ========= P1：瀏覽遊戲商城 =========
def view_games():
    res = send_request({"action": "get_games"})

    if not res or res["status"] != "ok":
        print("❌ 無法取得遊戲列表")
        return []

    games = res["games"]
    print("\n=== 可遊玩遊戲列表 ===")
    for idx, g in enumerate(games):
        print(f"{idx+1}. {g['name']} ({g['latest_version']}) - by {g['developer']}")
        # 顯示平均評分
        if g["avg_score"] is not None:
            print(f"    ★ {g['avg_score']:.2f} ({g['rating_count']}則評價)")
        else:
            print("    尚無評分")
        print(f"    {g['description']}")
    return games


# ========= P2：下載 / 更新遊戲 =========
def download_game(player):
    games = view_games()
    if not games:
        return

    try:
        idx = int(input("請輸入要下載/更新的遊戲編號: ")) - 1
        game = games[idx]
    except:
        print("❌ 無效輸入")
        return

    # 這裡簡化版本處理：永遠抓最新版本
    req = {
        "action": "download_game",
        "player": player,
        "game_key": game["game_key"],
        "version": game["latest_version"]
    }

    res = send_request(req)
    if not res:
        print("❌ 下載失敗（無回應）")
        return

    print("📣", res["message"])


# ========= P3：啟動遊戲（示意用 launcher） =========
def ensure_game_unzipped_for_player(player, game_key, version):
    """
    確保玩家端的 zip 已解壓縮：
    - zip 路徑: downloads/{player}/{game_key}_{version}.zip
    - unzip 到: downloads/{player}/{game_key}/{version}/
    """
    base_dir = os.path.join(BASE_DIR, "downloads", player)
    os.makedirs(base_dir, exist_ok=True)
    zip_name = f"{game_key}_{version}.zip"
    zip_path = os.path.join(base_dir, zip_name)

    if not os.path.exists(zip_path):
        return None

    target_dir = os.path.join(base_dir, game_key, version)
    if os.path.exists(target_dir) and os.listdir(target_dir):
        return target_dir

    os.makedirs(target_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(target_dir)
    return target_dir


def local_versions(player, game_key):
    base_dir = os.path.join(BASE_DIR, "downloads", player)
    if not os.path.exists(base_dir):
        return []
    versions = []
    for fname in os.listdir(base_dir):
        if fname.startswith(f"{game_key}_") and fname.endswith(".zip"):
            v = fname[len(game_key) + 1 : -4]
            versions.append(v)
    return versions


def has_latest_version(player, game_key, version):
    zip_path = os.path.join(BASE_DIR, "downloads", player, f"{game_key}_{version}.zip")
    if os.path.exists(zip_path):
        return True
    # 若有其他版本但不是最新版，提醒更新
    if local_versions(player, game_key):
        print("⚠ 本地版本與伺服器不同，請先下載/更新最新版本")
    else:
        print("⚠ 尚未下載此遊戲，請先『下載/更新遊戲』")
    return False


def launch_game_client(player, game_key, version, room_id, server_ip, server_port):
    """
    啟動 game client：
    - 解壓縮 zip（若尚未解壓）
    - 尋找 game_client.py
    - 使用 subprocess.Popen 啟動，將 server_ip/server_port/room_id 當作參數
    """
    runtime_dir = ensure_game_unzipped_for_player(player, game_key, version)
    if not runtime_dir:
        print("⚠ 尚未下載此遊戲或 zip 檔案遺失，請先『下載遊戲』")
        return

    client_script = os.path.join(runtime_dir, "game_client.py")
    if not os.path.exists(client_script):
        print(f"⚠ 找不到 game_client.py（{runtime_dir}）")
        return

    print(f"▶ 啟動 game client：房間 {room_id}, 遊戲 {game_key}, {version}")
    print(f"   連線到 game server: {server_ip}:{server_port}")

    # 使用 blocking run，讓玩家可以直接在同一個終端互動，遊戲結束後再回到大廳
    subprocess.run(
        ["python", client_script,
         "--server_ip", server_ip,
         "--server_port", str(server_port),
         "--room_id", str(room_id)],
        cwd=runtime_dir
    )
    print("🎮 遊戲結束，回到房間/大廳")


# ========= 房間相關：列表 / 建立 / 加入 / 離開 / 刪除 =========
def list_rooms(player, show=True):
    res = send_request({"action": "list_rooms"})
    if not res or res["status"] != "ok":
        print("❌ 無法取得房間列表")
        return []

    rooms = res["rooms"]
    if show:
        print("\n=== 房間列表 ===")
        if not rooms:
            print("（目前沒有房間）")
        for r in rooms:
            mark = "★" if player in r.get("players", []) else " "
            print(f"{mark} Room {r['room_id']} - {r['game']} v{r['version']} | 玩家: {', '.join(r['players'])} | 建立者: {r.get('creator','')}")
    return rooms


def current_room_on_server(player):
    """
    向 server 查詢玩家所在房間（避免本地狀態與 server 不一致）
    """
    rooms = list_rooms(player, show=False)
    for r in rooms:
        if player in r.get("players", []):
            return r
    return None


def list_online_players():
    res = send_request({"action": "list_players"})
    if not res or res.get("status") != "ok":
        print("❌ 無法取得玩家列表")
        return
    players = res["players"]
    print("\n=== 線上玩家 ===")
    if not players:
        print("（目前無人在線）")
    else:
        for p in players:
            print("-", p)


def create_room(player, current_room_id):
    server_room = current_room_on_server(player)
    if server_room:
        print("⚠ 你已在房間內，請先離開再建立新房間")
        return server_room["room_id"], server_room

    games = view_games()
    if not games:
        return None

    try:
        idx = int(input("請選擇要遊玩的遊戲編號: ")) - 1
        game = games[idx]
    except:
        print("❌ 無效輸入")
        return None

    req = {
        "action": "create_room",
        "player": player,
        "game_key": game["game_key"],
        "version": game["latest_version"]
    }

    if not has_latest_version(player, game["game_key"], game["latest_version"]):
        print("❌ 建立房間前請先下載/更新遊戲")
        return None

    res = send_request(req)
    if not res or res["status"] != "ok":
        print("❌ 建立房間失敗：", (res or {}).get("message",""))
        return None

    room = res["room"]
    room_id = room["room_id"]

    print(f"📣 房間建立成功：Room {room_id}, 遊戲 {room['game']} ({room['version']})")
    print("   房主可按『開始遊戲』啟動 game server，所有玩家再按『啟動遊戲 client』進入。")

    return room_id, room


def join_room(player, current_room_id):
    server_room = current_room_on_server(player)
    if server_room:
        print("⚠ 你已在房間內，請先離開再加入其他房間")
        return server_room["room_id"], server_room

    rooms = list_rooms(player)
    if not rooms:
        return None

    try:
        rid = int(input("輸入要加入的房間編號: "))
    except:
        print("❌ 無效輸入")
        return None

    res = send_request({
        "action": "join_room",
        "player": player,
        "room_id": rid
    })
    if not res or res["status"] != "ok":
        print("❌ 無法加入房間：", (res or {}).get("message",""))
        return None

    room = res["room"]

    if not has_latest_version(player, room["game"], room["version"]):
        print("❌ 請先下載/更新該遊戲最新版本，再啟動 client")
        return room["room_id"], room

    print(f"✅ 已加入 Room {room['room_id']}，玩家：{', '.join(room['players'])}")
    print("   等房主按『開始遊戲』啟動 server，之後再選『啟動遊戲 client』進入。")
    return room["room_id"], room


def leave_room(player):
    res = send_request({
        "action": "leave_room",
        "player": player
    })
    if not res or res["status"] != "ok":
        print("❌ 離開房間失敗：", (res or {}).get("message",""))
        return False

    print("✅ 已離開房間")
    return True


def delete_room(player, current_room_id):
    rooms = list_rooms(player, show=False)
    if not rooms:
        print("⚠ 沒有房間可以刪除")
        return False

    # 若目前在房間，預設刪除當前房間，否則讓使用者輸入
    target_id = current_room_id
    if target_id is None:
        try:
            target_id = int(input("輸入要刪除的房間編號: "))
        except:
            print("❌ 無效輸入")
            return False

    res = send_request({
        "action": "delete_room",
        "player": player,
        "room_id": target_id
    })
    if not res or res["status"] != "ok":
        print("❌ 刪除失敗：", (res or {}).get("message",""))
        return False

    print("✅ 已刪除房間")
    return True


def start_room(player, current_room_id):
    room = current_room_on_server(player)
    if not room or room["room_id"] != current_room_id:
        print("⚠ 你目前不在房間或房號不同")
        return False
    if room.get("creator") != player:
        print("⚠ 只有房主可以開始遊戲")
        return False

    res = send_request({
        "action": "start_room",
        "player": player,
        "room_id": room["room_id"]
    })
    if not res or res["status"] != "ok":
        print("❌ 無法開始遊戲：", (res or {}).get("message",""))
        return False

    room = res["room"]
    print(f"✅ 遊戲已啟動，房間 {room['room_id']} 伺服器埠 {room['server_port']}")
    # 房主按開始後直接啟動自己的 client
    launch_game_client(player, room["game"], room["version"], room["room_id"],
                       server_ip=LOBBY_IP, server_port=room["server_port"])
    return True


def launch_client(player, current_room_id):
    room = current_room_on_server(player)
    if not room or room["room_id"] != current_room_id:
        print("⚠ 你目前不在房間或房號不同")
        return False
    if not room.get("started"):
        print("⚠ 房主尚未開始遊戲")
        return False
    launch_game_client(player, room["game"], room["version"], room["room_id"],
                       server_ip=LOBBY_IP, server_port=room["server_port"])
    return True


def room_menu(player, current_room_id):
    """
    房間操作：列出房間、建立、加入、離開、刪除
    回傳更新後的 current_room_id
    """
    while True:
        # 同步實際房間狀態，避免前一次異常導致本地狀態不同步
        server_room = current_room_on_server(player)
        if server_room:
            current_room_id = server_room["room_id"]
        elif current_room_id and not server_room:
            current_room_id = None

        print("\n=== 房間操作 (P3) ===")
        print("1. 查看房間列表")
        print("2. 建立房間並啟動遊戲")
        print("3. 加入房間")
        print("4. 房主開始遊戲（啟動 server）")
        print("5. 啟動遊戲 client 連線")
        print("6. 離開目前房間")
        print("7. 刪除房間（僅建立者）")
        print("8. 返回")
        choice = input("選擇操作: ")

        if choice == "1":
            list_rooms(player)
        elif choice == "2":
            result = create_room(player, current_room_id)
            if result is not None:
                current_room_id, _ = result
        elif choice == "3":
            result = join_room(player, current_room_id)
            if result is not None:
                current_room_id, _ = result
        elif choice == "4":
            # 房主啟動遊戲 server
            if start_room(player, current_room_id):
                # start 成功後保持在房間
                current_room_id = current_room_id
        elif choice == "5":
            # 啟動自己的 game client
            launch_client(player, current_room_id)
        elif choice == "6":
            if leave_room(player):
                current_room_id = None
        elif choice == "7":
            if delete_room(player, current_room_id):
                # 若刪除的是自己所在房間，一併清空狀態
                current_room_id = None
        elif choice == "8":
            return current_room_id
        else:
            print("❌ 無效輸入")



# ========= P4：遊戲評分與留言 =========
def rate_game(player):
    games = view_games()
    if not games:
        return

    try:
        idx = int(input("請選擇要評分的遊戲編號: ")) - 1
        game = games[idx]
    except:
        print("❌ 無效輸入")
        return

    game_key = game["game_key"]

    # 先看詳細資訊（包含現有評價）
    detail = send_request({
        "action": "get_game_detail",
        "game_key": game_key
    })

    if not detail or detail["status"] != "ok":
        print("❌ 無法取得遊戲詳細資訊")
        return

    print(f"\n=== {detail['name']} 詳細資訊 ===")
    print("作者:", detail["developer"])
    print("簡介:", detail["description"])
    if detail["avg_score"] is not None:
        print(f"平均評分: ★ {detail['avg_score']:.2f} ({detail['rating_count']} 則)")
    else:
        print("尚無評分")

    if detail["comments"]:
        print("\n最近幾則評論：")
        for c in detail["comments"]:
            print(f"- {c['player']}：★{c['score']} - {c['comment']}")

    # 讓玩家輸入自己的評分
    try:
        score = int(input("\n請輸入評分（1~5）: "))
    except:
        print("❌ 分數格式錯誤")
        return

    comment = input("請輸入留言（可留空）: ")

    res = send_request({
        "action": "submit_rating",
        "player": player,
        "game_key": game_key,
        "score": score,
        "comment": comment
    })

    if not res:
        print("❌ 無回應")
    elif res["status"] != "ok":
        print("❌ 評分失敗：", res["message"])
    else:
        print("✅ 評分成功")


# ========= Plugin：查看可用 Plugin 清單（PL1） =========
def plugin_list(player):
    res = send_request({"action": "get_plugins"})
    if not res or res["status"] != "ok":
        print("❌ 無法取得 plugin 列表")
        return

    available = res["plugins"]
    installed = load_installed_plugins(player)

    print("\n=== Plugin 列表 ===")
    for idx, p in enumerate(available):
        status = "已安裝" if p["id"] in installed else "未安裝"
        print(f"{idx+1}. {p['name']} ({p['id']}) v{p['version']} [{status}]")
        print(f"    {p['description']}")


# ========= Plugin：安裝 / 移除（PL2） =========
def plugin_manage(player):
    while True:
        print("\n=== Plugin 管理 ===")
        print("1. 查看 Plugin 清單")
        print("2. 安裝 Plugin")
        print("3. 移除 Plugin")
        print("4. 返回")

        c = input("選擇操作: ")
        if c == "1":
            plugin_list(player)
        elif c == "2":
            install_plugin(player)
        elif c == "3":
            remove_plugin(player)
        elif c == "4":
            break
        else:
            print("❌ 無效輸入")


def install_plugin(player):
    res = send_request({"action": "get_plugins"})
    if not res or res["status"] != "ok":
        print("❌ 無法取得 plugin 列表")
        return

    available = res["plugins"]
    installed = load_installed_plugins(player)

    print("\n=== 可安裝 Plugin ===")
    for idx, p in enumerate(available):
        status = "已安裝" if p["id"] in installed else "未安裝"
        print(f"{idx+1}. {p['name']} ({p['id']}) [{status}]")

    try:
        idx = int(input("選擇要安裝的 Plugin 編號: ")) - 1
        p = available[idx]
    except:
        print("❌ 無效輸入")
        return

    installed.add(p["id"])
    save_installed_plugins(player, installed)
    print(f"✅ 已安裝 Plugin：{p['name']}")


def remove_plugin(player):
    installed = load_installed_plugins(player)
    if not installed:
        print("目前沒有安裝任何 Plugin")
        return

    installed_list = list(installed)
    print("\n=== 已安裝 Plugin ===")
    for idx, pid in enumerate(installed_list):
        print(f"{idx+1}. {pid}")

    try:
        idx = int(input("選擇要移除的 Plugin 編號: ")) - 1
        pid = installed_list[idx]
    except:
        print("❌ 無效輸入")
        return

    installed.remove(pid)
    save_installed_plugins(player, installed)
    print(f"✅ 已移除 Plugin：{pid}")


# ========= Plugin：房間聊天（PL3 / PL4） =========
def room_chat_ui(player, current_room_id):
    """
    這個 UI 只會在玩家：
    1. 已安裝 room_chat plugin
    2. 手動選擇進入「房間聊天」
    時被呼叫。

    沒有安裝的人完全不會呼叫這個功能 → PL4 保證不受影響。
    """
    if current_room_id is None:
        print("⚠ 你目前不在任何房間內")
        return

    installed = load_installed_plugins(player)
    if "room_chat" not in installed:
        print("⚠ 你沒有安裝 room_chat Plugin")
        return

    while True:
        # 確認仍在房間，避免房間被清除後還留著舊 ID
        server_room = current_room_on_server(player)
        if not server_room or server_room["room_id"] != current_room_id:
            print("⚠ 你目前不在任何房間或房間已被移除")
            return

        print(f"\n=== 房間聊天（Room {current_room_id}） ===")
        print("1. 查看訊息")
        print("2. 傳送訊息")
        print("3. 返回")
        c = input("選擇操作: ")

        if c == "1":
            res = send_request({
                "action": "room_chat_fetch",
                "room_id": current_room_id,
                "player": player
            })
            if res and res["status"] == "ok":
                msgs = res["messages"]
                if not msgs:
                    print("（沒有訊息）")
                else:
                    for m in msgs:
                        print(f"{m['player']}: {m['message']}")
            else:
                print("❌ 無法取得訊息：", (res or {}).get("message", ""))

        elif c == "2":
            msg = input("輸入訊息：")
            res = send_request({
                "action": "room_chat_send",
                "room_id": current_room_id,
                "player": player,
                "message": msg
            })
            if res and res["status"] == "ok":
                print("✅ 已送出")
            else:
                print("❌ 傳送失敗：", (res or {}).get("message", ""))

        elif c == "3":
            break
        else:
            print("❌ 無效輸入")


# ========= 主選單 =========
def main_menu(player):
    current_room_id = None  # 用來記錄玩家最近建立/加入的房間 ID

    while True:
        print("\n=== Player 大廳 ===")
        print("1. 瀏覽遊戲商城 (P1)")
        print("2. 查看線上玩家")
        print("3. 下載/更新遊戲 (P2)")
        print("4. 房間列表 / 建立 / 加入 / 離開 (P3)")
        print("5. 對遊戲評分與留言 (P4)")
        print("6. Plugin 管理 (PL1~PL2)")
        print("7. 房間聊天 (PL3, 需 room_chat Plugin)")
        print("8. 離開")

        c = input("選擇操作: ")
        if c == "1":
            view_games()
        elif c == "2":
            list_online_players()
        elif c == "3":
            download_game(player)
        elif c == "4":
            current_room_id = room_menu(player, current_room_id)
        elif c == "5":
            rate_game(player)
        elif c == "6":
            plugin_manage(player)
        elif c == "7":
            room_chat_ui(player, current_room_id)
        elif c == "8":
            send_request({"action":"player_logout","name":player})
            break
        else:
            print("❌ 無效輸入")


def login_flow():
    print("=== 玩家帳號 ===")
    print("1. 登入")
    print("2. 註冊並登入")
    choice = input("選擇: ")
    player = input("玩家名稱: ").strip()
    pwd = input("密碼: ").strip()
    if not player or not pwd:
        print("帳號/密碼不可為空")
        return None
    action = "player_login" if choice == "1" else "player_register"
    res = send_request({"action": action, "name": player, "password": pwd})
    if not res or res.get("status") != "ok":
        print("❌", (res or {}).get("message","登入/註冊失敗"))
        return None
    return player


if __name__ == "__main__":
    configure_lobby_endpoint()

    player = login_flow()
    if not player:
        exit(1)

    # 確保下載資料夾存在
    os.makedirs(os.path.join(BASE_DIR, "downloads", player), exist_ok=True)

    stop_hb = threading.Event()
    hb_thread = threading.Thread(target=heartbeat_loop, args=(player, stop_hb), daemon=True)
    hb_thread.start()

    try:
        main_menu(player)
    finally:
        stop_hb.set()
        hb_thread.join(timeout=1)
