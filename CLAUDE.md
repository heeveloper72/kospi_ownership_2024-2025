# 국내 상장사(KOSPI+KOSDAQ) 소유구조 시계열 분석

## 목적
DART 공시 기반으로 전체 상장사 ~2,400개의 최대주주 지분율·우호지분을
2015~2025년 시계열로 수집·분석.
자본시장연구원(2024) 보고서를 벤치마크로 재현 + 확장.

## 분석 대상
- KOSPI ~800개 + KOSDAQ ~1,600개 (약 2,400개사, 실제 2,661개)
- DART corp_cls: 'Y'=유가증권(KOSPI), 'K'=코스닥(KOSDAQ)

## 기술 스택
Python 3.10+ / requests / pandas / matplotlib, plotly / python-dotenv

## 데이터 정의
- 최대주주 지분율(`largest_pct`): hyslrSttus API, `relate ∈ {본인, 최대주주, 최대주주 본인}` 또는 "본인" 포함 행
- 특수관계인 합산(`related_pct`): 동 API, 본인·우리사주 제외한 나머지 행 합계
- 자사주 비율(`treasury_pct`): tesstkAcqsDspsSttus의 `trmend_rate`(1순위) 또는 `trmend_qy`/총발행주식수(2순위)
- 우호지분(`friendly_pct`): largest + related + treasury + esop
- 의결권 기준(`voting_friendly_pct`): friendly − treasury

## API 제약
- **일 10,000건** (모든 수집 스크립트가 공유하는 카운터 `data/raw/.api_daily_counter.json`)
- 요청 간 **0.5초 sleep**
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
src/ (스크립트), data/raw/, data/processed/, data/output/, diagnostics/ (진단 리포트)

## 코딩 규칙
snake_case, 타입 힌트, logging 모듈, 각 파일 독립 실행 가능

---

## 파이프라인 실행 순서 (자동 체인)

```
Step 1  (01_get_corp_list.py)      — listed_corps.csv 수집 (1회성)
Step 1b (01b_get_listing_dates.py) — 상장일 수집 (현재 미통합, H1 필요 시)
Step 2  (02_collect_ownership.py)  — hyslrSttus, 일일 스케줄 UTC 00:30
Step 3  (03_collect_treasury.py)   — tesstkAcqsDspsSttus + stockTotqySttus, 일일 스케줄 UTC 01:00
Step 4  (04_collect_minority.py)   — mrhlSttus, 일일 스케줄 UTC 02:00
Step 5  (05_clean_merge.py)        — 정제·병합 → ownership_panel.csv (auto-trigger)
Step 6  (06_analyze.py)            — 통계분석 (auto-trigger)
Step 7  (07_visualize.py)          — 시각화 + 결과 커밋 (수동 실행)
```

**자동 체인:** Step 2 완료 → Step 3 → Step 4 → Step 5 → Step 6 (각 스텝이 완료 시 다음 단계 `gh workflow run`으로 트리거).

---

## 수집 운영 지침

### 일일 API 예산 관리
- 단일 한도: **10,000건/일** (DART 정책)
- 공유 카운터: `data/raw/.api_daily_counter.json` (모든 스크립트가 같은 카운터 사용)
- 날짜 변경 시 자동 리셋 (`utils.load_daily_counter`)
- `is_daily_limit_reached()` 체크로 한도 도달 시 `break` — 체크포인트만 저장하고 종료

### 카나리아 검증 (전체 수집 전 필수)
`src/00_canary_validation.py` 실행 → 3개 기업(삼성전자·카카오·셀트리온) 2023년 데이터로 필드 존재·비공란 비율 확인. **모두 PASS된 후에만 전체 수집.** 스키마 변경(필드 추가/제거) 시 반드시 재실행.

> ⚠️ **알려진 카나리아 오류:** `00_canary_validation.py` L158–159의 `trmend_rate` 판정이 잘못 설정되어 있음 (있으면 ❌로 처리). DART는 실제로 `trmend_rate`를 제공하므로, 해당 로직을 ✅로 수정 후 재검증해야 함.

### 재수집 프로토콜 (force_reset)
Step 2/3/4 YML의 `workflow_dispatch` 입력으로 `force_reset: true` 체크박스 제공.
- **자동 동작:** 기존 아티팩트를 `step{N}-*-data-backup-{run_id}` 이름으로 30일간 보존 → 체크포인트 빈 상태 초기화 → CSV 삭제 → 전체 재수집 시작
- **사용 조건:** 스키마 변경(FIELDNAMES에 필드 추가), 데이터 품질 이슈 확인 시
- **주의:** 일반 재개 실행에서는 절대 체크하지 말 것 (완료된 수집이 모두 날아감)

### 아티팩트 보존
- 수집 아티팩트: 90일 (정상 실행)
- 백업 아티팩트: 30일 (force_reset 실행 시 자동 생성)
- 아티팩트명 예시: `step3-treasury-data` (정상) / `step3-treasury-data-backup-{run_id}` (백업)

---

## 현재 수집 상태 (2026-04-21 기준)

| Step | 상태 | 체크포인트 | 비고 |
|------|------|-----------|------|
| Step 1 | ✅ 완료 | 2,661개 | listed_corps.csv |
| Step 2 | ✅ 완료 | 29,271/29,271 | ownership_raw.csv 정상 |
| Step 3 | 🔄 재수집 중 | 0/29,271 × 2 | `trmend_rate` 추가 후 force_reset (2026-04-21 시작) |
| Step 4 | ✅ 완료 | 29,271/29,271 | minority_raw.csv 정상 |
| Step 5~7 | ⏳ 대기 | — | Step 3 완료 후 자동 체인 |

