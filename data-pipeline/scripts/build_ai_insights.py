import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


# =========================================================
# 1. 경로 설정
# =========================================================
BASE_DIR = Path(__file__).resolve().parents[1]

LATEST_DIR = BASE_DIR / "data" / "daily" / "latest"
OUTPUT_DIR = BASE_DIR / "data" / "daily" / "output"
FRONTEND_PUBLIC_DIR = BASE_DIR.parent / "earlypick-frontend" / "public"

SOURCE_JSON_PATH = LATEST_DIR / "daily_signals.json"
FRONTEND_JSON_PATH = FRONTEND_PUBLIC_DIR / "daily_signals.json"
AI_ONLY_OUTPUT_PATH = LATEST_DIR / "ai_insights_latest.json"


# =========================================================
# 2. 기본 유틸
# =========================================================
def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null", "<na>"}:
        return ""
    return text


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None:
            return default
        return int(float(value))
    except Exception:
        return default


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"파일이 없습니다: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_product_key(product: Dict[str, Any]) -> str:
    product_id = normalize_text(product.get("id"))
    if product_id:
        return product_id

    name = normalize_text(product.get("name"))
    source_type = normalize_text(product.get("sourceType"))
    rank = normalize_text(product.get("todayRank"))
    return f"{source_type}:{name}:{rank}"


def has_market_data(product: Dict[str, Any]) -> bool:
    market_status = product.get("marketDataStatus") or {}

    return bool(
        market_status.get("kamisMatched")
        or market_status.get("auctionMatched")
        or product.get("wholesalePriceNow") is not None
        or product.get("retailPriceNow") is not None
        or product.get("auctionDetail") is not None
    )


def compact_product(product: Dict[str, Any]) -> Dict[str, Any]:
    decision = product.get("decisionComment") or {}
    market_status = product.get("marketDataStatus") or {}

    return {
        "name": product.get("name"),
        "sourceType": product.get("sourceType"),
        "todayRank": product.get("todayRank"),
        "previousRank": product.get("previousRank"),
        "rankChangeLabel": product.get("rankChangeLabel"),
        "rankRange": product.get("rankRange"),
        "rankVelocity3d": product.get("rankVelocity3d"),
        "daysSeen7d": product.get("daysSeen7d"),
        "daysSeen14d": product.get("daysSeen14d"),
        "consecutiveDays": product.get("consecutiveDays"),
        "searchGrowthRate": product.get("searchGrowthRate"),
        "shoppingGrowthRate": product.get("shoppingGrowthRate"),
        "signalGroup": product.get("signalGroup"),
        "signalScore": product.get("signalScore"),
        "opportunityScore": product.get("opportunityScore"),
        "opportunityReason": product.get("opportunityReason"),
        "risingLevel": product.get("risingLevel"),
        "confidenceLevel": product.get("confidenceLevel"),
        "actionLevel": product.get("actionLevel"),
        "stableSummary": product.get("stableSummary"),
        "itemGroup": product.get("itemGroup"),
        "priceRisk": product.get("priceRisk"),
        "hasMarketData": has_market_data(product),
        "marketDataReason": market_status.get("reason"),
        "wholesalePriceNow": product.get("wholesalePriceNow"),
        "retailPriceNow": product.get("retailPriceNow"),
        "decisionSummary": decision.get("summary"),
        "marketNote": decision.get("marketNote"),
        "caution": decision.get("caution"),
        "recommendedUse": decision.get("recommendedUse"),
    }


