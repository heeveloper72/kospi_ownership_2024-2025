#!/usr/bin/env python3
"""카나리아 검증: 3개 기업으로 필드 존재 여부 및 데이터 품질 확인."""

import json
import logging
import sys

import pandas as pd

from utils import DATA_RAW, call_dart_api, load_api_key

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# 카나리아 대상: KOSPI 대형사, KOSDAQ 대형·중형
CANARY_CORPS = [
    ("00126380", "삼성전자", "KOSPI"),
    ("00401731", "카카오", "KOSDAQ"),
    ("00131577", "셀트리온", "KOSDAQ"),
]
CANARY_YEAR = "2023"

REQUIRED_FIELDS = {
    "hyslrSttus": ["nm", "relate", "trmend_posesn_stock_co", "trmend_posesn_stock_qota_rt"],
    "tesstkAcqsDspsSttus": ["stock_knd", "bsis_qy", "trmend_qy"],
    "mrhlSttus": ["se", "shrholdr_co", "hold_stock_rate"],
}


def validate_ownership() -> bool:
    """hyslrSttus 카나리아 검증."""
    logger.info("=" * 60)
    logger.info("Step 1: hyslrSttus (최대주주현황) 검증")
    logger.info("=" * 60)

    api_key = load_api_key()
    all_passed = True

    for corp_code, corp_name, market in CANARY_CORPS:
        logger.info(f"\n[{corp_name}] hyslrSttus 호출 ({corp_code}, {CANARY_YEAR})")

        data = call_dart_api(
            "hyslrSttus",
            api_key,
            {
                "corp_code": corp_code,
                "bsns_year": CANARY_YEAR,
                "reprt_code": "11011",
            },
        )

        if not data or "list" not in data:
            logger.error(f"  ❌ 응답 없음 또는 'list' 키 없음")
            all_passed = False
            continue

        logger.info(f"  응답 행 수: {len(data['list'])}")

        # Raw JSON 로그 (첫 1행만)
        if data["list"]:
            logger.info(f"  Raw response (first row):\n{json.dumps(data['list'][0], ensure_ascii=False, indent=2)}")

        # 필드 존재 확인
        missing_fields = []
        non_empty_counts = {f: 0 for f in REQUIRED_FIELDS["hyslrSttus"]}

        for item in data["list"]:
            for field in REQUIRED_FIELDS["hyslrSttus"]:
                if field not in item:
                    if field not in missing_fields:
                        missing_fields.append(field)
                else:
                    val = item.get(field, "")
                    if val not in ("", "-", None):
                        non_empty_counts[field] += 1

        if missing_fields:
            logger.error(f"  ❌ 필드 누락: {missing_fields}")
            logger.error(f"     사용 가능한 모든 키: {sorted(data['list'][0].keys())}")
            all_passed = False
        else:
            logger.info(f"  ✅ 필드 존재 확인 완료")

        # 비-공란 비율 확인
        for field in REQUIRED_FIELDS["hyslrSttus"]:
            if field in non_empty_counts:
                rate = non_empty_counts[field] / len(data["list"]) if data["list"] else 0
                symbol = "✅" if rate >= 0.8 else "⚠️"
                logger.info(f"  {symbol} {field}: {rate:.1%} 비-공란 ({non_empty_counts[field]}/{len(data['list'])})")
                if rate < 0.5:
                    all_passed = False

    return all_passed