### Step 3 재수집 타임라인
- 총 호출 수: 29,271 × 2 endpoints = **58,542건**
- 일일 예산: 10,000건 (03 + 03b 공유)
- 예상 소요: **6일** (2026-04-27 완료 예정)

**예상 완료 흐름:**
```
04/21 (D+0)  수동 force_reset=true → ~9,500건
04/22 (D+1)  schedule 01:00 UTC → 누적 19,500건
04/23 (D+2)  → 29,500건 (03 endpoint 완료, 03b 시작)
04/24 (D+3)  → 39,500건
04/25 (D+4)  → 49,500건
04/26 (D+5)  → 58,542건 (03b 완료)
04/26-27     auto-chain: Step 4(skip) → Step 5 → Step 6 (약 20분)
04/27+       수동: Step 7 (시각화)
```

---

## 가설별 데이터 요구사항 (H1~H5)

| 가설 | 필요 데이터 | 현재 상태 | 추가 수집 호출 |
|------|-----------|----------|------------|
| **H4** (클러스터 지속성) | `largest_pct, related_pct, treasury_pct, friendly_pct` 시계열 | ✅ Step 3 완료 후 충분 | **0건** |
| **H1** (2014 상장 × 지분율) | + 상장일, 재무지표 | ❌ 미수집 | ~32,000건 |
| **H5** (재벌 × 개혁) | + 재벌명단, 재무지표 | ❌ 미수집 + 수작업 | ~29,000건 |
| **H2** (인적분할 DiD) | + 인적분할 이벤트 | ❌ 미수집 | ~500건 |
| **H3** (우호지분 × Tobin Q) | + 시가총액(KRX), 재무지표 | ❌ 미수집 | ~29,000 (DART) + KRX 병렬 |

> **H4 우선 원칙:** Step 3 완료 즉시(4/27) 현재 데이터로 검정 가능 — 추가 API 호출 없음.

---

## API 토큰 제약 하의 추가 개발 로드맵

일일 10,000건 한도를 고려한 **순차 수집 계획** (Step 3 완료 이후):

### Phase A — H4 분석 (API 호출 불필요)
- **시점:** 2026-04-27
- **작업:** `06_analyze.py`에 PCA + GMM 클러스터링 추가, `07_visualize.py`에 클러스터 분포 차트 추가
- **산출:** 클러스터 레이블 + Markov 전이행렬

### Phase B — 재무데이터 수집 (H1·H5 공통 통제변수)
- **시점:** 2026-04-28 ~ 05-01 (3~4일)
- **호출 수:** 29,271건 (`fnlttSinglAcntAll` 또는 `fnlttSinglAcnt`)
- **수집 필드:** 자산총계, 부채총계, 영업이익, 매출액
- **구현:** `src/08_collect_financial.py` 신규 + `step8-financial.yml` 신규

### Phase C — 상장일 보완 (H1 IV)
- **시점:** 2026-05-02 (<1일)
- **호출 수:** 2,661건 (`company.json`)
- **수집 필드:** `est_dt`(설립일), `induty_code`(업종), `acc_mt`(결산월)
- **KRX 상장일:** `01b_get_listing_dates.py`를 YML 파이프라인에 통합 (KRX는 DART 한도 무관)

### Phase D — 인적분할 이벤트 (H2 처리집단)
- **시점:** 2026-05-03 (1일)
- **호출 수:** ~500건 (`majorReport` 검색, 인적분할 보고서만)
- **구현:** 신규 스크립트, 결과는 `spin_off_events.csv`

### Phase E — 시가총액 & 재벌 명단 (H3, H5)
- **시점:** 2026-05-04 이후 (DART API 불필요, 병렬 진행)
- KRX 일별 시가총액 수집 (H3 Tobin Q용) — KRX KIND 또는 PyKRX
- 공정위 기업집단포털 연도별 재벌 명단 수작업 정리 (H5)

### 총 소요 요약
- Step 3 완료: 4/27
- 추가 DART 호출: ~32,432건 → 4일
- **전체 분석 가능 시점: 2026-05-05 전후 (2주)**

---

## 우선순위 및 권고

1. **Step 3 재수집 완료 대기** (4/21~4/27) — 이미 시작됨, 현재 상태 유지
2. **카나리아 L158–159 수정** — Step 3 수집 중 짧은 코드 수정으로 처리 가능
3. **H4 분석 즉시 진행** — 4/27 이후 추가 API 없이 바로 시작
4. **재무데이터 수집 파이프라인 구축** (`step8-financial.yml`) — Step 3 완료 후 바로 연결
5. **연구 가설 범위 재조정 협의 필요** — H3(Tobin Q)는 KRX 데이터 수집 비용 크므로 research leader와 제외 여부 논의 권장

---

## 테스트 데이터 품질 원칙
- `tests/fixtures/*.csv` 는 반드시 실제 DART API 응답 스냅샷 기반으로 작성
- 코드 내부 컬럼명에 맞춘 수작업 가상 데이터 금지 (필드명 오류를 숨김)
- 카나리아 검증 통과 후 첫 응답을 픽스처로 저장하는 워크플로 권장
