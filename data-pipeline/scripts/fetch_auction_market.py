import json
import os
import time
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
from requests.exceptions import RequestException

from dotenv import load_dotenv
import os

load_dotenv()
# =========================================================
# 1. 설정
# =========================================================
BASE_DIR = Path(__file__).resolve().parents[1]

PROCESSED_DIR = BASE_DIR / "data" / "daily" / "processed"
HISTORICAL_DIR = BASE_DIR / "data" / "historical"

TOP20_PREFIX = "top20_with_search_shopping_"
ITEM_MAP_FILE = HISTORICAL_DIR / "auction_item_map.csv"

AUCTION_ITEM_MAP_AUTO_PREFIX = "auction_item_map_auto_"

API_URL = "https://apis.data.go.kr/B552845/katRealTime2/trades2"

# 환경변수 우선. 없으면 아래 문자열에 직접 넣어도 됨.
SERVICE_KEY = os.getenv("PUBLIC_DATA_SERVICE_KEY", "").strip()


NUM_OF_ROWS = 500
MAX_PAGES = 30

API_RETRY_COUNT = 3
API_RETRY_SLEEP_SECONDS = 2
API_SLEEP_BETWEEN_ITEMS = 0.6


# =========================================================
# 2. 공통 유틸
# =========================================================
def load_csv_with_fallback(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"파일이 없습니다: {path}")

    for enc in ["utf-8-sig", "cp949", "euc-kr", "utf-8"]:
        try:
            return pd.read_csv(path, encoding=enc, dtype=str)
        except UnicodeDecodeError:
            continue

    raise ValueError(f"CSV 인코딩을 확인해주세요: {path}")

def find_matching_file(prefix: str, suffix: str) -> Path:
    candidates = list(PROCESSED_DIR.rglob(f"{prefix}{suffix}.csv"))
    if not candidates:
        raise FileNotFoundError(f"processed 폴더에 {prefix}{suffix}.csv 파일이 없습니다.")
    return candidates[0]


def extract_date_slot_from_name(file_name: str, prefix: str) -> tuple[str, str]:
    if not file_name.startswith(prefix) or not file_name.endswith(".csv"):
        return ("0000-00-00", "am")

    suffix = file_name[len(prefix):-4]
    parts = suffix.rsplit("_", 1)

    if len(parts) != 2:
        return ("0000-00-00", "am")

    return parts[0], parts[1]


def find_latest_top20_file() -> Path:
    files = list(PROCESSED_DIR.rglob(f"{TOP20_PREFIX}*.csv"))

    if not files:
        raise FileNotFoundError("processed 폴더에 top20_with_search_shopping_*.csv 파일이 없습니다.")

    def sort_key(path: Path):
        date_part, slot_part = extract_date_slot_from_name(path.name, TOP20_PREFIX)
        slot_order = 0 if slot_part == "am" else 1
        return (date_part, slot_order)

    return max(files, key=sort_key)


def extract_body(response_json: Dict[str, Any]) -> Dict[str, Any]:
    if "response" in response_json:
        return response_json.get("response", {}).get("body", {})
    if "body" in response_json:
        return response_json.get("body", {})
    return response_json