# =========================================================
# 3. 룰 기반 fallback AI 인사이트
#    - API 키가 없거나 LLM 호출 실패 시 사용
# =========================================================
def build_rule_based_ai_insight(product: Dict[str, Any]) -> Dict[str, Any]:
    name = normalize_text(product.get("name")) or "해당 상품"
    source_type = normalize_text(product.get("sourceType"))
    item_group = normalize_text(product.get("itemGroup")) or "상품 유형 확인 필요"

    shopping_growth = safe_float(product.get("shoppingGrowthRate"), 0.0)
    search_growth = safe_float(product.get("searchGrowthRate"), 0.0)
    rank_velocity = safe_float(product.get("rankVelocity3d"), 0.0)
    opportunity_score = safe_float(product.get("opportunityScore"), safe_float(product.get("signalScore"), 0.0))

    market_linked = has_market_data(product)
    source_label = {
        "rising": "네이버 예비 인기권",
        "top20": "네이버 인기권",
        "sns": "소셜 관찰",
    }.get(source_type, "관찰")

    reasons: List[str] = []
    warnings: List[str] = []

    if product.get("todayRank") is not None:
        reasons.append(f"{source_label}에서 {product.get('todayRank')}위로 확인되었습니다.")

    if rank_velocity > 0:
        reasons.append(f"최근 3일 기준 순위가 {int(rank_velocity)}단계 상승했습니다.")
    elif rank_velocity < 0:
        reasons.append(f"최근 3일 기준 순위가 {abs(int(rank_velocity))}단계 하락했습니다.")

    if search_growth >= 10:
        reasons.append("검색 관심이 증가했습니다.")
    elif search_growth <= -10:
        warnings.append("검색 관심은 약화된 상태입니다.")

    if shopping_growth >= 10:
        reasons.append("쇼핑 클릭 관심이 증가했습니다.")
    elif shopping_growth <= -10:
        warnings.append("쇼핑 클릭 관심은 하락했습니다.")

    if market_linked:
        reasons.append("시장 가격 데이터가 연결되어 가격 흐름을 함께 확인할 수 있습니다.")
    else:
        warnings.append("시장 가격 데이터가 아직 연결되지 않았습니다.")

    if not reasons:
        reasons.append("현재 데이터 기준으로 관찰 신호가 확인되었습니다.")

    # 판단 단계
    if source_type in {"place", "unknown"}:
        diagnosis = "분석 제외"
        stage = "EXCLUDED"
    elif rank_velocity > 0 and shopping_growth <= -10:
        diagnosis = "판단 보류"
        stage = "HOLD"
    elif shopping_growth >= 10 and rank_velocity > 0 and market_linked:
        diagnosis = "시장 데이터 확인 필요"
        stage = "MARKET_CHECK"
    elif shopping_growth >= 10 and opportunity_score >= 60:
        diagnosis = "우선 관찰"
        stage = "PRIORITY"
    elif rank_velocity > 0 or opportunity_score >= 45:
        diagnosis = "관찰 유지"
        stage = "OBSERVE"
    else:
        diagnosis = "추가 관찰"
        stage = "WATCH"

    # 요약/추천
    if stage == "HOLD":
        summary = f"{name}은 순위 상승 신호는 있으나 쇼핑 관심이 약화되어 운영 판단을 보류해야 하는 후보입니다."
        recommended_action = "매입·재고 판단은 보류하고, 검색·쇼핑 반응이 다시 동반되는지 1~2일 추가 관찰하세요."
    elif stage == "MARKET_CHECK":
        summary = f"{name}은 관심 신호와 시장 데이터 확인이 함께 필요한 후보입니다."
        recommended_action = "검색·쇼핑 반응과 시장 가격 흐름을 함께 확인해 우선 관찰하세요."
    elif stage == "PRIORITY":
        summary = f"{name}은 검색·쇼핑 반응이 동반되는 우선 관찰 후보입니다."
        recommended_action = "즉시 매입 판단보다는 가격 데이터와 반복 등장 여부를 함께 확인하세요."
    else:
        summary = f"{name}은 {item_group} 유형의 관찰 후보입니다."
        recommended_action = "현재는 확정 판단보다 추가 관찰과 네이버 반응 검증이 적합합니다."

    if warnings:
        caution = " ".join(warnings)
    else:
        caution = "제공된 데이터 기준의 판단이며 전체 시장 수요로 단정하지 않습니다."

    insight = {
        "summary": summary,
        "diagnosis": diagnosis,
        "aiStage": stage,
        "confidenceLevel": normalize_text(product.get("confidenceLevel")) or "medium",
        "reasons": reasons[:4],
        "warnings": warnings[:3],
        "recommendedAction": recommended_action,
        "caution": caution,
        "generatedBy": "rule_based_ai_v0",
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
    }

    return clean_ai_insight(insight)


