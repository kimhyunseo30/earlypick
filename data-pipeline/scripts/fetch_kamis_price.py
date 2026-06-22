import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from dotenv import load_dotenv
import os

load_dotenv()
# =========================================================
# 1. 사용자 설정
# =========================================================
KAMIS_CERT_KEY = os.getenv("KAMIS_CERT_KEY")
KAMIS_CERT_ID = os.getenv("KAMIS_CERT_ID")

LOOKBACK_DAYS = 14

BASE_DIR = Path(__file__).resolve().parents[1]
PROCESSED_DIR = BASE_DIR / "data" / "daily" / "processed"
HISTORICAL_DIR = BASE_DIR / "data" / "historical"

TOP20_PREFIX = "top20_with_search_shopping_"
CANDIDATES_PREFIX = "candidates_with_search_shopping_"

MAP_FILE = HISTORICAL_DIR / "kamis_item_map.csv"

CODEBOOK_FILE = HISTORICAL_DIR / "농축수산물 품목 및 등급 코드표.xlsx"

DEFAULT_KIND_PRIORITY = {
    "사과": ["후지", "부사"],
    "배": ["신고"],
    "오이": ["다다기계통", "가시오이", "취청"],
    "토마토": ["토마토"],
    "감자": ["수미"],
    "양파": ["양파"],
    "대파": ["대파"],
    "마늘": ["깐마늘", "마늘"],
    "참외": ["참외"],
    "수박": ["수박"],
    "딸기": ["설향", "딸기"],
    "포도": ["캠벨얼리", "거봉"],
    "꽃게": ["꽃게"],
    "계란": ["계란"],
}

WHOLESALE_URL = "http://www.kamis.or.kr/service/price/xml.do?action=periodWholesaleProductList"
RETAIL_URL = "http://www.kamis.or.kr/service/price/xml.do?action=periodRetailProductList"


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


def normalize_text(text: str) -> str:
    return " ".join(str(text or "").strip().split())


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


def find_matching_candidates_file(suffix: str) -> Optional[Path]:
    candidates = list(PROCESSED_DIR.rglob(f"{CANDIDATES_PREFIX}{suffix}.csv"))
    return candidates[0] if candidates else None


def parse_suffix_from_filename(file_name: str, prefix: str) -> Optional[str]:
    if not file_name.startswith(prefix) or not file_name.endswith(".csv"):
        return None
    return file_name[len(prefix):-4]


def request_kamis(url: str, params: Dict[str, str]) -> Dict[str, Any]:
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def clean_code_value(value: Any, zfill_len: Optional[int] = None) -> str:
    if pd.isna(value):
        return ""

    s = str(value).strip()

    if s.lower() in {"nan", "none", ""}:
        return ""

    if s.endswith(".0"):
        s = s[:-2]

    if zfill_len:
        s = s.zfill(zfill_len)

    return s
def load_kamis_codebook(path: Path) -> pd.DataFrame:
    if not path.exists():
        print(f"KAMIS 코드표 없음: {path}")
        return pd.DataFrame()

    df = pd.read_excel(path, sheet_name="산물코드", header=1)

    df.columns = [str(c).strip() for c in df.columns]

    required = {
        "산물분류명",
        "품목분류명",
        "품목분류코드",
        "품목명",
        "품목코드",
        "품종명",
        "품종코드",
        "산물등급명",
        "산물등급코드",
        "산물부류별_단위",
    }

    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"KAMIS 코드표 필수 컬럼 누락: {missing}")

    df = df.dropna(subset=["품목명", "품목코드", "품종코드", "산물등급코드"]).copy()

    for col in [
        "산물분류명",
        "품목분류명",
        "품목명",
        "품종명",
        "산물등급명",
        "산물부류별_단위",
    ]:
        df[col] = df[col].astype(str).map(normalize_text)

    for col in ["품목분류코드", "품목코드", "품종코드", "산물등급코드"]:
        df[col] = df[col].apply(lambda x: clean_code_value(x, zfill_len=2 if col in {"품종코드", "산물등급코드"} else None))

    return df


