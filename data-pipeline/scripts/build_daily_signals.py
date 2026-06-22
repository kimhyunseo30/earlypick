import json
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

import pandas as pd


# =========================================================
# 1. 경로 설정
# =========================================================
BASE_DIR = Path(__file__).resolve().parents[1]

PROCESSED_DIR = BASE_DIR / "data" / "daily" / "processed"
OUTPUT_DIR = BASE_DIR / "data" / "daily" / "output"
LATEST_DIR = BASE_DIR / "data" / "daily" / "latest"

# React public 경로
FRONTEND_PUBLIC_DIR = BASE_DIR.parent / "earlypick-frontend" / "public"

# 선택: 수동 이벤트 태그
EVENT_TAG_FILE = BASE_DIR / "data" / "historical" / "event_tags.csv"
PRODUCT_TYPE_MAP_FILE = BASE_DIR / "data" / "historical" / "product_type_map.csv"
PRODUCT_ALIAS_MAP_FILE = BASE_DIR / "data" / "historical" / "product_alias_map.csv"

# 파일 prefix
TOP20_PREFIX = "top20_with_search_shopping_"
PRODUCT_DAILY_PREFIX = "product_daily_search_shopping_"
CANDIDATES_PREFIX = "candidates_with_search_shopping_"
KAMIS_PRICE_DAILY_PREFIX = "kamis_price_daily_"
KAMIS_MAP_FILE = BASE_DIR / "data" / "historical" / "kamis_item_map.csv"

AUCTION_SUMMARY_PREFIX = "auction_summary_"
AUCTION_MARKET_SUMMARY_PREFIX = "auction_market_summary_"
AUCTION_VARIETY_SUMMARY_PREFIX = "auction_variety_summary_"
RISING_FEATURE_PREFIX = "rising_candidate_features_"


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