def validate_treasury() -> bool:
    """tesstkAcqsDspsSttus 카나리아 검증."""
    logger.info("\n" + "=" * 60)
    logger.info("Step 2: tesstkAcqsDspsSttus (자기주식현황) 검증")
    logger.info("=" * 60)

    api_key = load_api_key()
    all_passed = True

    for corp_code, corp_name, market in CANARY_CORPS:
        logger.info(f"\n[{corp_name}] tesstkAcqsDspsSttus 호출 ({corp_code}, {CANARY_YEAR})")

        data = call_dart_api(
            "tesstkAcqsDspsSttus",
            api_key,
            {
                "corp_code": corp_code,
                "bsns_year": CANARY_YEAR,
                "reprt_code": "11011",
            },
        )

        if not data or "list" not in data:
            logger.warning(f"  ⚠️  응답 없음 (자사주 정보 없을 수 있음) — 정상")
            continue

        logger.info(f"  응답 행 수: {len(data['list'])}")

        if data["list"]:
            logger.info(f"  Raw response (first row):\n{json.dumps(data['list'][0], ensure_ascii=False, indent=2)}")

        # 필드 존재 확인
        missing_fields = []
        for item in data["list"]:
            for field in REQUIRED_FIELDS["tesstkAcqsDspsSttus"]:
                if field not in item:
                    if field not in missing_fields:
                        missing_fields.append(field)

        if missing_fields:
            logger.error(f"  ❌ 필드 누락: {missing_fields}")
            logger.error(f"     사용 가능한 모든 키: {sorted(data['list'][0].keys()) if data['list'] else []}")
            all_passed = False
        else:
            logger.info(f"  ✅ 필드 존재 확인 완료")

        # trmend_rate 존재 여부 확인 (API에 없을 것으로 예상)
        has_trmend_rate = any("trmend_rate" in item for item in data["list"])
        symbol = "❌" if has_trmend_rate else "✅"
        logger.info(f"  {symbol} trmend_rate 필드: {'있음 (예상 외!)' if has_trmend_rate else '없음 (예상대로)'}")

    return all_passed


def validate_minority() -> bool:
    """mrhlSttus 카나리아 검증."""
    logger.info("\n" + "=" * 60)
    logger.info("Step 3: mrhlSttus (소액주주현황) 검증")
    logger.info("=" * 60)

    api_key = load_api_key()
    all_passed = True

    for corp_code, corp_name, market in CANARY_CORPS:
        logger.info(f"\n[{corp_name}] mrhlSttus 호출 ({corp_code}, {CANARY_YEAR})")

        data = call_dart_api(
            "mrhlSttus",
            api_key,
            {
                "corp_code": corp_code,
                "bsns_year": CANARY_YEAR,
                "reprt_code": "11011",
            },
        )

        if not data or "list" not in data:
            logger.error(f"  ❌ 응답 없음 또는 'list' 키 없음")
            all_passed = False
            continue

        logger.info(f"  응답 행 수: {len(data['list'])}")

        if data["list"]:
            logger.info(f"  Raw response (first row):\n{json.dumps(data['list'][0], ensure_ascii=False, indent=2)}")

        # 필드 존재 확인
        missing_fields = []
        for item in data["list"]:
            for field in REQUIRED_FIELDS["mrhlSttus"]:
                if field not in item:
                    if field not in missing_fields:
                        missing_fields.append(field)

        if missing_fields:
            logger.error(f"  ❌ 필드 누락: {missing_fields}")
            logger.error(f"     사용 가능한 모든 키: {sorted(data['list'][0].keys())}")
            all_passed = False
        else:
            logger.info(f"  ✅ 필드 존재 확인 완료")

    return all_passed


def main() -> None:
    logger.info("\n" + "🔍 " * 30)
    logger.info("카나리아 검증 시작 — DART API 필드 확인")
    logger.info("🔍 " * 30)

    result_ownership = validate_ownership()
    result_treasury = validate_treasury()
    result_minority = validate_minority()

    logger.info("\n" + "=" * 60)
    logger.info("최종 결과")
    logger.info("=" * 60)
    logger.info(f"hyslrSttus (최대주주): {'✅ PASS' if result_ownership else '❌ FAIL'}")
    logger.info(f"tesstkAcqsDspsSttus (자사주): {'✅ PASS' if result_treasury else '❌ FAIL'}")
    logger.info(f"mrhlSttus (소액주주): {'✅ PASS' if result_minority else '❌ FAIL'}")

    if result_ownership and result_treasury and result_minority:
        logger.info("\n✅ 모든 검증 통과! 전체 수집으로 진행 가능합니다.")
        sys.exit(0)
    else:
        logger.error("\n❌ 일부 검증 실패. 위 오류를 해결한 후 재시도하세요.")
        sys.exit(1)


if __name__ == "__main__":
    main()