def select_best_kamis_row(product_name: str, codebook_df: pd.DataFrame) -> Optional[pd.Series]:
    if codebook_df.empty:
        return None

    name = normalize_text(product_name)

    matched = codebook_df[
        (codebook_df["품목명"] == name)
        & (codebook_df["산물등급명"] == "상품")
    ].copy()

    if matched.empty:
        matched = codebook_df[codebook_df["품목명"] == name].copy()

    if matched.empty:
        return None

    retail_matched = matched[matched["산물분류명"] == "소매"].copy()
    if not retail_matched.empty:
        matched = retail_matched

    priority_kinds = DEFAULT_KIND_PRIORITY.get(name, [])
    for kind in priority_kinds:
        kind_matched = matched[matched["품종명"].astype(str).str.contains(kind, na=False)].copy()
        if not kind_matched.empty:
            return kind_matched.iloc[0]

    matched = matched.sort_values(["품목코드", "품종코드", "산물등급코드"])
    return matched.iloc[0]


def find_unit_from_codebook(
    codebook_df: pd.DataFrame,
    itemcode: str,
    kindcode: str,
    rankcode: str,
    price_type_name: str,
) -> str:
    if codebook_df.empty:
        return ""

    matched = codebook_df[
        (codebook_df["품목코드"] == itemcode)
        & (codebook_df["품종코드"] == kindcode)
        & (codebook_df["산물등급코드"] == rankcode)
        & (codebook_df["산물분류명"] == price_type_name)
    ].copy()

    if matched.empty:
        return ""

    return normalize_text(matched.iloc[0].get("산물부류별_단위", ""))


def auto_match_kamis_item(product_name: str, codebook_df: pd.DataFrame) -> Optional[Dict[str, Any]]:
    row = select_best_kamis_row(product_name, codebook_df)
    if row is None:
        return None

    itemcategorycode = clean_code_value(row.get("품목분류코드"))
    itemcode = clean_code_value(row.get("품목코드"))
    kindcode = clean_code_value(row.get("품종코드"), zfill_len=2)
    rankcode = clean_code_value(row.get("산물등급코드"), zfill_len=2)

    retail_unit = find_unit_from_codebook(
        codebook_df=codebook_df,
        itemcode=itemcode,
        kindcode=kindcode,
        rankcode=rankcode,
        price_type_name="소매",
    )

    wholesale_unit = find_unit_from_codebook(
        codebook_df=codebook_df,
        itemcode=itemcode,
        kindcode=kindcode,
        rankcode=rankcode,
        price_type_name="중도매",
    )

    item_name = normalize_text(row.get("품목명", ""))
    kind_name = normalize_text(row.get("품종명", ""))
    rank_name = normalize_text(row.get("산물등급명", ""))

    return {
        "product_name": normalize_text(product_name),
        "itemcategorycode": itemcategorycode,
        "itemcode": itemcode,
        "kindcode": kindcode,
        "productrankcode": rankcode,
        "countrycode": "",
        "label": f"{item_name}-{kind_name}-{rank_name}",
        "item_name": item_name,
        "kind_name": kind_name,
        "rank_name": rank_name,
        "retail_unit_name": retail_unit,
        "wholesale_unit_name": wholesale_unit,
    }


