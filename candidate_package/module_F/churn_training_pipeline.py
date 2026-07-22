# -*- coding: utf-8 -*-
"""
訂單取消預測 — 特徵工程與訓練管線
===================================
背景：DS 團隊建了這個「訂單是否會被取消」的預測模型，離線測試 AUC 高達 0.9 以上，
模型上線兩週後，實際線上 AUC 只剩約 0.55（幾乎等於亂猜），業務端已停用。
DS 反覆檢查過模型演算法與超參數，確認沒有問題，懷疑是「資料的問題」，
請你（資料工程師）診斷這條特徵管線。

資料：../dataset/orders_base.csv 與 members.csv（與 Part A 相同）
執行（選配）：pip install scikit-learn 後 python churn_training_pipeline.py
（不執行、純閱讀程式碼作答亦可）
"""

import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATASET = os.path.join(HERE, "..", "dataset")


def load_orders():
    df = pd.read_csv(os.path.join(DATASET, "orders_base.csv"))
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df["created_ts"] = pd.to_datetime(df["order_created_at"], format="mixed", errors="coerce", utc=True)
    df["departure"] = pd.to_datetime(df["departure_date"], errors="coerce")
    df = df.dropna(subset=["amount", "created_ts", "departure"])
    # 標籤：訂單是否被取消
    df["label"] = (df["order_status"] == "cancelled").astype(int)
    return df


def build_features(df):
    """特徵工程：整合會員行為統計與產品風險統計。"""
    # 會員歷史行為特徵（會員的訂單數與取消率，反映會員的取消傾向）
    member_stats = df.groupby("member_id").agg(
        member_order_cnt=("order_id", "count"),
        member_cancel_rate=("label", "mean"),
    ).reset_index()
    df = df.merge(member_stats, on="member_id", how="left")

    # 會員 × 產品 親和度特徵（會員對特定產品的取消傾向，DS 說這個特徵重要性最高）
    mp_stats = df.groupby(["member_id", "product_id"]).agg(
        member_product_cancel_rate=("label", "mean"),
    ).reset_index()
    df = df.merge(mp_stats, on=["member_id", "product_id"], how="left")

    # 產品風險特徵（產品整體取消率，target encoding）
    prod_stats = df.groupby("product_id").agg(
        product_cancel_rate=("label", "mean"),
    ).reset_index()
    df = df.merge(prod_stats, on="product_id", how="left")

    # 訂單本身的特徵
    df["days_to_departure"] = (
        df["departure"].dt.tz_localize("UTC") - df["created_ts"]
    ).dt.days
    df["coupon_discount"] = pd.to_numeric(df["coupon_discount"], errors="coerce").fillna(0)

    feature_cols = [
        "member_order_cnt", "member_cancel_rate", "member_product_cancel_rate",
        "product_cancel_rate", "amount", "quantity", "coupon_discount", "days_to_departure",
    ]
    return df, feature_cols


def train(df, feature_cols):
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler

    X = df[feature_cols].fillna(0).values
    y = df["label"].values

    # 標準化後切分訓練/測試集
    scaler = StandardScaler()
    X = scaler.fit_transform(X)
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.25, random_state=7)

    model = LogisticRegression(max_iter=1000)
    model.fit(X_tr, y_tr)

    auc_tr = roc_auc_score(y_tr, model.predict_proba(X_tr)[:, 1])
    auc_te = roc_auc_score(y_te, model.predict_proba(X_te)[:, 1])
    print(f"Train AUC = {auc_tr:.4f}")
    print(f"Test  AUC = {auc_te:.4f}   ← 離線驗證結果（上線實測僅 ~0.55）")

    importance = sorted(zip(feature_cols, model.coef_[0]), key=lambda t: -abs(t[1]))
    print("\n特徵重要性（係數絕對值排序）：")
    for name, coef in importance:
        print(f"  {name:32s} {coef:+.4f}")


if __name__ == "__main__":
    orders = load_orders()
    feats, cols = build_features(orders)
    print(f"樣本數: {len(feats):,}  取消率: {feats['label'].mean():.3f}")
    train(feats, cols)
