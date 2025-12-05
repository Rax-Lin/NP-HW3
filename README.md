# Game Store System (Developer / Lobby / Sample Games)

## 環境需求
- Python 3.8+
- 不需額外套件（僅標準庫）

## 啟動方式（最少步驟）
在專案根目錄：
```bash
# 1. Lobby Server
bash start_lobby_server.sh
# 2. Developer Server
bash start_developer_server.sh
# 3. Developer Client（上架/更新）
bash start_developer_client.sh
# 4. 玩家 Client（下載/建房/聊天/遊玩）
bash start_player_client.sh
```
> 若腳本無執行權限，先執行 `chmod +x start_*.sh`

## 帳號註冊/登入範例
- Developer / Player 第一次啟動時可直接選「註冊並登入」，帳號/密碼自訂，例如帳號 `Rax` 密碼 `Rax`。
- 登入後可用選單操作；若異常中斷，下次登入會自動覆蓋舊 Session。

## 打包與上架遊戲
- 每款遊戲 zip 至少包含 `game_server.py`、`game_client.py`（可加資源/config）。
- 範例：
  - CLI 雙人：`sample_game/`
  - GUI 雙人剪刀石頭布：`gui_game/`
  - 三人攻防：`three_game/`
- 打包範例（以 GUI 為例，版本 1.0）：
  ```bash
  cd gui_game
  zip -r ../developer_client/uploaded_games/gui_rps_1.0.zip game_server.py game_client.py
  ```
- 開發者端選「上架新遊戲」並填入 zip 路徑；更新版本同理。

## 資料儲存與路徑
- 開發者 DB / 上架檔案：`developer_client/database.json`、`developer_client/uploaded_games/`
- Lobby 玩家/房間/聊天：`server/players.json`、`server/rooms.json`、`server/room_chats.json`
- 玩家下載：`player_client/downloads/{player}/`

## 工作流程
1. **Developer Server**：執行開發者 Client，註冊/登入後可上架/更新/下架。上架時提供 zip（內含 `game_server.py`、`game_client.py`）。
2. **Lobby Server**：啟動後自動讀取開發者上架的遊戲，玩家端可瀏覽/下載。
3. **玩家**：登入後可下載遊戲、建立/加入房間、啟動遊戲 client、聊天、評分。
4. **範例遊戲**：CLI（sample_game）、GUI 剪刀石頭布（gui_game）、三人攻防（three_game）可打包上架測試。

## 心跳/登入
- Developer / Player 客戶端每 30 秒送出心跳；Server 端 60 秒未收到會標記離線。
- 登入會覆蓋舊 Session，避免 Ctrl+C 殘留。

## 版本更新提示
- 建房/加房前會檢查本地是否有最新 zip，若無會提示先下載/更新。
- 建議先執行「下載/更新遊戲」確保最新版。

## 資料重置
- 可刪除以下檔案重置狀態：
  - `developer_client/database.json`
  - `server/players.json`、`server/rooms.json`、`server/room_chats.json`、`server/play_history.json`
  - `player_client/downloads/` 底下的玩家資料夾

## Error 處理
- 若client下載遊戲後，在建立或是進入房間時仍顯示遊戲尚未下載。請改成進入`developer_client/` 底下執行 `python3 developer_server.py`
- 對於部分錯誤，皆可嘗試不使用 bash, 改成進入各檔案(比如`server/`, `developer_clienter/`)下進行。
- 請確保能執行GUI (tkinter) 相關套件

## Demo 提示
- 所有操作都在選單內完成，無需額外指令。
- 輸入 `bash... `後，client 端可根據 server 端的ip位址是在本機上或是其他工作站而調整。
- 房間聊天僅同房玩家可見，房間刪除/遊戲結束會清理聊天室，且聊天功能僅下載 plugin 者可見。
- 房號分配會使用最小可用編號（補洞）。
- 上傳遊戲需包含 `game_server.py`、`game_client.py`，玩家需先下載最新版本再啟動。
- GUI 遊戲（Tkinter）需系統有安裝 `python3-tk` 並有可用的 DISPLAY（桌面/ssh -X 或虛擬顯示）；缺少這些環境時 GUI 會無法啟動。
