# scripts/validate_ml_labels.py

import re
from pathlib import Path
from typing import Any, Optional

import pandas as pd


# =========================================================
# 1. 경로 설정
# =========================================================
BASE_DIR = Path(__file__).resolve().parents[1]

ML_DIR = BASE_DIR / "data" / "ml"
VALIDATION_DIR = ML_DIR / "validation"

FEATURE_SNAPSHOTS_FILE = ML_DIR / "feature_snapshots.csv"
LABEL_OUTCOMES_FILE = ML_DIR / "label_outcomes.csv"
MODEL_TRAINING_DATASET_FILE = ML_DIR / "model_training_dataset.csv"

SUMMARY_FILE = VALIDATION_DIR / "label_validation_summary.csv"
TARGET_RATE_FILE = VALIDATION_DIR / "target_positive_rate_summary.csv"
STATUS_FILE = VALIDATION_DIR / "label_status_summary.csv"
SUSPICIOUS_FILE = VALIDATION_DIR / "suspicious_label_rows.csv"
POSITIVE_CASE_FILE = VALIDATION_DIR / "positive_label_cases.csv"


# =========================================================
# 2. 공통 유틸
# =========================================================
def load_csv_with_fallback(path: Path) -> pd.DataFrame:
    if not path.exists():
        print(f"[WARN] 파일 없음: {path}")
        return pd.DataFrame()

    if path.stat().st_size == 0:
        print(f"[WARN] 빈 파일: {path}")
        return pd.DataFrame()

    last_error = None

    for enc in ["utf-8-sig", "cp949", "euc-kr", "utf-8"]:
        try:
            df = pd.read_csv(path, encoding=enc)
            print(f"CSV 읽기 성공: {path.name} / encoding={enc}")
            return df
        except UnicodeDecodeError as e:
            last_error = e
        except pd.errors.EmptyDataError:
            return pd.DataFrame()

    raise last_error


def normalize_text(value: Any) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass

    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)

    if text.lower() in {"nan", "none", "null", "<na>"}:
        return ""

    return text


def safe_float(value: Any) -> Optional[float]:
    try:
        if pd.isna(value):
            return None

        text = str(value).replace(",", "").strip()

        if text == "":
            return None

        return float(text)
    except Exception:
        return None


def safe_int(value: Any) -> Optional[int]:
    number = safe_float(value)

    if number is None:
        return None

    return int(number)


def get_horizon_from_target_col(col: str) -> Optional[str]:
    if "_1d" in col:
        return "1d"

    if "_3d" in col:
        return "3d"

    if "_7d" in col:
        return "7d"

    return None


def status_col_for_horizon(horizon: Optional[str]) -> Optional[str]:
    if horizon == "1d":
        return "label_status_1d"

    if horizon == "3d":
        return "label_status_3d"

    if horizon == "7d":
        return "label_status_7d"

    return None


def is_one(value: Any) -> bool:
    number = safe_float(value)
    return number == 1


def is_zero(value: Any) -> bool:
    number = safe_float(value)
    return number == 0


def is_missing(value: Any) -> bool:
    if value is None:
        return True

    try:
        if pd.isna(value):
            return True
    except Exception:
        pass

    return normalize_text(value) == ""


