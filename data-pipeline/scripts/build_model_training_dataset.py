# scripts/build_model_training_dataset.py

import re
from pathlib import Path
from datetime import datetime
from typing import Any, Optional

import pandas as pd


# =========================================================
# 1. 경로 설정
# =========================================================
BASE_DIR = Path(__file__).resolve().parents[1]

PROCESSED_DIR = BASE_DIR / "data" / "daily" / "processed"
LATEST_DIR = BASE_DIR / "data" / "daily" / "latest"
ML_DIR = BASE_DIR / "data" / "ml"

FEATURE_SNAPSHOTS_FILE = ML_DIR / "feature_snapshots.csv"
LABEL_OUTCOMES_FILE = ML_DIR / "label_outcomes.csv"
MODEL_TRAINING_DATASET_FILE = ML_DIR / "model_training_dataset.csv"

RISING_FEATURE_PREFIX = "rising_candidate_features_"
CANDIDATES_PREFIX = "candidates_with_search_shopping_"


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


def build_snapshot_id(date: Any, slot: Any, source_type: Any, product_name: Any) -> str:
    return "|".join([
        normalize_text(date),
        normalize_slot(slot),
        normalize_text(source_type) or "rising",
        normalize_text(product_name),
    ])


# =========================================================
# 3. 파일 찾기
# =========================================================
def find_latest_rising_feature_file() -> Optional[Path]:
    latest_path = LATEST_DIR / "rising_candidate_features_latest.csv"

    if latest_path.exists():
        return latest_path

    files = list(PROCESSED_DIR.rglob(f"{RISING_FEATURE_PREFIX}*.csv"))

    if not files:
        return None

    def sort_key(path: Path):
        suffix = parse_suffix_from_filename(path.name, RISING_FEATURE_PREFIX)

        if not suffix:
            return ("0000-00-00", 0)

        date_part, slot_part = parse_suffix_date_slot(suffix)
        return date_part, slot_order(slot_part)

    return max(files, key=sort_key)


def find_candidates_file(date: str, slot: str) -> Optional[Path]:
    target_name = f"{CANDIDATES_PREFIX}{date}_{slot}.csv"
    matches = list(PROCESSED_DIR.rglob(target_name))

    if matches:
        return matches[0]

    return None


# =========================================================
# 4. 오늘 feature snapshot 만들기
# =========================================================
def find_all_rising_feature_files() -> list[Path]:
    files = list(PROCESSED_DIR.rglob(f"{RISING_FEATURE_PREFIX}*.csv"))

    # latest 파일은 제외
    files = [
        path for path in files
        if path.name != "rising_candidate_features_latest.csv"
    ]

    def sort_key(path: Path):
        suffix = parse_suffix_from_filename(path.name, RISING_FEATURE_PREFIX)

        if not suffix:
            return ("0000-00-00", 0)

        date_part, slot_part = parse_suffix_date_slot(suffix)
        return date_part, slot_order(slot_part)

    return sorted(files, key=sort_key)


def load_all_feature_snapshots() -> pd.DataFrame:
    files = find_all_rising_feature_files()

    if not files:
        print("[WARN] rising_candidate_features 파일을 찾지 못했습니다.")
        return pd.DataFrame()

    frames = []

    print(f"읽을 rising feature 파일 수: {len(files)}")

    for feature_file in files:
        df = load_csv_with_fallback(feature_file)

        if df.empty:
            continue

        df.columns = [str(c).strip() for c in df.columns]

        required = {"date", "slot", "product_name"}
        missing = required - set(df.columns)

        if missing:
            print(f"[WARN] 필수 컬럼 누락으로 제외: {feature_file.name} / {missing}")
            continue

        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        df["slot"] = df["slot"].map(normalize_slot)
        df["product_name"] = df["product_name"].map(normalize_text)

        if "source_type" not in df.columns:
            df["source_type"] = "rising"

        df["source_type"] = df["source_type"].map(normalize_text)
        df.loc[df["source_type"] == "", "source_type"] = "rising"

        if "canonical_product_name" not in df.columns:
            df["canonical_product_name"] = df["product_name"]

        df["canonical_product_name"] = df["canonical_product_name"].map(normalize_text)

        # 날짜/slot 기준 candidates_with_search_shopping 파일에서 검색/쇼핑 ratio 붙이기
        target_date = normalize_text(df["date"].dropna().iloc[0])
        target_slot = normalize_slot(df["slot"].dropna().iloc[0])

        candidates_file = find_candidates_file(target_date, target_slot)

        if candidates_file:
            candidates_df = load_csv_with_fallback(candidates_file)

            if not candidates_df.empty and "product_name" in candidates_df.columns:
                candidates_df.columns = [str(c).strip() for c in candidates_df.columns]
                candidates_df["product_name"] = candidates_df["product_name"].map(normalize_text)

                keep_cols = ["product_name"]

                if "search_ratio" in candidates_df.columns:
                    keep_cols.append("search_ratio")

                if "shopping_ratio" in candidates_df.columns:
                    keep_cols.append("shopping_ratio")

                candidates_df = candidates_df[keep_cols].drop_duplicates("product_name")

                rename_map = {}
                if "search_ratio" in candidates_df.columns:
                    rename_map["search_ratio"] = "current_search_ratio"
                if "shopping_ratio" in candidates_df.columns:
                    rename_map["shopping_ratio"] = "current_shopping_ratio"

                candidates_df = candidates_df.rename(columns=rename_map)

                df = df.merge(candidates_df, on="product_name", how="left")

        numeric_cols = [
            "rank",
            "prev_rank",
            "rank_change",
            "days_seen_7d",
            "days_seen_14d",
            "consecutive_days",
            "best_rank_14d",
            "worst_rank_14d",
            "rank_velocity_3d",
            "rising_score",
            "current_search_ratio",
            "current_shopping_ratio",
        ]

        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].map(safe_float)

        df["snapshot_id"] = df.apply(
            lambda r: build_snapshot_id(
                r.get("date"),
                r.get("slot"),
                r.get("source_type"),
                r.get("product_name"),
            ),
            axis=1,
        )

        df["snapshot_created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        df = df[
            (df["date"].notna())
            & (df["date"] != "")
            & (df["product_name"] != "")
        ].copy()

        frames.append(df)

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)
    result = result.drop_duplicates("snapshot_id", keep="last").reset_index(drop=True)

    return result


