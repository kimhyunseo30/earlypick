# data-pipeline/scripts/build_rising_candidate_features.py

import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Optional, Dict, Tuple, List

import pandas as pd

print("=== build_rising_candidate_features.py 실행 시작 ===")
print(f"실행 파일 위치: {__file__}")
# =========================================================
# 1. 경로 설정
# =========================================================
BASE_DIR = Path(__file__).resolve().parents[1]

PROCESSED_DIR = BASE_DIR / "data" / "daily" / "processed"
LATEST_DIR = BASE_DIR / "data" / "daily" / "latest"
HISTORICAL_DIR = BASE_DIR / "data" / "historical"

RISING_MASTER_FILE = HISTORICAL_DIR / "rising_candidates_master.csv"
PRODUCT_ALIAS_MAP_FILE = HISTORICAL_DIR / "product_alias_map.csv"

CANDIDATES_PREFIX = "candidates_with_search_shopping_"
RISING_FEATURE_PREFIX = "rising_candidate_features_"

# 특정 날짜/슬롯만 강제로 만들고 싶으면 여기에 입력
# 예: TARGET_DATE = "2026-05-09", TARGET_SLOT = "pm"
TARGET_DATE = None
TARGET_SLOT = None


# =========================================================
# 2. 공통 유틸
# =========================================================
def load_csv_with_fallback(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"파일이 없습니다: {path}")

    if path.stat().st_size == 0:
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


def safe_int(value: Any) -> Optional[int]:
    try:
        if pd.isna(value):
            return None
        return int(float(str(value).replace(",", "").strip()))
    except Exception:
        return None


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(str(value).replace(",", "").strip())
    except Exception:
        return default


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


def build_rank_range(rank: Optional[int]) -> str:
    if rank is None:
        return ""

    if 1 <= rank <= 20:
        return "1-20"

    if 21 <= rank <= 50:
        return "21-50"

    if 51 <= rank <= 100:
        return "51-100"

    if 101 <= rank <= 200:
        return "101-200"

    return ""


def parse_suffix_from_filename(file_name: str, prefix: str) -> Optional[str]:
    if not file_name.startswith(prefix) or not file_name.endswith(".csv"):
        return None

    return file_name[len(prefix):-4]


def parse_suffix_date_slot(suffix: str) -> Tuple[str, str]:
    parts = suffix.rsplit("_", 1)

    if len(parts) != 2:
        return "0000-00-00", "am"

    return parts[0], parts[1]


def find_latest_candidates_file() -> Optional[Path]:
    files = list(PROCESSED_DIR.rglob(f"{CANDIDATES_PREFIX}*.csv"))

    if not files:
        return None

    def sort_key(path: Path):
        suffix = parse_suffix_from_filename(path.name, CANDIDATES_PREFIX)

        if not suffix:
            return ("0000-00-00", 0)

        date_part, slot_part = parse_suffix_date_slot(suffix)
        return date_part, slot_order(slot_part)

    return max(files, key=sort_key)


# =========================================================
# 3. 매핑 파일
# =========================================================
def load_product_alias_map(path: Path) -> Dict[str, str]:
    """
    product_alias_map.csv를 읽어서
    product_name -> canonical name 매핑을 만든다.

    우선순위:
    1. canonical_product_name
    2. canonicalProductName
    3. standard_product_name
    4. marketMatchName
    5. market_match_name
    """

    if not path.exists():
        print(f"[WARN] product_alias_map.csv 없음: {path}")
        return {}

    df = load_csv_with_fallback(path)

    if df.empty:
        return {}

    df.columns = [str(c).strip() for c in df.columns]

    if "product_name" not in df.columns:
        return {}

    canonical_cols = [
        "canonical_product_name",
        "canonicalProductName",
        "standard_product_name",
        "marketMatchName",
        "market_match_name",
    ]

    available_cols = [col for col in canonical_cols if col in df.columns]

    if not available_cols:
        return {}

    df["product_name"] = df["product_name"].astype(str).map(normalize_text)

    alias_map = {}

    for _, row in df.iterrows():
        product_name = normalize_text(row.get("product_name", ""))

        if not product_name:
            continue

        canonical_name = ""

        for col in available_cols:
            value = normalize_text(row.get(col, ""))

            if value:
                canonical_name = value
                break

        if canonical_name:
            alias_map[product_name] = canonical_name

    return alias_map