# =========================================================
# 3. 기본 요약
# =========================================================
def build_basic_summary(dataset: pd.DataFrame) -> pd.DataFrame:
    rows = []

    total_rows = len(dataset)

    rows.append({
        "check_name": "total_rows",
        "value": total_rows,
        "description": "model_training_dataset 전체 행 수",
    })

    if "snapshot_id" in dataset.columns:
        duplicate_count = dataset["snapshot_id"].duplicated().sum()
        unique_count = dataset["snapshot_id"].nunique()

        rows.append({
            "check_name": "unique_snapshot_id",
            "value": unique_count,
            "description": "중복 제거 기준 snapshot_id 수",
        })

        rows.append({
            "check_name": "duplicate_snapshot_id",
            "value": int(duplicate_count),
            "description": "snapshot_id 중복 수. 0이면 정상",
        })

    if "date" in dataset.columns:
        date_series = pd.to_datetime(dataset["date"], errors="coerce")

        rows.append({
            "check_name": "min_date",
            "value": date_series.min().strftime("%Y-%m-%d") if date_series.notna().any() else "",
            "description": "가장 오래된 feature 날짜",
        })

        rows.append({
            "check_name": "max_date",
            "value": date_series.max().strftime("%Y-%m-%d") if date_series.notna().any() else "",
            "description": "가장 최신 feature 날짜",
        })

    required_feature_cols = [
        "date",
        "slot",
        "product_name",
        "rank",
        "rank_change",
        "days_seen_7d",
        "rank_velocity_3d",
        "rising_score",
        "rising_level",
        "confidence_level",
    ]

    for col in required_feature_cols:
        if col not in dataset.columns:
            rows.append({
                "check_name": f"missing_column__{col}",
                "value": "MISSING",
                "description": f"필수 feature 컬럼 {col} 없음",
            })
            continue

        null_count = dataset[col].isna().sum() + (dataset[col].astype(str).str.strip() == "").sum()

        rows.append({
            "check_name": f"null_or_blank__{col}",
            "value": int(null_count),
            "description": f"{col} 비어 있는 행 수",
        })

    return pd.DataFrame(rows)


# =========================================================
# 4. label status 요약
# =========================================================
def build_status_summary(dataset: pd.DataFrame) -> pd.DataFrame:
    rows = []

    for col in ["label_status_1d", "label_status_3d", "label_status_7d", "label_status"]:
        if col not in dataset.columns:
            rows.append({
                "status_column": col,
                "status_value": "MISSING_COLUMN",
                "count": 0,
                "rate": 0,
            })
            continue

        counts = dataset[col].fillna("NULL").astype(str).value_counts(dropna=False)

        for status_value, count in counts.items():
            rows.append({
                "status_column": col,
                "status_value": status_value,
                "count": int(count),
                "rate": round(count / len(dataset) * 100, 2) if len(dataset) else 0,
            })

    return pd.DataFrame(rows)


# =========================================================
# 5. target positive rate 요약
# =========================================================
def build_target_rate_summary(dataset: pd.DataFrame) -> pd.DataFrame:
    rows = []

    target_cols = [c for c in dataset.columns if c.startswith("target_")]

    for target_col in target_cols:
        horizon = get_horizon_from_target_col(target_col)
        status_col = status_col_for_horizon(horizon)

        if status_col and status_col in dataset.columns:
            target_base = dataset[dataset[status_col] == "ready"].copy()
        else:
            target_base = dataset.copy()

        total_ready = len(target_base)

        if total_ready == 0:
            rows.append({
                "target_column": target_col,
                "horizon": horizon or "",
                "ready_rows": 0,
                "positive_count": 0,
                "negative_count": 0,
                "missing_count": 0,
                "positive_rate": 0,
                "note": "ready 행 없음",
            })
            continue

        values = target_base[target_col]

        positive_count = values.map(is_one).sum()
        negative_count = values.map(is_zero).sum()
        missing_count = values.map(is_missing).sum()

        rows.append({
            "target_column": target_col,
            "horizon": horizon or "",
            "ready_rows": total_ready,
            "positive_count": int(positive_count),
            "negative_count": int(negative_count),
            "missing_count": int(missing_count),
            "positive_rate": round(positive_count / total_ready * 100, 2),
            "note": "",
        })

    return pd.DataFrame(rows)


