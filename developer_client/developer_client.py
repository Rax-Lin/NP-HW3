import socket
import json
import threading
import os

SERVER_IP = "127.0.0.1"
SERVER_PORT_START = 5050
SERVER_PORT_MAX = 6000
HEARTBEAT_INTERVAL = 30


# ========= 連線設定 =========
def configure_dev_endpoint():
    """
    允許使用者決定 developer server IP / 掃描區間。
    也支援環境變數：
    - DEV_SERVER_IP
    - DEV_PORT_START / DEV_PORT_MAX
    """
    global SERVER_IP, SERVER_PORT_START, SERVER_PORT_MAX

    env_ip = os.environ.get("DEV_SERVER_IP", SERVER_IP)
    env_start = os.environ.get("DEV_PORT_START")
    env_max = os.environ.get("DEV_PORT_MAX")
    if env_start and env_start.isdigit():
        SERVER_PORT_START = int(env_start)
    if env_max and env_max.isdigit():
        SERVER_PORT_MAX = int(env_max)

    print("=== Developer Server 連線設定 ===")
    print(f"1. 本機 ({env_ip})")
    print("2. 自訂 IP")
    choice = input("選擇: ").strip()
    if choice == "2":
        ip = input("輸入 Developer Server IP (例如 10.1.14.12 或 140.113.17.12): ").strip()
        if ip:
            SERVER_IP = ip
    else:
        SERVER_IP = env_ip
    print(f"➡ 使用 Developer Server {SERVER_IP}，掃描埠 {SERVER_PORT_START}-{SERVER_PORT_MAX}")


def connect_to_server():
    """
    find the developer server by scanning ports
    """
    last_error = None
    for port in range(SERVER_PORT_START, SERVER_PORT_MAX + 1):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect((SERVER_IP, port))
            return s, port
        except OSError as e:
            last_error = e
            s.close()
            continue
    raise ConnectionError(f"oh oh !!!!!, can't connect to developer server: {last_error}")


def send_request(data, expect_response=True):
    """
    統一包裝 developer client <-> developer server 的連線
    - expect_response=False 用在後面需要持續傳檔案的狀況時，先送 meta
    """
    s, port = connect_to_server()
    meta = json.dumps(data).encode()
    s.sendall(len(meta).to_bytes(4, "big") + meta)

    if not expect_response:
        return s, None

    raw = s.recv(4096)
    s.close()

    try:
        return None, json.loads(raw.decode())
    except:
        return None, None


def heartbeat_loop(name, stop_event): # for fear some one use ctrl + C and interrupt to exit
    while not stop_event.wait(HEARTBEAT_INTERVAL):
        try:
            send_request({"action": "heartbeat", "name": name})
        except:
            pass


# ==========================
# D1：Upload a new game !!!!!!!!!!!!
# ==========================
def upload_game(developer):
    game_name   = input("遊戲名稱: ")
    version     = input("初始版本號 (例如 1.0): ")
    description = input("遊戲簡介: ")
    file_path   = input("請輸入遊戲 zip 檔路徑: ")

    if not os.path.exists(file_path):
        print("oh oh 檔案不存在")
        return

    meta = {
        "action":      "upload_game",
        "developer":   developer,
        "game_name":   game_name,
        "version":     version,
        "description": description
    }

    # 先送 meta，不期待馬上有 response，因為接下來要傳檔案
    s, _ = send_request(meta, expect_response=False)

    # send file
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(4096)
            if not chunk:
                break
            s.sendall(chunk)
    s.sendall(b"<END>")

    # get server response
    raw = s.recv(4096)
    s.close()
    res = json.loads(raw.decode())
    print("📣", res["message"])


# ==========================
# print your game（for D2 / D3 ）
# ==========================
def list_my_games(developer, show=True):
    _, res = send_request({
        "action": "list_my_games",
        "developer": developer
    })

    if not res or res["status"] != "ok":
        print("❌ 無法取得遊戲列表")
        return []

    games = res["games"]
    if show:
        print("\n=== My Game ===")
        for idx, g in enumerate(games):
            status = "launch" if g["active"] else "removed"
            if(status == "launch"):
                print(f"{idx+1}. {g['name']} ({g['latest_version']}) [{status}]")
                print(f"    key: {g['game_key']}")
                print(f"    {g['description']}")
            else:
                print(f"{idx+1}. {g['name']} ({g['latest_version']}) [{status}]") # the removed game will not show description and key
    return games