# =========================================================
# 4. rising 원본 정리
# =========================================================
def load_rising_master(path: Path) -> pd.DataFrame:
    df = load_csv_with_fallback(path)

    if df.empty:
        return pd.DataFrame()

    rename_map = {}

    for col in df.columns:
        lower = str(col).strip().lower()

        if lower in {"date", "날짜"}:
            rename_map[col] = "date"
        elif lower in {"slot", "구분"}:
            rename_map[col] = "slot"
        elif lower in {"rank", "순위"}:
            rename_map[col] = "rank"
        elif lower in {"rank_range", "순위구간"}:
            rename_map[col] = "rank_range"
        elif lower in {"product_name", "상품명", "name"}:
            rename_map[col] = "product_name"
        elif lower in {"source", "출처"}:
            rename_map[col] = "source"
        elif lower in {"note", "메모"}:
            rename_map[col] = "note"
        elif lower in {"is_active", "active", "사용여부"}:
            rename_map[col] = "is_active"
        elif lower in {"product_group", "상품그룹"}:
            rename_map[col] = "product_group"
        elif lower in {"sub_group", "세부그룹"}:
            rename_map[col] = "sub_group"
        elif lower in {"original_product_group", "원본상품그룹"}:
            rename_map[col] = "original_product_group"
        elif lower in {"exclude_from_opportunity", "기회제외"}:
            rename_map[col] = "exclude_from_opportunity"
        elif lower in {"exclude_reason", "제외사유"}:
            rename_map[col] = "exclude_reason"

    df = df.rename(columns=rename_map)

    required = {"date", "slot", "rank", "product_name"}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"rising_candidates_master.csv 필수 컬럼 누락: {missing}")

    for col in [
        "source",
        "note",
        "is_active",
        "rank_range",
        "product_group",
        "sub_group",
        "original_product_group",
        "exclude_from_opportunity",
        "exclude_reason",
    ]:
        if col not in df.columns:
            df[col] = ""

    df["date_dt"] = pd.to_datetime(df["date"], errors="coerce")
    df["date"] = df["date_dt"].dt.strftime("%Y-%m-%d")
    df["slot"] = df["slot"].map(normalize_slot)
    df["slot_order"] = df["slot"].map(slot_order)

    df["rank"] = df["rank"].map(safe_int)
    df["product_name"] = df["product_name"].astype(str).map(normalize_text)
    df["source"] = df["source"].astype(str).map(normalize_text)
    df["note"] = df["note"].astype(str).map(normalize_text)

    df["is_active"] = df["is_active"].astype(str).map(normalize_text)
    df.loc[df["is_active"] == "", "is_active"] = "Y"
    df["is_active"] = df["is_active"].str.upper().str.strip()

    df["exclude_from_opportunity"] = (
        df["exclude_from_opportunity"]
        .astype(str)
        .map(normalize_text)
        .str.upper()
        .str.strip()
    )
    df.loc[df["exclude_from_opportunity"] == "", "exclude_from_opportunity"] = "N"

    for col in ["product_group", "sub_group", "original_product_group", "exclude_reason", "rank_range"]:
        df[col] = df[col].astype(str).map(normalize_text)

    df = df[
        df["date_dt"].notna()
        & df["rank"].notna()
        & (df["product_name"] != "")
        & (df["is_active"] == "Y")
    ].copy()

    df["rank"] = df["rank"].astype(int)

    # rank_range가 비어 있으면 rank 기준으로 자동 생성
    df["rank_range_auto"] = df["rank"].map(build_rank_range)
    df["rank_range"] = df.apply(
        lambda r: r["rank_range"] if normalize_text(r["rank_range"]) else r["rank_range_auto"],
        axis=1,
    )

    df = df.sort_values(["date_dt", "slot_order", "rank"]).reset_index(drop=True)

    return df

