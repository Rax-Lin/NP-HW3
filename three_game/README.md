# Three-Player Attack/Reflect Game

## 規則概要
- 三位玩家同局，每回合各自選擇「攻擊」或「反彈」，並指定單一目標。
- 攻擊/反彈判定：
  - 若 A 攻擊 B，且 B 沒有反彈向 A → B 死。
  - A、B 互相攻擊 → 兩人都死。
  - B 反彈向 A，且只有 A 攻擊 B → A 死，B 活。
  - 若多人同時攻擊 B，B 只反彈其中一人：被反彈的攻擊者死，B 仍會被其他攻擊擊殺。
  - 可能出現三人同死。
- 回合結束後，存活者各得 1 分。
- 先達 3 分且為唯一最高分者勝出，若平手持續下一回合。

## 檔案
- `game_server.py`：遊戲伺服器，等待 3 玩家連線，處理回合邏輯並廣播結果。
- `game_client.py`：Tkinter GUI 客戶端，點擊目標（兩個藍/紅圓代表其他玩家），選 Attack/Reflect 並 Confirm。

## 啟動（獨立測試）
在兩個以上終端：
1. 伺服器  
   ```bash
   python game_server.py --port 8000 --room_id 1
   ```
2. 玩家端（需三個，各自取名）  
   ```bash
   python game_client.py --server_ip 127.0.0.1 --server_port 8000 --name Alice
   python game_client.py --server_ip 127.0.0.1 --server_port 8000 --name Bob
   python game_client.py --server_ip 127.0.0.1 --server_port 8000 --name Carol
   ```

## 上架說明
打包上架時，將 `game_server.py`、`game_client.py`（及其他資源）打成 zip，透過開發者端上架；玩家端下載後即可在房間啟動此遊戲。預設勝利分數為 3。  
