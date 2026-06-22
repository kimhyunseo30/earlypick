import re
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]

PROCESSED_DIR = BASE_DIR / "data" / "daily" / "processed"
HISTORICAL_DIR = BASE_DIR / "data" / "historical"

CANDIDATES_PREFIX = "candidates_with_search_shopping_"

GOODS_CODE_FILE = HISTORICAL_DIR / "auction_goods_codes.csv"
ALIAS_FILE = HISTORICAL_DIR / "auction_alias_map.csv"


def load_csv_with_fallback(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"파일이 없습니다: {path}")

    for enc in ["utf-8-sig", "cp949", "euc-kr", "utf-8"]:
        try:
            return pd.read_csv(path, encoding=enc, dtype=str)
        except UnicodeDecodeError:
            continue

    raise ValueError(f"CSV 인코딩을 확인해주세요: {path}")


def normalize_text(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_product_name(value: Any) -> str:
    text = normalize_text(value)

    # 용량/수량 표현 제거
    text = re.sub(r"\d+(\.\d+)?\s?(kg|g|ml|l|개|입|팩|봉|박스|세트)", "", text, flags=re.I)
    text = re.sub(r"\d+(\.\d+)?", "", text)
    text = text.replace("냉동", "")
    text = text.replace("국산", "")
    text = text.replace("햇", "")
    text = normalize_text(text)

    return text


def extract_suffix_from_name(file_name: str, prefix: str) -> Optional[str]:
    if not file_name.startswith(prefix) or not file_name.endswith(".csv"):
        return None
    return file_name[len(prefix):-4]


def parse_suffix_date_slot(suffix: str) -> Tuple[str, str]:
    parts = suffix.rsplit("_", 1)
    if len(parts) != 2:
        return "0000-00-00", "am"
    return parts[0], parts[1]


def find_latest_candidates_file() -> Path:
    files = list(PROCESSED_DIR.rglob(f"{CANDIDATES_PREFIX}*.csv"))

    if not files:
        raise FileNotFoundError("processed 폴더에 candidates_with_search_shopping_*.csv 파일이 없습니다.")

    def sort_key(path: Path):
        suffix = extract_suffix_from_name(path.name, CANDIDATES_PREFIX)
        if not suffix:
            return ("0000-00-00", 0)
        date_part, slot = parse_suffix_date_slot(suffix)
        slot_order = 0 if slot == "am" else 1
        return date_part, slot_order

    return max(files, key=sort_key)


def clean_goods_name(value: Any) -> str:
    text = normalize_text(value)
    text = re.sub(r"\(.*?\)", "", text)
    return normalize_text(text)


def load_alias_map(path: Path) -> Dict[str, Dict[str, str]]:
    if not path.exists():
        return {}

    df = load_csv_with_fallback(path)

    if df.empty:
        return {}

    required = {"product_name", "standard_keyword", "is_active"}
    missing = required - set(df.columns)

    if missing:
        print(f"auction_alias_map.csv 컬럼 누락: {missing}")
        return {}

    result = {}

    for _, row in df.iterrows():
        product_name = normalize_text(row.get("product_name", ""))
        if not product_name:
            continue

        result[product_name] = {
            "standard_keyword": normalize_text(row.get("standard_keyword", "")),
            "is_active": normalize_text(row.get("is_active", "Y")).upper(),
            "note": normalize_text(row.get("note", "")),
        }

    return result


def prepare_goods_df(goods_df: pd.DataFrame) -> pd.DataFrame:
    goods_df = goods_df.copy()
    goods_df.columns = [str(c).strip() for c in goods_df.columns]

    required = {
        "gds_lclsf_cd",
        "gds_lclsf_nm",
        "gds_mclsf_cd",
        "gds_mclsf_nm",
        "gds_sclsf_cd",
        "gds_sclsf_nm",
    }

    missing = required - set(goods_df.columns)

    if missing:
        raise ValueError(f"auction_goods_codes.csv 필수 컬럼 누락: {missing}")

    for col in required:
        goods_df[col] = goods_df[col].astype(str).map(normalize_text)

    goods_df["m_name_clean"] = goods_df["gds_mclsf_nm"].map(clean_goods_name)
    goods_df["s_name_clean"] = goods_df["gds_sclsf_nm"].map(clean_goods_name)

    goods_df["gds_lclsf_cd"] = goods_df["gds_lclsf_cd"].str.zfill(2)
    goods_df["gds_mclsf_cd"] = goods_df["gds_mclsf_cd"].str.zfill(2)
    goods_df["gds_sclsf_cd"] = goods_df["gds_sclsf_cd"].str.zfill(2)

    return goods_df


def find_goods_match(
    product_name: str,
    goods_df: pd.DataFrame,
    alias_map: Dict[str, Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    original_name = normalize_text(product_name)
    search_name = normalize_product_name(product_name)
    note = ""

    if original_name in alias_map:
        alias = alias_map[original_name]

        if alias.get("is_active") != "Y":
            return None

        if alias.get("standard_keyword"):
            search_name = alias["standard_keyword"]

        note = alias.get("note", "")

    # 1순위: 소분류명 정확히 일치
    matched = goods_df[goods_df["s_name_clean"] == search_name].copy()

    # 2순위: 중분류명 정확히 일치
    if matched.empty:
        matched = goods_df[goods_df["m_name_clean"] == search_name].copy()

    # 3순위: 괄호 제거 전 원본 상품명 정확히 일치
    if matched.empty:
        matched = goods_df[
            (goods_df["gds_sclsf_nm"] == search_name)
            | (goods_df["gds_mclsf_nm"] == search_name)
        ].copy()

    if matched.empty:
        return None

    # 일반 품목 우선: 소분류코드 00, 또는 이름에 일반 포함
    matched["priority"] = 10
    matched.loc[matched["gds_sclsf_cd"] == "00", "priority"] = 1
    matched.loc[matched["gds_sclsf_nm"].str.contains("일반", na=False), "priority"] = 0

    target = matched.sort_values(["priority", "gds_lclsf_cd", "gds_mclsf_cd", "gds_sclsf_cd"]).iloc[0]

    return {
        "product_name": original_name,
        "gds_lclsf_cd": target["gds_lclsf_cd"],
        "gds_lclsf_nm": target["gds_lclsf_nm"],
        "gds_mclsf_cd": target["gds_mclsf_cd"],
        "gds_mclsf_nm": target["gds_mclsf_nm"],
        "gds_sclsf_cd": target["gds_sclsf_cd"],
        "gds_sclsf_nm": target["gds_sclsf_nm"],
        "match_keyword": search_name,
        "match_note": note,
    }


def should_skip_candidate(row: pd.Series) -> bool:
    product_name = normalize_text(row.get("product_name", ""))
    product_group = normalize_text(row.get("product_group", ""))
    sub_group = normalize_text(row.get("sub_group", ""))
    exclude = normalize_text(row.get("exclude_from_opportunity", "N")).upper()

    if not product_name:
        return True

    if exclude == "Y":
        return True

    # 건강식품/브랜드/임박/가공품은 원칙적으로 경락정보 제외
    skip_groups = {"건강식품", "브랜드", "임박상품"}
    if product_group in skip_groups or sub_group in skip_groups:
        return True

    return False


def main():
    candidates_file = find_latest_candidates_file()
    suffix = extract_suffix_from_name(candidates_file.name, CANDIDATES_PREFIX)

    if not suffix:
        raise ValueError(f"파일명에서 suffix를 해석할 수 없습니다: {candidates_file.name}")

    date_str, slot = parse_suffix_date_slot(suffix)

    print(f"Candidates 파일: {candidates_file}")
    print(f"기준일: {date_str}")
    print(f"slot: {slot}")

    candidates_df = load_csv_with_fallback(candidates_file)
    goods_df = prepare_goods_df(load_csv_with_fallback(GOODS_CODE_FILE))
    alias_map = load_alias_map(ALIAS_FILE)

    for col in ["product_group", "sub_group", "exclude_from_opportunity"]:
        if col not in candidates_df.columns:
            candidates_df[col] = ""

    candidates_df["product_name"] = candidates_df["product_name"].astype(str).map(normalize_text)
    candidates_df = candidates_df[candidates_df["product_name"] != ""].copy()
    candidates_df = candidates_df.drop_duplicates(subset=["product_name"])

    matched_rows: List[Dict[str, Any]] = []
    unmatched_rows: List[Dict[str, Any]] = []

    for _, row in candidates_df.iterrows():
        product_name = normalize_text(row.get("product_name", ""))

        if should_skip_candidate(row):
            unmatched_rows.append({
                "product_name": product_name,
                "reason": "excluded_or_not_target",
            })
            continue

        matched = find_goods_match(product_name, goods_df, alias_map)

        if matched:
            matched_rows.append(matched)
        else:
            unmatched_rows.append({
                "product_name": product_name,
                "reason": "no_goods_code_match",
            })

    matched_df = pd.DataFrame(matched_rows)
    unmatched_df = pd.DataFrame(unmatched_rows)

    month_dir = date_str[:7]
    output_dir = PROCESSED_DIR / month_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    matched_path = output_dir / f"auction_item_map_auto_{date_str}_{slot}.csv"
    unmatched_path = output_dir / f"auction_item_unmatched_{date_str}_{slot}.csv"

    matched_df.to_csv(matched_path, index=False, encoding="utf-8-sig")
    unmatched_df.to_csv(unmatched_path, index=False, encoding="utf-8-sig")

    print("\n완료")
    print(f"자동 매칭 성공: {len(matched_df)}개")
    print(f"자동 매칭 실패/제외: {len(unmatched_df)}개")
    print(f"매칭 파일: {matched_path}")
    print(f"미매칭 파일: {unmatched_path}")

    if not matched_df.empty:
        print("\n매칭 미리보기")
        print(matched_df.head(30).to_string(index=False))

    if not unmatched_df.empty:
        print("\n미매칭 미리보기")
        print(unmatched_df.head(30).to_string(index=False))


if __name__ == "__main__":
    main()