# =========================================================
# 6. 의심 행 찾기
# =========================================================
def find_suspicious_rows(dataset: pd.DataFrame) -> pd.DataFrame:
    suspicious = []

    for idx, row in dataset.iterrows():
        reasons = []

        product_name = normalize_text(row.get("product_name", ""))
        date = normalize_text(row.get("date", ""))
        slot = normalize_text(row.get("slot", ""))

        # 1. 핵심 식별자 누락
        if not date:
            reasons.append("date 없음")

        if not slot:
            reasons.append("slot 없음")

        if not product_name:
            reasons.append("product_name 없음")

        # 2. rank 이상값
        rank = safe_int(row.get("rank"))

        if rank is None:
            reasons.append("rank 없음")
        elif rank <= 0 or rank > 200:
            reasons.append(f"rank 범위 이상: {rank}")

        # 3. rising_score 이상값
        rising_score = safe_float(row.get("rising_score"))

        if rising_score is not None and (rising_score < 0 or rising_score > 100):
            reasons.append(f"rising_score 범위 이상: {rising_score}")

        # 4. ready인데 target이 비어 있음
        for horizon in ["1d", "3d", "7d"]:
            status_col = f"label_status_{horizon}"

            if status_col not in dataset.columns:
                continue

            if row.get(status_col) != "ready":
                continue

            related_target_cols = [
                c for c in dataset.columns
                if c.startswith("target_") and f"_{horizon}" in c
            ]

        for target_col in related_target_cols:
            # search/click 라벨은 현재 기준값이 없으면 계산 불가가 정상일 수 있음
            if "search_up" in target_col or "click_up" in target_col:
                 continue

            if is_missing(row.get(target_col)):
                reasons.append(f"{status_col}=ready인데 {target_col} 비어 있음")

        # 5. Top20이면 rank50도 1이어야 자연스러움
        if is_one(row.get("target_top20_next_3d")):
            if "target_rank_50_next_3d" in dataset.columns and not is_one(row.get("target_rank_50_next_3d")):
                reasons.append("Top20 3d=1인데 rank50 3d가 1이 아님")

        if is_one(row.get("target_top20_next_7d")):
            if "target_rank_50_next_7d" in dataset.columns and not is_one(row.get("target_rank_50_next_7d")):
                reasons.append("Top20 7d=1인데 rank50 7d가 1이 아님")

        # 6. interest_confirmed 3d 일관성
        if "target_interest_confirmed_next_3d" in dataset.columns:
            any_interest_3d = any([
                is_one(row.get("target_top20_next_3d")),
                is_one(row.get("target_rank_50_next_3d")),
                is_one(row.get("target_search_up_next_3d")),
                is_one(row.get("target_click_up_next_3d")),
            ])

            if any_interest_3d and not is_one(row.get("target_interest_confirmed_next_3d")):
                reasons.append("3일 관심 신호가 있는데 interest_confirmed_3d가 1이 아님")

        # 7. priority_success 7d 일관성
        if "target_priority_success_next_7d" in dataset.columns:
            any_success_7d = any([
                is_one(row.get("target_top20_next_7d")),
                is_one(row.get("target_rank_50_next_7d")),
                is_one(row.get("target_search_up_next_7d")),
                is_one(row.get("target_click_up_next_7d")),
            ])

            if any_success_7d and not is_one(row.get("target_priority_success_next_7d")):
                reasons.append("7일 성공 신호가 있는데 priority_success_7d가 1이 아님")

        if reasons:
            suspicious.append({
                "row_index": idx,
                "date": date,
                "slot": slot,
                "product_name": product_name,
                "rank": row.get("rank"),
                "rising_score": row.get("rising_score"),
                "label_status_3d": row.get("label_status_3d"),
                "label_status_7d": row.get("label_status_7d"),
                "target_top20_next_3d": row.get("target_top20_next_3d"),
                "target_rank_50_next_3d": row.get("target_rank_50_next_3d"),
                "target_search_up_next_3d": row.get("target_search_up_next_3d"),
                "target_click_up_next_3d": row.get("target_click_up_next_3d"),
                "target_interest_confirmed_next_3d": row.get("target_interest_confirmed_next_3d"),
                "suspicious_reason": " | ".join(reasons),
            })

    return pd.DataFrame(suspicious)


# =========================================================
# 7. positive case 추출
# =========================================================
def build_positive_cases(dataset: pd.DataFrame) -> pd.DataFrame:
    target_cols = [c for c in dataset.columns if c.startswith("target_")]

    if not target_cols:
        return pd.DataFrame()

    mask = pd.Series(False, index=dataset.index)

    for col in target_cols:
        mask = mask | dataset[col].map(is_one)

    positive_df = dataset[mask].copy()

    if positive_df.empty:
        return pd.DataFrame()

    keep_cols = [
        "date",
        "slot",
        "product_name",
        "canonical_product_name",
        "product_group",
        "sub_group",
        "rank",
        "rank_range",
        "rank_change",
        "rank_change_label",
        "days_seen_7d",
        "consecutive_days",
        "rank_velocity_3d",
        "rising_score",
        "rising_level",
        "confidence_level",
        "action_level",
        "target_top20_next_3d",
        "target_rank_50_next_3d",
        "target_search_up_next_3d",
        "target_click_up_next_3d",
        "target_interest_confirmed_next_3d",
        "target_priority_success_next_7d",
        "label_status_3d",
        "label_status_7d",
    ]

    keep_cols = [c for c in keep_cols if c in positive_df.columns]

    positive_df = positive_df[keep_cols].copy()

    sort_cols = [c for c in ["date", "slot", "rising_score"] if c in positive_df.columns]

    if sort_cols:
        positive_df = positive_df.sort_values(sort_cols, ascending=[True, True, False][:len(sort_cols)])

    return positive_df


