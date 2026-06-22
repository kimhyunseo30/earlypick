import csv
import json
import time
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

import pandas as pd
import requests
from dotenv import load_dotenv
import os

load_dotenv()
#======================================================
# 1. 사용자 설정
#======================================================

# 검색어 트렌드용 키
SEARCH_CLIENT_ID = os.getenv("SEARCH_CLIENT_ID")
SEARCH_CLIENT_SECRET = os.getenv("SEARCH_CLIENT_SECRET")

# 쇼핑인사이트용 키
SHOPPING_CLIENT_ID = os.getenv("SHOPPING_CLIENT_ID")
SHOPPING_CLIENT_SECRET = os.getenv("SHOPPING_CLIENT_SECRET")

# 식품 카테고리 cat_id
SHOPPING_CATEGORY_ID = "50000006" 

# 최근 며칠 추이
LOOKBACK_DAYS =14

FORCE_TOP20_FILE = None
FORCE_SNS_FILE = None

#=======================================================
# 2. 기본 경로
#=======================================================
BASE_DIR = Path(__file__).resolve().parents[1]
RAW_DIR= BASE_DIR / "data" / "daily" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "daily" / "processed"

HISTORICAL_DIR = BASE_DIR / "data" / "historical"
SNS_MASTER_FILE = HISTORICAL_DIR / "sns_candidates_master.csv"
RISING_MASTER_FILE = HISTORICAL_DIR / "rising_candidates_master.csv"

SEARCH_URL = "https://openapi.naver.com/v1/datalab/search"
SHOPPING_URL = "https://openapi.naver.com/v1/datalab/shopping/category/keywords"


#========================================================
# 3. 공통 함수
#========================================================
def ensure_config():
    placeholders = {
        "검색어트렌드_클라이언트아이디",
        "검색어트렌드_클라이언트시크릿",
        "쇼핑인사이트_클라이언트아이디",
        "쇼핑인사이트_클라이언트시크릿",
        "식품_cat_id",
    }
    values = {
        SEARCH_CLIENT_ID,
        SEARCH_CLIENT_SECRET,
        SHOPPING_CLIENT_ID,
        SHOPPING_CLIENT_SECRET,
        SHOPPING_CATEGORY_ID,
    }
    if values & placeholders:
        raise ValueError("API 키와 SHOPPING_CATEGORY_ID를 실제 값으로 바꿔주세요")
    
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
    
def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ",str(text or "").strip())

def chunked(items: List[Any], size:int) -> List[List[Any]]:
    return [items[i:i + size]for i in range(0, len(items),size)]

def get_headers(client_id:str, client_secret:str) -> Dict[str, str]:
    return{
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
        "Content-Type":"application/json",
    }

def post_json(url:str, payload: dict, client_id:str, client_secret:str)->dict:
    response = requests.post(
        url,
        headers=get_headers(client_id, client_secret),
        json=payload,
        timeout=30,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"API 요청 실패\n"
            f"URL:{url}\n"
            f"상태코드:{response.status_code}\n"
            f"응답 본문: {response.text}" 
        )
    
    return response.json()

def save_json(data: Any, path:Path):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_csv_rows(rows: List[dict], path:Path):
    if not rows:
        print(f"저장할 데이터 없음:{path.name}")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