def load_rising_history_from_candidate_files() -> pd.DataFrame:
    """
    processed 폴더에 있는 candidates_with_search_shopping_YYYY-MM-DD_slot.csv 전체를 읽어서
    rising 후보 history dataframe으로 변환한다.

    rising_candidates_master.csv에 과거 데이터가 없을 때 사용한다.
    """

    files = list(PROCESSED_DIR.rglob(f"{CANDIDATES_PREFIX}*.csv"))

    if not files:
        print("[WARN] candidates_with_search_shopping 파일을 찾지 못했습니다.")
        return pd.DataFrame()

    frames = []

    print(f"candidates history 파일 수: {len(files)}")

    for path in sorted(files):
        suffix = parse_suffix_from_filename(path.name, CANDIDATES_PREFIX)

        if not suffix:
            continue

        file_date, file_slot = parse_suffix_date_slot(suffix)

        df = load_csv_with_fallback(path)

        if df.empty:
            continue

        df.columns = [str(c).strip() for c in df.columns]

        if "product_name" not in df.columns:
            print(f"[WARN] product_name 없음: {path.name}")
            continue

        # source_type이 있으면 rising만 우선 사용
        if "source_type" in df.columns:
            df["source_type"] = df["source_type"].astype(str).map(normalize_text)
            rising_df = df[df["source_type"].isin(["rising", "naver_rising", "naver_top200"])].copy()

            # source_type 값이 제대로 없으면 전체 사용
            if rising_df.empty:
                rising_df = df.copy()
        else:
            rising_df = df.copy()
            rising_df["source_type"] = "rising"

        rising_df["date"] = file_date
        rising_df["slot"] = normalize_slot(file_slot)

        if "rank" not in rising_df.columns:
            if "todayRank" in rising_df.columns:
                rising_df["rank"] = rising_df["todayRank"]
            elif "naverRank" in rising_df.columns:
                rising_df["rank"] = rising_df["naverRank"]
            else:
                print(f"[WARN] rank 컬럼 없음: {path.name}")
                continue

        for col in [
            "source",
            "note",
            "is_active",
            "rank_range",
            "product_group",
            "sub_group",
            "original_product_group",
            "exclude_from_opportunity",
            "exclude_reason",
        ]:
            if col not in rising_df.columns:
                rising_df[col] = ""

        rising_df["source"] = rising_df.get("source", "naver_top200")
        rising_df["is_active"] = "Y"

        frames.append(rising_df)

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)

    result["date_dt"] = pd.to_datetime(result["date"], errors="coerce")
    result["date"] = result["date_dt"].dt.strftime("%Y-%m-%d")
    result["slot"] = result["slot"].map(normalize_slot)
    result["slot_order"] = result["slot"].map(slot_order)

    result["product_name"] = result["product_name"].astype(str).map(normalize_text)
    result["rank"] = result["rank"].map(safe_int)

    result = result[
        result["date_dt"].notna()
        & result["rank"].notna()
        & (result["product_name"] != "")
    ].copy()

    result["rank"] = result["rank"].astype(int)

    result["rank_range_auto"] = result["rank"].map(build_rank_range)

    result["rank_range"] = result.apply(
        lambda r: normalize_text(r.get("rank_range", "")) or r["rank_range_auto"],
        axis=1,
    )

    for col in [
        "source",
        "note",
        "product_group",
        "sub_group",
        "original_product_group",
        "exclude_from_opportunity",
        "exclude_reason",
    ]:
        result[col] = result[col].astype(str).map(normalize_text)

    result["exclude_from_opportunity"] = (
        result["exclude_from_opportunity"]
        .astype(str)
        .map(normalize_text)
        .str.upper()
    )

    result.loc[result["exclude_from_opportunity"] == "", "exclude_from_opportunity"] = "N"

    result = result.sort_values(["date_dt", "slot_order", "rank"]).reset_index(drop=True)

    print("\n[candidates 기반 history 확인]")
    print(f"전체 row 수: {len(result)}")
    print(f"날짜 범위: {result['date'].min()} ~ {result['date'].max()}")
    print(f"스냅샷 수: {result[['date', 'slot']].drop_duplicates().shape[0]}")

    return result

# =========================================================
# 5. 분석 함수
# =========================================================
def dedupe_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    """
    같은 날짜/slot 안에서 같은 상품이 중복될 경우 더 높은 순위, 즉 숫자가 작은 rank만 사용.
    """
    if df.empty:
        return df

    return (
        df.sort_values(["product_name", "rank"])
        .drop_duplicates(subset=["product_name"], keep="first")
        .sort_values("rank")
        .reset_index(drop=True)
    )


def get_target_date_slot(rising_df: pd.DataFrame) -> Tuple[str, str]:
    if TARGET_DATE and TARGET_SLOT:
        return TARGET_DATE, normalize_slot(TARGET_SLOT)

    latest_candidates = find_latest_candidates_file()

    if latest_candidates is not None:
        suffix = parse_suffix_from_filename(latest_candidates.name, CANDIDATES_PREFIX)

        if suffix:
            date_part, slot_part = parse_suffix_date_slot(suffix)
            print(f"최신 candidates 파일 기준 target 사용: {latest_candidates.name}")
            return date_part, normalize_slot(slot_part)

    # candidates 파일이 없으면 rising master에서 가장 최신 날짜/slot 사용
    latest_row = rising_df.sort_values(["date_dt", "slot_order"]).iloc[-1]
    return latest_row["date"], latest_row["slot"]


