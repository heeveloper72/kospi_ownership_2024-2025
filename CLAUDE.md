# 국내 상장사(KOSPI+KOSDAQ) 소유구조 시계열 분석

## 목적
DART 공시 기반으로 전체 상장사 ~2,400개의 최대주주 지분율·우호지분을
2015~2025년 시계열로 수집·분석.
자본시장연구원(2024) 보고서를 벤치마크로 재현 + 확장.

## 분석 대상
- KOSPI ~800개 + KOSDAQ ~1,600개 (약 2,400개사)
- DART corp_cls: 'Y'=유가증권(KOSPI), 'K'=코스닥(KOSDAQ)

## 기술 스택
Python 3.10+ / requests / pandas / matplotlib, plotly / python-dotenv

## 데이터 정의
- 최대주주 지분율: hyslrSttus API, 최대주주 본인 행
- 특수관계인 합산: 동 API, 특수관계인 행 합계
- 우호지분: 최대주주 + 특수관계인 + 자사주 + 우리사주
- 의결권 기준: 우호지분 − 자사주

## API 제약
- 일 10,000건, 요청 간 0.5초 sleep
- 2015년~ 제공 (reprt_code: 사업보고서=11011)
- checkpoint JSON 필수 (중단/재개)
- .env에서 키 로드

## 벤치마크 (자본시장연구원, 2023년말)
| 구분 | 최대주주 | 우호지분 |
|------|---------|---------|
| 전체 | 29.21% | 43.07% |
| KOSPI | — | 49.34% |
| KOSDAQ | — | 39.93% |

## 디렉토리
src/ (스크립트), data/raw/, data/processed/, data/output/

## 코딩 규칙
snake_case, 타입 힌트, logging 모듈, 각 파일 독립 실행 가능
