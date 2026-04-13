# 국내 상장사 소유구조 시계열 분석 (2015~2025)

DART 공시 API 기반으로 KOSPI·KOSDAQ 전체 상장사(~2,400개)의 최대주주 지분율 및 우호지분을 2015-2025년 시계열로 수집·분석하는 프로젝트입니다.

## 분석 목표

- 최대주주 단독 지분율 및 우호지분(특수관계인+자사주+우리사주) 추이 파악
- KOSPI vs KOSDAQ 소유구조 차이 비교
- 자본시장연구원(2024) 보고서 벤치마크 재현 및 확장

## 설치

```bash
git clone https://github.com/heeveloper72/kospi_ownership_2024-2025.git
cd kospi_ownership_2024-2025
pip install -r requirements.txt
```

## API 키 설정

1. [DART OpenAPI](https://opendart.fss.or.kr) 회원가입 후 인증키 발급
2. `.env` 파일 생성:
```bash
cp .env.example .env
# .env 파일에 실제 API 키 입력
```

## 사용법

순서대로 실행:

```bash
python src/01_get_corp_list.py        # 상장사 목록 수집
python src/02_collect_ownership.py    # 최대주주 데이터 수집 (여러 날 반복)
python src/03_collect_treasury.py     # 자사주 데이터 수집
python src/04_collect_minority.py     # 소액주주 데이터 수집
python src/05_clean_merge.py          # 데이터 정제 & 병합
python src/06_analyze.py              # 통계 분석
python src/07_visualize.py            # 시각화
```

> **참고**: DART API 일일 한도(10,000건)로 인해 Phase 2~3은 여러 날에 걸쳐 실행해야 합니다. 체크포인트 시스템이 자동으로 중단 지점에서 재개합니다.

## 프로젝트 구조

```
├── src/
│   ├── 01_get_corp_list.py        # 상장사 목록
│   ├── 02_collect_ownership.py    # 최대주주 수집
│   ├── 03_collect_treasury.py     # 자사주 수집
│   ├── 04_collect_minority.py     # 소액주주 수집
│   ├── 05_clean_merge.py          # 정제 & 병합
│   ├── 06_analyze.py              # 분석
│   └── 07_visualize.py            # 시각화
├── data/
│   ├── raw/                       # 원시 데이터
│   ├── processed/                 # 정제 데이터
│   └── output/                    # 분석 결과 & 차트
├── CLAUDE.md
├── requirements.txt
└── .env.example
```

## 데이터 출처

- [DART OpenAPI](https://opendart.fss.or.kr) — 금융감독원 전자공시시스템
- 벤치마크: 자본시장연구원 (2024), 국내 상장사 소유구조 분석 보고서