def get_previous_snapshot(df: pd.DataFrame, target_date: str, target_slot: str) -> Optional[Tuple[str, str]]:
    target_dt = pd.to_datetime(target_date)
    target_slot_order = slot_order(target_slot)

    snapshots = (
        df[["date", "date_dt", "slot", "slot_order"]]
        .drop_duplicates()
        .sort_values(["date_dt", "slot_order"])
    )

    prev = snapshots[
        (snapshots["date_dt"] < target_dt)
        | (
            (snapshots["date_dt"] == target_dt)
            & (snapshots["slot_order"] < target_slot_order)
        )
    ].copy()

    if prev.empty:
        return None

    row = prev.iloc[-1]
    return row["date"], row["slot"]


def count_days_seen(history: pd.DataFrame, product_name: str, target_dt: pd.Timestamp, days: int) -> int:
    start_dt = target_dt - timedelta(days=days - 1)

    sub = history[
        (history["product_name"] == product_name)
        & (history["date_dt"] >= start_dt)
        & (history["date_dt"] <= target_dt)
    ]

    return int(sub["date"].nunique())


def calculate_consecutive_days(history: pd.DataFrame, product_name: str, target_dt: pd.Timestamp) -> int:
    product_dates = set(
        history.loc[history["product_name"] == product_name, "date_dt"]
        .dropna()
        .dt.strftime("%Y-%m-%d")
        .tolist()
    )

    count = 0
    current = target_dt

    while True:
        date_key = current.strftime("%Y-%m-%d")

        if date_key in product_dates:
            count += 1
            current = current - timedelta(days=1)
        else:
            break

    return count


def best_worst_rank(history: pd.DataFrame, product_name: str, target_dt: pd.Timestamp, days: int = 14) -> Tuple[Optional[int], Optional[int]]:
    start_dt = target_dt - timedelta(days=days - 1)

    sub = history[
        (history["product_name"] == product_name)
        & (history["date_dt"] >= start_dt)
        & (history["date_dt"] <= target_dt)
    ].copy()

    if sub.empty:
        return None, None

    return int(sub["rank"].min()), int(sub["rank"].max())


def calculate_rank_velocity_3d(history: pd.DataFrame, product_name: str, target_dt: pd.Timestamp, current_rank: int) -> Optional[int]:
    """
    최근 3일 안에서 처음 관측 rank - 현재 rank.
    양수면 상승, 음수면 하락.
    예: 142위 -> 43위 = +99
    """
    start_dt = target_dt - timedelta(days=2)

    sub = history[
        (history["product_name"] == product_name)
        & (history["date_dt"] >= start_dt)
        & (history["date_dt"] <= target_dt)
    ].copy()

    if sub.empty:
        return None

    # 하루에 am/pm이 있으면 그날 가장 좋은 rank 사용
    daily_best = (
        sub.sort_values(["date_dt", "rank"])
        .groupby("date", as_index=False)
        .first()
        .sort_values("date")
    )

    if len(daily_best) < 2:
        return None

    first_rank = int(daily_best.iloc[0]["rank"])
    return first_rank - int(current_rank)


def build_rank_direction(rank_change: Optional[int], is_new_entry: bool, is_reentry: bool) -> str:
    if is_new_entry:
        return "new"

    if is_reentry:
        return "reentry"

    if rank_change is None:
        return "none"

    if rank_change > 0:
        return "up"

    if rank_change < 0:
        return "down"

    return "flat"


def build_rank_change_label(rank_change: Optional[int], is_new_entry: bool, is_reentry: bool) -> str:
    if is_new_entry:
        return "NEW"

    if is_reentry:
        return "RE-ENTRY"

    if rank_change is None:
        return "-"

    if rank_change > 0:
        return f"▲ {rank_change}단계"

    if rank_change < 0:
        return f"▼ {abs(rank_change)}단계"

    return "변동없음"


def classify_rising_stage(
    rank: int,
    rank_change: Optional[int],
    rank_velocity_3d: Optional[int],
    is_new_entry: bool,
    is_reentry: bool,
    exclude_from_opportunity: str,
) -> str:
    if exclude_from_opportunity == "Y":
        return "EXCLUDED"

    change = rank_change or 0
    velocity = rank_velocity_3d or 0

    if 21 <= rank <= 50:
        if change >= 20 or velocity >= 20:
            return "NAVER_RISING_FAST"
        return "NAVER_RISING"

    if 51 <= rank <= 100:
        if change >= 20 or velocity >= 20:
            return "NAVER_WARMING_FAST"
        return "NAVER_WARMING"

    if 101 <= rank <= 200:
        if is_new_entry:
            return "NAVER_DETECTED"
        if is_reentry:
            return "NAVER_REENTRY"
        return "NAVER_WATCH"

    return "NAVER_WATCH"