# =========================================================
# 4. LLM 호출
# =========================================================
def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None

    text = text.strip()

    try:
        return json.loads(text)
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None

    try:
        return json.loads(match.group(0))
    except Exception:
        return None

def clean_ai_text(text: Any) -> str:
    """
    AI 인사이트에 개발용 변수명이 노출되지 않도록 사용자 표시용 문장으로 정리한다.
    """
    value = normalize_text(text)

    if not value:
        return ""

    # 괄호 안에 개발용 필드명이 들어간 경우 제거
    value = re.sub(
        r"\((?:rankVelocity3d|shoppingGrowthRate|searchGrowthRate|daysSeen7d|daysSeen14d|sourceType|todayRank|previousRank|opportunityScore|signalScore)[^)]*\)",
        "",
        value,
    )

    # 대표 변수명 치환
    replacements = {
        "rankVelocity3d": "최근 3일 순위 속도",
        "shoppingGrowthRate": "쇼핑 클릭 관심 변화",
        "searchGrowthRate": "검색 관심 변화",
        "daysSeen7d": "최근 7일 등장일",
        "daysSeen14d": "최근 14일 등장일",
        "sourceType": "데이터 출처",
        "todayRank": "현재 순위",
        "previousRank": "이전 순위",
        "opportunityScore": "관찰 우선도 점수",
        "signalScore": "신호 점수",
        "risingLevel": "상승 후보 단계",
        "confidenceLevel": "신뢰도",
        "actionLevel": "추천 행동 단계",
    }

    for old, new in replacements.items():
        value = value.replace(old, new)

    # 2칸 이상 공백 정리
    value = re.sub(r"\s{2,}", " ", value).strip()

    return value


def clean_ai_insight(insight: Dict[str, Any]) -> Dict[str, Any]:
    """
    aiInsight 전체에서 사용자에게 보이면 안 되는 변수명을 정리한다.
    """
    text_keys = [
        "summary",
        "diagnosis",
        "confidenceLevel",
        "recommendedAction",
        "caution",
    ]

    for key in text_keys:
        if key in insight:
            insight[key] = clean_ai_text(insight.get(key))

    for list_key in ["reasons", "warnings"]:
        values = insight.get(list_key)

        if isinstance(values, list):
            insight[list_key] = [
                clean_ai_text(item)
                for item in values
                if clean_ai_text(item)
            ]

    return insight