def unique_keep_order(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        key = normalize_text(item)
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return result


def extract_date_slot_from_name(file_name: str, prefix: str) -> Tuple[str, str]:
    """
    예:
    top20_2026-04-21_am.csv -> ("2026-04-21", "am")
    sns_candidates_2026-04-21_pm.csv -> ("2026-04-21", "pm")
    """
    if not file_name.startswith(prefix) or not file_name.endswith(".csv"):
        return ("0000-00-00", "am")

    suffix = file_name[len(prefix):-4]  # 2026-04-21_am
    parts = suffix.rsplit("_", 1)
    if len(parts) != 2:
        return ("0000-00-00", "am")

    return parts[0], parts[1]

#======================================================
# 4. row 파일 읽기
#======================================================
def find_latest_top20_file() -> Path:
    files = list(RAW_DIR.rglob("top20_*.csv"))
    if not files:
        raise FileNotFoundError("raw 폴더에 top20_*.csv 파일이 없습니다.")

    def sort_key(path: Path):
        date_part, slot_part = extract_date_slot_from_name(path.name, "top20_")
        slot_order = 0 if slot_part == "am" else 1
        return (date_part, slot_order)

    return max(files, key=sort_key)


# def find_matching_sns_file(top20_path: Path) -> Optional[Path]:
#     file_name = top20_path.name
#     date_part, slot_part = extract_date_slot_from_name(file_name, "top20_")
#     target_name = f"sns_candidates_{date_part}_{slot_part}.csv"

#     candidates = list(RAW_DIR.rglob(target_name))
#     if not candidates:
#         return None
#     return candidates[0]
# =========================================================
# 5. raw 파일 읽기
# =========================================================
def load_top20_raw(path: Path) -> pd.DataFrame:
    df = load_csv_with_fallback(path)

    rename_map = {}
    for col in df.columns:
        lower = str(col).strip().lower()
        if lower in {"date", "날짜"}:
            rename_map[col] = "date"
        elif lower in {"rank", "순위"}:
            rename_map[col] = "rank"
        elif lower in {"product_name", "상품명", "name"}:
            rename_map[col] = "product_name"
        elif lower in {"slot"}:
            rename_map[col] = "slot"

    df = df.rename(columns=rename_map)

    required = {"date", "rank", "product_name"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Top20 파일 필수 컬럼 누락: {missing}")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["rank"] = pd.to_numeric(df["rank"], errors="coerce")
    df["product_name"] = df["product_name"].astype(str).map(normalize_text)

    df = df.dropna(subset=["date", "rank"]).copy()
    df["rank"] = df["rank"].astype(int)

    if "slot" not in df.columns:
        filename = path.name.lower()
        if "_am" in filename:
            df["slot"] = "am"
        elif "_pm" in filename:
            df["slot"] = "pm"
        else:
            df["slot"] = "am"

    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return df.sort_values("rank").reset_index(drop=True)


def load_sns_candidates(path: Optional[Path]) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame(columns=["source", "product_name", "note", "is_active"])

    df = load_csv_with_fallback(path)

    if df.empty:
        return pd.DataFrame(columns=["source", "product_name", "note", "is_active"])

    rename_map = {}
    for col in df.columns:
        lower = str(col).strip().lower()
        if lower in {"source", "출처"}:
            rename_map[col] = "source"
        elif lower in {"product_name", "상품명", "name"}:
            rename_map[col] = "product_name"
        elif lower in {"note", "메모"}:
            rename_map[col] = "note"
        elif lower in {"is_active", "active", "사용여부"}:
            rename_map[col] = "is_active"

    df = df.rename(columns=rename_map)

    required = {"source", "product_name"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"SNS master 파일 필수 컬럼 누락: {missing}")

   
    df["source"] = df["source"].astype(str).map(normalize_text)
    df["product_name"] = df["product_name"].astype(str).map(normalize_text)

    if "note" not in df.columns:
        df["note"] = ""

    if "is_active" not in df.columns:
        df["is_active"] = "Y"

    df["is_active"] = df["is_active"].astype(str).str.upper().str.strip()

    df = df[df["is_active"] == "Y"].copy()
    df = df[(df["product_name"] != "") & (df["source"] != "")]
    return df.reset_index(drop=True)


def load_rising_candidates(path: Optional[Path], date_label: str, slot: str) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame(columns=[
            "date", "slot", "rank", "rank_range", "product_name", "source", "note", "is_active"
        ])

    df = load_csv_with_fallback(path)

    if df.empty:
        return pd.DataFrame(columns=[
            "date", "slot", "rank", "rank_range", "product_name", "source", "note", "is_active"
        ])

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
        elif lower in {"product_group", "상품군", "분류"}:
            rename_map[col] = "product_group"
        elif lower in {"sub_group", "상세분류", "세부분류"}:
            rename_map[col] = "sub_group"
        elif lower in {"exclude_from_opportunity", "선점제외", "제외여부"}:
            rename_map[col] = "exclude_from_opportunity"


    df = df.rename(columns=rename_map)

    required = {"date", "slot", "rank", "product_name"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Rising master 파일 필수 컬럼 누락: {missing}")

    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["slot"] = df["slot"].astype(str).str.lower().str.strip()
    df["rank"] = pd.to_numeric(df["rank"], errors="coerce")
    df["product_name"] = df["product_name"].astype(str).map(normalize_text)

    if "rank_range" not in df.columns:
        df["rank_range"] = ""

    if "source" not in df.columns:
        df["source"] = "naver_top200"

    if "note" not in df.columns:
        df["note"] = ""

    if "is_active" not in df.columns:
        df["is_active"] = "Y"

    if "product_group" not in df.columns:
        df["product_group"] = ""

    if "sub_group" not in df.columns:
        df["sub_group"] = ""

    if "exclude_from_opportunity" not in df.columns:
        df["exclude_from_opportunity"] = "N"

    df["product_group"] = df["product_group"].astype(str).map(normalize_text)
    df["sub_group"] = df["sub_group"].astype(str).map(normalize_text)
    df["exclude_from_opportunity"] = (
        df["exclude_from_opportunity"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    df["source"] = df["source"].astype(str).map(normalize_text)
    df["note"] = df["note"].astype(str).map(normalize_text)
    df["is_active"] = df["is_active"].astype(str).str.upper().str.strip()

    df = df[
        (df["date"] == date_label)
        & (df["slot"] == slot)
        & (df["is_active"] == "Y")
        & (df["product_name"] != "")
    ].copy()

    return df.sort_values("rank").reset_index(drop=True)
# =========================================================
# 6. 검색어 트렌드 API
# =========================================================
def fetch_search_trend_batch(start_date: str, end_date: str, product_names: List[str]) -> dict:
    payload = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": "date",
        "keywordGroups": [{"groupName": name, "keywords": [name]} for name in product_names],
    }
    return post_json(
        SEARCH_URL,
        payload,
        SEARCH_CLIENT_ID,
        SEARCH_CLIENT_SECRET,
    )


def flatten_search_result(api_response: dict) -> List[dict]:
    rows = []
    for result in api_response.get("results", []):
        title = result.get("title", "")
        keywords = result.get("keywords", [])
        for point in result.get("data", []):
            rows.append(
                {
                    "product_name": title,
                    "period": point.get("period"),
                    "search_ratio": point.get("ratio"),
                    "search_keywords": ", ".join(keywords),
                }
            )
    return rows


# =========================================================
# 7. 쇼핑인사이트 API
# =========================================================
def fetch_shopping_keyword_batch(start_date: str, end_date: str, product_names: List[str]) -> dict:
    payload = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": "date",
        "category": SHOPPING_CATEGORY_ID,
        "keyword": [{"name": name, "param": [name]} for name in product_names],
    }
    return post_json(
        SHOPPING_URL,
        payload,
        SHOPPING_CLIENT_ID,
        SHOPPING_CLIENT_SECRET,
    )


def flatten_shopping_result(api_response: dict) -> List[dict]:
    rows = []
    for result in api_response.get("results", []):
        title = result.get("title", "")
        keywords = result.get("keyword", [])
        for point in result.get("data", []):
            rows.append(
                {
                    "product_name": title,
                    "period": point.get("period"),
                    "shopping_ratio": point.get("ratio"),
                    "shopping_keywords": ", ".join(keywords),
                }
            )
    return rows


# =========================================================
# 8. 메인 실행
# =========================================================
def main():
    ensure_config()

    top20_input_path = Path(FORCE_TOP20_FILE) if FORCE_TOP20_FILE else find_latest_top20_file()
    sns_input_path = Path(FORCE_SNS_FILE) if FORCE_SNS_FILE else SNS_MASTER_FILE

    print(f"Top20 입력 파일: {top20_input_path}")
    print(f"SNS master 파일: {sns_input_path}")
    print(f"SNS 파일 존재 여부: {sns_input_path.exists()}")

    top20_df = load_top20_raw(top20_input_path)
    sns_df = load_sns_candidates(sns_input_path)

    print("SNS 원본 columns:", list(sns_df.columns))
    print("SNS 원본 row 수:", len(sns_df))
    if not sns_df.empty:
        print(sns_df.head())

    date_label = top20_df["date"].iloc[0]
    slot = top20_df["slot"].iloc[0]
    rising_df = load_rising_candidates(RISING_MASTER_FILE, date_label, slot)

    print("Rising 후보 row 수:", len(rising_df))
    if not rising_df.empty:
        print(rising_df.head())
    month_dir = datetime.strptime(date_label, "%Y-%m-%d").strftime("%Y-%m")

    output_dir = PROCESSED_DIR / month_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    search_csv = output_dir / f"search_trend_{date_label}_{slot}.csv"
    shopping_csv = output_dir / f"shopping_trend_{date_label}_{slot}.csv"
    merged_daily_csv = output_dir / f"product_daily_search_shopping_{date_label}_{slot}.csv"
    merged_top20_csv = output_dir / f"top20_with_search_shopping_{date_label}_{slot}.csv"
    merged_candidates_csv = output_dir / f"candidates_with_search_shopping_{date_label}_{slot}.csv"

    start_date = (
        datetime.strptime(date_label, "%Y-%m-%d") - timedelta(days=LOOKBACK_DAYS - 1)
    ).strftime("%Y-%m-%d")
    end_date = date_label
    top20_names = top20_df["product_name"].dropna().astype(str).map(normalize_text).tolist()

    sns_names = []
    if not sns_df.empty:
        sns_names = sns_df["product_name"].dropna().astype(str).map(normalize_text).tolist()

    rising_names = []
    if not rising_df.empty:
        rising_names = rising_df["product_name"].dropna().astype(str).map(normalize_text).tolist()

    product_names = unique_keep_order(top20_names + rising_names + sns_names)

    print(f"Top20 상품 수: {len(unique_keep_order(top20_names))}")
    print(f"Rising 후보 수: {len(unique_keep_order(rising_names))}")
    print(f"SNS 후보 수: {len(unique_keep_order(sns_names))}")
    print(f"전체 추적 상품 수: {len(product_names)}")
    all_search_raw = []
    all_shopping_raw = []
    all_search_rows: List[dict] = []
    all_shopping_rows: List[dict] = []

    # 검색어 트렌드
    for i, batch in enumerate(chunked(product_names, 5), start=1):
        print(f"[검색 {i}] {batch}")
        raw = fetch_search_trend_batch(start_date, end_date, batch)
        all_search_raw.append(raw)
        all_search_rows.extend(flatten_search_result(raw))
        time.sleep(0.2)

    # 쇼핑인사이트
    for i, batch in enumerate(chunked(product_names, 5), start=1):
        print(f"[쇼핑 {i}] {batch}")
        raw = fetch_shopping_keyword_batch(start_date, end_date, batch)
        all_shopping_raw.append(raw)
        all_shopping_rows.extend(flatten_shopping_result(raw))
        time.sleep(0.2)

    # 원본 JSON 저장
    save_json(all_search_raw, search_csv.with_suffix(".json"))
    save_json(all_shopping_raw, shopping_csv.with_suffix(".json"))

    # 개별 csv 저장
    all_search_rows = sorted(all_search_rows, key=lambda x: (x["product_name"], x["period"]))
    all_shopping_rows = sorted(all_shopping_rows, key=lambda x: (x["product_name"], x["period"]))

    save_csv_rows(all_search_rows, search_csv)
    save_csv_rows(all_shopping_rows, shopping_csv)

    # 병합 1: 전체 후보 상품 날짜 시계열
    search_df = pd.DataFrame(all_search_rows)
    shopping_df = pd.DataFrame(all_shopping_rows)

    merged_daily = pd.merge(
        search_df,
        shopping_df,
        on=["product_name", "period"],
        how="outer",
    ).sort_values(["product_name", "period"])

    merged_daily.to_csv(merged_daily_csv, index=False, encoding="utf-8-sig")

    # 최신값 추출
    if not search_df.empty:
        search_df["period"] = pd.to_datetime(search_df["period"])
        latest_search = (
            search_df.sort_values("period")
            .groupby("product_name", as_index=False)
            .tail(1)[["product_name", "search_ratio"]]
        )
    else:
        latest_search = pd.DataFrame(columns=["product_name", "search_ratio"])

    if not shopping_df.empty:
        shopping_df["period"] = pd.to_datetime(shopping_df["period"])
        latest_shopping = (
            shopping_df.sort_values("period")
            .groupby("product_name", as_index=False)
            .tail(1)[["product_name", "shopping_ratio"]]
        )
    else:
        latest_shopping = pd.DataFrame(columns=["product_name", "shopping_ratio"])

    # 병합 2: Top20만 최신값 붙이기
    merged_top20 = (
        top20_df.merge(latest_search, on="product_name", how="left")
        .merge(latest_shopping, on="product_name", how="left")
        .sort_values("rank")
    )
    merged_top20.to_csv(merged_top20_csv, index=False, encoding="utf-8-sig")

    # 병합 3: Top20 + SNS 후보 전체 목록 최신값 붙이기
    candidate_rows = []

    for _, row in top20_df.iterrows():
        candidate_rows.append({
            "date": row["date"],
            "slot": row["slot"],
            "source_type": "top20",
            "source": "naver_datalab",
            "rank": row["rank"],
            "rank_range": "",
            "product_name": row["product_name"],
            "note": "",
            "product_group": "",
            "sub_group": "",
            "exclude_from_opportunity": "N",
        })
    if not rising_df.empty:
        for _, row in rising_df.iterrows():
           candidate_rows.append({
                "date": date_label,
                "slot": slot,
                "source_type": "rising",
                "source": row.get("source", "naver_top200"),
                "rank": row.get("rank"),
                "rank_range": row.get("rank_range", ""),
                "product_name": row["product_name"],
                "note": row.get("note", ""),
                "product_group": row.get("product_group", ""),
                "sub_group": row.get("sub_group", ""),
                "exclude_from_opportunity": row.get("exclude_from_opportunity", "N"),
            })   

    if not sns_df.empty:
        for _, row in sns_df.iterrows():
            candidate_rows.append({
                "date": date_label,
                "slot": slot,
                "source_type": "sns",
                "source": row["source"],
                "rank": None,
                "rank_range": "",
                "product_name": row["product_name"],
                "note": row.get("note", ""),
                "product_group": "",
                "sub_group": "",
                "exclude_from_opportunity": "N",
            })
    candidates_df = pd.DataFrame(candidate_rows)
    candidates_df["product_name"] = candidates_df["product_name"].astype(str).map(normalize_text)

    # 중복 제거: 같은 source_type + product_name 기준
    candidates_df = candidates_df.drop_duplicates(subset=["source_type", "product_name"]).copy()

    merged_candidates = (
        candidates_df.merge(latest_search, on="product_name", how="left")
        .merge(latest_shopping, on="product_name", how="left")
        .sort_values(["source_type", "rank"], na_position="last")
    )

    merged_candidates.to_csv(merged_candidates_csv, index=False, encoding="utf-8-sig")

    print("\n완료")
    print(f"검색어 트렌드: {search_csv}")
    print(f"쇼핑 클릭 추이: {shopping_csv}")
    print(f"상품별 일별 병합: {merged_daily_csv}")
    print(f"Top20 + 최신값 병합: {merged_top20_csv}")
    print(f"전체 후보 병합(Top20 + SNS): {merged_candidates_csv}")


if __name__ == "__main__":
    main()