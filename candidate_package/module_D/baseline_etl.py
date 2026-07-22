# -*- coding: utf-8 -*-
"""
模組 D — Baseline ETL（正確但慢，這是你要優化的對象）

任務：從 raw_events/ 的事件檔計算「每日 × 目的地國家」的 paid 事件營收（TWD）。
規則：
  1. 以 event_id 去重（上游會重送，重複列內容完全相同）
  2. 只計 event_type = 'paid'
  3. amount 依 event_ts 當日匯率換算為 TWD
  4. 關聯 products 取得 destination_country
  5. 輸出 daily_country_revenue.csv（依 event_date, destination_country 排序），
     並印出 [CHECKSUM] 列數與總金額

本腳本的輸出是「正確答案」。你的優化版本輸出必須與它完全一致（CHECKSUM 相同），
在同一台機器上達到越高的吞吐倍數越好。
"""

import glob
import os
import time
from datetime import datetime

import pandas as pd


def main(events_dir="raw_events", ref_dir="ref", out_path="daily_country_revenue.csv"):
    t0 = time.time()

    products = pd.read_csv(os.path.join(ref_dir, "products.csv"))
    fx = pd.read_csv(os.path.join(ref_dir, "fx_rates.csv"))

    # 建立查找結構
    product_country = {}
    for _, row in products.iterrows():
        product_country[row["product_id"]] = row["destination_country"]
    fx_lookup = {}
    for _, row in fx.iterrows():
        fx_lookup[(row["rate_date"], row["currency"])] = row["rate_to_twd"]

    # 逐檔讀取並合併
    all_events = pd.DataFrame()
    files = sorted(glob.glob(os.path.join(events_dir, "events_*.csv")))
    for i, f in enumerate(files):
        df = pd.read_csv(f)
        all_events = pd.concat([all_events, df], ignore_index=True)
        if (i + 1) % 50 == 0:
            print(f"  loaded {i+1}/{len(files)} files, rows={len(all_events):,}")

    # 以 event_id 去重
    seen = set()
    keep_flags = []
    for eid in all_events["event_id"]:
        if eid in seen:
            keep_flags.append(False)
        else:
            seen.add(eid)
            keep_flags.append(True)
    all_events = all_events[pd.Series(keep_flags, index=all_events.index)]

    # 只留 paid
    paid = all_events[all_events["event_type"] == "paid"].copy()

    # 逐列換算 TWD 與衍生日期
    def to_twd(row):
        d = datetime.strptime(row["event_ts"], "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")
        rate = fx_lookup.get((d, row["currency"]), 1.0)
        return row["amount"] * rate

    def event_date(row):
        return datetime.strptime(row["event_ts"], "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")

    def country(row):
        return product_country.get(row["product_id"], "UNKNOWN")

    paid["revenue_twd"] = paid.apply(to_twd, axis=1)
    paid["event_date"] = paid.apply(event_date, axis=1)
    paid["destination_country"] = paid.apply(country, axis=1)

    # 聚合
    result = (
        paid.groupby(["event_date", "destination_country"], as_index=False)["revenue_twd"]
        .sum()
        .sort_values(["event_date", "destination_country"])
        .reset_index(drop=True)
    )
    result["revenue_twd"] = result["revenue_twd"].round(2)
    result.to_csv(out_path, index=False, encoding="utf-8-sig")

    elapsed = time.time() - t0
    print(f"[CHECKSUM] rows={len(result)} total_twd={result['revenue_twd'].sum():.2f}")
    print(f"[TIME] baseline elapsed = {elapsed:.1f}s")


if __name__ == "__main__":
    main()