def ensure_kamis_map_for_names(names: List[str], map_df: pd.DataFrame, codebook_df: pd.DataFrame) -> pd.DataFrame:
    if map_df.empty:
        map_df = pd.DataFrame(columns=[
            "product_name",
            "itemcategorycode",
            "itemcode",
            "kindcode",
            "productrankcode",
            "countrycode",
            "label",
            "item_name",
            "kind_name",
            "rank_name",
            "retail_unit_name",
            "wholesale_unit_name",
        ])

    map_df.columns = [str(c).strip() for c in map_df.columns]

    required_cols = [
        "product_name",
        "itemcategorycode",
        "itemcode",
        "kindcode",
        "productrankcode",
        "countrycode",
        "label",
        "item_name",
        "kind_name",
        "rank_name",
        "retail_unit_name",
        "wholesale_unit_name",
    ]

    for col in required_cols:
        if col not in map_df.columns:
            map_df[col] = ""

    map_df["product_name"] = map_df["product_name"].astype(str).map(normalize_text)

    existing_names = set(map_df["product_name"].dropna().tolist())
    new_rows = []

    for name in names:
        clean_name = normalize_text(name)
        if not clean_name or clean_name in existing_names:
            continue

        auto_row = auto_match_kamis_item(clean_name, codebook_df)
        if auto_row is None:
            continue

        print(f"[KAMIS 자동매칭] {clean_name} → {auto_row['label']}")
        new_rows.append(auto_row)
        existing_names.add(clean_name)

    if new_rows:
        map_df = pd.concat([map_df, pd.DataFrame(new_rows)], ignore_index=True)
        map_df = map_df[required_cols]
        map_df.to_csv(MAP_FILE, index=False, encoding="utf-8-sig")
        print(f"KAMIS map 자동 업데이트 완료: {MAP_FILE}")
        print(f"자동 추가 상품 수: {len(new_rows)}")

    return map_df

def flatten_kamis_json(data: Dict[str, Any], price_type: str, product_name: str) -> List[Dict[str, Any]]:
    """
    KAMIS JSON 응답 구조를 느슨하게 파싱.
    단, 상세 itemname 이 있고 요청 상품명과 다르면 제외.
    """
    rows: List[Dict[str, Any]] = []

    candidates = []
    if isinstance(data, dict):
        for key in ["data", "item", "items", "price", "result"]:
            if key in data:
                candidates.append(data[key])

    candidates.append(data)

    def walk(obj: Any):
        if isinstance(obj, list):
            for x in obj:
                walk(x)

        elif isinstance(obj, dict):
            has_price_shape = (
                any(k in obj for k in ["regday", "price", "itemname", "kindname"])
                and "price" in obj
            )

            if has_price_shape:
                itemname = normalize_text(obj.get("itemname") or "")

                # 상세 품목명이 있는데 요청 상품과 다르면 제외
                if itemname and itemname != product_name:
                    return

                rows.append(
                    {
                        "product_name": product_name,
                        "price_type": price_type,
                        "itemname": obj.get("itemname"),
                        "kindname": obj.get("kindname"),
                        "countyname": obj.get("countyname"),
                        "marketname": obj.get("marketname"),
                        "yyyy": obj.get("yyyy"),
                        "regday": obj.get("regday"),
                        "price": obj.get("price"),
                    }
                )
            else:
                for v in obj.values():
                    walk(v)

    for c in candidates:
        walk(c)

    dedup = []
    seen = set()
    for r in rows:
        key = (
            r.get("product_name"),
            r.get("price_type"),
            r.get("itemname"),
            r.get("kindname"),
            r.get("countyname"),
            r.get("marketname"),
            r.get("yyyy"),
            r.get("regday"),
            r.get("price"),
        )
        if key not in seen:
            seen.add(key)
            dedup.append(r)

    return dedup


def build_full_regday(yyyy_value: Any, regday_value: Any) -> Optional[str]:
    if pd.isna(regday_value):
        return None

    regday = str(regday_value).strip()
    if not regday:
        return None

    if "/" in regday:
        parts = regday.split("/")
        if len(parts) == 2:
            mm, dd = parts
            yyyy = str(yyyy_value).strip() if not pd.isna(yyyy_value) else ""
            if yyyy and yyyy.isdigit():
                return f"{yyyy}-{mm.zfill(2)}-{dd.zfill(2)}"

    return None