# ==========================
# D2 : Update an existing game
# ==========================
def update_game(developer):
    games = list_my_games(developer)
    if not games:
        print("Sorry, 目前沒有遊戲可以updated")
        return

    try:
        idx = int(input("請選擇要更新的遊戲編號: ")) - 1
        game = games[idx]
    except:
        print("❌ Not effective input")
        return

    new_version = input("新版本號 (ex. 1.1): ")
    file_path   = input("請輸入新版本 zip 檔路徑: ")
    if not os.path.exists(file_path):
        print("❌ Sorry, 檔案不存在")
        return

    meta = {
        "action":    "update_game",
        "developer": developer,
        "game_key":  game["game_key"],
        "version":   new_version
    }

    s, _ = send_request(meta, expect_response=False)

    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(4096)
            if not chunk:
                break
            s.sendall(chunk)
    s.sendall(b"<END>")

    raw = s.recv(4096)
    s.close()
    res = json.loads(raw.decode())
    print("📣", res["message"])


# ==========================
# D3： Remove a game!!
# ==========================
def remove_game(developer):
    games = list_my_games(developer)
    if not games:
        print("目前沒有遊戲可以下架!")
        return

    try:
        idx = int(input("請選擇要下架的遊戲編號: ")) - 1
        game = games[idx]
    except:
        print("❌ Sorry, 無效輸入")
        return

    confirm = input(f"確認要下架 {game['name']} 嗎？(y/n): ")
    if confirm.lower() != "y":
        print("已取消remove遊戲")
        return

    _, res = send_request({
        "action":    "remove_game",
        "developer": developer,
        "game_key":  game["game_key"]
    })

    if not res:
        print("❌ 無回應")
    else:
        print("📣", res["message"])


# ==========================
# 主選單
# ==========================
def main_menu():
    while True:
        print("=== 開發者帳號 ===")
        print("1. 登入")
        print("2. 註冊並登入")
        print("3. 說掰掰(logout)!")
        choice = input("選擇: ").strip()

        if choice == "3":
            print("bye bye!")
            return
        if choice not in {"1", "2"}:
            print("❌ 輸入錯囉朋友，請重新輸入")
            continue

        developer = input("帳號: ").strip()
        pwd = input("密碼: ").strip()
        if not developer or not pwd:
            print("帳號/密碼不可為空")
            continue

        action = "login" if choice == "1" else "register"
        _, res = send_request({"action": action, "name": developer, "password": pwd})
        if not res or res.get("status") != "ok":
            print("❌", (res or {}).get("message","登入/註冊失敗"))
            continue

        # 登入成功，啟動 heartbeat 並進入功能選單
        stop_hb = threading.Event()
        hb_thread = threading.Thread(target=heartbeat_loop, args=(developer, stop_hb), daemon=True) # used to notify server that this client is still alive
        hb_thread.start()

        while True:
            print("\n=== 開發者平台 ===")
            print("1. 上架新遊戲 (D1)")
            print("2. 更新已上架遊戲版本 (D2)")
            print("3. 下架遊戲 (D3)")
            print("4. 看看我的遊戲列表")
            print("5. 登出(bye bye)")

            choice = input("請選擇功能: ")

            if choice == "1":
                upload_game(developer)
            elif choice == "2":
                update_game(developer)
            elif choice == "3":
                remove_game(developer)
            elif choice == "4":
                list_my_games(developer, show=True)
            elif choice == "5":
                send_request({"action":"logout","name":developer})
                stop_hb.set()
                hb_thread.join(timeout=1)
                print("bye bye!\n")
                break  # 回到登入/註冊選單
            else:
                print("❌ 無效選項，請重新輸入")


if __name__ == "__main__":
    configure_dev_endpoint()
    main_menu()
