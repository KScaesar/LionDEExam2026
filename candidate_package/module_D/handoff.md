# 模組 D ETL 優化 Handoff 文件

600 個 CSV 小檔（約 1,515 萬列事件數據）。基準腳本 `baseline_etl.py` 結果正確但執行時間過長，需要在**不改變輸出結果**的前提下優化效能。

本文件說明 `baseline_etl.py`（v1）→ `baseline_etl_v2.py`（v2）→ `baseline_etl_v3.py`（v3）三個版本各自做了什麼優化、為什麼做、以及實測結果。

**正確性基準**：`rows=240 total_twd=5443537191670.89`

## 優化預測

動手改之前先通讀 baseline，歸納出以下優化方向（即後續 [Prompt 1] 內容）。

### 優化預測表

| # | 我打算做的優化 | 依據重點 | 預期加速倍數 |
| :-- | :-- | :-- | :-- |
| 1 | 減少 `apply` 逐列操作，改向量化運算 | `apply` 逐列觸發 Python function call，無法走 C 語言的批次運算 | 未估算 |
| 2 | 並行讀取檔案，避免 I/O 等待 | 600 個小檔讀取為 I/O bound，讀檔彼此獨立可平行發起、疊等待時間 | 未估算 |
| 3 | 避免邊迭代邊 `pd.concat`；`event_id` 建 index 去重；提早剪枝欄位 | 迴圈內 `pd.concat` 是 $O(N^2)$ 記憶體搬移；剪枝減少 IO/記憶體 | 未估算 |
| 4 | 其他可自行改進之處（開放給 AI） | 未逐一拆解完 baseline 所有問題（如日期解析、匯率 join），交由 AI 自行判斷 | 無預期 |

**誠實說明**：預測表只做到定性列出瓶頸與原理，**沒有給出具體加速倍數**。

## AI 與開發者互動：出錯、修正與不採納

- **AI 選的 multiprocessing 不如預期**：
  Prompt 1 只要求「並行讀取」，我原本預期是 `asyncio` 或 multithreading（本質是 I/O 問題，multiprocessing 本來就不是拿來解決 I/O 的工具），但 AI 選了 `ProcessPoolExecutor`，行程建立＋序列化開銷讓它成為 v2 最大瓶頸（讀檔＋過濾 5.39s，佔 51.7%）；v3 改要求全面改用 `polars.scan_csv` 原生多執行緒讀取取代之，此階段降到 1.10s（-79.6%）。
- **AI 自行加的兩階段預聚合，靠道理而非量化驗證採納**：
  AI 在 Prompt 1 第 4 點自行補上先粗聚合再 join 匯率的手法，超出原始預測。我沒有另外量化驗證，只是覺得「盡可能提前減少資料筆數」這個原則說得通就採納，靠的是 CHECKSUM 與 baseline 一致確認正確性沒被破壞。

---

## 加速比總覽（各版本皆為 3 次量測取平均，`uv run`，同一環境）

| 版本 | 單次耗時 | 平均耗時 | 相對 v1 加速比 |
| :--- | :--- | :--- | :--- |
| baseline_etl.py (v1) | 178.4s / 163.9s / 160.2s | 167.5s | 1x |
| baseline_etl_v2.py (v2) | 10.70s / 10.12s / 10.40s | 10.41s | 16.1x |
| baseline_etl_v3.py (v3) | 3.43s / 1.64s / 1.67s | 2.25s | 74.5x |

CHECKSUM 三版三次量測皆一致：`rows=240 total_twd=5443537191670.89`。

**各版本主要最佳化重點：**
- **v1（基準）**：逐列 `apply`、迴圈內 `pd.concat`、Python 迴圈去重。
- **v2**：欄位剪枝＋讀檔即過濾＋多核心併行讀取；去重改 `set_index`+`duplicated`；日期/國家/匯率全面向量化＋兩階段預聚合。
- **v3**：全面改用 polars（`scan_csv` lazy 讀取＋全流程 polars 運算）；去重改 `unique()` 一步到位；依 seam 拆分 I/O／純運算函式。

以下章節說明各版本細節優化內容、原始 Prompt 與各階段耗時分解。

