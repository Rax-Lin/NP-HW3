# Sample Number Guessing Game

這是一個雙人猜數字範例遊戲，用來測試你的 Lobby/Developer 流程。

## 遊戲規則
- 伺服器隨機產生 1~100 的整數。
- 需要兩個玩家連線後才開始。
- 輪到你時輸入數字，伺服器會回傳 `LOW` 或 `HIGH`，猜中者獲勝。

## 直接啟動（單機測試）
在兩個終端分別執行：
1. 啟動伺服器  
   ```bash
   python game_server.py --port 7001 --room_id 1
   ```
2. 啟動玩家端（兩個各自跑一次）  
   ```bash
   python game_client.py --server_ip 127.0.0.1 --server_port 7001 --room_id 1
   ```

## 平台整合
- 開發者端請將 `game_server.py`、`game_client.py` 打包為 zip 上傳。
- Lobby 端啟動房間後會啟動 `game_server.py`，玩家按「啟動遊戲 client」會執行 `game_client.py` 並連線到對應埠。

