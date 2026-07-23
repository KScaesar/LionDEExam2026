# CLAUDE.md

本專案的 Python 環境與依賴皆由 `uv` 管理，所有指令與腳本執行都必須透過 `uv`，不要直接呼叫系統 `python` / `python3` / `pip`。

## 環境需求

- Python 版本：`3.13.11`（見 `.python-version`，由 `uv` 自動安裝與切換）
- 依賴管理：`pyproject.toml` + `uv.lock`

## 初次建置

```bash
# uv 版本較舊時，內建 Python 下載索引可能還沒收錄 3.13.11，需先更新
uv self update

# 安裝 Python 版本與所有依賴（含 dev 群組）
uv sync
```

## 執行慣例

- 執行任何 Python 腳本一律使用 `uv run python <script>`，例如：
  ```bash
  uv run python candidate_package/module_D/baseline_etl_v2.py
  ```
- 執行測試：
  ```bash
  uv run pytest
  ```
- 新增/更新依賴請修改 `pyproject.toml` 後執行 `uv sync`，不要手動 `pip install`，避免與 `uv.lock` 產生落差。
- 不需要手動啟動或管理 `.venv`，`uv run` 會自動使用專案虛擬環境。