# =========================================================
# 5. feature_snapshots.csv 누적 저장
# =========================================================
def update_feature_snapshots(today_df: pd.DataFrame) -> pd.DataFrame:
    ML_DIR.mkdir(parents=True, exist_ok=True)

    if today_df.empty:
        existing = load_csv_with_fallback(FEATURE_SNAPSHOTS_FILE)
        return existing

    existing = load_csv_with_fallback(FEATURE_SNAPSHOTS_FILE)

    if existing.empty:
        combined = today_df.copy()
    else:
        existing.columns = [str(c).strip() for c in existing.columns]

        if "snapshot_id" not in existing.columns:
            existing["source_type"] = existing.get("source_type", "rising")
            existing["snapshot_id"] = existing.apply(
                lambda r: build_snapshot_id(
                    r.get("date"),
                    r.get("slot"),
                    r.get("source_type"),
                    r.get("product_name"),
                ),
                axis=1,
            )

        combined = pd.concat([existing, today_df], ignore_index=True)

    combined = combined.drop_duplicates("snapshot_id", keep="last").reset_index(drop=True)

    combined.to_csv(FEATURE_SNAPSHOTS_FILE, index=False, encoding="utf-8-sig")

    return combined


# =========================================================
# 6. label과 병합해서 최종 학습용 dataset 생성
# =========================================================
def build_training_dataset(feature_df: pd.DataFrame) -> pd.DataFrame:
    if feature_df.empty:
        return pd.DataFrame()

    feature_df = feature_df.copy()
    feature_df.columns = [str(c).strip() for c in feature_df.columns]

    if "snapshot_id" not in feature_df.columns:
        feature_df["source_type"] = feature_df.get("source_type", "rising")
        feature_df["snapshot_id"] = feature_df.apply(
            lambda r: build_snapshot_id(
                r.get("date"),
                r.get("slot"),
                r.get("source_type"),
                r.get("product_name"),
            ),
            axis=1,
        )

    label_df = load_csv_with_fallback(LABEL_OUTCOMES_FILE)

    if label_df.empty:
        print("[INFO] label_outcomes.csv가 아직 없습니다. feature만 저장합니다.")
        dataset = feature_df.copy()
    else:
        label_df.columns = [str(c).strip() for c in label_df.columns]

        if "snapshot_id" not in label_df.columns:
            label_df["source_type"] = label_df.get("source_type", "rising")
            label_df["snapshot_id"] = label_df.apply(
                lambda r: build_snapshot_id(
                    r.get("date"),
                    r.get("slot"),
                    r.get("source_type"),
                    r.get("product_name"),
                ),
                axis=1,
            )

        label_df = label_df.drop_duplicates("snapshot_id", keep="last")

        # label 파일에서 feature와 겹치는 설명 컬럼은 제외하고 target만 붙임
        label_cols = [
            c for c in label_df.columns
            if c == "snapshot_id"
            or c.startswith("target_")
            or c.startswith("label_")
        ]

        dataset = feature_df.merge(
            label_df[label_cols],
            on="snapshot_id",
            how="left",
        )

    dataset.to_csv(MODEL_TRAINING_DATASET_FILE, index=False, encoding="utf-8-sig")

    return dataset


# =========================================================
# 7. 메인
# =========================================================
def main():
    all_feature_df = load_all_feature_snapshots()
    feature_df = update_feature_snapshots(all_feature_df)
    dataset = build_training_dataset(feature_df)

    print("\n완료")
    print(f"feature snapshot 수: {len(feature_df)}")
    print(f"model training row 수: {len(dataset)}")
    print(f"feature 저장: {FEATURE_SNAPSHOTS_FILE}")
    print(f"최종 학습용 저장: {MODEL_TRAINING_DATASET_FILE}")

    if not dataset.empty:
        preview_cols = [
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
            "target_top20_next_3d",
            "target_rank_50_next_3d",
            "target_click_up_next_3d",
            "label_status_3d",
        ]

        preview_cols = [c for c in preview_cols if c in dataset.columns]

        print("\n미리보기")
        print(dataset[preview_cols].tail(20).to_string(index=False))


if __name__ == "__main__":
    main()