def calculate_rising_score(
    rank: int,
    rank_change: Optional[int],
    days_seen_7d: int,
    consecutive_days: int,
    rank_velocity_3d: Optional[int],
    is_new_entry: bool,
    is_reentry: bool,
    exclude_from_opportunity: str,
) -> float:
    if exclude_from_opportunity == "Y":
        return 0.0

    score = 0.0

    # 1. 현재 순위권
    if 21 <= rank <= 50:
        score += 35
    elif 51 <= rank <= 100:
        score += 22
    elif 101 <= rank <= 200:
        score += 10

    # 2. 전 스냅샷 대비 순위 상승
    if rank_change is not None:
        if rank_change >= 50:
            score += 25
        elif rank_change >= 30:
            score += 20
        elif rank_change >= 20:
            score += 15
        elif rank_change >= 10:
            score += 10
        elif rank_change > 0:
            score += 5
        elif rank_change < 0:
            score -= min(12, abs(rank_change) * 0.3)

    # 3. 최근 7일 등장 횟수
    if days_seen_7d >= 6:
        score += 15
    elif days_seen_7d >= 4:
        score += 12
    elif days_seen_7d >= 3:
        score += 8
    elif days_seen_7d >= 2:
        score += 4

    # 4. 연속 등장
    if consecutive_days >= 5:
        score += 12
    elif consecutive_days >= 3:
        score += 8
    elif consecutive_days >= 2:
        score += 4

    # 5. 최근 3일 상승 속도
    velocity = rank_velocity_3d

    if velocity is not None:
        if velocity >= 50:
            score += 18
        elif velocity >= 30:
            score += 14
        elif velocity >= 20:
            score += 10
        elif velocity >= 10:
            score += 6
        elif velocity < 0:
            score -= min(10, abs(velocity) * 0.2)

    # 6. 신규/재진입 보정
    if is_new_entry and rank <= 50:
        score += 10
    elif is_new_entry:
        score += 4

    if is_reentry and rank <= 100:
        score += 5

    return round(max(0.0, min(100.0, score)), 1)

def classify_rising_level(
    rank: int,
    rising_score: float,
    days_seen_7d: int,
    consecutive_days: int,
    rank_velocity_3d: int | None,
    exclude_from_opportunity: str,
) -> str:
    if exclude_from_opportunity == "Y":
        return "EXCLUDED"

    velocity = rank_velocity_3d or 0

    if rank <= 50 and rising_score >= 70 and days_seen_7d >= 2:
        return "PRIORITY"

    if rank <= 50 and (velocity >= 20 or consecutive_days >= 2):
        return "PRIORITY"

    if rank <= 100 and rising_score >= 45:
        return "WARMING"

    if rank <= 200:
        return "WATCH"

    return "WATCH"


def classify_confidence_level(
    days_seen_7d: int,
    consecutive_days: int,
    rank_velocity_3d: int | None,
    is_new_entry: str,
) -> str:
    velocity = rank_velocity_3d or 0

    if days_seen_7d >= 4 or consecutive_days >= 3:
        return "high"

    if days_seen_7d >= 2 or velocity >= 20:
        return "medium"

    if is_new_entry == "Y":
        return "low"

    return "low"


def build_action_level(
    rising_level: str,
    confidence_level: str,
    has_market_data: bool = False,
) -> str:
    if rising_level == "EXCLUDED":
        return "판단 제외"

    if rising_level == "PRIORITY":
        if has_market_data:
            return "시장 가격 집중 확인"
        return "시장 데이터 확인 필요"

    if rising_level == "WARMING":
        return "관찰 강화"

    return "추가 관찰"