def extract_items(response_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    body = extract_body(response_json)
    items = body.get("items", {})

    if isinstance(items, dict):
        item = items.get("item", [])
    else:
        item = items

    if isinstance(item, dict):
        return [item]

    if isinstance(item, list):
        return item

    return []


def get_total_count(response_json: Dict[str, Any]) -> int:
    body = extract_body(response_json)

    try:
        return int(body.get("totalCount", 0))
    except Exception:
        return 0


def to_number(value: Any) -> Optional[float]:
    if value is None:
        return None

    text = str(value).replace(",", "").strip()

    if text == "" or text.lower() in {"nan", "none", "null"}:
        return None

    try:
        return float(text)
    except Exception:
        return None


# =========================================================
# 3. API 호출
# =========================================================
def fetch_page(
    item_row: Dict[str, Any],
    target_date: str,
    page_no: int,
    num_of_rows: int = 500,
) -> Dict[str, Any]:
    params = {
        "serviceKey": SERVICE_KEY,
        "returnType": "JSON",
        "pageNo": page_no,
        "numOfRows": num_of_rows,
        "cond[trd_clcln_ymd::EQ]": target_date,
        "cond[gds_lclsf_cd::EQ]": str(item_row["gds_lclsf_cd"]).zfill(2),
        "cond[gds_mclsf_cd::EQ]": str(item_row["gds_mclsf_cd"]).zfill(2),
        "cond[gds_sclsf_cd::EQ]": str(item_row["gds_sclsf_cd"]).zfill(2),
    }

    product_name = str(item_row.get("product_name", "")).strip()

    last_error = None

    for attempt in range(1, API_RETRY_COUNT + 1):
        try:
            response = requests.get(API_URL, params=params, timeout=40)

            # 공공데이터 API 일시 장애/게이트웨이 오류는 재시도
            if response.status_code in {429, 500, 502, 503, 504}:
                print(
                    f"[WARN] 경락 API 일시 오류 "
                    f"{response.status_code} / {product_name} / page={page_no} "
                    f"/ retry {attempt}/{API_RETRY_COUNT}"
                )
                last_error = f"HTTP {response.status_code}"
                time.sleep(API_RETRY_SLEEP_SECONDS * attempt)
                continue

            response.raise_for_status()

            try:
                return response.json()
            except Exception:
                print("[WARN] JSON 파싱 실패")
                print(response.url)
                print(response.text[:1000])
                return {}

        except RequestException as e:
            last_error = repr(e)
            print(
                f"[WARN] 경락 API 요청 실패 / {product_name} / page={page_no} "
                f"/ retry {attempt}/{API_RETRY_COUNT} / {type(e).__name__}"
            )
            time.sleep(API_RETRY_SLEEP_SECONDS * attempt)

    print(
        f"[SKIP] 경락 API 조회 실패로 품목 건너뜀: "
        f"{product_name} / page={page_no} / last_error={last_error}"
    )

    return {}


def fetch_item_all_pages(
    item_row: Dict[str, Any],
    target_date: str,
    num_of_rows: int = 1000,
    max_pages: int = 30,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    product_name = item_row["product_name"]

    all_items: List[Dict[str, Any]] = []
    raw_pages: List[Dict[str, Any]] = []

    first_json = fetch_page(
        item_row=item_row,
        target_date=target_date,
        page_no=1,
        num_of_rows=num_of_rows,
    )
    if not first_json:
        print(f"[SKIP] 첫 페이지 응답 없음: {product_name}")
        return [], []

    raw_pages.append(first_json)

    total_count = get_total_count(first_json)
    first_items = extract_items(first_json)
    all_items.extend(first_items)

    print(f"\n[{product_name}] totalCount: {total_count}, page1: {len(first_items)}")

    if total_count <= 0:
        total_pages = 1
    else:
        total_pages = min(max_pages, (total_count + num_of_rows - 1) // num_of_rows)

    for page_no in range(2, total_pages + 1):
        page_json = fetch_page(
            item_row=item_row,
            target_date=target_date,
            page_no=page_no,
            num_of_rows=num_of_rows,
        )

        raw_pages.append(page_json)

        items = extract_items(page_json)
        all_items.extend(items)

        print(f"[{product_name}] page {page_no}: {len(items)}")

        if not items:
            break

    for row in all_items:
        row["product_name"] = product_name

    return all_items, raw_pages


# =========================================================
# 4. 정규화/집계
# =========================================================
def normalize_auction_df(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    expected_cols = [
        "product_name",
        "auctn_seq",
        "scsbd_dt",
        "trd_clcln_ymd",
        "whsl_mrkt_cd",
        "whsl_mrkt_nm",
        "corp_cd",
        "corp_nm",
        "gds_lclsf_cd",
        "gds_lclsf_nm",
        "gds_mclsf_cd",
        "gds_mclsf_nm",
        "gds_sclsf_cd",
        "gds_sclsf_nm",
        "corp_gds_cd",
        "corp_gds_item_nm",
        "corp_gds_vrty_nm",
        "plor_cd",
        "plor_nm",
        "scsbd_prc",
        "qty",
        "unit_qty",
        "unit_cd",
        "unit_nm",
        "pkg_cd",
        "pkg_nm",
        "spm_no",
        "trd_se",
    ]

    for col in expected_cols:
        if col not in df.columns:
            df[col] = ""

    df = df[expected_cols].copy()

    df["auction_price_num"] = df["scsbd_prc"].map(to_number)
    df["qty_num"] = df["qty"].map(to_number)
    df["unit_qty_num"] = df["unit_qty"].map(to_number)

    df["trade_qty_est"] = df["qty_num"] * df["unit_qty_num"]

    return df

def filter_auction_outliers(group: pd.DataFrame) -> pd.DataFrame:
    """
    경락정보 대표값 계산용 이상치 제거.
    원본 detail 데이터는 보존하고, summary 계산에만 사용한다.
    """
    valid = group.dropna(subset=["auction_price_num"]).copy()

    valid = valid[valid["auction_price_num"] > 0].copy()

    if "trade_qty_est" in valid.columns:
        valid = valid[
            valid["trade_qty_est"].notna()
            & (valid["trade_qty_est"] > 0)
        ].copy()

    if valid.empty:
        return valid

    median_price = valid["auction_price_num"].median()

    if median_price <= 0:
        return valid

    # 중앙값 기준 1차 이상치 제거
    valid = valid[
        (valid["auction_price_num"] >= median_price * 0.2)
        & (valid["auction_price_num"] <= median_price * 5)
    ].copy()

    if len(valid) < 10:
        return valid

    # 상하위 1% 극단값 제거
    low_q = valid["auction_price_num"].quantile(0.01)
    high_q = valid["auction_price_num"].quantile(0.99)

    valid = valid[
        (valid["auction_price_num"] >= low_q)
        & (valid["auction_price_num"] <= high_q)
    ].copy()

    return valid

def weighted_avg_price(group: pd.DataFrame) -> float:
    valid = filter_auction_outliers(group)

    if valid.empty:
        raw_valid = group.dropna(subset=["auction_price_num"]).copy()
        if raw_valid.empty:
            return 0.0
        return round(raw_valid["auction_price_num"].mean(), 1)

    value = (
        valid["auction_price_num"] * valid["trade_qty_est"]
    ).sum() / valid["trade_qty_est"].sum()

    return round(value, 1)


def build_product_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    raw_valid = df.dropna(subset=["auction_price_num"]).copy()

    if raw_valid.empty:
        return pd.DataFrame()

    rows = []

    for (product_name, date), group in raw_valid.groupby(["product_name", "trd_clcln_ymd"]):
        filtered = filter_auction_outliers(group)

        target = filtered if not filtered.empty else group

        outlier_count = max(0, len(group) - len(target))

        rows.append({
            "product_name": product_name,
            "auction_date": date,

            # 화면 표시용 대표값: 이상치 제거 후 계산
            "avg_auction_price": round(target["auction_price_num"].mean(), 1),
            "weighted_avg_auction_price": weighted_avg_price(group),
            "high_price": round(target["auction_price_num"].max(), 1),
            "low_price": round(target["auction_price_num"].min(), 1),

            # 거래물량도 필터링된 거래 기준
            "total_trade_qty": round(target["trade_qty_est"].sum(), 1),

            # 품질 확인용
            "row_count": len(group),
            "valid_row_count": len(target),
            "outlier_count": outlier_count,

            "market_count": target["whsl_mrkt_cd"].nunique(),
            "corp_count": target["corp_cd"].nunique(),
            "variety_count": target["corp_gds_vrty_nm"].nunique(),

            # 원본 참고용
            "raw_high_price": round(group["auction_price_num"].max(), 1),
            "raw_low_price": round(group["auction_price_num"].min(), 1),
        })

    return pd.DataFrame(rows)


def build_market_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    raw_valid = df.dropna(subset=["auction_price_num"]).copy()

    if raw_valid.empty:
        return pd.DataFrame()

    rows = []

    group_cols = [
        "product_name",
        "trd_clcln_ymd",
        "whsl_mrkt_cd",
        "whsl_mrkt_nm",
    ]

    for keys, group in raw_valid.groupby(group_cols):
        product_name, date, market_code, market_name = keys

        filtered = filter_auction_outliers(group)
        target = filtered if not filtered.empty else group

        outlier_count = max(0, len(group) - len(target))

        rows.append({
            "product_name": product_name,
            "auction_date": date,
            "market_code": market_code,
            "market_name": market_name,
            "weighted_avg_auction_price": weighted_avg_price(group),
            "high_price": round(target["auction_price_num"].max(), 1),
            "low_price": round(target["auction_price_num"].min(), 1),
            "total_trade_qty": round(target["trade_qty_est"].sum(), 1),
            "row_count": len(group),
            "valid_row_count": len(target),
            "outlier_count": outlier_count,
            "corp_count": target["corp_cd"].nunique(),
            "raw_high_price": round(group["auction_price_num"].max(), 1),
            "raw_low_price": round(group["auction_price_num"].min(), 1),
        })

    return pd.DataFrame(rows).sort_values(
        ["product_name", "total_trade_qty"],
        ascending=[True, False],
    )

def build_variety_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    raw_valid = df.dropna(subset=["auction_price_num"]).copy()

    if raw_valid.empty:
        return pd.DataFrame()

    rows = []

    group_cols = [
        "product_name",
        "trd_clcln_ymd",
        "corp_gds_vrty_nm",
        "unit_nm",
    ]

    for keys, group in raw_valid.groupby(group_cols):
        product_name, date, variety_name, unit_name = keys

        filtered = filter_auction_outliers(group)
        target = filtered if not filtered.empty else group

        outlier_count = max(0, len(group) - len(target))

        rows.append({
            "product_name": product_name,
            "auction_date": date,
            "variety_name": variety_name,
            "unit_name": unit_name,
            "weighted_avg_auction_price": weighted_avg_price(group),
            "high_price": round(target["auction_price_num"].max(), 1),
            "low_price": round(target["auction_price_num"].min(), 1),
            "total_trade_qty": round(target["trade_qty_est"].sum(), 1),
            "row_count": len(group),
            "valid_row_count": len(target),
            "outlier_count": outlier_count,
            "market_count": target["whsl_mrkt_cd"].nunique(),
            "raw_high_price": round(group["auction_price_num"].max(), 1),
            "raw_low_price": round(group["auction_price_num"].min(), 1),
        })

    return pd.DataFrame(rows).sort_values(
        ["product_name", "total_trade_qty"],
        ascending=[True, False],
    )


# =========================================================
# 5. 메인
# =========================================================
def main():
    if not SERVICE_KEY:
        raise ValueError("PUBLIC_DATA_SERVICE_KEY 환경변수 또는 SERVICE_KEY 값을 넣어주세요.")

    latest_top20_file = find_latest_top20_file()
    target_date, slot = extract_date_slot_from_name(latest_top20_file.name, TOP20_PREFIX)

    print(f"Top20 기준 파일: {latest_top20_file}")
    print(f"경락정보 조회 기준일: {target_date}")
    print(f"slot: {slot}")

    item_map_file = find_matching_file(AUCTION_ITEM_MAP_AUTO_PREFIX, f"{target_date}_{slot}")
    print(f"자동 생성 경락 품목 매핑 파일: {item_map_file}")

    item_map = load_csv_with_fallback(item_map_file)
    required = {
        "product_name",
        "gds_lclsf_cd",
        "gds_mclsf_cd",
        "gds_sclsf_cd",
    }

    missing = required - set(item_map.columns)

    if missing:
        raise ValueError(f"auction_item_map.csv 필수 컬럼 누락: {missing}")

    all_rows: List[Dict[str, Any]] = []
    raw_all: Dict[str, Any] = {}

    failed_products = []

    for _, row in item_map.iterrows():
        product_name = row["product_name"]

        try:
            rows, raw_pages = fetch_item_all_pages(
                item_row=row.to_dict(),
                target_date=target_date,
                num_of_rows=NUM_OF_ROWS,
                max_pages=MAX_PAGES,
            )

            all_rows.extend(rows)
            raw_all[product_name] = raw_pages

        except Exception as e:
            print(f"[SKIP] 경락정보 수집 실패: {product_name} / {type(e).__name__}: {e}")
            failed_products.append({
                "product_name": product_name,
                "error_type": type(e).__name__,
                "error": str(e),
            })

        time.sleep(API_SLEEP_BETWEEN_ITEMS)

    detail_df = normalize_auction_df(all_rows)
    summary_df = build_product_summary(detail_df)
    market_summary_df = build_market_summary(detail_df)
    variety_summary_df = build_variety_summary(detail_df)

    month_dir = datetime.strptime(target_date, "%Y-%m-%d").strftime("%Y-%m")
    output_dir = PROCESSED_DIR / month_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_path = output_dir / f"auction_raw_{target_date}_{slot}.json"
    detail_path = output_dir / f"auction_detail_{target_date}_{slot}.csv"
    summary_path = output_dir / f"auction_summary_{target_date}_{slot}.csv"
    market_summary_path = output_dir / f"auction_market_summary_{target_date}_{slot}.csv"
    variety_summary_path = output_dir / f"auction_variety_summary_{target_date}_{slot}.csv"
    failed_path = output_dir / f"auction_failed_{target_date}_{slot}.csv"

    with raw_path.open("w", encoding="utf-8") as f:
        json.dump(raw_all, f, ensure_ascii=False, indent=2)

    detail_df.to_csv(detail_path, index=False, encoding="utf-8-sig")
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
    market_summary_df.to_csv(market_summary_path, index=False, encoding="utf-8-sig")
    variety_summary_df.to_csv(variety_summary_path, index=False, encoding="utf-8-sig")
    if failed_products:
        pd.DataFrame(failed_products).to_csv(
            failed_path,
            index=False,
            encoding="utf-8-sig",
        )
        print(f"실패 품목 CSV: {failed_path}")

    print("\n완료")
    print(f"raw JSON: {raw_path}")
    print(f"상세 CSV: {detail_path}")
    print(f"요약 CSV: {summary_path}")
    print(f"시장별 요약 CSV: {market_summary_path}")
    print(f"품종별 요약 CSV: {variety_summary_path}")
    print(f"상세 row 수: {len(detail_df)}")
    print(f"요약 row 수: {len(summary_df)}")


if __name__ == "__main__":
    main()