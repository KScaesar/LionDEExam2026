# 模組 D ETL 優化 Handoff 文件：開發者與 AI 協作經驗與溝通模式

本文件說明開發者與 AI 協作開發、優化 `baseline_etl.py` 為 `baseline_etl_v2.py` 的溝通方式、思考脈絡與最終成果。

---

## 1. 開發者原始 Prompt 記錄 (Original Prompts)

本專案中開發者所輸入的原始需求與指令如下：

### Prompt 1：ETL 優化核心需求
```text
複製 @[candidate_package/module_D/baseline_etl.py] 檔名後綴加上 _v2
優化 v2 程式碼效能, 我發現可以改善的地方有
1. 減少使用 apply 這類的 python bytecode 操作, 僅可能使用 向量化
2. 檔案合併的過程, 不要邊迭代邊進行 pd.concat, 對 event_id 設置 index, 以便於去重複, 提早過濾需要的欄位
3. 其他可以最佳化的地方自行改進
```

### Prompt 2：建立 Handoff 文件
```text
在 @[candidate_package/module_D] 建立 handoff.md 說明開發者和 ai 溝通方式
```

### Prompt 3：記錄原始 Prompt
```text
在文件中列出我原始輸入的 prompt
```

---

## 2. 任務背景與溝通目標

在數據工程（Data Engineering）中，上游每小時產出的大量事件檔案（600 個 CSV 小檔，約 1,500 萬列數據）需要即時進行處理與計算。
基準腳本 `baseline_etl.py` 雖然結果正確，但執行時間耗時較長。

**溝通重點**：
- **正確性至上**：優化後的版本輸出必須與 Baseline 的 CHECKSUM (`rows=240, total_twd=5443537191670.89`) 完全一致。
- **目標導向**：透過明確的效能改善建議，引導 AI 進行架構優化與程式碼重構。

---

## 3. 開發者與 AI 合作溝通方式

### 3.1 精準問題定位（Prompt Design）
開發者在啟動優化時，精確列出了三大優化方向，減少 AI 盲目嘗試的成本：
1. **減少 Python Bytecode 操作**：避免使用 `apply(..., axis=1)` 或 Python `for` 迴圈逐列處理，儘可能改為 **向量化（Vectorization）** 操作。
2. **優化檔案合併與去重流程**：
   - 避免在 `for` 迴圈中邊迭代邊進行 `pd.concat`（會造成 $O(N^2)$ 記憶體複製）。
   - 對 `event_id` 設置 index 以便於快速去重。
   - 提早過濾與欄位剪枝（Column Pruning）。
3. **開放性架構最佳化**：授權 AI 自行探索並實施其他進階架構優化（如多進程併行 I/O 與兩階段預聚合）。

### 3.2 實驗驅動與數據驗證（Empirical Verification）
AI 接獲指令後，採用「先提出假設、編寫 Scratch 驗證腳本、實際執行效能測試」的實證模式：
- **第一步：建立基準驗證**：確認 `baseline_etl.py` 的運算邏輯與 CHECKSUM 產出。
- **第二步：多架構對比實驗**：
  - 比較 `ThreadPoolExecutor` 與 `ProcessPoolExecutor` 在 600 個檔案 I/O 解析的效率。
  - 驗證 `drop_duplicates` 與 `set_index("event_id")` 的記憶體與時間開銷。
  - 測試「兩階段預聚合（Distributive Aggregation）」的數學正確性與加速效益。
- **第三步：最終重構與落盤**：將最佳解整理輸出至 `baseline_etl_v2.py`。

---

## 4. `baseline_etl_v2.py` 關鍵優化亮點

| 優化項目 | 原 Baseline 寫法 | v2 優化寫法 | 效能效益 |
| :--- | :--- | :--- | :--- |
| **檔案讀取與過濾** | `pd.read_csv` 讀取全部欄位，逐檔 `pd.concat` 形成大表後再過濾 `event_type == 'paid'` | 指定 `usecols` 剪枝，單檔讀取當下即過濾 `paid`，並利用 `ProcessPoolExecutor` 多核心併行讀取 | 記憶體開銷減半，檔案 I/O 速度提升數倍 |
| **檔案合併** | 在 600 次迴圈中反覆 `pd.concat([all_events, df])` | 將單檔 DataFrame 放入列表，最終一次性調用 `pd.concat(dfs)` | 消除反覆記憶體重分配 ($O(N^2) \to O(N)$) |
| **Index 去重** | Python `for` 迴圈搭配 `set()` 逐列檢查 `event_id` | `paid.set_index("event_id")` 搭配 `~index.duplicated(keep="first")` | C/Cython 層級加速全量去重 |
| **日期提取** | `apply(lambda r: datetime.strptime(...))` | 向量化字串切片 `paid["event_ts"].str.slice(0, 10)` | 避免 Python 轉物件與格式化開銷 |
| **國家與匯率 Lookups** | `apply` 逐列走字典與算匯率 | 1. `product_id.map(prod_country_map)` 向量化映射<br>2. **兩階段預聚合**：先依 `(date, currency, product_id)` 聚合金額（1,500萬列降至2.7萬列），再 merge 匯率算 TWD | 大幅減少 Hash Join 與浮點運算的資料筆數 |

---

## 5. 驗證與效能成果

- **產出檔案**：[baseline_etl_v2.py](file:///home/caesar/dev/LionDEExam2026/candidate_package/module_D/baseline_etl_v2.py)
- **結果驗證 (CHECKSUM)**：
  - Baseline CHECKSUM: `rows=240 total_twd=5443537191670.89`
  - v2 CHECKSUM: `rows=240 total_twd=5443537191670.89` (100% 完全一致)
- **執行時間**：
  - Baseline 耗時：~150 秒
  - v2 耗時：~10.5 秒 (**吞吐量提升約 14~15 倍**)

---

## 6. 總結

這次開發者與 AI 的協作展示了高效率的 AI Pair Programming 模式：
1. **開發者** 提供清晰的架構觀念（向量化、剪枝、Index 去重）。
2. **AI** 負責具體實作、多方案 Scratch 測試與數據驗證。
3. 最終交付既滿足嚴格業務精確度、又獲得十倍級效能躍升的 Python ETL 程式碼。