def build_llm_prompt(product_data: Dict[str, Any]) -> str:
    return f"""
아래 상품 데이터를 바탕으로 EarlyPick AI 인사이트를 JSON으로 생성하라.

규칙:
1. 제공된 데이터만 사용한다.
2. 가격 상승, 매출 증가, 유행 확정, 재고 확보를 단정하지 않는다.
3. 순위 상승과 쇼핑 관심 하락이 충돌하면 보수적으로 판단한다.
4. 추천 행동은 관찰, 검증, 시장 데이터 확인 중심으로 작성한다.
5. 한국어로 작성한다.
6. 과장된 마케팅 문구를 쓰지 않는다.
7. JSON만 출력한다.
8. 사용자에게 보이는 문장에는 영어 변수명이나 개발용 필드명을 절대 쓰지 않는다.
9. rankVelocity3d는 "최근 3일 순위 속도" 또는 "최근 3일 기준 n단계 상승/하락"으로 표현한다.
10. shoppingGrowthRate는 "쇼핑 클릭 관심", searchGrowthRate는 "검색 관심", daysSeen7d는 "최근 7일 등장일"로 표현한다.
11. 단순히 데이터를 나열하지 말고, 운영자가 오늘 무엇을 해야 하는지 행동 중심으로 작성한다.
12. "확인 필요"라고만 쓰지 말고, 무엇을 확인해야 하는지 구체적으로 쓴다.
13. 쇼핑 클릭 관심이 하락했으면 매입·광고 확대를 보류하라고 명시한다.
14. 시장 데이터가 없으면 "가격 상승 가능성"이 아니라 "가격 데이터 연결 필요"로 표현한다.
15. 추천 행동은 판매자/MD/소상공인이 이해할 수 있는 실무 문장으로 작성한다.

출력 JSON 형식:
{{
  "oneLineConclusion": "운영자가 바로 이해할 수 있는 한 줄 결론",
  "summary": "상품 상태 요약 1~2문장",
  "diagnosis": "추가 관찰 | 관찰 유지 | 우선 관찰 | 가격 데이터 연결 필요 | 시장 데이터 확인 필요 | 판단 보류 | 분석 제외",
  "aiStage": "WATCH | OBSERVE | PRIORITY | PRICE_LINK_CHECK | MARKET_CHECK | HOLD | EXCLUDED",
  "confidenceLevel": "high | medium | low",
  "businessMeaning": "이 신호가 판매/광고/매입 판단에서 어떤 의미인지 설명",
  "reasons": ["판단 근거 1", "판단 근거 2", "판단 근거 3"],
  "warnings": ["주의 신호 1", "주의 신호 2"],
  "doNow": ["지금 해야 할 행동 1", "지금 해야 할 행동 2"],
  "doNot": ["지금 하지 말아야 할 행동 1"],
  "nextCheck": ["다음 수집 때 확인할 조건 1", "다음 수집 때 확인할 조건 2"],
  "recommendedAction": "최종 추천 행동 1~2문장",
  "caution": "단정 금지 또는 해석 주의 문구"
}}

상품 데이터:
{json.dumps(product_data, ensure_ascii=False, indent=2)}
""".strip()


