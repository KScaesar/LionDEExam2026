# -*- coding: utf-8 -*-
"""
模組 D — 效能測試資料生成器（候選人請直接執行，資料在你的機器本地生成）

用法:
    python generate_perf_data.py            # 完整規模（約 600 檔 / 1,500 萬列 / ~1.5GB）
    python generate_perf_data.py --scale 0.05   # 快速小規模（僅供煙霧測試）

產出:
    raw_events/events_00001.csv ... （訂單事件檔，模擬上游系統每小時落地的小檔）
    ref/products.csv                 產品主檔（小表）
    ref/fx_rates.csv                 每日匯率

注意：請勿修改本腳本。所有人使用相同 seed，產出內容完全一致。
"""

import argparse
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

SEED = 20260709
N_FILES_FULL = 600
ROWS_PER_FILE = 25_000
START = datetime(2026, 6, 1)
DAYS = 30
CURRENCIES = np.array(["TWD", "TWD", "TWD", "TWD", "USD", "USD", "JPY"])
EVENT_TYPES = np.array(["created", "paid", "paid", "paid", "cancelled", "completed"])
COUNTRIES = ["日本", "韓國", "泰國", "越南", "台灣", "法國", "義大利", "美國"]


def gen_ref(rng, out):
    os.makedirs(os.path.join(out, "ref"), exist_ok=True)
    prods = pd.DataFrame({
        "product_id": [f"P{i:05d}" for i in range(1, 301)],
        "destination_country": [COUNTRIES[int(rng.integers(0, len(COUNTRIES)))] for _ in range(300)],
        "product_type": [["團體旅遊", "自由行", "機票", "訂房"][int(rng.integers(0, 4))] for _ in range(300)],
    })
    prods.to_csv(os.path.join(out, "ref", "products.csv"), index=False, encoding="utf-8-sig")

    fx_rows = []
    usd, jpy = 31.5, 0.205
    for d in range(DAYS + 1):
        day = (START + timedelta(days=d)).strftime("%Y-%m-%d")
        usd += rng.normal(0, 0.05)
        jpy += rng.normal(0, 0.0005)
        fx_rows += [
            {"rate_date": day, "currency": "TWD", "rate_to_twd": 1.0},
            {"rate_date": day, "currency": "USD", "rate_to_twd": round(usd, 3)},
            {"rate_date": day, "currency": "JPY", "rate_to_twd": round(jpy, 5)},
        ]
    pd.DataFrame(fx_rows).to_csv(os.path.join(out, "ref", "fx_rates.csv"), index=False, encoding="utf-8-sig")


def gen_events(rng, out, n_files):
    ev_dir = os.path.join(out, "raw_events")
    os.makedirs(ev_dir, exist_ok=True)
    eid_counter = 0
    carry_dup = None  # 跨檔重複列（模擬上游重送）
    for f in range(1, n_files + 1):
        n = ROWS_PER_FILE
        secs = rng.integers(0, DAYS * 86400, size=n)
        ts = pd.to_datetime(START) + pd.to_timedelta(secs, unit="s")
        df = pd.DataFrame({
            "event_id": np.arange(eid_counter, eid_counter + n),
            "order_id": rng.integers(1, 4_000_000, size=n),
            "member_id": rng.integers(1, 200_000, size=n),
            "product_id": [f"P{i:05d}" for i in rng.integers(1, 301, size=n)],
            "event_type": EVENT_TYPES[rng.integers(0, len(EVENT_TYPES), size=n)],
            "event_ts": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "currency": CURRENCIES[rng.integers(0, len(CURRENCIES), size=n)],
            "amount": np.round(rng.uniform(500, 150_000, size=n), 2),
            "quantity": rng.integers(1, 5, size=n),
        })
        df["event_id"] = df["event_id"].apply(lambda x: f"EV{x:012d}")
        eid_counter += n
        # 1% 列重複出現在下一個檔（上游重送，需以 event_id 去重）
        if carry_dup is not None:
            df = pd.concat([df, carry_dup], ignore_index=True)
        carry_dup = df.sample(n=max(1, n // 100), random_state=int(rng.integers(0, 10**6)))
        df.to_csv(os.path.join(ev_dir, f"events_{f:05d}.csv"), index=False)
        if f % 100 == 0:
            print(f"  {f}/{n_files} files ...")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.0, help="規模比例，煙霧測試用")
    ap.add_argument("--out", default=".")
    args = ap.parse_args()
    n_files = max(2, int(N_FILES_FULL * args.scale))
    rng = np.random.default_rng(SEED)
    print(f"生成 {n_files} 個事件檔（每檔 {ROWS_PER_FILE:,} 列）...")
    gen_ref(rng, args.out)
    gen_events(rng, args.out, n_files)
    print("完成。")


if __name__ == "__main__":
    main()
