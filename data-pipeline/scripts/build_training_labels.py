# scripts/build_training_labels.py

import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd


# =========================================================
# 1. 경로 설정
# =========================================================
BASE_DIR = Path(__file__).resolve().parents[1]

PROCESSED_DIR = BASE_DIR / "data" / "daily" / "processed"
ML_DIR = BASE_DIR / "data" / "ml"

FEATURE_SNAPSHOTS_FILE = ML_DIR / "feature_snapshots.csv"
LABEL_OUTCOMES_FILE = ML_DIR / "label_outcomes.csv"

TOP20_PREFIX = "top20_with_search_shopping_"
CANDIDATES_PREFIX = "candidates_with_search_shopping_"
PRODUCT_DAILY_PREFIX = "product_daily_search_shopping_"

# =========================================================
# Search / Click label 기준
# 기존보다 빡세게 조정
# =========================================================

# 검색 지수: 30% 이상 상승
SEARCH_UP_RATE = 0.30

# 쇼핑 클릭 지수: 25% 이상 상승
CLICK_UP_RATE = 0.25

# 검색 지수는 최소 10포인트 이상 올라야 상승으로 인정
SEARCH_MIN_RATIO_DIFF = 10.0

# 쇼핑 클릭 지수도 최소 10포인트 이상 올라야 상승으로 인정
CLICK_MIN_RATIO_DIFF = 10.0

# 미래 최대값 자체도 최소 이 값 이상이어야 함
# 너무 작은 값에서 살짝 오른 것을 성공으로 잡지 않기 위한 장치
SEARCH_MIN_FUTURE_RATIO = 15.0
CLICK_MIN_FUTURE_RATIO = 15.0