def build_stable_summary(
    product_name: str,
    rank: int,
    rank_change_label: str,
    rising_level: str,
    confidence_level: str,
    days_seen_7d: int,
    rank_velocity_3d: int | None,
) -> str:
    velocity = rank_velocity_3d or 0

    if rising_level == "PRIORITY":
        return (
            f"{product_name}은 네이버 예비 인기권에서 우선 관찰이 필요한 후보입니다. "
            f"현재 {rank}위이며, 최근 7일 중 {days_seen_7d}일 등장했습니다."
        )

    if rising_level == "WARMING":
        return (
            f"{product_name}은 관심 형성 구간에 있는 후보입니다. "
            f"현재 {rank}위이며, 순위 변화는 {rank_change_label}입니다."
        )

    if velocity > 0:
        return (
            f"{product_name}은 초기 관찰 후보입니다. "
            f"최근 3일 기준 {velocity}단계 상승 흐름이 확인됩니다."
        )

    return (
        f"{product_name}은 네이버 21~200위권에서 관찰 중인 후보입니다. "
        f"추가 수집 후 반복 등장 여부를 확인해야 합니다."
    )




def build_reason(
    rank: int,
    rank_change: Optional[int],
    days_seen_7d: int,
    consecutive_days: int,
    rank_velocity_3d: Optional[int],
    is_new_entry: bool,
    is_reentry: bool,
    exclude_from_opportunity: str,
    exclude_reason: str,
) -> str:
    if exclude_from_opportunity == "Y":
        return exclude_reason or "기회 판단 제외 상품입니다."

    reasons = []

    if 21 <= rank <= 50:
        reasons.append("Top20 진입 직전 구간")
    elif 51 <= rank <= 100:
        reasons.append("중위권 관심 형성 구간")
    elif 101 <= rank <= 200:
        reasons.append("초기 관찰 구간")

    if is_new_entry:
        reasons.append("신규 진입")
    elif is_reentry:
        reasons.append("재진입")

    if rank_change is not None:
        if rank_change >= 30:
            reasons.append("전 스냅샷 대비 급상승")
        elif rank_change >= 10:
            reasons.append("전 스냅샷 대비 상승")
        elif rank_change < 0:
            reasons.append("순위 하락")

    if rank_velocity_3d is not None:
        if rank_velocity_3d >= 30:
            reasons.append("최근 3일 상승 속도 빠름")
        elif rank_velocity_3d >= 10:
            reasons.append("최근 3일 상승 흐름")

    if days_seen_7d >= 4:
        reasons.append(f"최근 7일 중 {days_seen_7d}일 등장")

    if consecutive_days >= 3:
        reasons.append(f"{consecutive_days}일 연속 등장")

    if not reasons:
        return "추가 관찰이 필요한 네이버 예비 인기권 후보입니다."

    return " · ".join(reasons)


