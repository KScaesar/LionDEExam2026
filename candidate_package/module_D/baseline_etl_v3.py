# -*- coding: utf-8 -*-
"""
模組 D — Optimized ETL v3（全 polars 版本，函數化封裝／Seam 設計）

任務：從 raw_events/ 的事件檔計算「每日 × 目的地國家」的 paid 事件營收（TWD）。
相對 v2 的改進：
  1. I/O 瓶頸：v2 的觀測數據顯示「多進程讀檔＋過濾」占整體耗時 55%，最大瓶頸。
     v3 改用 polars.scan_csv 對 600 個檔案做原生多執行緒（Rust）平行讀取＋lazy 欄位剪枝／過濾，
     取代 Python ProcessPoolExecutor（省去跨進程序列化／反序列化與行程啟動開銷）。
  2. 去重瓶頸：v2 的觀測數據顯示 event_id 去重占 36%，其中 set_index + duplicated + reset_index
     是不必要的中間操作（建立 index 只是為了去重，之後又立刻拋棄）。
     v3 直接用 polars 的 unique(subset=["event_id"], keep="first") 一步到位去重，不建 index。
  3. 全流程改用 polars：讀取參考主檔、預聚合、國家 join、fx join、二級聚合、寫檔皆以 polars
     完成，不再轉換為 pandas DataFrame。

函數封裝（Seam 設計）：
  將原本集中在 main() 的流程拆成職責單一的函式，並在 I/O 與純運算之間劃出明確的測試接縫（seam）：
    - I/O 邊界函式（read_reference_data / list_event_files / read_and_filter_events / write_result）：
      唯一會碰觸檔案系統的地方，測試時可整體替換（monkeypatch）掉，不需要真的準備 CSV 檔案。
    - 純轉換函式（dedup_events / pre_aggregate / join_country / join_fx_and_calc_revenue /
      final_aggregate）：只吃 DataFrame 進、DataFrame 出，不含任何 I/O 或副作用，可直接用小型
      in-memory 的 polars DataFrame 做單元測試，驗證去重、聚合、join 邏輯的正確性。
  main() 只負責串接這些函式並記錄各階段耗時，不含商業邏輯本身。
"""

import glob
import os
import time

import polars as pl

EVENT_COLUMNS = [
    "event_id",
    "product_id",
    "event_type",
    "event_ts",
    "currency",
    "amount",
]
EVENT_SCHEMA_OVERRIDES = {
    "event_id": pl.Utf8,
    "product_id": pl.Utf8,
    "event_type": pl.Utf8,
    "event_ts": pl.Utf8,
    "currency": pl.Utf8,
    "amount": pl.Float64,
}


# --------------------------------------------------------------------------
# I/O 邊界（seam）：唯一碰觸檔案系統的函式，測試時可整體替換掉
# --------------------------------------------------------------------------


def read_reference_data(ref_dir):
    """讀取 products / fx_rates 參考主檔"""
    products = pl.read_csv(os.path.join(ref_dir, "products.csv"))
    fx = pl.read_csv(os.path.join(ref_dir, "fx_rates.csv"))
    return products, fx


def list_event_files(events_dir):
    """列出事件檔案，排序以確保後續去重 keep='first' 的結果具備決定性"""
    return sorted(glob.glob(os.path.join(events_dir, "events_*.csv")))


def read_and_filter_events(files):
    """polars 原生多執行緒讀取 + lazy 欄位剪枝／提早過濾 paid 事件"""
    if not files:
        return pl.DataFrame(
            schema={
                "event_id": pl.Utf8,
                "product_id": pl.Utf8,
                "currency": pl.Utf8,
                "amount": pl.Float64,
                "event_date": pl.Utf8,
            }
        )

    lf = pl.scan_csv(files, schema_overrides=EVENT_SCHEMA_OVERRIDES)
    paid_lf = (
        lf.select(EVENT_COLUMNS)
        .filter(pl.col("event_type") == "paid")
        .with_columns(pl.col("event_ts").str.slice(0, 10).alias("event_date"))
        .select(["event_id", "product_id", "currency", "amount", "event_date"])
    )
    return paid_lf.collect()


def write_result(result, out_path):
    """寫出最終結果，含 UTF-8 BOM 以相容 Excel"""
    result.write_csv(out_path, include_bom=True)


