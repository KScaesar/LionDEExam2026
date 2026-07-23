# -*- coding: utf-8 -*-
"""
模組 D — Optimized ETL v2（高效能向量化與多進程處理版本）

任務：從 raw_events/ 的事件檔計算「每日 × 目的地國家」的 paid 事件營收（TWD）。
優化重點：
  1. 提早過濾與欄位剪枝：讀取 CSV 時僅載入必要欄位並在單檔層級提早過濾 event_type == 'paid'
  2. 多處理器併行讀取：使用 ProcessPoolExecutor 充分利用多核心 CPU 進行併行 I/O 解析
  3. 避免邊迭代邊 concat：將所有 DataFrame 集中於 list 中，最後一次性 pd.concat
  4. 以 event_id 設置 index 去重複：使用 set_index("event_id") 並利用 ~index.duplicated() 高效去重
  5. 全向量化處理：
     - event_date：使用字串切片 .str.slice(0, 10) 取代 apply(strptime)
     - destination_country：使用字典 map 與 fillna 取代逐列 apply
     - 匯率換算與聚合：先依 (event_date, currency, product_id) 做一級聚合，再與 fx_rates merge 向量化乘算匯率，最後做 (event_date, destination_country) 二級聚合
"""

import glob
import os
import time
from concurrent.futures import ProcessPoolExecutor

import pandas as pd


def _read_and_filter_file(file_path):
    """讀取單一 CSV 檔，提早過濾欄位、paid 事件與日期切片"""
    df = pd.read_csv(
        file_path,
        usecols=["event_id", "product_id", "event_type", "event_ts", "currency", "amount"],
        dtype={
            "event_id": str,
            "product_id": str,
            "event_type": str,
            "event_ts": str,
            "currency": str,
            "amount": float,
        },
    )
    # 提早過濾只留 paid 事件
    paid = df[df["event_type"] == "paid"]
    if paid.empty:
        return pd.DataFrame(columns=["event_id", "product_id", "currency", "amount", "event_date"])

    # 提取 event_date
    date_col = paid["event_ts"].str.slice(0, 10)

    res = paid[["event_id", "product_id", "currency", "amount"]].copy()
    res["event_date"] = date_col
    return res


def main(events_dir="raw_events", ref_dir="ref", out_path="daily_country_revenue.csv"):
    t0 = time.time()

    # 讀取參考主檔
    products = pd.read_csv(os.path.join(ref_dir, "products.csv"))
    fx = pd.read_csv(os.path.join(ref_dir, "fx_rates.csv"))

    # 併行讀取事件檔案並進行提早過濾
    files = sorted(glob.glob(os.path.join(events_dir, "events_*.csv")))
    max_workers = min(os.cpu_count() or 4, len(files)) if files else 1

    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        dfs = list(pool.map(_read_and_filter_file, files, chunksize=10))

    # 一次性 concat 合併，避免邊迭代邊 concat
    if dfs:
        paid = pd.concat(dfs, ignore_index=True)
    else:
        paid = pd.DataFrame(columns=["event_id", "product_id", "currency", "amount", "event_date"])

    # 對 event_id 設置 index 以便於去重複
    paid = paid.set_index("event_id")
    paid = paid[~paid.index.duplicated(keep="first")].reset_index()

    # 向量化預聚合：先依 (event_date, currency, product_id) 聚合金額，巨幅降低後續運算資料量
    agg = paid.groupby(["event_date", "currency", "product_id"], as_index=False)["amount"].sum()

    # 向量化關聯 products 取得 destination_country
    prod_country_map = dict(zip(products["product_id"], products["destination_country"]))
    agg["destination_country"] = agg["product_id"].map(prod_country_map).fillna("UNKNOWN")

    # 向量化關聯 fx 換算 TWD
    agg = agg.merge(
        fx[["rate_date", "currency", "rate_to_twd"]],
        left_on=["event_date", "currency"],
        right_on=["rate_date", "currency"],
        how="left",
    )
    agg["rate_to_twd"] = agg["rate_to_twd"].fillna(1.0)
    agg["revenue_twd"] = agg["amount"] * agg["rate_to_twd"]

    # 二級聚合：(event_date, destination_country) 排序並輸出
    result = (
        agg.groupby(["event_date", "destination_country"], as_index=False)["revenue_twd"]
        .sum()
        .sort_values(["event_date", "destination_country"])
        .reset_index(drop=True)
    )
    result["revenue_twd"] = result["revenue_twd"].round(2)
    result.to_csv(out_path, index=False, encoding="utf-8-sig")

    elapsed = time.time() - t0
    print(f"[CHECKSUM] rows={len(result)} total_twd={result['revenue_twd'].sum():.2f}")
    print(f"[TIME] v2 elapsed = {elapsed:.2f}s")


if __name__ == "__main__":
    main()