---

## 原始 Prompt 記錄

Prompt 1：ETL 優化核心需求
```text
複製 @[candidate_package/module_D/baseline_etl.py] 檔名後綴加上 _v2
優化 v2 程式碼效能, 我發現可以改善的地方有
1. 減少使用 apply 這類的 python bytecode 操作, 使用 向量化 運算
2. 並行讀取檔案, 避免不必要的 io 等待
3. 檔案合併的過程, 不要邊迭代邊進行 pd.concat, 對 event_id 設置 index, 以便於去重複, 提早過濾需要的欄位
4. 其他可以最佳化的地方自行改進
```

---

Prompt 2：建立 Handoff 文件
```text
在 @[candidate_package/module_D] 建立 handoff.md 說明開發者和 ai 溝通方式
```

---

Prompt 3：新增觀測性、比較新環境下兩版本耗時
```text
在 v2 加上耗時觀測點，我想知道 v2 主要瓶頸在什麼地方：io、cpu、join？
我目前在新的工作環境，用 uv run 分別執行 baseline 與 v2 兩個版本，比較實際花費時間，
並整理成對比表。
```

---

Prompt 4：複製為 v3，針對 v2 觀測到的瓶頸繼續優化
```text
複製 v2 為 v3：
1. 徹底移除 pandas，全改用 polars，嘗試改善 I/O 瓶頸
2. event_id 去重，移除不必要的操作
3. 對 v3 進行函數封裝並加上註解說明，以 seam（測試接縫）為概念拆分 I/O 與純運算，方便日後單元測試與維護

v3 完成後立刻執行，查看每個階段的耗時是否縮短。
```

---

## v1：`baseline_etl.py`（基準版本）

**寫法特徵：**
- 逐檔 `pd.read_csv` 讀取全部欄位，for 迴圈中反覆 `pd.concat` 合併。
- 讀完後才用 `event_type == 'paid'` 過濾，沒有欄位剪枝。
- `event_id` 去重用 Python `for` 迴圈搭配 `set()` 逐列檢查。
- 日期提取、國家 lookup、匯率換算皆用 `apply(lambda r: ...)` 逐列處理。

**實測結果（`uv run`，3 次量測取平均）：**
- 單次耗時：178.4s / 163.9s / 160.2s → **平均 167.5s**
- CHECKSUM 三次皆一致：`rows=240 total_twd=5443537191670.89`（作為對照組，後續加速比皆以平均值 167.5s 為 1x 基準）

---

## v2：`baseline_etl_v2.py`

對應 Prompt 1，做了以下優化：

- **檔案讀取與過濾**：指定 `usecols` 欄位剪枝，單檔讀取當下即過濾 `paid`，並用 `ProcessPoolExecutor` 多核心併行讀取（原本讀全部欄位、逐檔 concat 後才過濾）。
- **檔案合併**：單檔結果先放入 list，最後一次性 `pd.concat(dfs)`（原本在迴圈中反覆 `pd.concat([all_events, df])`，造成 $O(N^2)$ 記憶體重分配）。
- **event_id 去重**：改用 `set_index("event_id")` + `~index.duplicated(keep="first")`（原本 Python `for` 迴圈 + `set()` 逐列檢查）。
- **日期提取**：向量化字串切片 `event_ts.str.slice(0, 10)`（取代 `apply(lambda r: datetime.strptime(...))`）。
- **國家與匯率換算**：`product_id.map(prod_country_map)` 向量化映射；並採用兩階段預聚合——先依 `(date, currency, product_id)` 聚合金額（1,500 萬列→2.7 萬列），再 merge 匯率算 TWD，大幅減少 join 與浮點運算筆數（取代逐列 `apply` 查字典算匯率）。
- **可觀測性**（對應 Prompt 3）：在 `main()` 加入 `mark(label)` 打點，記錄各階段耗時與類型（如 `io+cpu`、`join`），用來定位瓶頸。

**實測結果（`uv run`，600 檔 / 1,515 萬列，3 次量測取平均，CHECKSUM 三次皆與 v1 一致）：**
- 單次耗時：10.70s / 10.12s / 10.40s → **平均 10.41s**（相對 v1 平均加速約 **16.1x**）
- 各階段耗時分解：

