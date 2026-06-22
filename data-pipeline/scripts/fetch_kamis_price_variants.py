import json
import ssl
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException
from urllib3.util.retry import Retry
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


def normalize_text(text: Any) -> str:
    return " ".join(str(text or "").strip().split())


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

class LegacyTLSAdapter(HTTPAdapter):
    """
    일부 공공 API 서버에서 최신 Python/OpenSSL과 SSL handshake가 실패하는 경우를 완화한다.
    """

    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context()

        # OpenSSL 보안 레벨 완화
        try:
            context.set_ciphers("DEFAULT@SECLEVEL=1")
        except ssl.SSLError:
            pass

        # TLS 1.2 이상 우선
        try:
            context.minimum_version = ssl.TLSVersion.TLSv1_2
        except Exception:
            pass

        kwargs["ssl_context"] = context
        return super().init_poolmanager(*args, **kwargs)


def make_kamis_session() -> requests.Session:
    session = requests.Session()

    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )

    adapter = LegacyTLSAdapter(max_retries=retry)

    session.mount("http://", adapter)
    session.mount("https://", adapter)

    session.headers.update({
        "User-Agent": "Mozilla/5.0 EarlyPick/1.0",
        "Accept": "application/json,text/plain,*/*",
        "Connection": "close",
    })

    return session


KAMIS_SESSION = make_kamis_session()

def request_kamis(url: str, params: Dict[str, str]) -> Dict[str, Any]:
    last_error = None

    for attempt in range(1, 4):
        try:
            response = KAMIS_SESSION.get(
                url,
                params=params,
                timeout=40,
                allow_redirects=True,
            )

            # 실제 최종 URL 확인용
            if response.url.startswith("https://"):
                print(f"    [INFO] KAMIS 최종 요청 URL이 https로 전환됨")

            if response.status_code in [429, 500, 502, 503, 504]:
                print(f"    [WARN] KAMIS 일시 오류 {response.status_code} / retry {attempt}/3")
                last_error = f"HTTP {response.status_code}"
                time.sleep(attempt * 2)
                continue

            response.raise_for_status()

            try:
                return response.json()
            except Exception:
                print("    [WARN] KAMIS JSON 파싱 실패")
                print(response.text[:500])
                return {}

        except RequestException as e:
            last_error = e
            print(f"    [WARN] KAMIS 요청 실패 / retry {attempt}/3 / {type(e).__name__}: {e}")
            time.sleep(attempt * 2)

    print(f"    [SKIP] KAMIS 요청 최종 실패: {last_error}")
    return {}


def extract_date_slot_from_name(file_name: str, prefix: str) -> tuple[str, str]:
    if not file_name.startswith(prefix) or not file_name.endswith(".csv"):
        return ("0000-00-00", "am")

    suffix = file_name[len(prefix):-4]
    parts = suffix.rsplit("_", 1)

    if len(parts) != 2:
        return ("0000-00-00", "am")

    return parts[0], parts[1]


def parse_suffix_from_filename(file_name: str, prefix: str) -> Optional[str]:
    if not file_name.startswith(prefix) or not file_name.endswith(".csv"):
        return None

    return file_name[len(prefix):-4]


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
    files = list(PROCESSED_DIR.rglob(f"{CANDIDATES_PREFIX}{suffix}.csv"))
    return files[0] if files else None


# =========================================================
# 3. KAMIS 코드표 읽기
# =========================================================
def load_kamis_codebook(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"KAMIS 코드표 파일이 없습니다: {path}")

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

    xls = pd.ExcelFile(path)

    for sheet_name in xls.sheet_names:
        for header_row in range(0, 6):
            try:
                df = pd.read_excel(path, sheet_name=sheet_name, header=header_row)
                df.columns = [str(c).strip() for c in df.columns]

                if required.issubset(set(df.columns)):
                    print(f"KAMIS 코드표 읽기 성공: sheet={sheet_name}, header={header_row}")
                    return normalize_codebook(df)
            except Exception:
                continue

    raise ValueError("KAMIS 코드표에서 필요한 컬럼을 찾지 못했습니다.")