def build_llm_ai_insight(
    client: Any,
    model: str,
    product: Dict[str, Any],
) -> Dict[str, Any]:
    fallback = build_rule_based_ai_insight(product)
    product_data = compact_product(product)

    system_prompt = """
너는 식품 트렌드 조기 감지 서비스 EarlyPick의 AI 분석 엔진이다.
사용자에게 상품별 조기 신호를 보수적으로 해석해준다.
제공된 데이터 밖의 사실을 추정하지 않는다.
출력은 반드시 JSON 객체 하나만 작성한다.
""".strip()

    user_prompt = build_llm_prompt(product_data)

    try:
        response = client.responses.create(
            model=model,
            instructions=system_prompt,
            input=user_prompt,
        )

        raw_text = getattr(response, "output_text", "")
        parsed = extract_json_object(raw_text)

        if not parsed:
            fallback["warnings"] = fallback.get("warnings", []) + ["LLM 응답 파싱 실패로 fallback 인사이트를 사용했습니다."]
            fallback["generatedBy"] = "rule_based_ai_v0_llm_parse_failed"
            return clean_ai_insight(fallback)

        required_keys = [
            "summary",
            "diagnosis",
            "aiStage",
            "confidenceLevel",
            "reasons",
            "warnings",
            "recommendedAction",
            "caution",
        ]

        for key in required_keys:
            if key not in parsed:
                parsed[key] = fallback.get(key)

        if not isinstance(parsed.get("reasons"), list):
            parsed["reasons"] = fallback["reasons"]

        if not isinstance(parsed.get("warnings"), list):
            parsed["warnings"] = fallback["warnings"]

        parsed["generatedBy"] = "llm_insight_v1"
        parsed["generatedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
        return clean_ai_insight(parsed)

    except Exception as e:
        fallback["warnings"] = fallback.get("warnings", []) + [f"LLM 호출 실패: {type(e).__name__}"]
        fallback["generatedBy"] = "rule_based_ai_v0_llm_failed"
        return clean_ai_insight(fallback)


# =========================================================
# 5. LLM 적용 대상 선정
# =========================================================
def collect_unique_products(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    sections = ["risingCandidates", "naverTop20", "products", "snsCandidates"]
    seen = set()
    result = []

    for section in sections:
        items = data.get(section) or []
        if not isinstance(items, list):
            continue

        for product in items:
            if not isinstance(product, dict):
                continue

            key = get_product_key(product)
            if key in seen:
                continue

            seen.add(key)
            result.append(product)

    return result


def select_llm_targets(products: List[Dict[str, Any]], max_count: int) -> set:
    def score(product: Dict[str, Any]) -> float:
        base = safe_float(product.get("opportunityScore"), safe_float(product.get("signalScore"), 0.0))
        shopping = safe_float(product.get("shoppingGrowthRate"), 0.0)
        velocity = safe_float(product.get("rankVelocity3d"), 0.0)

        source_bonus = 0.0
        if product.get("sourceType") == "rising":
            source_bonus += 15.0
        if product.get("sourceType") == "top20":
            source_bonus += 10.0

        conflict_bonus = 0.0
        if velocity > 0 and shopping <= -10:
            conflict_bonus += 25.0

        market_bonus = 8.0 if has_market_data(product) else 0.0

        return base + source_bonus + conflict_bonus + market_bonus

    candidates = sorted(products, key=score, reverse=True)
    return {get_product_key(product) for product in candidates[:max_count]}


def apply_insights_to_sections(
    data: Dict[str, Any],
    insight_lookup: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    sections = ["products", "naverTop20", "risingCandidates", "snsCandidates"]

    for section in sections:
        items = data.get(section) or []
        if not isinstance(items, list):
            continue

        for product in items:
            if not isinstance(product, dict):
                continue

            key = get_product_key(product)
            product["aiInsight"] = insight_lookup.get(key) or build_rule_based_ai_insight(product)

    return data


# =========================================================
# 6. main
# =========================================================
def main() -> None:
    if load_dotenv is not None:
        load_dotenv(BASE_DIR / ".env")
        load_dotenv(BASE_DIR.parent / ".env")

    data = load_json(SOURCE_JSON_PATH)
    products = collect_unique_products(data)

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = os.environ.get("OPENAI_MODEL", "gpt-5.2").strip()
    max_llm_products = safe_int(os.environ.get("MAX_LLM_PRODUCTS"), 12) or 12

    use_llm = bool(api_key) and OpenAI is not None
    client = OpenAI(api_key=api_key) if use_llm else None

    llm_targets = select_llm_targets(products, max_llm_products) if use_llm else set()

    insight_lookup: Dict[str, Dict[str, Any]] = {}
    ai_records: List[Dict[str, Any]] = []

    print(f"전체 상품 수: {len(products)}")
    print(f"LLM 사용 여부: {'Y' if use_llm else 'N'}")
    print(f"LLM 생성 대상 수: {len(llm_targets)}")

    for idx, product in enumerate(products, start=1):
        key = get_product_key(product)
        name = normalize_text(product.get("name"))

        if use_llm and key in llm_targets and client is not None:
            insight = build_llm_ai_insight(client, model, product)
        else:
            insight = build_rule_based_ai_insight(product)

        insight_lookup[key] = insight
        ai_records.append({
            "productKey": key,
            "productName": name,
            "sourceType": product.get("sourceType"),
            "aiInsight": insight,
        })

        print(f"[{idx}/{len(products)}] {name} / {insight.get('generatedBy')} / {insight.get('diagnosis')}")

    data = apply_insights_to_sections(data, insight_lookup)

    data["aiInsightSummary"] = {
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "method": "llm_insight_v1_with_rule_fallback",
        "llmEnabled": use_llm,
        "llmModel": model if use_llm else "",
        "llmTargetCount": len(llm_targets),
        "totalInsightCount": len(products),
        "description": "상품별 데이터 기반 생성형 AI 인사이트입니다. 가격 상승·매출 증가·유행 확정은 단정하지 않습니다.",
    }

    save_json(data, SOURCE_JSON_PATH)
    save_json(data, FRONTEND_JSON_PATH)
    save_json({"records": ai_records}, AI_ONLY_OUTPUT_PATH)

    print("\n완료")
    print(f"latest JSON 갱신: {SOURCE_JSON_PATH}")
    print(f"frontend JSON 갱신: {FRONTEND_JSON_PATH}")
    print(f"AI 인사이트 별도 파일: {AI_ONLY_OUTPUT_PATH}")


if __name__ == "__main__":
    main()