| 階段 | 3 次量測 | 平均耗時 | 佔比 | 類型 |
| :--- | :--- | :--- | :--- | :--- |
| 多進程讀檔＋過濾 | 5.564 / 5.221 / 5.374 | 5.39s | 51.7% | I/O 為主 |
| event_id 去重（set_index + duplicated） | 4.545 / 4.405 / 4.547 | 4.50s | 43.2% | CPU |
| 一級預聚合（groupby） | 0.552 / 0.458 / 0.447 | 0.49s | 4.7% | CPU |
| concat 合併 | 0.018 / 0.017 / 0.019 | 0.018s | 0.17% | CPU/記憶體 |
| 其餘（讀 ref、列檔、國家 map、fx merge/join、二級聚合、寫檔） | — | <0.01s | <0.1% | 可忽略 |
- **瓶頸結論**：join 不是瓶頸（fx 匯率 merge 平均僅 0.0053s，因兩階段預聚合已把 1,500 萬列縮小到 2.7 萬列才 join）。真正瓶頸依序為 **I/O（約 52%）> 去重 CPU（約 43%）> 預聚合 CPU（約 5%）**，三者合計逾 99%。此結論直接引導了 v3 的優化方向。

---

## v3：`baseline_etl_v3.py`

對應 Prompt 4，延續 v2 的瓶頸結論（I/O 55% > 去重 CPU 36%），做了以下優化：

- **讀檔**：改用 `polars.scan_csv` 原生多執行緒讀取＋lazy 欄位剪枝/過濾，取代 v2 的 `ProcessPoolExecutor` + pandas 逐檔讀取後 concat，目的是降低 I/O 瓶頸。
- **去重**：改用 `unique(subset=["event_id"], keep="first")` 一步到位，取代 v2 的 `set_index` + `duplicated()` + `reset_index()`，移除不必要的 index 建構/拆除操作。
- **運算引擎**：全流程改用 polars（groupby/join/寫檔皆不再轉 pandas），徹底移除 pandas 依賴，省去 `to_pandas()` 轉換開銷。
- **程式結構**：拆成 I/O 邊界函式（`read_reference_data` / `list_event_files` / `read_and_filter_events` / `write_result`）與純轉換函式（`dedup_events` / `pre_aggregate` / `join_country` / `join_fx_and_calc_revenue` / `final_aggregate`），以 seam 概念切開 I/O 與純運算，方便單元測試與維護。
- **註解**：在 `pre_aggregate` / `final_aggregate` 補上「為什麼要做兩階段聚合」的說明（SUM 可分配性、product_id→country 多對一需二次收斂），降低後續維護者的理解成本。

**實測結果（`uv run`，600 檔 / 1,515 萬列，3 次量測取平均，CHECKSUM 三次皆與 v1/v2 一致）：**
- 單次耗時：3.43s / 1.64s / 1.67s → **平均 2.25s**（相對 v1 平均加速約 **74.5x**）
  - 第一次量測 (3.43s) 明顯偏高，推測是 OS 檔案快取尚未預熱（read_filter 1.95s、dedup 1.33s）；第二、三次快取已熱後穩定在 1.6~1.7s 區間（read_filter ~0.67s、dedup ~0.85s）。
- 各階段耗時分解：

| 階段 | 3 次量測 | 平均耗時 | 佔比 | 類型 |
| :--- | :--- | :--- | :--- | :--- |
| polars 讀檔＋過濾 | 1.950 / 0.671 / 0.666 | 1.10s | 48.8% | I/O 為主 |
| event_id 去重（unique） | 1.327 / 0.824 / 0.885 | 1.01s | 45.0% | CPU |
| 一級預聚合＋國家 join＋fx join＋二級聚合＋寫檔 | — | 0.13s | 5.5% | CPU（皆已縮小到 2.7 萬列規模） |
- **對照 v2 平均值**：讀檔階段從 5.39s 降到約 1.10s（**-79.6%**），去重從 4.50s 降到約 1.01s（**-77.5%**）。I/O 與去重仍是前兩大占比，但絕對耗時已大幅縮短。
