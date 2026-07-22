# 資料工程師 Take-home — 考題資料包

請先閱讀隨附的考題卷（`prd.md`），本 README 僅說明資料包內容。

## 內容

```
candidate_package/
├── buggy_pipeline.py    ← Part B 審查標的（不需執行）
├── dataset/
│   ├── orders_base.csv               訂單初始全量（2026-05-01 ~ 2026-06-30）
│   ├── orders_incremental_day1.csv   每日增量（2026-07-01）
│   ├── orders_incremental_day2.csv   每日增量（2026-07-02）
│   ├── orders_incremental_day3.csv   每日增量（2026-07-03）
│   ├── members.csv                   會員每日快照萃取
│   ├── products.csv                  行程產品主檔
│   └── fx_rates.csv                  每日匯率（對 TWD）
├── module_D/            ← 進階模組 D（效能工程）：generate_perf_data.py＋baseline_etl.py
│                           ※ 測試資料請執行生成器於本地產生（約 1.5GB，請預留空間）
├── module_E/            ← 進階模組 E（LLM 評分守門）：warehouse/＋questions.json＋llm_answers.json
└── module_F/            ← 進階模組 F（特徵管線除錯）：churn_training_pipeline.py（讀 ../dataset）
```

> 進階模組 **D／E／F 三選一**，規則詳見考題卷。

## 欄位說明

**orders_*.csv**：`order_id`, `member_id`, `product_id`, `channel`, `order_status`（created/paid/completed/cancelled）, `quantity`, `currency`, `amount`（原幣別金額）, `coupon_discount`（TWD）, `order_created_at`, `departure_date`, `updated_at`

- 增量檔中同一 `order_id` 可能出現多次（狀態更新事件），以 `updated_at` 區分新舊。

**members.csv**：`member_id`, `member_name`, `member_level`（一般/銀卡/金卡/白金）, `city`, `birth_date`, `register_date`, `extract_date`（快照萃取日）

**products.csv**：`product_id`, `product_name`, `product_type`, `destination_country`, `destination_city`, `trip_days`, `base_price_twd`, `is_active`

**fx_rates.csv**：`rate_date`, `currency`, `rate_to_twd`

## 提醒

- 資料為合成資料，模擬真實上游系統的輸出——**包含真實世界會有的各種狀況**。資料品質狀況即為題目的一部分。
- 引擎不限：pandas / PySpark / DuckDB / 任何 SQL 皆可。
- 你的繳交物需附說明文件（README；Word 或 Markdown 皆可），讓閱卷者能在 30 分鐘內重現結果。