# =========================================================
# 6. feature 생성
# =========================================================
def build_features(rising_df: pd.DataFrame, target_date: str, target_slot: str) -> pd.DataFrame:
    target_dt = pd.to_datetime(target_date)
    target_slot = normalize_slot(target_slot)
    target_slot_order = slot_order(target_slot)

    target_df = rising_df[
        (rising_df["date"] == target_date)
        & (rising_df["slot"] == target_slot)
    ].copy()

    if target_df.empty:
        raise ValueError(f"rising master에 target 데이터가 없습니다: {target_date}_{target_slot}")

    target_df = dedupe_snapshot(target_df)

    previous_snapshot = get_previous_snapshot(rising_df, target_date, target_slot)

    if previous_snapshot:
        prev_date, prev_slot = previous_snapshot

        prev_df = rising_df[
            (rising_df["date"] == prev_date)
            & (rising_df["slot"] == prev_slot)
        ].copy()

        prev_df = dedupe_snapshot(prev_df)

        prev_lookup = prev_df.set_index("product_name")["rank"].to_dict()

        print(f"이전 스냅샷: {prev_date}_{prev_slot} / {len(prev_lookup)}개")
    else:
        prev_lookup = {}
        print("이전 스냅샷 없음")

    alias_map = load_product_alias_map(PRODUCT_ALIAS_MAP_FILE)

    rows: List[Dict[str, Any]] = []

    for _, row in target_df.iterrows():
        product_name = normalize_text(row.get("product_name", ""))
        rank = int(row.get("rank"))

        prev_rank = prev_lookup.get(product_name)
        rank_change = None

        if prev_rank is not None:
            rank_change = int(prev_rank) - int(rank)

        prior_history = rising_df[
            (
                (rising_df["date_dt"] < target_dt)
                | (
                    (rising_df["date_dt"] == target_dt)
                    & (rising_df["slot_order"] < target_slot_order)
                )
            )
            & (rising_df["product_name"] == product_name)
        ].copy()

        is_new_entry = prior_history.empty
        is_reentry = (prev_rank is None) and (not prior_history.empty)

        last_seen_date = ""
        last_seen_slot = ""
        last_seen_rank = None
        days_since_last_seen = None

        if not prior_history.empty:
            last_seen = prior_history.sort_values(["date_dt", "slot_order"]).iloc[-1]
            last_seen_date = normalize_text(last_seen.get("date", ""))
            last_seen_slot = normalize_text(last_seen.get("slot", ""))
            last_seen_rank = safe_int(last_seen.get("rank"))

            last_seen_dt = pd.to_datetime(last_seen_date, errors="coerce")

            if pd.notna(last_seen_dt):
                days_since_last_seen = int((target_dt - last_seen_dt).days)

        days_seen_7d = count_days_seen(rising_df, product_name, target_dt, 7)
        days_seen_14d = count_days_seen(rising_df, product_name, target_dt, 14)
        consecutive_days = calculate_consecutive_days(rising_df, product_name, target_dt)
        best_rank_14d, worst_rank_14d = best_worst_rank(rising_df, product_name, target_dt, 14)
        rank_velocity_3d = calculate_rank_velocity_3d(rising_df, product_name, target_dt, rank)

        exclude_from_opportunity = normalize_text(row.get("exclude_from_opportunity", "N")).upper() or "N"
        exclude_reason = normalize_text(row.get("exclude_reason", ""))

        rising_stage = classify_rising_stage(
            rank=rank,
            rank_change=rank_change,
            rank_velocity_3d=rank_velocity_3d,
            is_new_entry=is_new_entry,
            is_reentry=is_reentry,
            exclude_from_opportunity=exclude_from_opportunity,
        )

        rising_score = calculate_rising_score(
            rank=rank,
            rank_change=rank_change,
            days_seen_7d=days_seen_7d,
            consecutive_days=consecutive_days,
            rank_velocity_3d=rank_velocity_3d,
            is_new_entry=is_new_entry,
            is_reentry=is_reentry,
            exclude_from_opportunity=exclude_from_opportunity,
        )

        rank_direction = build_rank_direction(rank_change, is_new_entry, is_reentry)
        rank_change_label = build_rank_change_label(rank_change, is_new_entry, is_reentry)



        rising_level = classify_rising_level(
            rank=rank,
            rising_score=rising_score,
            days_seen_7d=days_seen_7d,
            consecutive_days=consecutive_days,
            rank_velocity_3d=rank_velocity_3d,
            exclude_from_opportunity=exclude_from_opportunity,
        )

        confidence_level = classify_confidence_level(
            days_seen_7d=days_seen_7d,
            consecutive_days=consecutive_days,
            rank_velocity_3d=rank_velocity_3d,
            is_new_entry="Y" if is_new_entry else "N",
        )

        action_level = build_action_level(
            rising_level=rising_level,
            confidence_level=confidence_level,
            has_market_data=False,
        )

        stable_summary = build_stable_summary(
            product_name=product_name,
            rank=rank,
            rank_change_label=rank_change_label,
            rising_level=rising_level,
            confidence_level=confidence_level,
            days_seen_7d=days_seen_7d,
            rank_velocity_3d=rank_velocity_3d,
        )

        rising_reason = build_reason(
            rank=rank,
            rank_change=rank_change,
            days_seen_7d=days_seen_7d,
            consecutive_days=consecutive_days,
            rank_velocity_3d=rank_velocity_3d,
            is_new_entry=is_new_entry,
            is_reentry=is_reentry,
            exclude_from_opportunity=exclude_from_opportunity,
            exclude_reason=exclude_reason,
        )

        canonical_product_name = alias_map.get(product_name, product_name)

        rows.append({
            "date": target_date,
            "slot": target_slot,
            "source_type": "rising",
            "source": normalize_text(row.get("source", "naver_top200")) or "naver_top200",

            "product_name": product_name,
            "canonical_product_name": canonical_product_name,

            "rank": rank,
            "rank_range": normalize_text(row.get("rank_range", "")) or build_rank_range(rank),

            "prev_rank": prev_rank,
            "rank_change": rank_change,
            "rank_direction": rank_direction,
            "rank_change_label": rank_change_label,

            "is_new_entry": "Y" if is_new_entry else "N",
            "is_reentry": "Y" if is_reentry else "N",

            "last_seen_date": last_seen_date,
            "last_seen_slot": last_seen_slot,
            "last_seen_rank": last_seen_rank,
            "days_since_last_seen": days_since_last_seen,

            "days_seen_7d": days_seen_7d,
            "days_seen_14d": days_seen_14d,
            "consecutive_days": consecutive_days,

            "best_rank_14d": best_rank_14d,
            "worst_rank_14d": worst_rank_14d,
            "rank_velocity_3d": rank_velocity_3d,

            "rising_stage": rising_stage,
            "rising_score": rising_score,
            "rising_reason": rising_reason,

            "rising_level": rising_level,
            "confidence_level": confidence_level,
            "action_level": action_level,
            "stable_summary": stable_summary,

            "product_group": normalize_text(row.get("product_group", "")),
            "sub_group": normalize_text(row.get("sub_group", "")),
            "original_product_group": normalize_text(row.get("original_product_group", "")),
            "exclude_from_opportunity": exclude_from_opportunity,
            "exclude_reason": exclude_reason,

            "note": normalize_text(row.get("note", "")),
        })

    features_df = pd.DataFrame(rows)

    features_df = features_df.sort_values(
        ["exclude_from_opportunity", "rising_score", "rank"],
        ascending=[True, False, True],
    ).reset_index(drop=True)

    return features_df