def normalize_codebook(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    df = df.dropna(subset=["품목명", "품목코드", "품종명", "품종코드", "산물등급명", "산물등급코드"]).copy()

    text_cols = [
        "산물분류명",
        "품목분류명",
        "품목명",
        "품종명",
        "산물등급명",
        "산물부류별_단위",
    ]

    for col in text_cols:
        df[col] = df[col].astype(str).map(normalize_text)

    df["품목분류코드"] = df["품목분류코드"].apply(clean_code_value)
    df["품목코드"] = df["품목코드"].apply(clean_code_value)
    df["품종코드"] = df["품종코드"].apply(lambda x: clean_code_value(x, zfill_len=2))
    df["산물등급코드"] = df["산물등급코드"].apply(lambda x: clean_code_value(x, zfill_len=2))

    df = df[
        (df["품목명"] != "")
        & (df["품목코드"] != "")
        & (df["품종코드"] != "")
        & (df["산물등급코드"] != "")
    ].copy()

    return df.reset_index(drop=True)


def get_unit_for_type(group: pd.DataFrame, price_type_label: str) -> str:
    if price_type_label == "retail":
        matched = group[group["산물분류명"].str.contains("소매", na=False)].copy()
    else:
        matched = group[
            group["산물분류명"].str.contains("중도매", na=False)
            | group["산물분류명"].str.contains("도매", na=False)
        ].copy()

    if matched.empty:
        return ""

    return normalize_text(matched.iloc[0].get("산물부류별_단위", ""))


def build_variant_rows_for_product(product_name: str, codebook_df: pd.DataFrame) -> List[Dict[str, Any]]:
    name = normalize_text(product_name)

    matched = codebook_df[codebook_df["품목명"] == name].copy()

    if matched.empty:
        return []

    group_cols = [
        "품목분류코드",
        "품목코드",
        "품종코드",
        "산물등급코드",
    ]

    rows: List[Dict[str, Any]] = []

    for keys, group in matched.groupby(group_cols):
        itemcategorycode, itemcode, kindcode, rankcode = keys

        first = group.iloc[0]

        item_name = normalize_text(first.get("품목명", ""))
        kind_name = normalize_text(first.get("품종명", ""))
        rank_name = normalize_text(first.get("산물등급명", ""))

        retail_unit = get_unit_for_type(group, "retail")
        wholesale_unit = get_unit_for_type(group, "wholesale")

        rows.append({
            "product_name": name,
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
        })

    return rows


def ensure_kamis_variant_map_for_names(
    names: List[str],
    map_df: pd.DataFrame,
    codebook_df: pd.DataFrame,
) -> pd.DataFrame:
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

    if map_df.empty:
        map_df = pd.DataFrame(columns=required_cols)

    map_df.columns = [str(c).strip() for c in map_df.columns]

    for col in required_cols:
        if col not in map_df.columns:
            map_df[col] = ""

    map_df["product_name"] = map_df["product_name"].astype(str).map(normalize_text)

    auto_rows: List[Dict[str, Any]] = []
    auto_matched_names = set()

    for name in names:
        clean_name = normalize_text(name)

        if not clean_name:
            continue

        variant_rows = build_variant_rows_for_product(clean_name, codebook_df)

        if not variant_rows:
            continue

        auto_rows.extend(variant_rows)
        auto_matched_names.add(clean_name)

    if auto_rows:
        auto_df = pd.DataFrame(auto_rows)

        # 자동 매칭된 상품은 기존 대표 1줄을 제거하고 품종/등급 전체로 교체
        map_df = map_df[~map_df["product_name"].isin(auto_matched_names)].copy()

        map_df = pd.concat([map_df[required_cols], auto_df[required_cols]], ignore_index=True)

        map_df = (
            map_df.drop_duplicates(
                subset=["product_name", "itemcode", "kindcode", "productrankcode"],
                keep="last",
            )
            .sort_values(["product_name", "itemcode", "kindcode", "productrankcode"])
            .reset_index(drop=True)
        )

        map_df.to_csv(MAP_FILE, index=False, encoding="utf-8-sig")

        print(f"KAMIS map 자동 업데이트 완료: {MAP_FILE}")
        print(f"자동 매칭 상품 수: {len(auto_matched_names)}")
        print(f"품종/등급 row 수: {len(auto_rows)}")

    return map_df


# =========================================================
# 4. KAMIS 응답 파싱
# =========================================================
def flatten_kamis_json(
    data: Dict[str, Any],
    price_type: str,
    product_name: str,
    variant: Dict[str, Any],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    expected_item_name = normalize_text(variant.get("item_name", ""))
    unit_name = (
        normalize_text(variant.get("retail_unit_name", ""))
        if price_type == "retail"
        else normalize_text(variant.get("wholesale_unit_name", ""))
    )

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
                response_item_name = normalize_text(obj.get("itemname") or "")

                if response_item_name and expected_item_name and response_item_name != expected_item_name:
                    return

                rows.append({
                    "product_name": normalize_text(product_name),
                    "price_type": price_type,

                    "itemcategorycode": variant.get("itemcategorycode"),
                    "itemcode": variant.get("itemcode"),
                    "kindcode": variant.get("kindcode"),
                    "productrankcode": variant.get("productrankcode"),

                    "item_name": variant.get("item_name"),
                    "kind_name": variant.get("kind_name"),
                    "rank_name": variant.get("rank_name"),
                    "unit_name": unit_name,

                    "itemname": obj.get("itemname"),
                    "kindname": obj.get("kindname"),
                    "countyname": obj.get("countyname"),
                    "marketname": obj.get("marketname"),
                    "yyyy": obj.get("yyyy"),
                    "regday": obj.get("regday"),
                    "price": obj.get("price"),
                })
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
            r.get("itemcode"),
            r.get("kindcode"),
            r.get("productrankcode"),
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
# 5. 메인
# =========================================================
def main():
    if KAMIS_CERT_KEY.startswith("여기에_") or KAMIS_CERT_ID.startswith("여기에_"):
        raise ValueError("KAMIS_CERT_KEY / KAMIS_CERT_ID를 기존 값으로 넣어주세요.")

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

    names = list(dict.fromkeys([normalize_text(n) for n in names if normalize_text(n)]))

    print(f"전체 가격 조회 후보 수: {len(names)}")

    if MAP_FILE.exists():
        map_df = load_csv_with_fallback(MAP_FILE)
    else:
        map_df = pd.DataFrame()

    codebook_df = load_kamis_codebook(CODEBOOK_FILE)

    map_df = ensure_kamis_variant_map_for_names(
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
        "item_name",
        "kind_name",
        "rank_name",
        "retail_unit_name",
        "wholesale_unit_name",
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

    all_rows: List[Dict[str, Any]] = []
    raw_responses: Dict[str, Any] = {"wholesale": {}, "retail": {}}
    skipped_names: List[Dict[str, Any]] = []

    for name in names:
        matched = map_df[map_df["product_name"] == name].copy()

        print(f"\n[상품] {name}")
        print(f"품종/등급 매핑 row 수: {len(matched)}")

        if matched.empty:
            print("→ KAMIS 코드표 매칭 없음")
            skipped_names.append({
                "product_name": name,
                "reason": "KAMIS 코드표 매칭 없음",
            })
            continue

        for _, row in matched.iterrows():
            variant = row.to_dict()

            label = normalize_text(row.get("label", ""))
            print(f"  - 조회: {label}")

            common_params = {
                "p_cert_key": KAMIS_CERT_KEY,
                "p_cert_id": KAMIS_CERT_ID,
                "p_returntype": "json",
                "p_startday": start_date,
                "p_endday": end_date,
                "p_itemcategorycode": clean_code_value(row.get("itemcategorycode")),
                "p_itemcode": clean_code_value(row.get("itemcode")),
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

            try:
                wholesale_raw = request_kamis(WHOLESALE_URL, common_params)
                raw_responses["wholesale"].setdefault(name, {})[label] = wholesale_raw

                wholesale_rows = flatten_kamis_json(
                    data=wholesale_raw,
                    price_type="wholesale",
                    product_name=name,
                    variant=variant,
                )

                print(f"    [도매] row 수: {len(wholesale_rows)}")
                all_rows.extend(wholesale_rows)

            except Exception as e:
                print(f"    [도매 실패] {e}")

            try:
                retail_raw = request_kamis(RETAIL_URL, common_params)
                raw_responses["retail"].setdefault(name, {})[label] = retail_raw

                retail_rows = flatten_kamis_json(
                    data=retail_raw,
                    price_type="retail",
                    product_name=name,
                    variant=variant,
                )

                print(f"    [소매] row 수: {len(retail_rows)}")
                all_rows.extend(retail_rows)

            except Exception as e:
                print(f"    [소매 실패] {e}")

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
            [
                "product_name",
                "price_type",
                "itemcode",
                "kindcode",
                "productrankcode",
                "regday_dt",
                "row_order",
            ],
            na_position="last",
        )

        daily_df.to_csv(price_daily_csv, index=False, encoding="utf-8-sig")

        latest_df = (
            daily_df.groupby(
                [
                    "product_name",
                    "price_type",
                    "itemcode",
                    "kindcode",
                    "productrankcode",
                ],
                as_index=False,
            )
            .tail(1)
            .drop(columns=["row_order"])
            .reset_index(drop=True)
        )

        latest_df.to_csv(price_latest_csv, index=False, encoding="utf-8-sig")

    else:
        empty_cols = [
            "product_name",
            "price_type",
            "itemcategorycode",
            "itemcode",
            "kindcode",
            "productrankcode",
            "item_name",
            "kind_name",
            "rank_name",
            "unit_name",
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

    pd.DataFrame(skipped_names).to_csv(price_skip_csv, index=False, encoding="utf-8-sig")

    print("\n완료")
    print(f"가격 raw json: {price_raw_json}")
    print(f"가격 daily csv: {price_daily_csv}")
    print(f"가격 latest csv: {price_latest_csv}")
    print(f"스킵 목록: {price_skip_csv}")


if __name__ == "__main__":
    main()