# =========================================================
# 2. 공통 유틸
# =========================================================
def load_csv_with_fallback(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    if path.stat().st_size == 0:
        return pd.DataFrame()

    last_error = None

    for enc in ["utf-8-sig", "cp949", "euc-kr", "utf-8"]:
        try:
            return pd.read_csv(path, encoding=enc)
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


def normalize_slot(value: Any) -> str:
    text = normalize_text(value).lower()

    if text in {"am", "morning", "오전"}:
        return "am"

    if text in {"pm", "evening", "afternoon", "오후"}:
        return "pm"

    return text or "am"


def slot_order(slot: Any) -> int:
    slot = normalize_slot(slot)

    if slot == "am":
        return 0

    if slot == "pm":
        return 1

    return 0


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
    try:
        if pd.isna(value):
            return None
        text = str(value).replace(",", "").strip()
        if text == "":
            return None
        return int(float(text))
    except Exception:
        return None


def parse_suffix_from_filename(file_name: str, prefix: str) -> Optional[str]:
    if not file_name.startswith(prefix) or not file_name.endswith(".csv"):
        return None

    return file_name[len(prefix):-4]


def parse_suffix_date_slot(suffix: str) -> tuple[str, str]:
    parts = suffix.rsplit("_", 1)

    if len(parts) != 2:
        return "0000-00-00", "am"

    return parts[0], normalize_slot(parts[1])


def build_snapshot_datetime(date_value: Any, slot_value: Any) -> Optional[pd.Timestamp]:
    date_text = normalize_text(date_value)
    slot_text = normalize_slot(slot_value)

    dt = pd.to_datetime(date_text, errors="coerce")

    if pd.isna(dt):
        return None

    if slot_text == "pm":
        return dt + pd.Timedelta(hours=12)

    return dt


def build_snapshot_id(date: Any, slot: Any, source_type: Any, product_name: Any) -> str:
    return "|".join([
        normalize_text(date),
        normalize_slot(slot),
        normalize_text(source_type) or "rising",
        normalize_text(product_name),
    ])


def get_match_names(row: pd.Series) -> set[str]:
    names = {
        normalize_text(row.get("product_name", "")),
        normalize_text(row.get("canonical_product_name", "")),
    }

    return {name for name in names if name}


def is_ready_for_horizon(base_date: pd.Timestamp, max_observed_date: Optional[pd.Timestamp], days: int) -> bool:
    if max_observed_date is None or pd.isna(max_observed_date):
        return False

    required_date = base_date + pd.Timedelta(days=days)
    return max_observed_date.normalize() >= required_date.normalize()


# =========================================================
# 3. 관측 데이터 로딩
# =========================================================
def load_top20_history() -> pd.DataFrame:
    rows = []

    files = list(PROCESSED_DIR.rglob(f"{TOP20_PREFIX}*.csv"))

    for path in files:
        suffix = parse_suffix_from_filename(path.name, TOP20_PREFIX)

        if not suffix:
            continue

        file_date, file_slot = parse_suffix_date_slot(suffix)

        df = load_csv_with_fallback(path)

        if df.empty:
            continue

        df.columns = [str(c).strip() for c in df.columns]

        if "product_name" not in df.columns:
            continue

        for _, row in df.iterrows():
            product_name = normalize_text(row.get("product_name", ""))

            if not product_name:
                continue

            rank = safe_int(row.get("rank"))

            rows.append({
                "date": file_date,
                "slot": file_slot,
                "snapshot_dt": build_snapshot_datetime(file_date, file_slot),
                "product_name": product_name,
                "rank": rank if rank is not None else safe_int(row.get("todayRank")),
                "source": "top20",
            })

    result = pd.DataFrame(rows)

    if not result.empty:
        result["date_dt"] = pd.to_datetime(result["date"], errors="coerce")
        result = result.dropna(subset=["date_dt", "snapshot_dt"])

    return result


def load_candidates_history() -> pd.DataFrame:
    rows = []

    files = list(PROCESSED_DIR.rglob(f"{CANDIDATES_PREFIX}*.csv"))

    for path in files:
        suffix = parse_suffix_from_filename(path.name, CANDIDATES_PREFIX)

        if not suffix:
            continue

        file_date, file_slot = parse_suffix_date_slot(suffix)

        df = load_csv_with_fallback(path)

        if df.empty:
            continue

        df.columns = [str(c).strip() for c in df.columns]

        if "product_name" not in df.columns:
            continue

        for _, row in df.iterrows():
            product_name = normalize_text(row.get("product_name", ""))

            if not product_name:
                continue

            rank = safe_int(row.get("rank"))

            rows.append({
                "date": file_date,
                "slot": file_slot,
                "snapshot_dt": build_snapshot_datetime(file_date, file_slot),
                "product_name": product_name,
                "rank": rank,
                "source_type": normalize_text(row.get("source_type", "")),
            })

    result = pd.DataFrame(rows)

    if not result.empty:
        result["date_dt"] = pd.to_datetime(result["date"], errors="coerce")
        result = result.dropna(subset=["date_dt", "snapshot_dt"])

    return result


def load_product_daily_history() -> pd.DataFrame:
    rows = []

    files = list(PROCESSED_DIR.rglob(f"{PRODUCT_DAILY_PREFIX}*.csv"))

    for path in files:
        df = load_csv_with_fallback(path)

        if df.empty:
            continue

        df.columns = [str(c).strip() for c in df.columns]

        if "product_name" not in df.columns or "period" not in df.columns:
            continue

        for _, row in df.iterrows():
            product_name = normalize_text(row.get("product_name", ""))

            if not product_name:
                continue

            period_dt = pd.to_datetime(row.get("period"), errors="coerce")

            if pd.isna(period_dt):
                continue

            rows.append({
                "product_name": product_name,
                "period": period_dt.strftime("%Y-%m-%d"),
                "period_dt": period_dt,
                "search_ratio": safe_float(row.get("search_ratio")),
                "shopping_ratio": safe_float(row.get("shopping_ratio")),
            })

    result = pd.DataFrame(rows)

    if result.empty:
        return result

    # 같은 상품/날짜가 여러 번 들어오면 가장 큰 ratio를 사용.
    # 초기 라벨링용으로는 "미래에 반응이 관측됐는가"를 보는 목적이라 max가 안전함.
    result = (
        result
        .groupby(["product_name", "period"], as_index=False)
        .agg({
            "period_dt": "max",
            "search_ratio": "max",
            "shopping_ratio": "max",
        })
    )

    return result


# =========================================================
# 4. 라벨 계산 함수
# =========================================================
def has_future_top20(
    top20_df: pd.DataFrame,
    names: set[str],
    base_snapshot_dt: pd.Timestamp,
    base_date: pd.Timestamp,
    days: int,
) -> int:
    if top20_df.empty:
        return 0

    end_date = base_date + pd.Timedelta(days=days)

    sub = top20_df[
        (top20_df["snapshot_dt"] > base_snapshot_dt)
        & (top20_df["date_dt"] <= end_date)
        & (top20_df["product_name"].isin(names))
    ]

    return int(not sub.empty)


def has_future_rank_50(
    candidates_df: pd.DataFrame,
    top20_df: pd.DataFrame,
    names: set[str],
    base_snapshot_dt: pd.Timestamp,
    base_date: pd.Timestamp,
    days: int,
) -> int:
    end_date = base_date + pd.Timedelta(days=days)

    has_top20 = has_future_top20(
        top20_df=top20_df,
        names=names,
        base_snapshot_dt=base_snapshot_dt,
        base_date=base_date,
        days=days,
    )

    if has_top20:
        return 1

    if candidates_df.empty:
        return 0

    sub = candidates_df[
        (candidates_df["snapshot_dt"] > base_snapshot_dt)
        & (candidates_df["date_dt"] <= end_date)
        & (candidates_df["product_name"].isin(names))
        & (candidates_df["rank"].notna())
        & (candidates_df["rank"] <= 50)
    ]

    return int(not sub.empty)


def ratio_up_label(
    daily_df: pd.DataFrame,
    names: set[str],
    base_date: pd.Timestamp,
    current_value: Optional[float],
    days: int,
    up_rate: float,
    min_diff: float,
    min_future_value: float,
    value_col: str,
) -> Optional[int]:
    """
    검색/쇼핑 클릭 상승 라벨 계산.

    상승 인정 조건:
    1. 현재 기준값이 있어야 함
    2. 미래 N일 안의 최대값이 min_future_value 이상이어야 함
    3. 현재 대비 up_rate 이상 상승해야 함
    4. 절대 상승폭이 min_diff 이상이어야 함

    예:
    current = 20
    future_max = 31
    up_rate = 0.30
    min_diff = 10

    31 >= 20 * 1.30  → True
    31 - 20 >= 10    → True
    따라서 상승 인정
    """

    if current_value is None:
        return None

    if daily_df.empty:
        return None

    end_date = base_date + pd.Timedelta(days=days)

    sub = daily_df[
        (daily_df["product_name"].isin(names))
        & (daily_df["period_dt"] > base_date)
        & (daily_df["period_dt"] <= end_date)
    ]

    if sub.empty or value_col not in sub.columns:
        return 0

    future_max = safe_float(sub[value_col].max())

    if future_max is None:
        return 0

    diff = future_max - current_value

    # 미래 최대값 자체가 너무 낮으면 성공으로 보지 않음
    if future_max < min_future_value:
        return 0

    # 현재값이 0 이하이면 비율 계산이 의미 없으므로 절대 상승폭 + 미래 최소값만 본다
    if current_value <= 0:
        return int(diff >= min_diff and future_max >= min_future_value)

    return int(
        (future_max >= current_value * (1 + up_rate))
        and (diff >= min_diff)
        and (future_max >= min_future_value)
    )


def int_or_zero(value: Optional[int]) -> int:
    if value is None:
        return 0
    return int(value)


# =========================================================
# 5. label_outcomes 생성
# =========================================================
def build_labels() -> pd.DataFrame:
    feature_df = load_csv_with_fallback(FEATURE_SNAPSHOTS_FILE)

    if feature_df.empty:
        print("[WARN] feature_snapshots.csv가 없습니다. 먼저 build_model_training_dataset.py를 실행하세요.")
        return pd.DataFrame()

    feature_df.columns = [str(c).strip() for c in feature_df.columns]

    required = {"date", "slot", "product_name"}

    missing = required - set(feature_df.columns)
    if missing:
        raise ValueError(f"feature_snapshots.csv 필수 컬럼 누락: {missing}")

    if "source_type" not in feature_df.columns:
        feature_df["source_type"] = "rising"

    if "canonical_product_name" not in feature_df.columns:
        feature_df["canonical_product_name"] = feature_df["product_name"]

    feature_df["date"] = pd.to_datetime(feature_df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    feature_df["slot"] = feature_df["slot"].map(normalize_slot)
    feature_df["product_name"] = feature_df["product_name"].map(normalize_text)
    feature_df["canonical_product_name"] = feature_df["canonical_product_name"].map(normalize_text)
    feature_df["source_type"] = feature_df["source_type"].map(normalize_text)
    feature_df.loc[feature_df["source_type"] == "", "source_type"] = "rising"

    feature_df["snapshot_dt"] = feature_df.apply(
        lambda r: build_snapshot_datetime(r.get("date"), r.get("slot")),
        axis=1,
    )

    feature_df["date_dt"] = pd.to_datetime(feature_df["date"], errors="coerce")

    feature_df["snapshot_id"] = feature_df.apply(
        lambda r: build_snapshot_id(
            r.get("date"),
            r.get("slot"),
            r.get("source_type"),
            r.get("product_name"),
        ),
        axis=1,
    )

    feature_df = feature_df.dropna(subset=["snapshot_dt", "date_dt"]).copy()

    top20_df = load_top20_history()
    candidates_df = load_candidates_history()
    daily_df = load_product_daily_history()

    observed_dates = []

    if not top20_df.empty:
        observed_dates.append(top20_df["date_dt"].max())

    if not candidates_df.empty:
        observed_dates.append(candidates_df["date_dt"].max())

    if not daily_df.empty:
        observed_dates.append(daily_df["period_dt"].max())

    max_observed_date = max(observed_dates) if observed_dates else None

    print("\n[DEBUG] 라벨 생성 기준 확인")
    print(f"feature 최소 날짜: {feature_df['date_dt'].min()}")
    print(f"feature 최대 날짜: {feature_df['date_dt'].max()}")

    if not top20_df.empty:
        print(f"Top20 관측 최대 날짜: {top20_df['date_dt'].max()}")
    else:
        print("Top20 관측 데이터 없음")

    if not candidates_df.empty:
        print(f"Candidates 관측 최대 날짜: {candidates_df['date_dt'].max()}")
    else:
        print("Candidates 관측 데이터 없음")

    if not daily_df.empty:
        print(f"Product daily 관측 최대 날짜: {daily_df['period_dt'].max()}")
    else:
        print("Product daily 관측 데이터 없음")

    print(f"최종 max_observed_date: {max_observed_date}")

    rows = []

    for _, row in feature_df.iterrows():
        base_date = row["date_dt"]
        base_snapshot_dt = row["snapshot_dt"]
        names = get_match_names(row)

        current_search = safe_float(row.get("current_search_ratio"))
        current_click = safe_float(row.get("current_shopping_ratio"))

        ready_1d = is_ready_for_horizon(base_date, max_observed_date, 1)
        ready_3d = is_ready_for_horizon(base_date, max_observed_date, 3)
        ready_7d = is_ready_for_horizon(base_date, max_observed_date, 7)

        top20_1d = has_future_top20(top20_df, names, base_snapshot_dt, base_date, 1) if ready_1d else None
        top20_3d = has_future_top20(top20_df, names, base_snapshot_dt, base_date, 3) if ready_3d else None
        top20_7d = has_future_top20(top20_df, names, base_snapshot_dt, base_date, 7) if ready_7d else None

        rank50_3d = has_future_rank_50(candidates_df, top20_df, names, base_snapshot_dt, base_date, 3) if ready_3d else None
        rank50_7d = has_future_rank_50(candidates_df, top20_df, names, base_snapshot_dt, base_date, 7) if ready_7d else None

        search_up_3d = (
            ratio_up_label(
                daily_df=daily_df,
                names=names,
                base_date=base_date,
                current_value=current_search,
                days=3,
                up_rate=SEARCH_UP_RATE,
                min_diff=SEARCH_MIN_RATIO_DIFF,
                min_future_value=SEARCH_MIN_FUTURE_RATIO,
                value_col="search_ratio",
            )
            if ready_3d
            else None
        )

        click_up_3d = (
            ratio_up_label(
                daily_df=daily_df,
                names=names,
                base_date=base_date,
                current_value=current_click,
                days=3,
                up_rate=CLICK_UP_RATE,
                min_diff=CLICK_MIN_RATIO_DIFF,
                min_future_value=CLICK_MIN_FUTURE_RATIO,
                value_col="shopping_ratio",
            )
            if ready_3d
            else None
        )

        search_up_7d = (
            ratio_up_label(
                daily_df=daily_df,
                names=names,
                base_date=base_date,
                current_value=current_search,
                days=7,
                up_rate=SEARCH_UP_RATE,
                min_diff=SEARCH_MIN_RATIO_DIFF,
                min_future_value=SEARCH_MIN_FUTURE_RATIO,
                value_col="search_ratio",
            )
            if ready_7d
            else None
        )

        click_up_7d = (
            ratio_up_label(
                daily_df=daily_df,
                names=names,
                base_date=base_date,
                current_value=current_click,
                days=7,
                up_rate=CLICK_UP_RATE,
                min_diff=CLICK_MIN_RATIO_DIFF,
                min_future_value=CLICK_MIN_FUTURE_RATIO,
                value_col="shopping_ratio",
            )
            if ready_7d
            else None
        )

        if ready_3d:
            interest_confirmed_3d = int(
                int_or_zero(top20_3d)
                or int_or_zero(rank50_3d)
                or int_or_zero(search_up_3d)
                or int_or_zero(click_up_3d)
            )
        else:
            interest_confirmed_3d = None

        if ready_7d:
            priority_success_7d = int(
                int_or_zero(top20_7d)
                or int_or_zero(rank50_7d)
                or int_or_zero(search_up_7d)
                or int_or_zero(click_up_7d)
            )
        else:
            priority_success_7d = None

        if ready_7d:
            label_status = "ready"
        elif ready_3d:
            label_status = "partial_ready"
        else:
            label_status = "pending"

        rows.append({
            "snapshot_id": row["snapshot_id"],
            "date": row["date"],
            "slot": row["slot"],
            "source_type": row["source_type"],
            "product_name": row["product_name"],
            "canonical_product_name": row["canonical_product_name"],

            "target_top20_next_1d": top20_1d,
            "target_top20_next_3d": top20_3d,
            "target_top20_next_7d": top20_7d,

            "target_rank_50_next_3d": rank50_3d,
            "target_rank_50_next_7d": rank50_7d,

            "target_search_up_next_3d": search_up_3d,
            "target_click_up_next_3d": click_up_3d,
            "target_search_up_next_7d": search_up_7d,
            "target_click_up_next_7d": click_up_7d,

            "target_interest_confirmed_next_3d": interest_confirmed_3d,
            "target_priority_success_next_7d": priority_success_7d,

            "label_status_1d": "ready" if ready_1d else "pending",
            "label_status_3d": "ready" if ready_3d else "pending",
            "label_status_7d": "ready" if ready_7d else "pending",
            "label_status": label_status,
            "label_created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

    label_df = pd.DataFrame(rows)

    return label_df


# =========================================================
# 6. 저장
# =========================================================
def main():
    ML_DIR.mkdir(parents=True, exist_ok=True)

    label_df = build_labels()

    if label_df.empty:
        print("생성된 label이 없습니다.")
        return

    existing = load_csv_with_fallback(LABEL_OUTCOMES_FILE)

    if existing.empty:
        combined = label_df.copy()
    else:
        existing.columns = [str(c).strip() for c in existing.columns]
        combined = pd.concat([existing, label_df], ignore_index=True)

    combined = combined.drop_duplicates("snapshot_id", keep="last").reset_index(drop=True)
    combined.to_csv(LABEL_OUTCOMES_FILE, index=False, encoding="utf-8-sig")

    print("\n완료")
    print(f"label row 수: {len(combined)}")
    print(f"저장 파일: {LABEL_OUTCOMES_FILE}")

    preview_cols = [
        "date",
        "slot",
        "product_name",
        "target_top20_next_3d",
        "target_rank_50_next_3d",
        "target_search_up_next_3d",
        "target_click_up_next_3d",
        "target_interest_confirmed_next_3d",
        "label_status_3d",
        "label_status_7d",
    ]

    preview_cols = [c for c in preview_cols if c in combined.columns]

    print("\n미리보기")
    print(combined[preview_cols].tail(30).to_string(index=False))


if __name__ == "__main__":
    main()