# --------------------------------------------------------------------------
# 純轉換函式（seam）：只吃 DataFrame 進、DataFrame 出，無 I/O，方便單元測試
# --------------------------------------------------------------------------


def dedup_events(paid):
    """對 event_id 去重，保留每個 event_id 第一次出現的紀錄"""
    return paid.unique(subset=["event_id"], keep="first", maintain_order=True)


def pre_aggregate(paid):
    """一級預聚合：依 (event_date, currency, product_id) 加總金額，縮小後續運算資料量

    SUM 具備可分配性（distributive）：先在細粒度 (event_date, currency, product_id) 加總，
    之後再乘上對應匯率、依國家二次加總，結果與逐列計算完全相同。但因同一天/同一幣別/
    同一產品的付款筆數龐大，先在此把 1,500 萬列壓縮到約 2.7 萬列，可讓後續 join 與二級
    聚合的運算量大幅下降，是整個 pipeline 最關鍵的效能設計。
    """
    return paid.group_by(["event_date", "currency", "product_id"]).agg(
        pl.col("amount").sum()
    )


def join_country(agg, products):
    """關聯 products 取得 destination_country，缺漏補 UNKNOWN"""
    return agg.join(
        products.select(["product_id", "destination_country"]),
        on="product_id",
        how="left",
    ).with_columns(pl.col("destination_country").fill_null("UNKNOWN"))


def join_fx_and_calc_revenue(agg, fx):
    """關聯 fx_rates 換算 TWD，缺漏匯率視為 1.0（原幣即 TWD）"""
    agg = agg.join(
        fx.select(["rate_date", "currency", "rate_to_twd"]),
        left_on=["event_date", "currency"],
        right_on=["rate_date", "currency"],
        how="left",
    ).with_columns(pl.col("rate_to_twd").fill_null(1.0))
    return agg.with_columns(
        (pl.col("amount") * pl.col("rate_to_twd")).alias("revenue_twd")
    )


def final_aggregate(agg):
    """二級聚合：依 (event_date, destination_country) 加總 TWD 營收，排序並四捨五入

    一級預聚合是以 product_id 為粒度，但多個 product_id 可能對應到同一個
    destination_country，join 完成後同一天、同一國家會出現多筆列。因此需要這一次
    二級聚合把 product_id 粒度收斂到最終要輸出的 (event_date, destination_country) 粒度，
    才能得到正確、不重複的每日/國家營收。
    """
    return (
        agg.group_by(["event_date", "destination_country"])
        .agg(pl.col("revenue_twd").sum())
        .sort(["event_date", "destination_country"])
        .with_columns(pl.col("revenue_twd").round(2))
    )


# --------------------------------------------------------------------------
# 流程串接與觀測性
# --------------------------------------------------------------------------


def main(events_dir="raw_events", ref_dir="ref", out_path="daily_country_revenue.csv"):
    t0 = time.time()
    checkpoints = []

    def mark(label):
        now = time.time()
        checkpoints.append((label, now))
        prev = checkpoints[-2][1] if len(checkpoints) > 1 else t0
        print(f"[TIME] {label}: {now - prev:.3f}s (cumulative {now - t0:.3f}s)")

    products, fx = read_reference_data(ref_dir)
    mark("01_read_ref")

    files = list_event_files(events_dir)
    mark("02_list_files")

    paid = read_and_filter_events(files)
    mark("03_polars_read_filter(io+cpu)")

    paid = dedup_events(paid)
    mark("04_dedup_unique(cpu)")

    agg = pre_aggregate(paid)
    mark("05_pre_aggregate(groupby)")

    agg = join_country(agg, products)
    mark("06_country_join")

    agg = join_fx_and_calc_revenue(agg, fx)
    mark("07_fx_join_and_calc(join)")

    result = final_aggregate(agg)
    mark("08_final_aggregate_sort")

    write_result(result, out_path)
    mark("09_write_csv(io)")

    elapsed = time.time() - t0
    print(
        f"[CHECKSUM] rows={result.height} total_twd={result['revenue_twd'].sum():.2f}"
    )
    print(f"[TIME] v3 elapsed = {elapsed:.2f}s")


if __name__ == "__main__":
    main()