def safe_float(value, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def normalize_text(value: Any) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass

    text = str(value).strip()

    if text.lower() in ["nan", "none", "null", "<na>"]:
        return ""

    return text


def unique_keep_order(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        key = normalize_text(item)
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return result


def save_json(data: Any, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_event_tags(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["product_name", "event_tag"])

    df = load_csv_with_fallback(path)

    if df.empty:
        return pd.DataFrame(columns=["product_name", "event_tag"])

    rename_map = {}
    for col in df.columns:
        lower = str(col).strip().lower()
        if lower in {"product_name", "상품명", "name"}:
            rename_map[col] = "product_name"
        elif lower in {"event_tag", "이벤트", "tag", "이벤트태그"}:
            rename_map[col] = "event_tag"

    df = df.rename(columns=rename_map)

    if not {"product_name", "event_tag"}.issubset(df.columns):
        print("event_tags.csv 컬럼 형식이 맞지 않아 이벤트 태그는 건너뜁니다.")
        return pd.DataFrame(columns=["product_name", "event_tag"])

    df["product_name"] = df["product_name"].astype(str).map(normalize_text)
    df["event_tag"] = df["event_tag"].astype(str).map(normalize_text)
    df = df[(df["product_name"] != "") & (df["event_tag"] != "")]
    return df


# =========================================================
# 3. 최신 processed 파일 찾기
# =========================================================
def extract_date_slot_from_name(file_name: str, prefix: str) -> Tuple[str, str]:
    if not file_name.startswith(prefix) or not file_name.endswith(".csv"):
        return ("0000-00-00", "am")

    suffix = file_name[len(prefix):-4]
    parts = suffix.rsplit("_", 1)

    if len(parts) != 2:
        return ("0000-00-00", "am")

    date_part, slot_part = parts[0], parts[1]
    return (date_part, slot_part)


def find_latest_top20_file() -> Path:
    files = list(PROCESSED_DIR.rglob(f"{TOP20_PREFIX}*.csv"))
    if not files:
        raise FileNotFoundError("processed 폴더에 top20_with_search_shopping_*.csv 파일이 없습니다.")

    def sort_key(path: Path):
        date_part, slot_part = extract_date_slot_from_name(path.name, TOP20_PREFIX)
        slot_order = 0 if slot_part == "am" else 1
        return (date_part, slot_order)

    return max(files, key=sort_key)


def parse_suffix_from_filename(file_name: str, prefix: str) -> Optional[str]:
    if not file_name.startswith(prefix) or not file_name.endswith(".csv"):
        return None
    return file_name[len(prefix):-4]


def find_matching_file(prefix: str, suffix: str) -> Path:
    candidates = list(PROCESSED_DIR.rglob(f"{prefix}{suffix}.csv"))
    if not candidates:
        raise FileNotFoundError(f"processed 폴더에 {prefix}{suffix}.csv 파일이 없습니다.")
    return candidates[0]


def find_optional_matching_file(prefix: str, suffix: str) -> Optional[Path]:
    candidates = list(PROCESSED_DIR.rglob(f"{prefix}{suffix}.csv"))
    return candidates[0] if candidates else None

def parse_suffix_date_slot(suffix: str) -> Tuple[str, str]:
    parts = suffix.rsplit("_", 1)
    if len(parts) != 2:
        return ("0000-00-00", "am")
    return parts[0], parts[1]


def find_previous_day_file(prefix: str, current_suffix: str) -> Optional[Path]:
    current_date, current_slot = parse_suffix_date_slot(current_suffix)

    files = list(PROCESSED_DIR.rglob(f"{prefix}*.csv"))
    previous_files = []

    for path in files:
        suffix = parse_suffix_from_filename(path.name, prefix)
        if not suffix:
            continue

        date_part, slot_part = parse_suffix_date_slot(suffix)

        # 같은 날짜 am/pm 비교가 아니라, 전날 데이터만 비교
        if date_part < current_date:
            previous_files.append((path, date_part, slot_part))

    if not previous_files:
        return None

    # 가능하면 같은 slot 우선
    same_slot = [x for x in previous_files if x[2] == current_slot]
    target_pool = same_slot if same_slot else previous_files

    def sort_key(item):
        path, date_part, slot_part = item
        slot_order = 0 if slot_part == "am" else 1
        return (date_part, slot_order)

    return max(target_pool, key=sort_key)[0]


def load_previous_rank_lookup(path: Optional[Path]) -> Dict[str, int]:
    if path is None or not path.exists():
        return {}

    df = load_csv_with_fallback(path)
    if df.empty:
        return {}

    df.columns = [str(c).strip() for c in df.columns]

    required = {"product_name", "source_type", "rank"}
    missing = required - set(df.columns)
    if missing:
        print(f"이전 후보 파일에 순위 비교용 컬럼 누락: {missing}")
        return {}

    df["product_name"] = df["product_name"].astype(str).map(normalize_text)
    df["source_type"] = df["source_type"].astype(str).map(normalize_text)
    df["rank"] = pd.to_numeric(df["rank"], errors="coerce")

    df = df[
        df["source_type"].isin(["top20", "rising"])
        & df["rank"].notna()
        & (df["product_name"] != "")
    ].copy()

    if df.empty:
        return {}

    df["rank"] = df["rank"].astype(int)

    # 같은 상품이 중복될 경우 더 높은 순위, 즉 숫자가 작은 rank 사용
    rank_lookup = (
        df.sort_values("rank")
        .drop_duplicates(subset=["product_name"])
        .set_index("product_name")["rank"]
        .to_dict()
    )

    return rank_lookup

def safe_int_or_none(value):
    try:
        if pd.isna(value):
            return None
        return int(float(str(value).replace(",", "").strip()))
    except Exception:
        return None


def load_rising_feature_lookup(path: Optional[Path]) -> Dict[str, Dict[str, Any]]:
    if path is None or not path.exists():
        return {}

    df = load_csv_with_fallback(path)

    if df.empty:
        return {}

    df.columns = [str(c).strip() for c in df.columns]

    if "product_name" not in df.columns:
        print("rising feature 파일에 product_name 컬럼이 없습니다.")
        return {}

    df["product_name"] = df["product_name"].astype(str).map(normalize_text)

    lookup: Dict[str, Dict[str, Any]] = {}

    for _, row in df.iterrows():
        product_name = normalize_text(row.get("product_name", ""))

        if not product_name:
            continue

        lookup[product_name] = {
            "canonicalProductName": normalize_text(row.get("canonical_product_name", "")),
            "risingStage": normalize_text(row.get("rising_stage", "")),
            "risingScore": safe_float(row.get("rising_score"), 0.0),
            "risingReason": normalize_text(row.get("rising_reason", "")),

            "risingLevel": normalize_text(row.get("rising_level", "")),
            "confidenceLevel": normalize_text(row.get("confidence_level", "")),
            "actionLevel": normalize_text(row.get("action_level", "")),
            "stableSummary": normalize_text(row.get("stable_summary", "")),

            "daysSeen7d": safe_int_or_none(row.get("days_seen_7d")),
            "daysSeen14d": safe_int_or_none(row.get("days_seen_14d")),
            "consecutiveDays": safe_int_or_none(row.get("consecutive_days")),
            "bestRank14d": safe_int_or_none(row.get("best_rank_14d")),
            "worstRank14d": safe_int_or_none(row.get("worst_rank_14d")),
            "rankVelocity3d": safe_int_or_none(row.get("rank_velocity_3d")),

            "isNewEntry": normalize_text(row.get("is_new_entry", "")),
            "isReentry": normalize_text(row.get("is_reentry", "")),
            "lastSeenDate": normalize_text(row.get("last_seen_date", "")),
            "daysSinceLastSeen": safe_int_or_none(row.get("days_since_last_seen")),
        }

    return lookup




def build_rank_change_info(
    today_rank: Optional[int],
    previous_rank: Optional[int],
) -> Dict[str, Any]:
    if today_rank is None:
        return {
            "previousRank": previous_rank,
            "rankChange": None,
            "rankDirection": "none",
            "rankChangeLabel": "-",
        }

    if previous_rank is None:
        return {
            "previousRank": None,
            "rankChange": None,
            "rankDirection": "new",
            "rankChangeLabel": "NEW",
        }

    change = previous_rank - today_rank

    if change > 0:
        return {
            "previousRank": previous_rank,
            "rankChange": change,
            "rankDirection": "up",
            "rankChangeLabel": f"▲ {change}단계",
        }

    if change < 0:
        return {
            "previousRank": previous_rank,
            "rankChange": change,
            "rankDirection": "down",
            "rankChangeLabel": f"▼ {abs(change)}단계",
        }

    return {
        "previousRank": previous_rank,
        "rankChange": 0,
        "rankDirection": "flat",
        "rankChangeLabel": "변동없음",
    }

# =========================================================
# 4. 가격 요약 로딩
# =========================================================
def get_price_as_of_date(price_daily_file: Optional[Path]) -> str:
    if price_daily_file is None or not price_daily_file.exists():
        return ""

    df = load_csv_with_fallback(price_daily_file)

    if df.empty:
        return ""

    if "full_regday" in df.columns:
        dates = pd.to_datetime(df["full_regday"], errors="coerce")
    elif "regday_dt" in df.columns:
        dates = pd.to_datetime(df["regday_dt"], errors="coerce")
    else:
        return ""

    max_date = dates.max()

    if pd.isna(max_date):
        return ""

    return max_date.strftime("%Y-%m-%d")


def load_price_detail_lookup(path: Optional[Path]) -> Dict[str, Dict[str, Any]]:
    if path is None or not path.exists():
        return {}

    df = load_csv_with_fallback(path)
    if df.empty:
        return {}

    df.columns = [str(c).strip() for c in df.columns]

    required = {"product_name", "price_type"}
    missing = required - set(df.columns)
    if missing:
        print(f"KAMIS 가격 상세 파일 필수 컬럼 누락: {missing}")
        return {}

    df["product_name"] = df["product_name"].astype(str).map(normalize_text)

    if "price_num" not in df.columns:
        df["price_num"] = (
            df["price"]
            .astype(str)
            .str.replace(",", "", regex=False)
            .str.extract(r"(\d+\.?\d*)")[0]
            .astype(float)
        )

    if "regday_dt" in df.columns:
        df["regday_dt"] = pd.to_datetime(df["regday_dt"], errors="coerce")
    elif "full_regday" in df.columns:
        df["regday_dt"] = pd.to_datetime(df["full_regday"], errors="coerce")
    else:
        df["regday_dt"] = pd.NaT

    for col in [
        "item_name",
        "kind_name",
        "rank_name",
        "unit_name",
        "countyname",
        "marketname",
        "itemcode",
        "kindcode",
        "productrankcode",
    ]:
        if col not in df.columns:
            df[col] = ""

    df["item_name"] = df["item_name"].map(clean_display_value)
    df["kind_name"] = df["kind_name"].map(clean_display_value)
    df["rank_name"] = df["rank_name"].map(clean_display_value)
    df["unit_name"] = df["unit_name"].map(clean_display_value)
    df["countyname"] = df["countyname"].map(clean_display_value)
    df["marketname"] = df["marketname"].map(clean_display_value)

    df["itemcode_key"] = df["itemcode"].map(lambda x: normalize_kamis_code(x, 3))
    df["kindcode_key"] = df["kindcode"].map(lambda x: normalize_kamis_code(x, 2))
    df["productrankcode_key"] = df["productrankcode"].map(lambda x: normalize_kamis_code(x, 2))   

    df = df.dropna(subset=["price_num"]).copy()

    detail_lookup: Dict[str, Dict[str, Any]] = {}

    for product_name, product_group in df.groupby("product_name"):
        result = {
            "wholesaleAverageNow": None,
            "retailAverageNow": None,
            "wholesaleSeries7d": [],
            "retailSeries7d": [],
            "wholesaleMarkets": [],
            "retailMarkets": [],
            "variants": [],
        }

        variant_keys = (
            product_group[
                [
                    "item_name",
                    "kind_name",
                    "rank_name",
                    "itemcode_key",
                    "kindcode_key",
                    "productrankcode_key",
                ]
            ]
            .drop_duplicates()
            .sort_values(["kind_name", "productrankcode_key"])
            .to_dict("records")
        )

        for variant in variant_keys:
            item_name = normalize_text(variant.get("item_name", ""))
            kind_name = normalize_text(variant.get("kind_name", ""))
            rank_name = normalize_text(variant.get("rank_name", ""))
            itemcode = normalize_text(variant.get("itemcode_key", ""))
            kindcode = normalize_text(variant.get("kindcode_key", ""))
            productrankcode = normalize_text(variant.get("productrankcode_key", ""))

            variant_df = product_group[
                (product_group["itemcode_key"] == itemcode)
                & (product_group["kindcode_key"] == kindcode)
                & (product_group["productrankcode_key"] == productrankcode)
            ].copy()

            variant_result = {
                "itemName": item_name,
                "kindName": kind_name,
                "rankName": rank_name,
                "itemcode": itemcode,
                "kindcode": kindcode,
                "productrankcode": productrankcode,
                "wholesaleUnitName": None,
                "retailUnitName": None,
                "wholesalePriceNow": None,
                "retailPriceNow": None,
                "wholesaleChangeRate": None,
                "retailChangeRate": None,
                "wholesaleTrend": None,
                "retailTrend": None,
                "wholesaleDate": None,
                "retailDate": None,
            }

            for price_type in ["wholesale", "retail"]:
                typed = variant_df[variant_df["price_type"] == price_type].copy()

                if typed.empty:
                    continue

                avg_group = typed[
                    typed["countyname"].astype(str).str.strip() == "평균"
                ].copy()

                target = avg_group if not avg_group.empty else typed

                if target["regday_dt"].notna().any():
                    target = target.sort_values("regday_dt")
                else:
                    target = target.reset_index(drop=True)

                latest = target.iloc[-1]
                prev = target.iloc[-2] if len(target) >= 2 else None

                latest_price = safe_float(latest.get("price_num"), 0.0)
                change_rate = None
                trend = "보합"

                if prev is not None:
                    prev_price = safe_float(prev.get("price_num"), 0.0)

                    if prev_price > 0:
                        change_rate = round(((latest_price - prev_price) / prev_price) * 100, 1)

                        if change_rate >= 1:
                            trend = "상승"
                        elif change_rate <= -1:
                            trend = "하락"

                date_value = latest.get("regday_dt")
                date_label = date_value.strftime("%m-%d") if pd.notna(date_value) else ""

                if price_type == "wholesale":
                    variant_result["wholesaleUnitName"] = clean_display_value(latest.get("unit_name", ""))
                    variant_result["wholesalePriceNow"] = round(latest_price, 1)
                    variant_result["wholesaleChangeRate"] = change_rate
                    variant_result["wholesaleTrend"] = trend
                    variant_result["wholesaleDate"] = date_label

                else:
                    variant_result["retailUnitName"] = clean_display_value(latest.get("unit_name", ""))
                    variant_result["retailPriceNow"] = round(latest_price, 1)
                    variant_result["retailChangeRate"] = change_rate
                    variant_result["retailTrend"] = trend
                    variant_result["retailDate"] = date_label

            if (
                variant_result["wholesalePriceNow"] is not None
                or variant_result["retailPriceNow"] is not None
            ):
                result["variants"].append(variant_result)

        # 대표 가격/차트는 우선 상품 등급 + 첫 번째 품종 기준으로 요약
        representative = None

        product_variants = result["variants"]

        if product_variants:
            상품_variants = [v for v in product_variants if v.get("rankName") == "상품"]
            representative = 상품_variants[0] if 상품_variants else product_variants[0]

            result["wholesaleAverageNow"] = representative.get("wholesalePriceNow")
            result["retailAverageNow"] = representative.get("retailPriceNow")

        if representative:
            rep_itemcode = representative.get("itemcode", "")
            rep_kindcode = representative.get("kindcode", "")
            rep_rankcode = representative.get("productrankcode", "")

            rep_df = product_group[
                (product_group["itemcode_key"] == str(rep_itemcode))
                & (product_group["kindcode_key"] == str(rep_kindcode))
                & (product_group["productrankcode_key"] == str(rep_rankcode))
            ].copy()

            for price_type in ["wholesale", "retail"]:
                typed = rep_df[rep_df["price_type"] == price_type].copy()
                avg_group = typed[
                    typed["countyname"].astype(str).str.strip() == "평균"
                ].copy()

                target = avg_group if not avg_group.empty else typed

                if target.empty:
                    continue

                target = target.sort_values("regday_dt")
                series7 = target.tail(7)

                series = [
                    {
                        "date": d.strftime("%m-%d") if pd.notna(d) else "",
                        "value": round(safe_float(v), 1),
                    }
                    for d, v in zip(series7["regday_dt"], series7["price_num"])
                ]

                if price_type == "wholesale":
                    result["wholesaleSeries7d"] = series
                else:
                    result["retailSeries7d"] = series

        # 주요 시장별 가격은 기존처럼 최신일 기준 일부만 유지
        for price_type in ["wholesale", "retail"]:
            typed = product_group[product_group["price_type"] == price_type].copy()

            if typed.empty:
                continue

            latest_date = typed["regday_dt"].max() if typed["regday_dt"].notna().any() else pd.NaT

            if pd.notna(latest_date):
                market_rows = typed[
                    (typed["regday_dt"] == latest_date)
                    & (~typed["countyname"].astype(str).str.strip().isin(["평균", "평년"]))
                    & (typed["marketname"].astype(str).str.strip() != "")
                ].copy()
            else:
                market_rows = pd.DataFrame()

            if not market_rows.empty:
                market_rows = market_rows.sort_values(
                    ["kind_name", "rank_name", "countyname", "marketname"]
                ).head(10)

                market_list = [
                    {
                        "kindName": normalize_text(row.get("kind_name", "")),
                        "rankName": normalize_text(row.get("rank_name", "")),
                        "county": normalize_text(row.get("countyname", "")),
                        "market": normalize_text(row.get("marketname", "")),
                        "unitName": clean_display_value(row.get("unit_name", "")),
                        "price": round(safe_float(row.get("price_num"), 0.0), 1),
                        "date": latest_date.strftime("%m-%d") if pd.notna(latest_date) else "",
                    }
                    for _, row in market_rows.iterrows()
                ]

                if price_type == "wholesale":
                    result["wholesaleMarkets"] = market_list
                else:
                    result["retailMarkets"] = market_list

        detail_lookup[product_name] = result

    return detail_lookup

def clean_display_value(value: Any) -> str:
    if pd.isna(value):
        return ""

    text = str(value).strip()

    if text.lower() in {"nan", "none", "null"}:
        return ""

    return normalize_text(text)


def load_kamis_meta_lookup(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        return {}

    df = load_csv_with_fallback(path)
    if df.empty:
        return {}

    df.columns = [str(c).strip() for c in df.columns]

    if "product_name" not in df.columns:
        return {}

    required_cols = [
        "item_name",
        "kind_name",
        "rank_name",
        "retail_unit_name",
        "wholesale_unit_name",
        "label",
    ]

    for col in required_cols:
        if col not in df.columns:
            df[col] = ""

    df["product_name"] = df["product_name"].astype(str).map(normalize_text)

    lookup: Dict[str, Dict[str, Any]] = {}

    for product_name, group in df.groupby("product_name"):
        group = group.copy()

        # 대표 메타는 상품 등급을 우선 사용
        preferred = group[group["rank_name"].astype(str).str.strip() == "상품"].copy()

        if preferred.empty:
            preferred = group[
                group["rank_name"].astype(str).str.contains("상품", na=False)
            ].copy()

        target = preferred.iloc[0] if not preferred.empty else group.iloc[0]

        lookup[product_name] = {
            "itemName": clean_display_value(target.get("item_name", "")),
            "kindName": clean_display_value(target.get("kind_name", "")),
            "rankName": clean_display_value(target.get("rank_name", "")),
            "retailUnitName": clean_display_value(target.get("retail_unit_name", "")),
            "wholesaleUnitName": clean_display_value(target.get("wholesale_unit_name", "")),
            "label": clean_display_value(target.get("label", "")),
        }

    return lookup

def normalize_kamis_code(value: Any, width: int = 2) -> str:
    if pd.isna(value):
        return ""

    text = str(value).strip()

    if text.lower() in {"nan", "none", "null", ""}:
        return ""

    # 4.0, 04.0 같은 값 처리
    try:
        if re.fullmatch(r"\d+(\.0+)?", text):
            number = int(float(text))
            return str(number).zfill(width)
    except Exception:
        pass

    # 순수 숫자 처리
    if text.isdigit():
        return text.zfill(width)

    return normalize_text(text)


def build_auction_quality(row_count: int, valid_row_count: int, outlier_count: int) -> Dict[str, Any]:
    if row_count <= 0:
        return {
            "level": "none",
            "label": "데이터 없음",
            "reason": "경매 거래 데이터가 없습니다.",
        }

    outlier_ratio = outlier_count / row_count if row_count > 0 else 0

    if valid_row_count >= 100 and outlier_ratio < 0.2:
        return {
            "level": "high",
            "label": "높음",
            "reason": "거래건수가 충분하고 이상치 비율이 낮습니다.",
        }

    if valid_row_count >= 30 and outlier_ratio < 0.3:
        return {
            "level": "medium",
            "label": "보통",
            "reason": "대표값으로 참고 가능한 수준의 거래건수가 있습니다.",
        }

    if valid_row_count >= 10:
        return {
            "level": "low",
            "label": "낮음",
            "reason": "거래건수가 적어 대표값 해석에 주의가 필요합니다.",
        }

    return {
        "level": "very_low",
        "label": "매우 낮음",
        "reason": "거래건수가 매우 적어 참고용으로만 확인해야 합니다.",
    }

def load_auction_detail_lookup(
    summary_path: Optional[Path],
    market_summary_path: Optional[Path],
    variety_summary_path: Optional[Path],
) -> Dict[str, Dict[str, Any]]:
    if summary_path is None or not summary_path.exists():
        return {}

    summary_df = load_csv_with_fallback(summary_path)

    if summary_df.empty:
        return {}

    summary_df.columns = [str(c).strip() for c in summary_df.columns]

    required = {"product_name", "auction_date"}
    missing = required - set(summary_df.columns)

    if missing:
        print(f"경락정보 요약 파일 필수 컬럼 누락: {missing}")
        return {}

    summary_df["product_name"] = summary_df["product_name"].astype(str).map(normalize_text)

    market_df = pd.DataFrame()
    if market_summary_path is not None and market_summary_path.exists():
        market_df = load_csv_with_fallback(market_summary_path)
        if not market_df.empty:
            market_df.columns = [str(c).strip() for c in market_df.columns]
            market_df["product_name"] = market_df["product_name"].astype(str).map(normalize_text)

    variety_df = pd.DataFrame()
    if variety_summary_path is not None and variety_summary_path.exists():
        variety_df = load_csv_with_fallback(variety_summary_path)
        if not variety_df.empty:
            variety_df.columns = [str(c).strip() for c in variety_df.columns]
            variety_df["product_name"] = variety_df["product_name"].astype(str).map(normalize_text)

    lookup: Dict[str, Dict[str, Any]] = {}

    for _, row in summary_df.iterrows():
        product_name = normalize_text(row.get("product_name", ""))

        if not product_name:
            continue

        markets = []
        if not market_df.empty:
            product_markets = market_df[market_df["product_name"] == product_name].copy()

            if not product_markets.empty:
                product_markets = product_markets.sort_values(
                    "total_trade_qty",
                    ascending=False,
                ).head(10)

                markets = [
                    {
                        "marketCode": normalize_text(m.get("market_code", "")),
                        "marketName": normalize_text(m.get("market_name", "")),
                        "weightedAvgAuctionPrice": safe_float(m.get("weighted_avg_auction_price"), 0.0),
                        "highPrice": safe_float(m.get("high_price"), 0.0),
                        "lowPrice": safe_float(m.get("low_price"), 0.0),
                        "totalTradeQty": safe_float(m.get("total_trade_qty"), 0.0),
                        "rowCount": int(safe_float(m.get("row_count"), 0.0)),
                        "validRowCount": int(safe_float(m.get("valid_row_count"), 0.0)),
                        "outlierCount": int(safe_float(m.get("outlier_count"), 0.0)),
                        "corpCount": int(safe_float(m.get("corp_count"), 0.0)),
                        "rawHighPrice": safe_float(m.get("raw_high_price"), 0.0),
                        "rawLowPrice": safe_float(m.get("raw_low_price"), 0.0),
                    }
                    for _, m in product_markets.iterrows()
                ]

        varieties = []
        if not variety_df.empty:
            product_varieties = variety_df[variety_df["product_name"] == product_name].copy()

            if not product_varieties.empty:
                product_varieties = product_varieties.sort_values(
                    "total_trade_qty",
                    ascending=False,
                ).head(10)

                varieties = [
                    {
                        "varietyName": normalize_text(v.get("variety_name", "")),
                        "unitName": normalize_text(v.get("unit_name", "")),
                        "weightedAvgAuctionPrice": safe_float(v.get("weighted_avg_auction_price"), 0.0),
                        "highPrice": safe_float(v.get("high_price"), 0.0),
                        "lowPrice": safe_float(v.get("low_price"), 0.0),
                        "totalTradeQty": safe_float(v.get("total_trade_qty"), 0.0),
                        "rowCount": int(safe_float(v.get("row_count"), 0.0)),
                        "validRowCount": int(safe_float(v.get("valid_row_count"), 0.0)),
                        "outlierCount": int(safe_float(v.get("outlier_count"), 0.0)),
                        "marketCount": int(safe_float(v.get("market_count"), 0.0)),
                        "rawHighPrice": safe_float(v.get("raw_high_price"), 0.0),
                        "rawLowPrice": safe_float(v.get("raw_low_price"), 0.0),
                    }
                    for _, v in product_varieties.iterrows()
                ]
        row_count = int(safe_float(row.get("row_count"), 0.0))
        valid_row_count = int(safe_float(row.get("valid_row_count"), row_count))
        outlier_count = int(safe_float(row.get("outlier_count"), 0.0))

        lookup[product_name] = {
            "source": "전국 공영도매시장 실시간 경매정보",
            "date": normalize_text(row.get("auction_date", "")),

            # 이상치 제거 후 대표값
            "avgAuctionPrice": safe_float(row.get("avg_auction_price"), 0.0),
            "weightedAvgAuctionPrice": safe_float(row.get("weighted_avg_auction_price"), 0.0),
            "highPrice": safe_float(row.get("high_price"), 0.0),
            "lowPrice": safe_float(row.get("low_price"), 0.0),

            # 원본 참고값
            "rawHighPrice": safe_float(row.get("raw_high_price"), 0.0),
            "rawLowPrice": safe_float(row.get("raw_low_price"), 0.0),

            # 거래량/품질 정보
            "totalTradeQty": safe_float(row.get("total_trade_qty"), 0.0),
            "rowCount": row_count,
            "validRowCount": valid_row_count,
            "outlierCount": outlier_count,
            "marketCount": int(safe_float(row.get("market_count"), 0.0)),
            "corpCount": int(safe_float(row.get("corp_count"), 0.0)),
            "varietyCount": int(safe_float(row.get("variety_count"), 0.0)),

            "auctionQuality": build_auction_quality(
                row_count=row_count,
                valid_row_count=valid_row_count,
                outlier_count=outlier_count,
            ),

            "markets": markets,
            "varieties": varieties,
        }

    return lookup

def build_price_comment(
    wholesale_info: Optional[Dict[str, Any]],
    retail_info: Optional[Dict[str, Any]],
) -> Optional[str]:
    if wholesale_info and retail_info:
        return f"도매 {wholesale_info['trend']} / 소매 {retail_info['trend']}"
    if wholesale_info:
        return f"도매 {wholesale_info['trend']}"
    if retail_info:
        return f"소매 {retail_info['trend']}"
    return None


def merge_price_risk(
    current_risk: str,
    wholesale_info: Optional[Dict[str, Any]],
    retail_info: Optional[Dict[str, Any]],
) -> str:
    score_map = {"낮음": 1, "보통": 2, "높음": 3}
    reverse_map = {1: "낮음", 2: "보통", 3: "높음"}

    derived = "낮음"
    up_count = 0

    if wholesale_info and wholesale_info.get("trend") == "상승":
        up_count += 1
    if retail_info and retail_info.get("trend") == "상승":
        up_count += 1

    if up_count >= 2:
        derived = "높음"
    elif up_count == 1:
        derived = "보통"

    final_score = max(score_map.get(current_risk, 1), score_map.get(derived, 1))
    return reverse_map[final_score]

def load_price_daily_summary(path: Optional[Path]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    if path is None or not path.exists():
        return {}

    df = load_csv_with_fallback(path)
    if df.empty:
        return {}

    df.columns = [str(c).strip() for c in df.columns]

    required = {"product_name", "price_type"}
    missing = required - set(df.columns)
    if missing:
        print(f"KAMIS 가격 파일 필수 컬럼 누락: {missing}")
        return {}

    df["product_name"] = df["product_name"].astype(str).map(normalize_text)

    if "price_num" not in df.columns:
        df["price_num"] = (
            df["price"]
            .astype(str)
            .str.replace(",", "", regex=False)
            .str.extract(r"(\d+\.?\d*)")[0]
            .astype(float)
        )

    if "regday_dt" in df.columns:
        df["regday_dt"] = pd.to_datetime(df["regday_dt"], errors="coerce")
    elif "full_regday" in df.columns:
        df["regday_dt"] = pd.to_datetime(df["full_regday"], errors="coerce")
    else:
        df["regday_dt"] = pd.NaT

    if "countyname" not in df.columns:
        df["countyname"] = ""

    if "marketname" not in df.columns:
        df["marketname"] = ""

    df = df.dropna(subset=["price_num"]).copy()

    price_lookup: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for (product_name, price_type), group in df.groupby(["product_name", "price_type"]):
        group = group.copy()

        avg_group = group[group["countyname"].astype(str).str.strip() == "평균"].copy()
        target = avg_group if not avg_group.empty else group

        if "regday_dt" in target.columns and target["regday_dt"].notna().any():
            target = target.sort_values(["regday_dt"])
        else:
            target = target.reset_index(drop=True)

        latest = target.iloc[-1]
        prev = target.iloc[-2] if len(target) >= 2 else None

        latest_price = safe_float(latest.get("price_num"), 0.0)
        change_rate = None
        trend = "보합"

        if prev is not None:
            prev_price = safe_float(prev.get("price_num"), 0.0)
            if prev_price > 0:
                change_rate = round(((latest_price - prev_price) / prev_price) * 100, 1)
                if change_rate >= 1:
                    trend = "상승"
                elif change_rate <= -1:
                    trend = "하락"

        price_lookup.setdefault(product_name, {})[price_type] = {
            "price_now": round(latest_price, 1),
            "change_rate": change_rate,
            "trend": trend,
            "countyname": latest.get("countyname"),
            "marketname": latest.get("marketname"),
        }

    return price_lookup


# =========================================================
# 5. 분류/점수 계산
# =========================================================

def load_product_type_map(path: Path) -> Dict[str, Dict[str, Any]]:
    """
    product_type_map.csv를 읽어서 수동 보정용 상품 유형 맵으로 반환한다.
    전체 상품 목록이 아니라 자동 분류가 헷갈리는 상품만 보정하는 용도다.
    """
    if not path.exists():
        print(f"[WARN] product_type_map.csv 없음: {path}")
        return {}

    df = load_csv_with_fallback(path)

    if df.empty:
        return {}

    df.columns = [str(c).strip() for c in df.columns]

    if "product_name" not in df.columns:
        print("[WARN] product_type_map.csv에 product_name 컬럼이 없습니다.")
        return {}

    for col in [
        "itemType",
        "itemGroup",
        "decisionAxis",
        "priceInterpretation",
        "recommendedUse",
    ]:
        if col not in df.columns:
            df[col] = ""

    df["product_name"] = df["product_name"].astype(str).map(normalize_text)

    result: Dict[str, Dict[str, Any]] = {}

    for _, row in df.iterrows():
        product_name = normalize_text(row.get("product_name", ""))

        if not product_name:
            continue

        result[product_name] = {
            "itemType": normalize_text(row.get("itemType", "")) or "unknown",
            "itemGroup": normalize_text(row.get("itemGroup", "")) or "상품 유형 확인 필요",
            "decisionAxis": normalize_text(row.get("decisionAxis", "")) or "추가 확인 필요",
            "priceInterpretation": normalize_text(row.get("priceInterpretation", "")) or "시장 가격 연결 여부 확인 필요",
            "recommendedUse": normalize_text(row.get("recommendedUse", "")) or "상품 유형 분류가 필요합니다.",
            "classificationMethod": "manual_map",
            "classificationConfidence": "high",
            "classificationReason": "수동 보정 파일 기준으로 분류했습니다.",
            "autoClassified": False,
        }

    print(f"[OK] product_type_map 로드: {len(result)}개")
    return result

def load_product_alias_map(path: Path) -> Dict[str, Dict[str, str]]:
    """
    product_alias_map.csv를 읽어서 쇼핑 상품명 → 시장가격 매칭용 표준명으로 변환한다.
    예: 쌀20kg → 쌀
    """
    if not path.exists():
        print(f"[WARN] product_alias_map.csv 없음: {path}")
        return {}

    df = load_csv_with_fallback(path)

    if df.empty:
        return {}

    df.columns = [str(c).strip() for c in df.columns]

    required_cols = ["product_name", "marketMatchName"]
    for col in required_cols:
        if col not in df.columns:
            print(f"[WARN] product_alias_map.csv에 {col} 컬럼이 없습니다.")
            return {}

    if "aliasReason" not in df.columns:
        df["aliasReason"] = ""

    result: Dict[str, Dict[str, str]] = {}

    for _, row in df.iterrows():
        product_name = normalize_text(row.get("product_name", ""))
        market_match_name = normalize_text(row.get("marketMatchName", ""))

        if not product_name or not market_match_name:
            continue

        result[product_name] = {
            "marketMatchName": market_match_name,
            "marketMatchMethod": "alias_map",
            "marketMatchReason": normalize_text(row.get("aliasReason", ""))
            or f"시장 가격은 표준 품목명 {market_match_name} 기준으로 참고합니다.",
        }

    print(f"[OK] product_alias_map 로드: {len(result)}개")
    return result

def _contains_any(text: str, keywords: List[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def infer_product_type_from_group(
    product_group: str,
    sub_group: str = "",
) -> Optional[Dict[str, Any]]:
    """
    rising_candidates_master.csv의 product_group/sub_group을 기준으로
    상품 유형을 우선 분류한다.
    """

    group = normalize_text(product_group).lower()

    group_alias = {
        "농산물": "agri",
        "채소": "agri",
        "과일": "agri",
        "곡물": "grain",
        "곡물/농산물": "grain",
        "쌀": "grain",
        "수산물": "seafood",
        "수산": "seafood",
        "생선": "seafood",
        "축산물": "meat",
        "축산": "meat",
        "원재료": "ingredient",
        "소재": "ingredient",
        "원재료/소재": "ingredient",
        "가공식품": "processed",
        "가공": "processed",
        "디저트": "dessert",
        "간식": "dessert",
        "선물": "gift",
        "선물/세트": "gift",
        "선물세트": "gift",
        "건강식품": "health",
        "건강": "health",
        "브랜드": "brand",
        "완제품": "brand",
        "브랜드/완제품": "brand",
    }

    group = group_alias.get(group, group)

    sub = normalize_text(sub_group)

    group_map = {
        "agri": {
            "itemType": "raw_agri",
            "itemGroup": "농산물 원물",
            "decisionAxis": "판매·재고·매입 운영",
            "priceInterpretation": "시장 가격 직접 참고 가능",
            "recommendedUse": "검색·쇼핑 관심 흐름과 시장 가격 데이터를 함께 확인해 판매·재고·매입 운영을 검토하는 것이 적합합니다.",
        },
        "grain": {
            "itemType": "raw_agri",
            "itemGroup": "곡물/농산물",
            "decisionAxis": "판매·재고·가격 노출 운영",
            "priceInterpretation": "표준 품목명 기준 가격 참고",
            "recommendedUse": "관심 흐름과 기준 가격을 함께 확인해 판매 타이밍과 재고 운영을 검토하는 것이 적합합니다.",
        },
        "seafood": {
            "itemType": "seafood",
            "itemGroup": "수산물",
            "decisionAxis": "판매·재고·가격 모니터링",
            "priceInterpretation": "수산물 시장 가격 데이터 별도 연결 필요",
            "recommendedUse": "검색·쇼핑 관심 흐름을 바탕으로 판매 타이밍과 재고 운영을 검토하는 것이 적합합니다.",
        },
        "meat": {
            "itemType": "meat",
            "itemGroup": "축산물",
            "decisionAxis": "판매·재고·가격 모니터링",
            "priceInterpretation": "축산물 가격 데이터 별도 연결 필요",
            "recommendedUse": "검색·쇼핑 관심 흐름을 바탕으로 판매 타이밍과 재고 운영을 검토하는 것이 적합합니다.",
        },
        "ingredient": {
            "itemType": "ingredient",
            "itemGroup": "원재료/소재",
            "decisionAxis": "소량 소싱·상품화 검토",
            "priceInterpretation": "시장 가격 부분 참고",
            "recommendedUse": "원재료 관심 흐름을 바탕으로 소량 소싱과 상품화 가능성을 검토할 수 있습니다.",
        },
        "processed": {
            "itemType": "processed_food",
            "itemGroup": "가공식품",
            "decisionAxis": "판매 반응·콘텐츠 운영",
            "priceInterpretation": "원물 가격 직접 연결 어려움",
            "recommendedUse": "검색·쇼핑 반응을 중심으로 판매 반응과 콘텐츠 운영을 검토하는 것이 적합합니다.",
        },
        "dessert": {
            "itemType": "processed_food",
            "itemGroup": "가공/디저트형 상품",
            "decisionAxis": "테스트 상품 기획",
            "priceInterpretation": "원물 가격 직접 연결 어려움",
            "recommendedUse": "소셜·검색·쇼핑 반응을 바탕으로 테스트 상품 기획을 검토하는 것이 적합합니다.",
        },
        "gift": {
            "itemType": "seasonal_event",
            "itemGroup": "선물/세트",
            "decisionAxis": "기념일 수요·프로모션 운영",
            "priceInterpretation": "가격 직접 연결 어려움",
            "recommendedUse": "기념일 수요를 고려해 프로모션·선물 기획전 노출을 검토하는 것이 적합합니다.",
        },
        "health": {
            "itemType": "processed_food",
            "itemGroup": "건강식품",
            "decisionAxis": "판매 반응·콘텐츠 운영",
            "priceInterpretation": "원물 가격 직접 연결 어려움",
            "recommendedUse": "검색·쇼핑 반응을 중심으로 판매 반응과 콘텐츠 운영을 검토하는 것이 적합합니다.",
        },
        "brand": {
            "itemType": "brand_product",
            "itemGroup": "브랜드/완제품",
            "decisionAxis": "판매 반응·콘텐츠 운영",
            "priceInterpretation": "원물 가격 직접 연결 어려움",
            "recommendedUse": "특정 제품·브랜드 반응을 중심으로 콘텐츠 운영과 판매 반응을 관찰하는 것이 적합합니다.",
        },
    }

    if group not in group_map:
        return None

    result = {
        **group_map[group],
        "classificationMethod": "operator_group",
        "classificationConfidence": "high",
        "classificationReason": (
            f"운영자가 지정한 product_group={product_group}"
            + (f" / sub_group={sub_group}" if sub_group else "")
            + " 기준으로 분류했습니다."
        ),
        "autoClassified": False,
    }

    # sub_group 세부 보정
    if group == "agri" and sub in ["시즌농산물", "제철농산물", "옥수수·시즌농산물"]:
        result["itemType"] = "seasonal_agri"
        result["itemGroup"] = "시즌 농산물"
        result["decisionAxis"] = "판매 타이밍·재고 운영"
        result["recommendedUse"] = "시즌 수요 흐름을 고려해 판매 타이밍과 재고 운영을 검토하는 데 적합합니다."

    if group == "processed" and sub in ["김치·절임", "김치/절임"]:
        result["itemGroup"] = "가공식품"
        result["priceInterpretation"] = "원재료 가격 간접 참고 가능"

    if group == "processed" and sub in ["장류·소스", "장류/소스"]:
        result["itemGroup"] = "가공식품"
        result["priceInterpretation"] = "원재료 가격 간접 참고 가능"

    if group == "processed" and sub in ["반찬·수산가공", "수산가공"]:
        result["itemGroup"] = "가공식품"
        result["priceInterpretation"] = "수산물 원물 가격 간접 참고 가능"

    return result

def infer_product_type(
    product_name: str,
    manual_type_map: Optional[Dict[str, Dict[str, Any]]] = None,
    market_data_status: Optional[Dict[str, Any]] = None,
    product_group: str = "",
    sub_group: str = "",
) -> Dict[str, Any]:
    """
    상품명을 기반으로 상품 유형을 자동 추론한다.

    우선순위:
    1. 수동 보정값
    2. 가공/디저트 키워드
    3. 원재료/소재 키워드
    4. 시즌 농산물 키워드
    5. 원물 농산물 키워드
    6. 시장 데이터 연결 여부
    7. unknown
    """
    name = normalize_text(product_name)
    compact_name = name.replace(" ", "")

    if manual_type_map and name in manual_type_map:
        return manual_type_map[name]
    
    # 2) 운영자가 매일 입력한 product_group/sub_group 우선 반영
    group_info = infer_product_type_from_group(product_group, sub_group)
    if group_info:
        return group_info

    market_data_status = market_data_status or {}
    kamis_matched = bool(market_data_status.get("kamisMatched"))
    auction_matched = bool(market_data_status.get("auctionMatched"))
    market_matched = kamis_matched or auction_matched

    processed_keywords = [
        "고추장", "간장", "된장", "쌈장", "초장", "게장", "간장게장",
        "양념게장", "김치", "파김치", "겉절이", "장아찌", "젓갈",
        "반찬", "절임", "소스", "장류",
        "케이크", "쿠키", "칩", "빵", "베이글", "떡", "라떼", "음료", "스낵",
        "과자", "젤리", "푸딩", "요거트", "초콜릿", "초코", "디저트", "닭가슴살",
        "단백질", "프로틴", "알부민", "즙", "주스", "청", "잼", "아이스크림",
        "시리얼", "바", "캔디", "젤라또"
    ]

    ingredient_keywords = [
        "파우더", "분말", "가루", "원액", "시럽", "소스", "페이스트",
        "말차", "우베", "카카오", "코코아", "바닐라", "크림치즈",
        "버터", "치즈", "생크림", "밀가루"
    ]

    seasonal_event_keywords = [
    "선물세트", "선물 세트", "기념선물", "기념 선물",
    "어버이날선물", "스승의날선물", "명절선물", "추석선물", "설선물"
    ]

    seasonal_agri_keywords = [
        "딸기", "참외", "수박", "매실", "두릅", "봄동", "복숭아",
        "자두", "체리", "블루베리", "샤인머스켓", "귤", "한라봉"
    ]

    seafood_keywords = [
        "장어", "꽃게", "게", "대게", "홍게", "킹크랩",
        "연어", "고등어", "갈치", "명태", "동태", "대구", "참치",
        "오징어", "문어", "낙지", "주꾸미", "쭈꾸미",
        "새우", "전복", "굴", "홍합", "조개", "바지락", "꼬막",
        "멸치", "김", "미역", "다시마", "수산물", "생선",
        "회", "건어물"
    ]
    raw_agri_keywords = [
        "감자", "오이", "사과", "배", "양파", "마늘", "고구마", "무",
        "배추", "상추", "깻잎", "당근", "토마토", "호박", "가지",
        "대파", "쪽파", "마늘쫑", "콩나물", "버섯", "브로콜리",
        "양배추", "파프리카", "고추", "부추", "시금치"
    ]

    brand_like_keywords = [
         "기획", "한정", "에디션", "신상", "브랜드"
    ]

    # 중요: 딸기케이크, 감자칩 같은 오분류 방지를 위해 가공 키워드를 먼저 본다.
    if _contains_any(compact_name, [keyword.replace(" ", "") for keyword in seasonal_event_keywords]):
        return {
            "itemType": "seasonal_event",
            "itemGroup": "선물/세트",
            "decisionAxis": "기념일 수요·프로모션 운영",
            "priceInterpretation": "가격 직접 연결 어려움",
            "recommendedUse": "기념일 수요를 고려해 프로모션·선물 기획전 노출을 검토하는 것이 적합합니다.",
            "classificationMethod": "auto_keyword",
            "classificationConfidence": "medium",
            "classificationReason": "상품명에 선물/세트형 키워드가 포함되어 자동 분류했습니다.",
            "autoClassified": True,
        }

    if _contains_any(compact_name, ingredient_keywords):
        return {
            "itemType": "ingredient",
            "itemGroup": "원재료/소재",
            "decisionAxis": "소량 소싱·상품화 검토",
            "priceInterpretation": "시장 가격 부분 참고",
            "recommendedUse": "원재료 관심 흐름을 바탕으로 소량 소싱과 상품화 가능성을 검토할 수 있습니다.",
            "classificationMethod": "auto_keyword",
            "classificationConfidence": "medium",
            "classificationReason": "상품명에 원재료/소재형 키워드가 포함되어 자동 분류했습니다.",
            "autoClassified": True,
        }

    if _contains_any(compact_name, seasonal_agri_keywords):
        return {
            "itemType": "seasonal_agri",
            "itemGroup": "시즌 농산물",
            "decisionAxis": "판매 타이밍·재고 운영",
            "priceInterpretation": "시장 가격 직접 참고 가능",
            "recommendedUse": "시즌 수요 흐름을 고려해 판매 타이밍과 재고 운영을 검토하는 데 적합합니다.",
            "classificationMethod": "auto_keyword_market" if market_matched else "auto_keyword",
            "classificationConfidence": "high" if market_matched else "medium",
            "classificationReason": "상품명과 시장 데이터 연결 여부를 기준으로 시즌 농산물로 분류했습니다." if market_matched else "상품명에 시즌 농산물 키워드가 포함되어 자동 분류했습니다.",
            "autoClassified": True,
        }

    if _contains_any(compact_name, seafood_keywords):
        return {
            "itemType": "seafood",
            "itemGroup": "수산물",
            "decisionAxis": "판매·재고·가격 모니터링",
            "priceInterpretation": "수산물 시장 가격 데이터 별도 연결 필요",
            "recommendedUse": "검색·쇼핑 관심 흐름을 바탕으로 판매 타이밍과 재고 운영을 검토하는 것이 적합합니다.",
            "classificationMethod": "auto_keyword",
            "classificationConfidence": "medium",
            "classificationReason": "상품명에 수산물 키워드가 포함되어 자동 분류했습니다.",
            "autoClassified": True,
        }
    
    if _contains_any(compact_name, raw_agri_keywords):
        return {
            "itemType": "raw_agri",
            "itemGroup": "농산물 원물",
            "decisionAxis": "광고·재고·매입 운영",
            "priceInterpretation": "시장 가격 직접 참고 가능",
            "recommendedUse": "기존 유통 품목으로 광고·재고·매입 운영 검토에 적합합니다.",
            "classificationMethod": "auto_keyword_market" if market_matched else "auto_keyword",
            "classificationConfidence": "high" if market_matched else "medium",
            "classificationReason": "상품명과 시장 데이터 연결 여부를 기준으로 농산물 원물로 분류했습니다." if market_matched else "상품명에 농산물 키워드가 포함되어 자동 분류했습니다.",
            "autoClassified": True,
        }

    if _contains_any(compact_name, brand_like_keywords):
        return {
            "itemType": "brand_product",
            "itemGroup": "브랜드/완제품",
            "decisionAxis": "판매 반응·콘텐츠 운영",
            "priceInterpretation": "원물 가격 직접 연결 어려움",
            "recommendedUse": "검색·쇼핑 반응을 중심으로 판매 반응과 콘텐츠 운영을 검토하는 것이 적합합니다.",
            "classificationMethod": "auto_keyword",
            "classificationConfidence": "low",
            "classificationReason": "브랜드/완제품성 키워드가 포함되어 있으나 수동 확인이 필요합니다.",
            "autoClassified": True,
        }

    if market_matched:
        return {
            "itemType": "raw_agri",
            "itemGroup": "농산물 원물",
            "decisionAxis": "광고·재고·매입 운영",
            "priceInterpretation": "시장 가격 직접 참고 가능",
            "recommendedUse": "기존 유통 품목으로 광고·재고·매입 운영 검토에 적합합니다.",
            "classificationMethod": "market_data_matched",
            "classificationConfidence": "medium",
            "classificationReason": "KAMIS 또는 공영도매시장 경락정보가 연결되어 농산물 원물 가능성이 높습니다.",
            "autoClassified": True,
        }

    return {
        "itemType": "unknown",
        "itemGroup": "상품 유형 확인 필요",
        "decisionAxis": "추가 확인 필요",
        "priceInterpretation": "시장 가격 연결 여부 확인 필요",
        "recommendedUse": "상품 유형 분류가 필요합니다. 검색·쇼핑 흐름을 우선 확인하고 수동 보정 여부를 검토하세요.",
        "classificationMethod": "unclassified",
        "classificationConfidence": "low",
        "classificationReason": "자동 분류 기준에 해당하지 않아 수동 확인이 필요합니다.",
        "autoClassified": False,
    }





DOMESTIC_FRUIT_KEYWORDS = ["딸기", "사과", "배", "참외", "수박", "포도", "복숭아", "토마토", "레몬"]
DOMESTIC_VEG_KEYWORDS = ["대파", "양배추", "배추", "상추", "깻잎", "오이", "호박", "봄동", "무", "감자", "두릅", "엄나무순", "마늘쫑"]
IMPORTED_INGREDIENT_KEYWORDS = ["말차", "치즈", "버터", "코코아", "원두", "바닐라", "시럽", "파우더", "올리브오일"]
FROZEN_KEYWORDS = ["냉동"]
BEVERAGE_KEYWORDS = ["생수", "두유", "커피", "음료", "차"]

SIGNAL_LABELS = {
    "early": "초기 관심 신호",
    "conversion": "구매 관심 확인",
    "overheated": "과열 주의 후보",
}

DEFAULT_ACTIONS = {
    "early": "소량 테스트",
    "conversion": "우선 검토",
    "overheated": "관망",
}


def infer_market_group(name: str) -> str:
    n = str(name)

    if any(k in n for k in DOMESTIC_FRUIT_KEYWORDS):
        return "국내산 과일"
    if any(k in n for k in DOMESTIC_VEG_KEYWORDS):
        return "국내산 채소"
    if any(k in n for k in IMPORTED_INGREDIENT_KEYWORDS):
        return "수입 원재료"
    if any(k in n for k in FROZEN_KEYWORDS):
        return "냉동식품"
    if any(k in n for k in BEVERAGE_KEYWORDS):
        return "커피/음료"

    return "기타 식품"


def infer_category_and_subcategory(name: str) -> Tuple[str, str]:
    n = str(name)

    if any(k in n for k in DOMESTIC_FRUIT_KEYWORDS):
        return "과일", "과일류"
    if any(k in n for k in DOMESTIC_VEG_KEYWORDS):
        return "채소", "채소류"
    if "떡" in n:
        return "간식", "떡류"
    if "쿠키" in n:
        return "간식", "쿠키류"
    if any(k in n for k in IMPORTED_INGREDIENT_KEYWORDS):
        return "원재료", "수입 원재료"
    if any(k in n for k in FROZEN_KEYWORDS):
        return "냉동식품", "냉동식품"
    if any(k in n for k in BEVERAGE_KEYWORDS):
        return "음료", "음료류"

    return "기타", "기타"


def infer_origin_type(market_group: str) -> str:
    if market_group == "수입 원재료":
        return "수입"
    return "국내산"


def infer_unit(name: str) -> str:
    n = str(name).lower()
    if "20kg" in n:
        return "20kg"
    if "10kg" in n:
        return "10kg"
    if "kg" in n:
        return "kg"
    if "박스" in n:
        return "1박스"
    if "팩" in n:
        return "1팩"
    return "1개"


def compute_search_lead_days(search_series: pd.Series, shopping_series: pd.Series) -> int:
    s = search_series.fillna(0).reset_index(drop=True)
    p = shopping_series.fillna(0).reset_index(drop=True)

    if len(s) < 3 or len(p) < 3:
        return 0

    def first_jump(x: pd.Series) -> Optional[int]:
        baseline = x.iloc[: min(3, len(x))].mean()
        for i in range(len(x)):
            if x.iloc[i] > max(1.0, baseline * 1.2):
                return i
        return None

    s_idx = first_jump(s)
    p_idx = first_jump(p)

    if s_idx is None or p_idx is None:
        return 0

    lead = p_idx - s_idx
    return int(max(-7, min(7, lead)))


def compute_conversion_score(search_today: float, shopping_today: float) -> float:
    if search_today <= 0 and shopping_today <= 0:
        return 0.0

    ratio = 0.0 if search_today <= 0 else shopping_today / search_today
    score = min(100.0, ratio * 70 + min(shopping_today, 30))
    return round(score, 1)


def compute_persistence_score(search_series: pd.Series) -> float:
    s = search_series.fillna(0).reset_index(drop=True)
    if len(s) == 0:
        return 0.0

    peak = safe_float(s.max())
    if peak <= 0:
        return 0.0

    peak_idx = int(s.idxmax())
    tail = s.iloc[peak_idx:]
    if len(tail) == 0:
        return 0.0

    score = (safe_float(tail.mean()) / peak) * 100
    return round(min(100.0, score), 1)


def compute_bubble_risk(search_series: pd.Series, shopping_series: pd.Series) -> float:
    s = search_series.fillna(0).reset_index(drop=True)
    p = shopping_series.fillna(0).reset_index(drop=True)

    if len(s) == 0:
        return 0.0

    search_peak = safe_float(s.max())
    shopping_peak = safe_float(p.max())

    if search_peak <= 0:
        return 0.0

    gap = max(0.0, search_peak - shopping_peak)

    peak_idx = int(s.idxmax())
    tail = s.iloc[peak_idx:]
    if len(tail) > 0:
        tail_avg = safe_float(tail.mean())
        drop_ratio = max(0.0, (search_peak - tail_avg) / search_peak)
    else:
        drop_ratio = 0.0

    raw = gap * 0.7 + drop_ratio * 100 * 0.3
    return round(min(100.0, raw), 1)

def compute_recent_growth(series: pd.Series) -> float:
    s = series.fillna(0).reset_index(drop=True)

    if len(s) < 4:
        return 0.0

    today = safe_float(s.iloc[-1], 0.0)
    prev_avg = safe_float(s.iloc[-4:-1].mean(), 0.0)

    if prev_avg <= 0:
        if today > 0:
            return 100.0
        return 0.0

    growth = ((today - prev_avg) / prev_avg) * 100
    return round(max(-100.0, min(300.0, growth)), 1)
def compute_click_efficiency(search_today: float, shopping_today: float) -> float:
    if search_today <= 0:
        return 0.0

    # 검색량이 너무 낮으면 클릭효율이 과장될 수 있으므로 감점
    ratio = shopping_today / search_today
    efficiency = min(100.0, ratio * 100)

    if search_today < 10:
        efficiency *= 0.4
    elif search_today < 20:
        efficiency *= 0.7

    return round(efficiency, 1)


def compute_rank_zone_score(today_rank: Optional[int]) -> float:
    if today_rank is None:
        return 5.0

    if 21 <= today_rank <= 50:
        return 20.0

    if 51 <= today_rank <= 100:
        return 14.0

    if 101 <= today_rank <= 200:
        return 8.0

    if today_rank <= 20:
        return 3.0

    return 3.0

def compute_opportunity_score(
    source_type: str,
    today_rank: Optional[int],
    rank_change: Optional[float],
    search_growth_rate: float,
    shopping_growth_rate: float,
    conversion_score: float,
    persistence_score: float,
    bubble_risk_score: float,
    market_group: str,
    drivers: List[str],
    has_price_data: bool,
) -> float:
    rank_zone_score = compute_rank_zone_score(today_rank)

    score = 0.0

    # 1) 후보 위치 점수
    if source_type == "rising":
        score += rank_zone_score
    elif source_type == "sns":
        score += 18.0
    elif source_type == "top20":
        score += 5.0

    # 2) 전일 대비 순위 상승
    # rank_change는 previousRank - todayRank 이므로 양수면 상승
    if rank_change is not None:
        if rank_change >= 30:
            score += 18.0
        elif rank_change >= 20:
            score += 14.0
        elif rank_change >= 10:
            score += 10.0
        elif rank_change >= 3:
            score += 5.0
        elif rank_change < 0:
            score -= min(10.0, abs(rank_change) * 0.3)

    # 3) 검색 증가율
    if search_growth_rate >= 100:
        score += 20.0
    elif search_growth_rate >= 50:
        score += 15.0
    elif search_growth_rate >= 20:
        score += 10.0
    elif search_growth_rate > 0:
        score += 5.0

    # 4) 쇼핑 클릭 증가율
    # 현재값 비교가 아니라 같은 상품의 최근 흐름만 반영
    if shopping_growth_rate >= 100:
        score += 16.0
    elif shopping_growth_rate >= 50:
        score += 12.0
    elif shopping_growth_rate >= 20:
        score += 8.0
    elif shopping_growth_rate > 0:
        score += 3.0

    # 5) 전환 점수는 보조 지표로만 약하게 반영
    score += min(8.0, conversion_score * 0.08)

    # 6) 유지력
    score += min(10.0, persistence_score * 0.10)

    # 7) 가격 연결 가능성
    if has_price_data:
        score += 5.0

    # 8) 서비스 목적 적합도
    if market_group in {"국내산 과일", "국내산 채소"}:
        score += 5.0
    elif market_group in {"수입 원재료", "수입원재료"}:
        score += 4.0

    # 9) SNS 신호 보너스
    if "SNS선행" in drivers or "SNS확산" in drivers:
        score += 5.0

    # 10) 과열 감점
    if bubble_risk_score >= 80:
        score -= 20.0
    elif bubble_risk_score >= 65:
        score -= 10.0

    return round(max(0.0, min(100.0, score)), 1)
def build_opportunity_reason(
    source_type: str,
    today_rank: Optional[int],
    rank_change: Optional[float],
    search_growth_rate: float,
    shopping_growth_rate: float,
    market_group: str,
    has_price_data: bool,
) -> str:
    reasons = []

    if source_type == "rising":
        if today_rank is not None:
            if 21 <= today_rank <= 50:
                reasons.append("Top20 진입 직전 구간")
            elif 51 <= today_rank <= 100:
                reasons.append("중위권 상승 관찰 구간")
            elif 101 <= today_rank <= 200:
                reasons.append("하위권 선행 관찰 구간")

    if rank_change is not None:
        if rank_change >= 20:
            reasons.append("순위 급상승")
        elif rank_change >= 5:
            reasons.append("순위 상승 중")
        elif rank_change < 0:
            reasons.append("순위 하락 관찰")

    if search_growth_rate >= 50:
        reasons.append("검색 반응 급상승")
    elif search_growth_rate >= 20:
        reasons.append("검색 반응 상승 중")

    if shopping_growth_rate >= 50:
        reasons.append("쇼핑 클릭 추이 급상승")
    elif shopping_growth_rate >= 20:
        reasons.append("쇼핑 클릭 추이 상승 중")

    if market_group in {"국내산 과일", "국내산 채소"}:
        reasons.append("국내 시장가 연결 가능")
    elif market_group in {"수입 원재료", "수입원재료"}:
        reasons.append("수입 원가 영향 가능")

    if has_price_data:
        reasons.append("KAMIS 가격 데이터 연결됨")

    if not reasons:
        return "검색·클릭 흐름과 순위 변화를 추가 관찰할 후보입니다."

    return " · ".join(reasons)

def classify_signal_group(
    search_lead_days: int,
    conversion_score: float,
    persistence_score: float,
    bubble_risk_score: float,
    search_today: float,
    shopping_today: float,
) -> str:
    if bubble_risk_score >= 75:
        return "overheated"

    if conversion_score >= 75 and persistence_score >= 60:
        return "conversion"

    if search_lead_days >= 2 and bubble_risk_score < 60:
        return "early"

    if search_today >= 40 and shopping_today >= 30:
        return "conversion"

    if bubble_risk_score >= 60:
        return "overheated"

    return "early"


def build_summary_text(signal_group: str, source_type: str = "top20") -> str:
    if source_type == "sns":
        if signal_group == "early":
            return "SNS에서 먼저 포착됐고 네이버 반응이 뒤따르는 초기 관찰 후보입니다."
        if signal_group == "conversion":
            return "SNS 선행 후 네이버 검색과 쇼핑 반응이 함께 붙는 전환형 후보입니다."
        return "SNS에서 먼저 포착됐고 네이버 반응은 붙었지만 과열 가능성을 함께 봐야 하는 후보입니다."

    if signal_group == "early":
        return "검색이 먼저 붙고 쇼핑 클릭이 뒤따르는 초기 확산 패턴입니다."
    if signal_group == "conversion":
        return "검색과 쇼핑 클릭이 함께 강하게 움직이는 전환형 상품입니다."
    return "검색 급등 대비 쇼핑 추종이 약하거나 이벤트성이 큰 과열 주의 패턴입니다."


def build_detail_reason(signal_group: str, search_lead_days: int, source_type: str = "top20") -> str:
    if source_type == "sns":
        if signal_group == "early":
            return (
                f"SNS에서 먼저 포착된 뒤 네이버 검색 반응이 붙고 있습니다. "
                f"검색이 쇼핑보다 약 {search_lead_days}일 선행하는 흐름이 보여 초기 관찰 후보로 분류했습니다."
            )
        if signal_group == "conversion":
            return (
                "SNS 선행 신호 이후 네이버 검색과 쇼핑 클릭이 함께 움직이고 있어 "
                "실제 구매 검토 단계로 넘어가는 후보로 해석했습니다."
            )
        return (
            "SNS에서 강하게 보였고 네이버 반응도 붙었지만, 쇼핑 추종보다 검색 급등이 커 "
            "과열 가능성을 함께 확인해야 하는 후보로 분류했습니다."
        )

    if signal_group == "early":
        return (
            f"최근 검색 반응이 쇼핑보다 약 {search_lead_days}일 먼저 움직였습니다. "
            "아직 과열 구간으로 보이진 않아 초기 관심 신호로 분류했습니다."
        )
    if signal_group == "conversion":
        return (
            "검색과 쇼핑 클릭이 함께 강하게 움직이고 있으며 유지력도 좋아 "
            "실제 구매 검토 단계에 가까운 상품으로 해석했습니다."
        )
    return (
        "검색량 급등 대비 쇼핑 추종이 상대적으로 약하거나, 이벤트 이슈가 겹친 흐름으로 보여 "
        "과열 주의 후보로 분류했습니다."
    )


def build_forecast7(signal_group: str, source_type: str = "top20") -> str:
    if source_type == "sns":
        if signal_group == "early":
            return "향후 7일 내 네이버 반응 확대 여부 확인 필요"
        if signal_group == "conversion":
            return "향후 7일 내 네이버 쇼핑 전환 확대 가능성"
        return "향후 7일 내 과열 변동성 확대 가능성"

    if signal_group == "early":
        return "향후 7일 내 관심도 완만한 상승 가능성"
    if signal_group == "conversion":
        return "향후 7일 내 높은 관심 유지 가능성"
    return "향후 7일 내 과열 변동성 확대 가능성"


def build_forecast14(signal_group: str, source_type: str = "top20") -> str:
    if source_type == "sns":
        if signal_group == "early":
            return "향후 14일 내 Top20 진입 여부 확인 필요"
        if signal_group == "conversion":
            return "향후 14일 내 시장 확산 여부 확인 필요"
        return "향후 14일 내 공급·이벤트 이슈에 따라 급변 가능성"

    if signal_group == "early":
        return "향후 14일 내 쇼핑 전환 확대 여부 확인 필요"
    if signal_group == "conversion":
        return "향후 14일 내 후기·재고 흐름에 따라 강세 유지 가능성"
    return "향후 14일 내 공급·이벤트 이슈에 따라 급변 가능성"


def build_price_risk(market_group: str, bubble_risk: float) -> str:
    if market_group == "수입 원재료":
        return "높음"
    if bubble_risk >= 75:
        return "높음"
    if bubble_risk >= 45:
        return "보통"
    return "낮음"


def build_weather_risk(market_group: str) -> str:
    if market_group in {"국내산 채소", "국내산 과일"}:
        return "보통"
    return "낮음"


def build_fx_risk(market_group: str) -> str:
    if market_group == "수입 원재료":
        return "보통"
    return "낮음"


def infer_drivers(product_name: str, signal_group: str, search_lead_days: int, bubble_risk_score: float, source_type: str) -> List[str]:
    drivers = []
    n = str(product_name)

    if source_type == "sns":
        drivers.append("SNS선행")

    if search_lead_days >= 2:
        drivers.append("검색선행")
    if signal_group == "conversion":
        drivers.append("쇼핑전환")
    if signal_group == "overheated":
        drivers.append("검색급등")
    if any(k in n for k in ["참외", "딸기", "봄동", "오이"]):
        drivers.append("계절성")
    if any(k in n for k in ["대파", "양배추", "토마토", "두릅", "엄나무순", "오이", "마늘쫑"]):
        drivers.append("출하량")
    if any(k in n for k in ["두쫀쿠", "버터떡", "창억떡"]):
        drivers.append("SNS확산")
    if any(k in n for k in ["말차", "버터", "올리브오일"]):
        drivers.append("원가민감")
    if bubble_risk_score >= 75:
        drivers.append("과열주의")

    return unique_keep_order(drivers)


def infer_event_tags(product_name: str, event_df: pd.DataFrame) -> List[str]:
    tags = []
    n = str(product_name)

    if "두쫀쿠" in n:
        tags.extend(["SNS", "품절"])
    if "버터떡" in n or "창억떡" in n:
        tags.append("SNS")

    if not event_df.empty:
        matched = event_df[event_df["product_name"] == product_name]["event_tag"].tolist()
        tags.extend(matched)

    return unique_keep_order(tags)
def build_interest_direction(shopping_growth_rate: float) -> Dict[str, str]:
    if shopping_growth_rate >= 10:
        return {
            "label": "관심 증가",
            "description": "최근 쇼핑 관심 흐름이 증가하고 있습니다.",
        }

    if shopping_growth_rate <= -10:
        return {
            "label": "관심 둔화",
            "description": "최근 쇼핑 관심 흐름이 둔화되고 있습니다.",
        }

    return {
        "label": "관심 유지",
        "description": "최근 쇼핑 관심 흐름이 크게 흔들리지 않고 유지되고 있습니다.",
    }
def get_interest_sentence(shopping_growth_rate: float) -> str:
    if shopping_growth_rate >= 10:
        return "최근 쇼핑 관심 흐름은 증가세로 관찰됩니다."
    if shopping_growth_rate <= -10:
        return "최근 쇼핑 관심 흐름은 둔화되는 모습입니다."
    return "최근 쇼핑 관심 흐름은 유지되는 모습입니다."


def get_market_connection_label(
    market_data_status: Dict[str, Any],
    market_match_method: str = "direct",
) -> str:
    kamis_matched = bool(market_data_status.get("kamisMatched"))
    auction_matched = bool(market_data_status.get("auctionMatched"))

    if market_match_method == "alias_map" and (kamis_matched or auction_matched):
        return "기준 품목 연결"

    if kamis_matched or auction_matched:
        return "가격 연결"

    return "가격 미연결"

def build_processed_subgroup_comment(
    product_name: str,
    sub_group: str,
    interest_sentence: str,
    recommended_use_from_type: str = "",
) -> Optional[Dict[str, str]]:
    """
    가공식품(processed_food) 중에서도 sub_group 기준으로 문구를 세분화한다.
    예: 김치/절임, 장류/소스, 반찬/수산가공, 간편식/밀키트
    """

    sub = normalize_text(sub_group)

    # 1) 김치/절임
    if sub in ["김치·절임", "김치/절임", "김치", "절임"]:
        return {
            "summary": (
                f"{product_name}은/는 김치·절임류에 해당하는 가공식품입니다. "
                "완제품 가격이 배추·무·고춧가루 등 원재료 가격과 직접 일치하지는 않지만, "
                "원재료 가격 흐름은 판매가와 프로모션 판단의 참고 지표가 될 수 있습니다. "
                f"{interest_sentence}"
            ),
            "recommendedUse": (
                recommended_use_from_type
                or "검색·쇼핑 관심 흐름과 원재료 가격 흐름을 함께 참고해 판매 타이밍과 프로모션 운영을 검토하는 것이 적합합니다."
            ),
            "marketNote": (
                "김치·절임류는 완제품/가공식품 성격이 강해 특정 원물 가격과 직접 연결하기 어렵습니다. "
                "다만 배추·무·쪽파·고춧가루 등 주요 원재료 가격은 간접 참고 지표로 활용할 수 있습니다."
            ),
            "caution": (
                "네이버 기준 관심 신호이며 전체 시장 수요로 단정하지 않습니다. "
                "김치류는 원재료 가격 외에도 브랜드, 제조 방식, 용량, 배송 조건에 따라 판매가격 차이가 발생합니다."
            ),
        }

    # 2) 장류/소스
    if sub in ["장류·소스", "장류/소스", "장류", "소스"]:
        return {
            "summary": (
                f"{product_name}은/는 장류·소스류에 해당하는 가공식품입니다. "
                "브랜드·용량·제조사별 가격 차이가 커서 원재료 시장가격과 직접 연결하기보다 "
                "검색·쇼핑 관심 흐름 중심으로 해석하는 것이 적합합니다. "
                f"{interest_sentence}"
            ),
            "recommendedUse": (
                recommended_use_from_type
                or "검색·쇼핑 반응을 중심으로 판매 반응, 노출 키워드, 프로모션 운영 여부를 검토하는 것이 적합합니다."
            ),
            "marketNote": (
                "장류·소스류는 콩, 고추, 소금 등 원재료 영향을 받을 수 있으나 완제품 가격과 직접 일치하지는 않습니다. "
                "시장 가격은 직접 연결보다 원재료 가격의 간접 참고 수준으로 해석하는 것이 안전합니다."
            ),
            "caution": (
                "네이버 기준 관심 신호이며 전체 시장 수요로 단정하지 않습니다. "
                "장류·소스류는 브랜드, 숙성 방식, 용량, 세트 구성에 따라 가격 편차가 큽니다."
            ),
        }

    # 3) 반찬/수산가공
    if sub in ["반찬·수산가공", "반찬/수산가공", "수산가공", "반찬"]:
        return {
            "summary": (
                f"{product_name}은/는 반찬·수산가공형 상품으로 분류됩니다. "
                "수산물 원물 가격과 완제품 가격이 직접 일치하지는 않으므로 "
                "검색·쇼핑 관심과 판매 기획 맥락을 중심으로 해석하는 것이 적합합니다. "
                f"{interest_sentence}"
            ),
            "recommendedUse": (
                recommended_use_from_type
                or "검색·쇼핑 관심 흐름을 바탕으로 판매 타이밍, 구성 상품, 프로모션 노출 여부를 검토하는 것이 적합합니다."
            ),
            "marketNote": (
                "반찬·수산가공 상품은 원물 수산물 가격의 영향을 받을 수 있으나 양념, 제조, 포장, 배송 조건이 반영된 완제품입니다. "
                "현재는 수산물 원물 가격보다 검색·쇼핑 관심 흐름 중심으로 참고하는 것이 적합합니다."
            ),
            "caution": (
                "네이버 기준 관심 신호이며 전체 시장 수요로 단정하지 않습니다. "
                "수산가공 상품은 원산지, 냉장/냉동 여부, 양념 구성, 제조사에 따라 가격 차이가 큽니다."
            ),
        }

    # 4) 간편식/밀키트
    if sub in ["간편식", "밀키트", "간편식·밀키트", "간편식/밀키트"]:
        return {
            "summary": (
                f"{product_name}은/는 간편식·밀키트형 가공식품입니다. "
                "원재료 가격보다 상품 구성, 판매처 노출, 리뷰, 재구매 반응을 중심으로 해석하는 것이 적합합니다. "
                f"{interest_sentence}"
            ),
            "recommendedUse": (
                recommended_use_from_type
                or "상품 구성, 가격 노출, 리뷰 증가 여부를 함께 보며 테스트 판매와 프로모션 운영을 검토할 수 있습니다."
            ),
            "marketNote": (
                "간편식·밀키트는 여러 원재료와 제조·포장 비용이 결합된 상품이므로 단일 원물 시장가격과 직접 연결하기 어렵습니다."
            ),
            "caution": (
                "검색 관심은 상품 검토의 참고 신호이며 실제 수요 판단에는 판매처 수, 리뷰, 재구매 지표를 함께 확인해야 합니다."
            ),
        }

    # 5) 육가공
    if sub in ["육가공", "축산가공", "햄·소시지", "햄/소시지"]:
        return {
            "summary": (
                f"{product_name}은/는 육가공형 상품입니다. "
                "축산물 원물 가격의 영향을 받을 수 있으나 완제품 가격은 브랜드, 부위, 가공 방식, 용량에 따라 달라집니다. "
                f"{interest_sentence}"
            ),
            "recommendedUse": (
                recommended_use_from_type
                or "검색·쇼핑 관심 흐름과 상품 구성, 가격 노출, 프로모션 반응을 함께 검토하는 것이 적합합니다."
            ),
            "marketNote": (
                "육가공 상품은 축산물 가격을 간접 참고할 수 있으나 완제품 가격과 직접 일치하지 않습니다. "
                "부위, 원산지, 가공 방식, 브랜드 차이를 함께 확인해야 합니다."
            ),
            "caution": (
                "네이버 기준 관심 신호이며 전체 시장 수요로 단정하지 않습니다. "
                "육가공 상품은 원물 가격보다 상품 구성과 판매 채널의 영향이 클 수 있습니다."
            ),
        }

    return None

def build_type_based_comment(
    product_name: str,
    product_type_info: Dict[str, Any],
    market_data_status: Dict[str, Any],
    shopping_growth_rate: float,
    market_match_name: str = "",
    market_match_method: str = "direct",
    market_match_reason: str = "",
    sub_group: str = "",
) -> Dict[str, str]:
    item_type = product_type_info.get("itemType", "unknown")
    item_group = product_type_info.get("itemGroup", "상품 유형 확인 필요")
    recommended_use_from_type = product_type_info.get("recommendedUse", "")

    interest_sentence = get_interest_sentence(shopping_growth_rate)

    kamis_matched = bool(market_data_status.get("kamisMatched"))
    auction_matched = bool(market_data_status.get("auctionMatched"))
    has_market_data = kamis_matched or auction_matched

    # 1) 기준 품목 alias 매칭 상품: 쌀20kg → 쌀
    if market_match_method == "alias_map":
        standard_name = market_match_name or product_name

        return {
            "summary": (
                f"{product_name}은/는 포장 단위나 세부 표현이 포함된 쇼핑 상품명입니다. "
                f"시장 가격은 표준 품목명 ‘{standard_name}’을 기준으로 보정해 참고하는 것이 적합합니다. "
                f"{interest_sentence}"
            ),
            "recommendedUse": (
                recommended_use_from_type
                or "관심 흐름과 기준 가격을 함께 확인해 판매 타이밍, 재고 운영, 가격 노출 전략을 검토할 수 있습니다."
            ),
            "marketNote": (
                market_match_reason
                or f"KAMIS 기준 ‘{standard_name}’ 가격과 연결해 참고할 수 있습니다. "
                   "단, 쇼핑 상품의 용량·브랜드·배송 조건에 따라 실제 판매가격과 차이가 발생할 수 있습니다."
            ),
            "caution": (
                "네이버 기준 관심 신호이며 전체 시장 수요로 단정하지 않습니다. "
                "쇼핑 상품명과 시장 가격 품목명은 다를 수 있으므로 표준 품목명 기준으로 보정해 해석합니다."
            ),
        }

    # 2) 선물/세트, 기념일형 검색어
    if item_type == "seasonal_event" or item_group in ["선물/세트", "기념일 선물"]:
        return {
            "summary": (
                f"{product_name}은/는 기념일 수요와 연동되는 선물형 검색어입니다. "
                "시장 가격보다 검색·클릭 흐름과 기획전 노출 타이밍을 중심으로 해석하는 것이 적합합니다. "
                f"{interest_sentence}"
            ),
            "recommendedUse": (
                recommended_use_from_type
                or "기념일 수요에 맞춰 프로모션, 선물 기획전, 검색 광고 노출 여부를 검토할 수 있습니다."
            ),
            "marketNote": (
                "특정 원물 가격과 직접 연결하기 어려운 상품군입니다. "
                "가격 데이터보다는 검색·쇼핑 관심과 판매 기획 맥락을 중심으로 참고하는 것이 적합합니다."
            ),
            "caution": (
                "네이버 기준 관심 신호이며 전체 시장 수요로 단정하지 않습니다. "
                "기념일·행사성 키워드는 기간 효과가 크므로 기준일과 노출 시점을 함께 확인해야 합니다."
            ),
        }

    # 3) 농산물 원물
    if item_type in ["raw_agri", "seasonal_agri"]:
        if has_market_data:
            market_note = "KAMIS 기준 가격과 공영도매시장 경락정보를 함께 참고할 수 있습니다."
        elif kamis_matched:
            market_note = "KAMIS 기준 가격을 참고할 수 있습니다."
        elif auction_matched:
            market_note = "공영도매시장 경락정보를 참고할 수 있습니다."
        else:
            market_note = (
                "시장 가격 데이터가 아직 연결되지 않았습니다. "
                "품목명 매칭 또는 표준 품목명 보정이 필요한지 확인하는 것이 좋습니다."
            )

        return {
            "summary": (
                f"{product_name}은/는 네이버 쇼핑인사이트 기준 관심 흐름이 확인된 {item_group}입니다. "
                f"{interest_sentence}"
            ),
            "recommendedUse": (
                recommended_use_from_type
                or "광고 노출, 재고 운영, 매입 타이밍을 함께 점검하는 데 적합합니다."
            ),
            "marketNote": market_note,
            "caution": (
                "네이버 기준 관심 신호이며 전체 시장 수요로 단정하지 않습니다. "
                "경락정보는 거래 단위와 이상치 여부를 함께 확인해야 합니다."
            ),
        }
    
    # 수산물
    if item_type == "seafood":
        return {
            "summary": (
                f"{product_name}은/는 네이버 쇼핑인사이트 기준 관심 흐름이 확인된 수산물 품목입니다. "
                f"{interest_sentence}"
            ),
            "recommendedUse": (
                recommended_use_from_type
                or "검색·쇼핑 관심 흐름을 바탕으로 판매 타이밍과 재고 운영을 검토하는 것이 적합합니다."
            ),
            "marketNote": (
                "현재 연결된 시장 가격 데이터는 농산물 중심이므로 수산물 가격은 별도 데이터 연동이 필요합니다. "
                "가격 판단보다는 검색·쇼핑 관심 흐름과 판매 기획 맥락을 우선 참고하는 것이 적합합니다."
            ),
            "caution": (
                "네이버 기준 관심 신호이며 전체 시장 수요로 단정하지 않습니다. "
                "수산물은 산지·어획량·수입량·냉동·생물 여부에 따라 가격 변동 요인이 달라 별도 기준 데이터가 필요합니다."
            ),
        }

    # 축산물
    if item_type == "meat":
        return {
            "summary": (
                f"{product_name}은/는 네이버 쇼핑인사이트 기준 관심 흐름이 확인된 축산물 품목입니다. "
                f"{interest_sentence}"
            ),
            "recommendedUse": (
                recommended_use_from_type
                or "검색·쇼핑 관심 흐름을 바탕으로 판매 타이밍과 재고 운영을 검토하는 것이 적합합니다."
            ),
            "marketNote": (
                "현재 연결된 시장 가격 데이터는 농산물 중심이므로 축산물 가격은 별도 데이터 연동이 필요합니다. "
                "가격 판단보다는 검색·쇼핑 관심 흐름과 판매 기획 맥락을 우선 참고하는 것이 적합합니다."
            ),
            "caution": (
                "네이버 기준 관심 신호이며 전체 시장 수요로 단정하지 않습니다. "
                "축산물은 등급·부위·원산지·냉장/냉동 여부에 따라 가격 차이가 크므로 별도 기준 데이터가 필요합니다."
            ),
        }

    # 4) 원재료/소재
    if item_type == "ingredient":
        return {
            "summary": (
                f"{product_name}은/는 음료·디저트 상품화로 확장 가능한 원재료형 후보입니다. "
                "검색·쇼핑 관심 흐름과 상품 수 증가 여부를 함께 확인하는 것이 적합합니다. "
                f"{interest_sentence}"
            ),
            "recommendedUse": (
                recommended_use_from_type
                or "소량 소싱, 테스트 메뉴, 신제품 기획 검토에 활용할 수 있습니다."
            ),
            "marketNote": (
                "원재료 가격은 별도 매핑이 필요하며, 소비자 관심과 원재료 가격이 직접 일치하지 않을 수 있습니다."
            ),
            "caution": (
                "검색 관심은 상품화 가능성의 참고 신호이며, 실제 수요 판단에는 상품 수·판매처·리뷰 증가 여부를 함께 봐야 합니다."
            ),
        }
    
    # 5) 가공식품 / 브랜드 / 완제품
    if item_type in ["processed_food", "brand_product"]:
        processed_sub_comment = build_processed_subgroup_comment(
            product_name=product_name,
            sub_group=sub_group,
            interest_sentence=interest_sentence,
            recommended_use_from_type=recommended_use_from_type,
        )

        if processed_sub_comment:
            return processed_sub_comment

        return {
            "summary": (
                f"{product_name}은/는 검색·쇼핑 반응을 중심으로 관찰할 수 있는 {item_group}입니다. "
                "원물 시장가격보다 판매 반응과 상품 노출 흐름을 중심으로 해석하는 것이 적합합니다. "
                f"{interest_sentence}"
            ),
            "recommendedUse": (
                recommended_use_from_type
                or "검색·쇼핑 반응을 중심으로 판매 반응과 콘텐츠 운영을 검토하는 것이 적합합니다."
            ),
            "marketNote": (
                "완제품 또는 가공식품 성격이 강해 공영도매시장 경락정보와 직접 연결하기 어렵습니다."
            ),
            "caution": (
                "시장 가격 미연결은 오류가 아니라 상품 유형에 따른 해석 제한입니다. "
                "브랜드, 용량, 제조 방식, 판매 채널에 따라 가격 차이가 발생할 수 있습니다."
            ),
        }

    # 6) unknown
    return {
        "summary": (
            f"{product_name}은/는 현재 자동 분류 기준으로 상품 유형 확인이 필요한 후보입니다. "
            f"{interest_sentence}"
        ),
        "recommendedUse": (
            "검색·쇼핑 흐름을 우선 관찰하고, 상품 유형을 보정한 뒤 시장 가격 연결 여부를 판단하는 것이 적합합니다."
        ),
        "marketNote": (
            market_data_status.get("reason")
            or "시장 가격 연결 여부를 판단하려면 상품 유형과 표준 품목명 확인이 필요합니다."
        ),
        "caution": (
            "네이버 기준 관심 신호이며 전체 시장 수요로 단정하지 않습니다. "
            "자동 분류가 어려운 상품은 수동 보정 후 해석하는 것이 안전합니다."
        ),
    }
def build_decision_comment(
    product_name: str,
    source_type: str,
    signal_group: str,
    rank_direction: str,
    shopping_growth_rate: float,
    search_growth_rate: float,
    market_data_status: Dict[str, Any],
    auction_detail: Optional[Dict[str, Any]],
    price_comment: Optional[str],
    product_type_info: Dict[str, Any],
    market_match_name: str = "",
    market_match_method: str = "direct",
    market_match_reason: str = "",
    sub_group: str = "",
) -> Dict[str, Any]:
    """
    상품 유형, sub_group, 시장 데이터 연결 상태, alias 매칭 정보를 바탕으로
    화면에 노출할 EarlyPick 판단 문구를 생성한다.
    """

    interest = {
        "label": "관심 유지",
        "level": "neutral",
    }

    if shopping_growth_rate >= 10:
        interest = {
            "label": "관심 증가",
            "level": "positive",
        }
    elif shopping_growth_rate <= -10:
        interest = {
            "label": "관심 하락",
            "level": "negative",
        }

    type_comment = build_type_based_comment(
        product_name=product_name,
        product_type_info=product_type_info,
        market_data_status=market_data_status,
        shopping_growth_rate=shopping_growth_rate,
        market_match_name=market_match_name,
        market_match_method=market_match_method,
        market_match_reason=market_match_reason,
        sub_group=sub_group,
    )

    return {
        "summary": type_comment["summary"],
        "interestLabel": interest["label"],
        "interestLevel": interest["level"],
        "recommendedUse": type_comment["recommendedUse"],
        "marketNote": type_comment["marketNote"],
        "caution": type_comment["caution"],
        "classificationConfidence": product_type_info.get("classificationConfidence", "low"),
        "classificationReason": product_type_info.get("classificationReason", ""),
    }


def build_product_object(
    product_name: str,
    today_rank: Optional[int],
    previous_rank: Optional[int],
    source_type: str,
    source: str,
    note: str,
    product_group: str,
    sub_group: str,
    exclude_from_opportunity: str,
    history: pd.DataFrame,
    event_df: pd.DataFrame,
    date_str: str,
    price_lookup: Dict[str, Dict[str, Dict[str, Any]]],
    price_detail_lookup: Dict[str, Dict[str, Any]],
    kamis_meta_lookup: Dict[str, Dict[str, Any]],
    auction_detail_lookup: Dict[str, Dict[str, Any]],
    product_type_map: Dict[str, Dict[str, Any]],
    product_alias_map: Dict[str, Dict[str, str]],
) -> Dict[str, Any]:
    recent = history.tail(7).copy()

    # 쇼핑 상품명과 시장가격 매칭용 표준 품목명이 다를 수 있음
    # 예: 쌀20kg → 쌀
    alias_info = product_alias_map.get(product_name, {})

    market_match_name = alias_info.get("marketMatchName", product_name)
    market_match_method = alias_info.get("marketMatchMethod", "direct")
    market_match_reason = alias_info.get(
        "marketMatchReason",
        "상품명 기준으로 시장 가격 데이터를 조회합니다.",
    )

    if recent.empty:
        raise ValueError(f"검색/쇼핑 이력이 비어 있습니다: {product_name}")

    if "search_ratio" not in recent.columns or "shopping_ratio" not in recent.columns:
        raise ValueError(f"검색/쇼핑 컬럼이 없습니다: {product_name}")
    
    search_today = safe_float(recent["search_ratio"].iloc[-1], 0.0)
    shopping_today = safe_float(recent["shopping_ratio"].iloc[-1], 0.0)

    search_growth_rate = compute_recent_growth(recent["search_ratio"])
    shopping_growth_rate = compute_recent_growth(recent["shopping_ratio"])

    search_lead_days = compute_search_lead_days(recent["search_ratio"], recent["shopping_ratio"])
    conversion_score = compute_conversion_score(search_today, shopping_today)
    persistence_score = compute_persistence_score(recent["search_ratio"])
    bubble_risk_score = compute_bubble_risk(recent["search_ratio"], recent["shopping_ratio"])

    signal_group = classify_signal_group(
        search_lead_days=search_lead_days,
        conversion_score=conversion_score,
        persistence_score=persistence_score,
        bubble_risk_score=bubble_risk_score,
        search_today=search_today,
        shopping_today=shopping_today,
    )

    signal_label = SIGNAL_LABELS[signal_group]
    action = DEFAULT_ACTIONS[signal_group]

    market_group = infer_market_group(product_name)
    category, sub_category = infer_category_and_subcategory(product_name)
    origin_type = infer_origin_type(market_group)
    unit = infer_unit(product_name)

    drivers = infer_drivers(product_name, signal_group, search_lead_days, bubble_risk_score, source_type)
    event_tags = infer_event_tags(product_name, event_df)

    signal_score = round(
        min(
            100.0,
            (
                max(0, search_lead_days) * 8
                + conversion_score * 0.35
                + persistence_score * 0.25
                + (100 - bubble_risk_score) * 0.32
            ),
        ),
        1,
    )

    price_info = (
        price_lookup.get(product_name)
        or price_lookup.get(market_match_name)
        or {}
    )

    price_detail = (
        price_detail_lookup.get(product_name)
        or price_detail_lookup.get(market_match_name)
        or {
            "wholesaleAverageNow": None,
            "retailAverageNow": None,
            "wholesaleSeries7d": [],
            "retailSeries7d": [],
            "wholesaleMarkets": [],
            "retailMarkets": [],
            "variants": [],
        }
    )

    kamis_meta = (
        kamis_meta_lookup.get(product_name)
        or kamis_meta_lookup.get(market_match_name)
        or {
            "itemName": "",
            "kindName": "",
            "rankName": "",
            "retailUnitName": "",
            "wholesaleUnitName": "",
            "label": "",
        }
    )
    auction_detail = (
        auction_detail_lookup.get(product_name)
        or auction_detail_lookup.get(market_match_name)
    )

    wholesale_info = price_info.get("wholesale")
    retail_info = price_info.get("retail")

    has_price_data = wholesale_info is not None or retail_info is not None
    click_efficiency = compute_click_efficiency(search_today, shopping_today)

    kamis_matched = wholesale_info is not None or retail_info is not None
    auction_matched = auction_detail is not None

    if kamis_matched and auction_matched:
        market_data_status = {
            "kamisMatched": True,
            "auctionMatched": True,
            "marketType": "fresh_market",
            "reason": "KAMIS 가격과 전국 도매시장 경락정보가 모두 연결되었습니다.",
        }
    elif kamis_matched:
        market_data_status = {
            "kamisMatched": True,
            "auctionMatched": False,
            "marketType": "kamis_only",
            "reason": "KAMIS 도매·소매 가격만 연결되었습니다.",
        }
    elif auction_matched:
        market_data_status = {
            "kamisMatched": False,
            "auctionMatched": True,
            "marketType": "auction_only",
            "reason": "전국 도매시장 경락정보만 연결되었습니다.",
        }
    else:
        market_data_status = {
            "kamisMatched": False,
            "auctionMatched": False,
            "marketType": "processed_food",
            "reason": "가공식품으로 KAMIS·경락정보 직접 연결이 제한적입니다.",
        }
    
    product_type_info = infer_product_type(
        product_name=product_name,
        manual_type_map=product_type_map,
        market_data_status=market_data_status,
        product_group=product_group,
        sub_group=sub_group,
    )

    rank_change_info = build_rank_change_info(today_rank, previous_rank)
    rank_change_value = rank_change_info.get("rankChange")
    rank_direction = rank_change_info.get("rankDirection", "none")
    
    opportunity_score = compute_opportunity_score(
        source_type=source_type,
        today_rank=today_rank,
        rank_change=rank_change_value,
        search_growth_rate=search_growth_rate,
        shopping_growth_rate=shopping_growth_rate,
        conversion_score=conversion_score,
        persistence_score=persistence_score,
        bubble_risk_score=bubble_risk_score,
        market_group=market_group,
        drivers=drivers,
        has_price_data=has_price_data,
    )

    opportunity_reason = build_opportunity_reason(
        source_type=source_type,
        today_rank=today_rank,
        rank_change=rank_change_value,
        search_growth_rate=search_growth_rate,
        shopping_growth_rate=shopping_growth_rate,
        market_group=market_group,
        has_price_data=has_price_data,
    )
    price_comment = build_price_comment(wholesale_info, retail_info)

    current_price_risk = build_price_risk(market_group, bubble_risk_score)
    merged_price_risk = merge_price_risk(current_price_risk, wholesale_info, retail_info)

    primary_price = retail_info if retail_info else wholesale_info

    product_id_rank = today_rank if today_rank is not None else f"sns-{product_name}"
   
    decision_comment = build_decision_comment(
        product_name=product_name,
        source_type=source_type,
        signal_group=signal_group,
        rank_direction=rank_direction,
        shopping_growth_rate=shopping_growth_rate,
        search_growth_rate=search_growth_rate,
        market_data_status=market_data_status,
        auction_detail=auction_detail,
        price_comment=price_comment,
        product_type_info=product_type_info,
        market_match_name=market_match_name,
        market_match_method=market_match_method,
        market_match_reason=market_match_reason,
        sub_group=sub_group,
    )

    return {
        "id": f"{date_str}-{product_id_rank}",
        "name": product_name,
        "todayRank": today_rank,
        "naverRank": today_rank,
        "isInNaverTop200": today_rank is not None and today_rank <= 200,
        "naverRankLabel": f"네이버 {today_rank}위 확인" if today_rank is not None and today_rank <= 200 else "네이버 Top200 미확인",
        "previousRank": rank_change_info["previousRank"],
        "rankChange": rank_change_info["rankChange"],
        "rankDirection": rank_change_info["rankDirection"],
        "rankChangeLabel": rank_change_info["rankChangeLabel"],
        "marketGroup": market_group,

        "itemType": product_type_info.get("itemType"),
        "itemGroup": product_type_info.get("itemGroup"),
        "decisionAxis": product_type_info.get("decisionAxis"),
        "priceInterpretation": product_type_info.get("priceInterpretation"),
        "recommendedUse": product_type_info.get("recommendedUse"),
        "classificationMethod": product_type_info.get("classificationMethod"),
        "classificationConfidence": product_type_info.get("classificationConfidence"),
        "classificationReason": product_type_info.get("classificationReason"),
        "autoClassified": product_type_info.get("autoClassified"),

        "category": category,
        "subCategory": sub_category,
        "originType": origin_type,
        "unit": unit,
        "origin": "국내산" if origin_type == "국내산" else "수입",
        "sourceType": source_type,
        "source": source,
        "sourceNote": note,
        "productGroup": product_group,
        "subGroup": sub_group,
        "excludeFromOpportunity": str(exclude_from_opportunity).upper().strip() == "Y",
        "signalGroup": signal_group,
        "signalLabel": signal_label,
        "signalScore": signal_score,
        "action": action,
        "priceRisk": merged_price_risk,
        "searchGrowthRate": search_growth_rate,
        "shoppingGrowthRate": shopping_growth_rate,
        "clickEfficiency": click_efficiency,
        "opportunityScore": opportunity_score,
        "opportunityReason": opportunity_reason,
        "searchRatioToday": round(search_today, 1),
        "shoppingRatioToday": round(shopping_today, 1),
        "searchLeadDays": int(search_lead_days),
        "conversionScore": round(conversion_score, 1),
        "persistenceScore": round(persistence_score, 1),
        "bubbleRiskScore": round(bubble_risk_score, 1),
        "drivers": drivers,
        "summary": build_summary_text(signal_group, source_type),
        "detailReason": build_detail_reason(signal_group, search_lead_days, source_type),
        "decisionComment": decision_comment,
        "forecast7d": build_forecast7(signal_group, source_type),
        "forecast14d": build_forecast14(signal_group, source_type),

        "priceNow": primary_price["price_now"] if primary_price else None,
        "priceChangeRate": primary_price["change_rate"] if primary_price else None,
        "priceSource": "KAMIS" if primary_price else None,

        "wholesalePriceNow": wholesale_info["price_now"] if wholesale_info else None,
        "retailPriceNow": retail_info["price_now"] if retail_info else None,
        "wholesaleTrend": wholesale_info["trend"] if wholesale_info else None,
        "retailTrend": retail_info["trend"] if retail_info else None,
        "wholesaleChangeRate": wholesale_info["change_rate"] if wholesale_info else None,
        "retailChangeRate": retail_info["change_rate"] if retail_info else None,
        "priceComment": price_comment,
        "priceDetail": price_detail,
        "priceMeta": kamis_meta,
        "auctionDetail": auction_detail,
        "marketDataStatus": market_data_status,
        "weatherRisk": build_weather_risk(market_group),
        "fxRisk": build_fx_risk(market_group),
        "eventTags": event_tags,
        "series": {
            "search": [
                {
                    "date": d.strftime("%m-%d") if pd.notna(d) else "",
                    "value": round(safe_float(v), 1),
                }
                for d, v in zip(recent["period"], recent["search_ratio"])
            ],
            "shopping": [
                {
                    "date": d.strftime("%m-%d") if pd.notna(d) else "",
                    "value": round(safe_float(v), 1),
                }
                for d, v in zip(recent["period"], recent["shopping_ratio"])
            ],
        },
    }


# =========================================================
# 6. 메인
# =========================================================
def main():
    latest_top20_file = find_latest_top20_file()
    suffix = parse_suffix_from_filename(latest_top20_file.name, TOP20_PREFIX)
    if not suffix:
        raise ValueError(f"파일명 형식을 해석할 수 없습니다: {latest_top20_file.name}")

    product_daily_file = find_matching_file(PRODUCT_DAILY_PREFIX, suffix)
    candidates_file = find_matching_file(CANDIDATES_PREFIX, suffix)
    price_daily_file = find_optional_matching_file(KAMIS_PRICE_DAILY_PREFIX, suffix)
    rising_feature_file = find_optional_matching_file(RISING_FEATURE_PREFIX, suffix)
    rising_feature_lookup = load_rising_feature_lookup(rising_feature_file)

    auction_summary_file = find_optional_matching_file(AUCTION_SUMMARY_PREFIX, suffix)
    auction_market_summary_file = find_optional_matching_file(AUCTION_MARKET_SUMMARY_PREFIX, suffix)
    auction_variety_summary_file = find_optional_matching_file(AUCTION_VARIETY_SUMMARY_PREFIX, suffix)

    print(f"Top20 파일: {latest_top20_file}")
    print(f"Product Daily 파일: {product_daily_file}")
    print(f"Rising feature 파일: {rising_feature_file if rising_feature_file else '없음'}")
    print(f"Rising feature 연결 상품 수: {len(rising_feature_lookup)}")
    print(f"Candidates 파일: {candidates_file}")
    print(f"KAMIS Price 파일: {price_daily_file if price_daily_file else '없음'}")

    print(f"Auction Summary 파일: {auction_summary_file if auction_summary_file else '없음'}")
    print(f"Auction Market Summary 파일: {auction_market_summary_file if auction_market_summary_file else '없음'}")
    print(f"Auction Variety Summary 파일: {auction_variety_summary_file if auction_variety_summary_file else '없음'}")

    top20_df = load_csv_with_fallback(latest_top20_file)
    product_daily_df = load_csv_with_fallback(product_daily_file)
    candidates_df = load_csv_with_fallback(candidates_file)
    event_df = read_event_tags(EVENT_TAG_FILE)
    product_type_map = load_product_type_map(PRODUCT_TYPE_MAP_FILE)
    product_alias_map = load_product_alias_map(PRODUCT_ALIAS_MAP_FILE)
    
    price_lookup = load_price_daily_summary(price_daily_file)
    price_detail_lookup = load_price_detail_lookup(price_daily_file)
    kamis_meta_lookup = load_kamis_meta_lookup(KAMIS_MAP_FILE)

    auction_detail_lookup = load_auction_detail_lookup(
        summary_path=auction_summary_file,
        market_summary_path=auction_market_summary_file,
        variety_summary_path=auction_variety_summary_file,
    )
    previous_candidates_file = find_previous_day_file(CANDIDATES_PREFIX, suffix)
    previous_rank_lookup = load_previous_rank_lookup(previous_candidates_file)
    
    print(f"KAMIS 가격 상세 연결 상품 수: {len(price_detail_lookup)}")
    print(f"KAMIS 가격 연결 상품 수: {len(price_lookup)}")
    print(f"KAMIS 메타 연결 상품 수: {len(kamis_meta_lookup)}")
    print(f"상품 유형 수동 보정 수: {len(product_type_map)}")
    print(f"상품 alias 매칭 수: {len(product_alias_map)}")
    print(f"이전 Candidates 파일: {previous_candidates_file if previous_candidates_file else '없음'}")
    print(f"이전 순위 비교 상품 수: {len(previous_rank_lookup)}")
    print(f"경락정보 연결 상품 수: {len(auction_detail_lookup)}")

    top20_df.columns = [str(c).strip() for c in top20_df.columns]
    product_daily_df.columns = [str(c).strip() for c in product_daily_df.columns]
    candidates_df.columns = [str(c).strip() for c in candidates_df.columns]

    if "product_group" not in candidates_df.columns:
        candidates_df["product_group"] = ""

    if "sub_group" not in candidates_df.columns:
        candidates_df["sub_group"] = ""

    if "exclude_from_opportunity" not in candidates_df.columns:
        candidates_df["exclude_from_opportunity"] = "N"

    candidates_df["product_group"] = candidates_df["product_group"].astype(str).map(normalize_text)
    candidates_df["sub_group"] = candidates_df["sub_group"].astype(str).map(normalize_text)
    candidates_df["exclude_from_opportunity"] = (
        candidates_df["exclude_from_opportunity"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    required_top20 = {"date", "rank", "product_name"}
    missing_top20 = required_top20 - set(top20_df.columns)
    if missing_top20:
        raise ValueError(f"top20_with_search_shopping 파일 필수 컬럼 누락: {missing_top20}")

    required_daily = {"product_name", "period", "search_ratio", "shopping_ratio"}
    missing_daily = required_daily - set(product_daily_df.columns)
    if missing_daily:
        raise ValueError(f"product_daily_search_shopping 파일 필수 컬럼 누락: {missing_daily}")

    required_candidates = {"date", "slot", "source_type", "source", "product_name"}
    missing_candidates = required_candidates - set(candidates_df.columns)
    if missing_candidates:
        raise ValueError(f"candidates_with_search_shopping 파일 필수 컬럼 누락: {missing_candidates}")

    top20_df["product_name"] = top20_df["product_name"].astype(str).map(normalize_text)
    product_daily_df["product_name"] = product_daily_df["product_name"].astype(str).map(normalize_text)
    candidates_df["product_name"] = candidates_df["product_name"].astype(str).map(normalize_text)

    top20_df["date"] = pd.to_datetime(top20_df["date"], errors="coerce")
    top20_df["rank"] = pd.to_numeric(top20_df["rank"], errors="coerce")
    product_daily_df["period"] = pd.to_datetime(product_daily_df["period"], errors="coerce")
    candidates_df["date"] = pd.to_datetime(candidates_df["date"], errors="coerce")

    if "rank" in candidates_df.columns:
        candidates_df["rank"] = pd.to_numeric(candidates_df["rank"], errors="coerce")
    else:
        candidates_df["rank"] = pd.NA

    top20_df = top20_df.dropna(subset=["date", "rank"]).copy()
    product_daily_df = product_daily_df.dropna(subset=["period"]).copy()
    candidates_df = candidates_df.dropna(subset=["date"]).copy()

    latest_date = top20_df["date"].max()
    date_str = latest_date.strftime("%Y-%m-%d")

    naver_signal_date = date_str
    price_as_of_date = get_price_as_of_date(price_daily_file)
    analysis_date = datetime.now().strftime("%Y-%m-%d")

    today_top20 = (
        top20_df[top20_df["date"] == latest_date]
        .sort_values("rank")
        .reset_index(drop=True)
    )

    today_candidates = (
        candidates_df[candidates_df["date"] == latest_date]
        .copy()
        .reset_index(drop=True)
    )

    # 오늘 기준 네이버 인기순위 lookup
    # - Top20은 top20_df에서 가져옴
    # - Top21~200은 candidates_df의 rising/top200 rank에서 가져옴
    naver_rank_sources = []

    if not today_top20.empty:
        top20_rank_df = today_top20[["product_name", "rank"]].copy()
        top20_rank_df["rankSource"] = "top20"
        naver_rank_sources.append(top20_rank_df)

    if "rank" in today_candidates.columns:
        candidate_rank_df = today_candidates[
            today_candidates["rank"].notna()
        ][["product_name", "rank", "source_type"]].copy()

        if not candidate_rank_df.empty:
            candidate_rank_df["rankSource"] = candidate_rank_df["source_type"].astype(str)
            candidate_rank_df = candidate_rank_df[["product_name", "rank", "rankSource"]]
            naver_rank_sources.append(candidate_rank_df)

    if naver_rank_sources:
        naver_rank_df = pd.concat(naver_rank_sources, ignore_index=True)
        naver_rank_df["product_name"] = naver_rank_df["product_name"].astype(str).map(normalize_text)
        naver_rank_df["rank"] = pd.to_numeric(naver_rank_df["rank"], errors="coerce")
        naver_rank_df = naver_rank_df.dropna(subset=["product_name", "rank"]).copy()
        naver_rank_df["rank"] = naver_rank_df["rank"].astype(int)

        # 같은 상품이 여러 번 있으면 가장 높은 순위, 즉 숫자가 작은 rank 사용
        naver_rank_lookup = (
            naver_rank_df
            .sort_values("rank")
            .drop_duplicates(subset=["product_name"])
            .set_index("product_name")["rank"]
            .to_dict()
        )
    else:
        naver_rank_lookup = {}

    print(f"오늘 네이버 순위 lookup 상품 수: {len(naver_rank_lookup)}")

    naver_products_output: List[Dict[str, Any]] = []
    rising_products_output: List[Dict[str, Any]] = []
    sns_products_output: List[Dict[str, Any]] = []

    # 네이버 Top20
    for _, row in today_top20.iterrows():
        product_name = normalize_text(row["product_name"])
        today_rank = int(row["rank"])

        history = (
            product_daily_df[product_daily_df["product_name"] == product_name]
            .copy()
            .sort_values("period")
            .reset_index(drop=True)
        )

        if history.empty:
            print(f"[SKIP] 검색/쇼핑 이력 없음: {product_name} / source_type=top20")
            continue

        if "search_ratio" not in history.columns or "shopping_ratio" not in history.columns:
            print(f"[SKIP] 검색/쇼핑 컬럼 없음: {product_name} / source_type=top20")
            continue

        previous_rank = previous_rank_lookup.get(product_name)

        obj = build_product_object(
            product_name=product_name,
            today_rank=today_rank,
            previous_rank=previous_rank,
            source_type="top20",
            source="naver_datalab",
            note="",
            product_group="",
            sub_group="",
            exclude_from_opportunity="N",
            history=history,
            event_df=event_df,
            date_str=date_str,
            price_lookup=price_lookup,
            price_detail_lookup=price_detail_lookup,
            kamis_meta_lookup=kamis_meta_lookup,
            auction_detail_lookup=auction_detail_lookup,
            product_type_map=product_type_map,
            product_alias_map=product_alias_map,
        )
        naver_products_output.append(obj)

    #Rising 후보
    rising_only = today_candidates[today_candidates["source_type"] == "rising"].copy()
    rising_only = rising_only.drop_duplicates(subset=["product_name"]).reset_index(drop=True)

    for _, row in rising_only.iterrows():
        product_name = normalize_text(row["product_name"])
        source = normalize_text(row.get("source", "naver_top200"))
        note = normalize_text(row.get("note", ""))
        rank_value = row.get("rank")

        today_rank = None
        if pd.notna(rank_value):
            today_rank = int(rank_value)

        history = (
            product_daily_df[product_daily_df["product_name"] == product_name]
            .copy()
            .sort_values("period")
            .reset_index(drop=True)
        )

        if history.empty:
            print(f"[SKIP] 검색/쇼핑 이력 없음: {product_name} / source_type=rising")
            continue

        if "search_ratio" not in history.columns or "shopping_ratio" not in history.columns:
            print(f"[SKIP] 검색/쇼핑 컬럼 없음: {product_name} / source_type=rising")
            continue
        previous_rank = previous_rank_lookup.get(product_name)
        obj = build_product_object(
            product_name=product_name,
            today_rank=today_rank,
            previous_rank=previous_rank,
            source_type="rising",
            source=source,
            note=note,
            product_group=normalize_text(row.get("product_group", "")),
            sub_group=normalize_text(row.get("sub_group", "")),
            exclude_from_opportunity=normalize_text(row.get("exclude_from_opportunity", "N")),
            history=history,
            event_df=event_df,
            date_str=date_str,
            price_lookup=price_lookup,
            price_detail_lookup=price_detail_lookup,
            kamis_meta_lookup=kamis_meta_lookup,
            auction_detail_lookup=auction_detail_lookup,
            product_type_map=product_type_map,
            product_alias_map=product_alias_map,
        )

        obj["rankRange"] = normalize_text(row.get("rank_range", ""))
        feature = rising_feature_lookup.get(product_name, {})

        if feature:
            obj.update(feature)

            # 기존 opportunityScore보다 risingScore가 더 높으면 상승 후보 점수로 보정
            rising_score = safe_float(feature.get("risingScore"), 0.0)
            current_score = safe_float(obj.get("opportunityScore"), 0.0)

            if rising_score > current_score:
                obj["opportunityScore"] = rising_score

            if feature.get("risingReason"):
                obj["opportunityReason"] = feature["risingReason"]

            if feature.get("risingStage"):
                obj["risingStage"] = feature["risingStage"]

        rising_products_output.append(obj)

    # SNS 후보
    sns_only = today_candidates[today_candidates["source_type"] == "sns"].copy()
    sns_only = sns_only.drop_duplicates(subset=["product_name"]).reset_index(drop=True)

    for _, row in sns_only.iterrows():
        product_name = normalize_text(row["product_name"])
        source = normalize_text(row.get("source", "sns"))
        note = normalize_text(row.get("note", ""))

        today_rank = naver_rank_lookup.get(product_name)

        history = (
            product_daily_df[product_daily_df["product_name"] == product_name]
            .copy()
            .sort_values("period")
            .reset_index(drop=True)
        )

        if history.empty:
            print(f"[SKIP] 검색/쇼핑 이력 없음: {product_name} / source_type=sns")
            continue

        if "search_ratio" not in history.columns or "shopping_ratio" not in history.columns:
            print(f"[SKIP] 검색/쇼핑 컬럼 없음: {product_name} / source_type=sns")
            continue
        obj = build_product_object(
            product_name=product_name,
            today_rank=None,
            previous_rank=None,
            source_type="sns",
            source=source,
            note=note,
            product_group="",
            sub_group="",
            exclude_from_opportunity="N",
            history=history,
            event_df=event_df,
            date_str=date_str,
            price_lookup=price_lookup,
            price_detail_lookup=price_detail_lookup,
            kamis_meta_lookup=kamis_meta_lookup,
            auction_detail_lookup=auction_detail_lookup,
            product_type_map=product_type_map,
            product_alias_map=product_alias_map,
        )

        obj["isInNaverTop200"] = today_rank is not None
        obj["naverRank"] = today_rank
        obj["naverRankLabel"] = f"네이버 {today_rank}위 확인" if today_rank is not None else "네이버 Top200 미확인"

        sns_products_output.append(obj)

    naver_products_output = sorted(
        naver_products_output,
        key=lambda x: (x["todayRank"] is None, x["todayRank"])
    )

    rising_products_output = sorted(
        rising_products_output,
        key=lambda x: (
            -safe_float(x.get("opportunityScore"), 0.0),
            x["todayRank"] is None,
            x["todayRank"] if x["todayRank"] is not None else 9999,
        )
    )

    sns_products_output = sorted(sns_products_output, key=lambda x: x["name"])

    summary = {
        "analyzedCount": len(naver_products_output),
        "earlyCount": sum(1 for p in naver_products_output if p["signalGroup"] == "early"),
        "conversionCount": sum(1 for p in naver_products_output if p["signalGroup"] == "conversion"),
        "overheatedCount": sum(1 for p in naver_products_output if p["signalGroup"] == "overheated"),
        "priceRiskCount": sum(1 for p in naver_products_output if p["priceRisk"] == "높음"),
    }

    sns_summary = {
        "candidateCount": len(sns_products_output),
        "earlyCount": sum(1 for p in sns_products_output if p["signalGroup"] == "early"),
        "conversionCount": sum(1 for p in sns_products_output if p["signalGroup"] == "conversion"),
        "overheatedCount": sum(1 for p in sns_products_output if p["signalGroup"] == "overheated"),
    }

    rising_summary = {
    "candidateCount": len(rising_products_output),
    "earlyCount": sum(1 for p in rising_products_output if p["signalGroup"] == "early"),
    "conversionCount": sum(1 for p in rising_products_output if p["signalGroup"] == "conversion"),
    "overheatedCount": sum(1 for p in rising_products_output if p["signalGroup"] == "overheated"),
    }

    highlights = {
        "early": [p["name"] for p in naver_products_output if p["signalGroup"] == "early"][:3],
        "conversion": [p["name"] for p in naver_products_output if p["signalGroup"] == "conversion"][:3],
        "overheated": [p["name"] for p in naver_products_output if p["signalGroup"] == "overheated"][:3],
    }

    sns_highlights = {
        "early": [p["name"] for p in sns_products_output if p["signalGroup"] == "early"][:3],
        "conversion": [p["name"] for p in sns_products_output if p["signalGroup"] == "conversion"][:3],
        "overheated": [p["name"] for p in sns_products_output if p["signalGroup"] == "overheated"][:3],
    }

    output = {
       "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dateLabel": date_str,
        "naverSignalDate": naver_signal_date,
        "priceAsOfDate": price_as_of_date,
        "analysisDate": analysis_date,
        "summary": summary,
        "snsSummary": sns_summary,
        "risingSummary": rising_summary,
        "highlights": highlights,
        "snsHighlights": sns_highlights,
        "products": naver_products_output,
        "naverTop20": naver_products_output,
        "risingCandidates": rising_products_output,
        "snsCandidates": sns_products_output,
        }

    slot_part = "am" if suffix.endswith("_am") else "pm" if suffix.endswith("_pm") else "am"
    month_dir = latest_date.strftime("%Y-%m")

    dated_output_path = OUTPUT_DIR / month_dir / f"daily_signals_{date_str}_{slot_part}.json"
    latest_output_path = LATEST_DIR / "daily_signals.json"
    frontend_output_path = FRONTEND_PUBLIC_DIR / "daily_signals.json"

    save_json(output, dated_output_path)
    save_json(output, latest_output_path)
    save_json(output, frontend_output_path)

    print("\n완료")
    print(f"날짜별 JSON: {dated_output_path}")
    print(f"latest JSON: {latest_output_path}")
    print(f"frontend JSON: {frontend_output_path}")
    print(f"네이버 Top20 상품 수: {summary['analyzedCount']}")
    print(f"SNS 후보 수: {sns_summary['candidateCount']}")
    print(f"SNS 초기 선점: {sns_summary['earlyCount']}")
    print(f"SNS 구매전환: {sns_summary['conversionCount']}")
    print(f"SNS 과열 주의: {sns_summary['overheatedCount']}")
    print(f"네이버 기준일: {naver_signal_date}")
    print(f"가격 기준일: {price_as_of_date if price_as_of_date else '없음'}")
    print(f"분석 실행일: {analysis_date}")


if __name__ == "__main__":
    main()