# =========================================================
# 7. 저장
# =========================================================
def save_outputs(features_df: pd.DataFrame, target_date: str, target_slot: str) -> Tuple[Path, Path]:
    month_dir = datetime.strptime(target_date, "%Y-%m-%d").strftime("%Y-%m")

    output_dir = PROCESSED_DIR / month_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    LATEST_DIR.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{RISING_FEATURE_PREFIX}{target_date}_{target_slot}.csv"
    latest_path = LATEST_DIR / "rising_candidate_features_latest.csv"

    features_df.to_csv(output_path, index=False, encoding="utf-8-sig")
    features_df.to_csv(latest_path, index=False, encoding="utf-8-sig")

    return output_path, latest_path


# =========================================================
# 8. 메인
# =========================================================
def main():
    # 1차: rising_candidates_master.csv 읽기
    rising_df = load_rising_master(RISING_MASTER_FILE)

    print("\n[rising_candidates_master 확인]")
    if not rising_df.empty:
        print(f"row 수: {len(rising_df)}")
        print(f"날짜 범위: {rising_df['date'].min()} ~ {rising_df['date'].max()}")
        print(f"스냅샷 수: {rising_df[['date', 'slot']].drop_duplicates().shape[0]}")
    else:
        print("rising_candidates_master 데이터 없음")

    # master에 스냅샷이 1개 이하라면 candidates 파일 전체로 대체
    snapshot_count = 0

    if not rising_df.empty:
        snapshot_count = rising_df[["date", "slot"]].drop_duplicates().shape[0]

    if snapshot_count <= 1:
        print("\n[INFO] rising_candidates_master에 과거 스냅샷이 부족합니다.")
        print("[INFO] candidates_with_search_shopping_*.csv 전체를 사용합니다.")

        candidate_history_df = load_rising_history_from_candidate_files()

        if not candidate_history_df.empty:
            rising_df = candidate_history_df

    if rising_df.empty:
        raise ValueError("rising 후보 history 데이터를 만들 수 없습니다.")

    # 특정 날짜/슬롯 지정이 있으면 하나만 생성
    if TARGET_DATE and TARGET_SLOT:
        targets = [(TARGET_DATE, normalize_slot(TARGET_SLOT))]
    else:
        snapshots = (
            rising_df[["date", "date_dt", "slot", "slot_order"]]
            .drop_duplicates()
            .sort_values(["date_dt", "slot_order"])
        )

        targets = [
            (row["date"], row["slot"])
            for _, row in snapshots.iterrows()
        ]

    print(f"\n생성 대상 스냅샷 수: {len(targets)}")

    all_outputs = []

    for target_date, target_slot in targets:
        try:
            print("\n" + "=" * 60)
            print(f"기준일: {target_date}")
            print(f"slot: {target_slot}")

            features_df = build_features(rising_df, target_date, target_slot)
            output_path, latest_path = save_outputs(features_df, target_date, target_slot)

            all_outputs.append({
                "date": target_date,
                "slot": target_slot,
                "rows": len(features_df),
                "output_path": str(output_path),
            })

            print(f"완료: {len(features_df)} rows")
            print(f"저장 파일: {output_path}")

        except Exception as e:
            print(f"[ERROR] {target_date}_{target_slot} 생성 실패: {e}")

    print("\n전체 생성 완료")
    print(f"성공 스냅샷 수: {len(all_outputs)}")

    if all_outputs:
        summary_df = pd.DataFrame(all_outputs)
        print(summary_df.to_string(index=False))

if __name__ == "__main__":
    main()   