# =========================================================
# 8. 메인
# =========================================================
def main():
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)

    dataset = load_csv_with_fallback(MODEL_TRAINING_DATASET_FILE)

    if dataset.empty:
        print("[ERROR] model_training_dataset.csv가 없습니다.")
        print("먼저 아래 순서로 실행하세요.")
        print("python scripts\\build_model_training_dataset.py")
        print("python scripts\\build_training_labels.py")
        print("python scripts\\build_model_training_dataset.py")
        return

    dataset.columns = [str(c).strip() for c in dataset.columns]

    summary_df = build_basic_summary(dataset)
    status_df = build_status_summary(dataset)
    target_rate_df = build_target_rate_summary(dataset)
    suspicious_df = find_suspicious_rows(dataset)
    positive_df = build_positive_cases(dataset)

    if suspicious_df.empty:
        suspicious_df = pd.DataFrame(columns=[
            "row_index",
            "date",
            "slot",
            "product_name",
            "rank",
            "rising_score",
            "label_status_3d",
            "label_status_7d",
            "target_top20_next_3d",
            "target_rank_50_next_3d",
            "target_search_up_next_3d",
            "target_click_up_next_3d",
            "target_interest_confirmed_next_3d",
            "suspicious_reason",
        ])

    if positive_df.empty:
        positive_df = pd.DataFrame(columns=[
            "date",
            "slot",
            "product_name",
            "canonical_product_name",
            "product_group",
            "sub_group",
            "rank",
            "rank_range",
            "rank_change",
            "rank_change_label",
            "days_seen_7d",
            "consecutive_days",
            "rank_velocity_3d",
            "rising_score",
            "rising_level",
            "confidence_level",
            "action_level",
            "target_top20_next_3d",
            "target_rank_50_next_3d",
            "target_search_up_next_3d",
            "target_click_up_next_3d",
            "target_interest_confirmed_next_3d",
            "target_priority_success_next_7d",
            "label_status_3d",
            "label_status_7d",
        ])

    summary_df.to_csv(SUMMARY_FILE, index=False, encoding="utf-8-sig")
    status_df.to_csv(STATUS_FILE, index=False, encoding="utf-8-sig")
    target_rate_df.to_csv(TARGET_RATE_FILE, index=False, encoding="utf-8-sig")
    suspicious_df.to_csv(SUSPICIOUS_FILE, index=False, encoding="utf-8-sig")
    positive_df.to_csv(POSITIVE_CASE_FILE, index=False, encoding="utf-8-sig")

    print("\n검증 완료")
    print(f"전체 row 수: {len(dataset)}")
    print(f"의심 row 수: {len(suspicious_df)}")
    print(f"positive case 수: {len(positive_df)}")

    print("\n저장 파일")
    print(f"- {SUMMARY_FILE}")
    print(f"- {STATUS_FILE}")
    print(f"- {TARGET_RATE_FILE}")
    print(f"- {SUSPICIOUS_FILE}")
    print(f"- {POSITIVE_CASE_FILE}")

    print("\nlabel status 요약")
    if not status_df.empty:
        print(status_df.to_string(index=False))

    print("\ntarget positive rate 요약")
    if not target_rate_df.empty:
        print(target_rate_df.to_string(index=False))

    if not suspicious_df.empty:
        print("\n의심 row 미리보기")
        preview_cols = [
            "date",
            "slot",
            "product_name",
            "rank",
            "rising_score",
            "label_status_3d",
            "label_status_7d",
            "suspicious_reason",
        ]
        preview_cols = [c for c in preview_cols if c in suspicious_df.columns]
        print(suspicious_df[preview_cols].head(30).to_string(index=False))
    else:
        print("\n의심 row 없음")


if __name__ == "__main__":
    main()