# =========================================================
# 3. 메인
# =========================================================
def main():
    if KAMIS_CERT_KEY == "발급받은_KAMIS_CERT_KEY" or KAMIS_CERT_ID == "발급받은_KAMIS_CERT_ID":
        raise ValueError("KAMIS_CERT_KEY / KAMIS_CERT_ID 를 실제 값으로 바꿔주세요.")

    top20_file = find_latest_top20_file()
    suffix = parse_suffix_from_filename(top20_file.name, TOP20_PREFIX)
    if not suffix:
        raise ValueError("최신 top20 파일명에서 날짜/슬롯을 읽지 못했습니다.")

    date_part, slot_part = suffix.rsplit("_", 1)
    month_dir = datetime.strptime(date_part, "%Y-%m-%d").strftime("%Y-%m")

    output_dir = PROCESSED_DIR / month_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates_file = find_matching_candidates_file(suffix)

    top20_df = load_csv_with_fallback(top20_file)
    top20_df["product_name"] = top20_df["product_name"].astype(str).map(normalize_text)

    names = top20_df["product_name"].dropna().tolist()

    if candidates_file and candidates_file.exists():
        candidates_df = load_csv_with_fallback(candidates_file)
        if "product_name" in candidates_df.columns:
            candidates_df["product_name"] = candidates_df["product_name"].astype(str).map(normalize_text)
            names += candidates_df["product_name"].dropna().tolist()

    names = list(dict.fromkeys(names))

    if MAP_FILE.exists():
        map_df = load_csv_with_fallback(MAP_FILE)
    else:
        map_df = pd.DataFrame()

    codebook_df = load_kamis_codebook(CODEBOOK_FILE)

    map_df = ensure_kamis_map_for_names(
        names=names,
        map_df=map_df,
        codebook_df=codebook_df,
    )

    required_cols = {
        "product_name",
        "itemcategorycode",
        "itemcode",
        "kindcode",
        "productrankcode",
        "countrycode",
    }
    missing = required_cols - set(map_df.columns)
    if missing:
        raise ValueError(f"kamis_item_map.csv 필수 컬럼 누락: {missing}")

    map_df["product_name"] = map_df["product_name"].astype(str).map(normalize_text)

    start_date = (
        datetime.strptime(date_part, "%Y-%m-%d") - timedelta(days=LOOKBACK_DAYS - 1)
    ).strftime("%Y-%m-%d")
    end_date = date_part

    print(f"조회 기간: {start_date} ~ {end_date}")
    print(f"전체 가격 조회 후보 수: {len(names)}")

    all_rows: List[Dict[str, Any]] = []
    raw_responses: Dict[str, Any] = {"wholesale": {}, "retail": {}}
    skipped_names: List[str] = []

    for name in names:
        print(f"\n[상품] {name}")

        matched = map_df[map_df["product_name"] == name]
        print("매핑 row 수:", len(matched))

        if matched.empty:
            print("→ 매핑 없음, skipped 처리")
            skipped_names.append(name)
            continue

        row = matched.iloc[0]

        common_params = {
            "p_cert_key": KAMIS_CERT_KEY,
            "p_cert_id": KAMIS_CERT_ID,
            "p_returntype": "json",
            "p_startday": start_date,
            "p_endday": end_date,
            "p_itemcategorycode": clean_code_value(row["itemcategorycode"]),
            "p_itemcode": clean_code_value(row["itemcode"]),
            "p_convert_kg_yn": "N",
        }

        kindcode = clean_code_value(row.get("kindcode"), zfill_len=2)
        productrankcode = clean_code_value(row.get("productrankcode"), zfill_len=2)
        countrycode = clean_code_value(row.get("countrycode"))

        if kindcode:
            common_params["p_kindcode"] = kindcode

        if productrankcode:
            common_params["p_productrankcode"] = productrankcode

        if countrycode:
            common_params["p_countycode"] = countrycode

        print("요청 파라미터:", common_params)

        try:
            wholesale_raw = request_kamis(WHOLESALE_URL, common_params)
            raw_responses["wholesale"][name] = wholesale_raw

            wholesale_error = wholesale_raw.get("data", {}).get("error_code")
            print(f"[도매] {name} error_code: {wholesale_error}")

            wholesale_rows = flatten_kamis_json(wholesale_raw, "wholesale", name)
            print(f"[도매] {name} row 수: {len(wholesale_rows)}")
            all_rows.extend(wholesale_rows)

        except Exception as e:
            print(f"[도매가 실패] {name}: {e}")

        try:
            retail_raw = request_kamis(RETAIL_URL, common_params)
            raw_responses["retail"][name] = retail_raw

            retail_error = retail_raw.get("data", {}).get("error_code")
            print(f"[소매] {name} error_code: {retail_error}")

            retail_rows = flatten_kamis_json(retail_raw, "retail", name)
            print(f"[소매] {name} row 수: {len(retail_rows)}")
            all_rows.extend(retail_rows)

        except Exception as e:
            print(f"[소매가 실패] {name}: {e}")

    price_raw_json = output_dir / f"kamis_price_raw_{date_part}_{slot_part}.json"
    price_daily_csv = output_dir / f"kamis_price_daily_{date_part}_{slot_part}.csv"
    price_latest_csv = output_dir / f"kamis_price_latest_{date_part}_{slot_part}.csv"
    price_skip_csv = output_dir / f"kamis_price_skipped_{date_part}_{slot_part}.csv"

    with price_raw_json.open("w", encoding="utf-8") as f:
        json.dump(raw_responses, f, ensure_ascii=False, indent=2)

    if all_rows:
        daily_df = pd.DataFrame(all_rows)

        daily_df["full_regday"] = daily_df.apply(
            lambda x: build_full_regday(x.get("yyyy"), x.get("regday")),
            axis=1,
        )
        daily_df["regday_dt"] = pd.to_datetime(daily_df["full_regday"], errors="coerce")

        daily_df["price_num"] = (
            daily_df["price"]
            .astype(str)
            .str.replace(",", "", regex=False)
            .str.extract(r"(\d+\.?\d*)")[0]
            .astype(float)
        )

        daily_df = daily_df.reset_index(drop=True)
        daily_df["row_order"] = daily_df.index

        daily_df = daily_df.sort_values(
            ["product_name", "price_type", "regday_dt", "row_order"],
            na_position="last"
        )
        daily_df.to_csv(price_daily_csv, index=False, encoding="utf-8-sig")

        latest_df = (
            daily_df.groupby(["product_name", "price_type"], as_index=False)
            .tail(1)
            .drop(columns=["row_order"])
            .reset_index(drop=True)
        )
        latest_df.to_csv(price_latest_csv, index=False, encoding="utf-8-sig")

    else:
        empty_cols = [
            "product_name",
            "price_type",
            "itemname",
            "kindname",
            "countyname",
            "marketname",
            "yyyy",
            "regday",
            "full_regday",
            "regday_dt",
            "price",
            "price_num",
        ]
        pd.DataFrame(columns=empty_cols).to_csv(price_daily_csv, index=False, encoding="utf-8-sig")
        pd.DataFrame(columns=empty_cols).to_csv(price_latest_csv, index=False, encoding="utf-8-sig")

    pd.DataFrame({"product_name": skipped_names}).to_csv(
        price_skip_csv, index=False, encoding="utf-8-sig"
    )

    print("\n완료")
    print(f"도소매 raw JSON: {price_raw_json}")
    print(f"도소매 일별 가격: {price_daily_csv}")
    print(f"도소매 최신 가격: {price_latest_csv}")
    print(f"가격 미매핑 상품: {price_skip_csv}")
    print(f"건너뛴 상품 수: {len(skipped_names)}")


if __name__ == "__main__":
    main()