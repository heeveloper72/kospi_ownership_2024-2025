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

## 외부 크리덴셜 요건 (신규 의존성 추가 시 여기에 먼저 문서화)

| 서비스 | 환경변수 | 용도 | 가입 URL | GitHub Secret 이름 |
|--------|---------|------|---------|-------------------|
| DART OpenAPI | `DART_API_KEY` | Step 2~4, 8 수집 | https://opendart.fss.or.kr | `DART_API_KEY` |
| KRX OpenAPI | `KRX_AUTH_KEY` | Step 9 시가총액 | https://openapi.krx.co.kr (무료, 이메일 1일 승인) | `KRX_AUTH_KEY` |
> KRX API 실제 호출 host: `data-dbg.krx.co.kr/svc/apis/` ("dbg"는 debug 아닌 내부 네이밍 — 프로덕션).
> **인증**: `AUTH_KEY`를 HTTP **헤더**로 전달 (URL 쿼리 파라미터 아님).
> **필수 사전조치**: 키 발급과 별도로 마이페이지 > API 서비스 신청에서 **주식(sto) 카테고리 이용신청 승인** 필요 (최대 1영업일).

> **개발 원칙**: 새 외부 API/라이브러리 도입 시 크리덴셜·레이트리밋·인증방식을 이 표에 먼저 추가하고, `.env.example`에도 항목 추가 후 코드 작성.

## API 필드 매핑 검증표 (API 원본 → 우리 컬럼명)

### Step 2: DART `hyslrSttus` → `ownership_raw.csv` ✅ 검증완료
| DART API 필드 | 우리 컬럼명 | 설명 |
|---|---|---|
| `nm` | `nm` | 주주명 |
| `relate` | `relate` | 관계(본인/특수관계인 등) |
| `trmend_posesn_stock_co` | `stock_cnt` | 기말소유주식수 |
| `trmend_posesn_stock_qota_rt` | `stock_rate` | 기말소유지분율(%) |

### Step 3: DART `tesstkAcqsDspsSttus` → `treasury_raw.csv` ✅ 검증완료
| DART API 필드 | 우리 컬럼명 | 설명 |
|---|---|---|
| `stock_knd` | `stock_knd` | 주식종류 |
| `acqs_mth1` / `acqs_mth2` / `acqs_mth3` | 동일 | 취득방법 |
| `bsis_qy` | `bsis_qy` | 기초수량 |
| `change_qy` | `change_qy` | 변동수량 |
| `trmend_qy` | `trmend_qy` | 기말수량 |
| `trmend_rate` | `trmend_rate` | 기말소유비율(%) — treasury_pct 1순위 |

### Step 4: DART `mrhlSttus` → `minority_raw.csv` ✅ 검증완료
| DART API 필드 | 우리 컬럼명 | 설명 |
|---|---|---|
| `se` | `se` | 구분(소액주주 등) |
| `shrholdr_co` | `shrholdr_co` | 주주수 |
| `shrholdr_tot_co` | `shrholdr_tot_co` | 전체주주수 |
| `shrholdr_rate` | `shrholdr_rate` | 주주비율(%) |
| `hold_stock_co` | `hold_stock_co` | 보유주식수 |
| `stock_tot_co` | `stock_tot_co` | 총발행주식수 |
| `hold_stock_rate` | `hold_stock_rate` | 소유지분율(%) |

### Step 8: DART `fnlttSinglAcntAll` → `financial_raw.csv` ✅ 검증완료
| DART API 필드 | 우리 컬럼명 | 매핑 로직 |
|---|---|---|
| `account_nm == "자산총계"` | `total_assets` | account_nm 텍스트 매칭 |
| `account_nm == "부채총계"` | `total_liabilities` | account_nm 텍스트 매칭 |
| `account_nm == "자본총계"` | `total_equity` | account_nm 텍스트 매칭 |
| `account_nm ∈ {매출액, 수익(매출액), 영업수익, 매출}` | `revenue` | account_nm 텍스트 매칭 |
| `account_nm ∈ {영업이익, 영업이익(손실)}` | `operating_income` | account_nm 텍스트 매칭 |
| `thstrm_amount` | 위 5개 컬럼 공통 값 소스 | 당기 금액(원, 문자열) |
| `fs_div` | `fs_div_used` | CFS/OFS 구분 기록 |

### Step 9: KRX OpenAPI → `market_cap_raw.csv` ✅ 필드명 확인 완료
| KRX API 응답 필드 | 우리 컬럼명 | 설명 |
|---|---|---|
| `ISU_SRT_CD` | `stock_code` | 6자리 단축 종목코드 |
| `MKTCAP` | `market_cap` | 시가총액(원, 콤마 제거 후 int) |
| `LIST_SHRS` | `shares` | 상장주식수 |
| (파라미터 `basDd`) | `snapshot_date` | 연말 마지막 거래일 YYYYMMDD |
| KOSPI: `sto/stk_bydd_trd` / KOSDAQ: `sto/ksq_bydd_trd` | `market` | 시장 구분 |
> 응답 JSON 최상위 키: `OutBlock_1` (list). 일일 한도: 10,000건 (DART 카운터와 **독립**).

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

## 현재 수집 상태 (2026-04-24 기준)

| Step | 상태 | 체크포인트 | 비고 |
|------|------|-----------|------|
| Step 1 | ✅ 완료 | 2,661개 | listed_corps.csv |
| Step 1b | ✅ 완료 | — | KRX KIND 상장일 수집 완료 |
| Step 1c | 🔄 진행 중 | — | Step 8 완료 후 자동 트리거됨, <1일 소요 |
| Step 2 | ✅ 완료 | 29,271/29,271 | ownership_raw.csv 정상 |
| Step 3 | ✅ 완료 | 58,542/58,542 | treasury_raw.csv + total_shares_raw.csv |
| Step 4 | ✅ 완료 | — | minority_raw.csv |
| Step 5~7 | ✅ 완료 | — | ownership_panel.csv + 분석 + 차트 |
| Step 8 | ✅ 완료 | 29,271/29,271 | financial_raw.csv |
| Step 9 | ✅ 완료 | — | market_cap_raw.csv (KRX 2015~2025) |
| Step 10 | ⏳ 준비 | — | Tobin Q 계산, 수동 트리거 (`step10-tobin-q.yml`) |

---

## 가설별 데이터 요구사항 (H1~H5)

| 가설 | 필요 데이터 | 현재 상태 | 추가 수집 호출 |
|------|-----------|----------|------------|
| **H4** (클러스터 지속성) | `largest_pct, related_pct, treasury_pct, friendly_pct` 시계열 | ✅ Step 6 진행 중 | **0건** |
| **H3** (우호지분 × Tobin Q) | + 시가총액(KRX) ✅ + 재무지표 ✅ | ⏳ Step 10 준비 (수동 트리거 필요) | **0건** |
| **H1** (2014 상장 × 지분율) | + 상장일 ✅ + 재무지표 ✅ + 기업상세(1c) | 🔄 Step 1c 완료 후 분석 가능 | **0건** |
| **H5** (재벌 × 개혁) | + 재무지표 ✅ + 재벌명단(수작업) | ❌ 재벌 명단 수집 필요 | **0건 (수작업)** |
| **H2** (인적분할 DiD) | + 인적분할 이벤트 | ❌ 미수집 | ~500건 |

> **현재 데이터 완비 상태:** Step 1~9 완료, API 추가 호출 없이 H3·H4 즉시 분석 가능.

---

## API 토큰 제약 하의 추가 개발 로드맵

일일 10,000건 한도를 고려한 **순차 수집 계획** (Step 3 완료 이후):

### Phase A — H4 분석 ✅ 구현 완료, 실행 중
- **상태:** `step6-analyze.yml` 진행 중
- **산출:** `cluster_labels_by_year.csv`, `bic_aic_scores.csv`, `clustering_ari_matrix.csv`

### Phase B — 재무데이터 수집 ✅ 완료
- **결과:** `financial_raw.csv` (29,271 기업-연도, CFS/OFS)
- **구현:** `src/08_collect_financial.py` + `step8-financial.yml`

### Phase C — 기업 상세정보 수집 🔄 진행 중
- **상태:** Step 8 완료 후 자동 트리거, 2,661건 < 1일
- **구현:** `src/01c_get_corp_details.py` + `step1c-corp-details.yml`
- **KRX 상장일:** ✅ `01b_get_listing_dates.py` 완료

### Phase E — Tobin Q 계산 ⏳ 준비 완료 (수동 트리거 필요)
- **상태:** `src/10_compute_tobin_q.py` + `step10-tobin-q.yml` 구현 완료
- **입력:** `financial_raw.csv` ✅ + `market_cap_raw.csv` ✅
- **출력:** `financial_panel.csv` + `ownership_financial_panel.csv`
- **변수:** `tobin_q`, `leverage`, `size`, `roa`, `roe`, `market_to_book`
- **실행:** Actions 탭 → `step10-tobin-q.yml` 수동 트리거

### Phase D — 인적분할 이벤트 (H2 처리집단)
- **시점:** 2026-05-02 (1일)
- **호출 수:** ~500건 (`majorReport` 검색, 인적분할 보고서만)
- **구현:** 미구현 — 신규 스크립트 + `spin_off_events.csv`

### 총 소요 요약 (2026-04-28 기준)
- **추가 API 호출 없이 분석 가능:** H3 (Tobin Q), H4 (클러스터링), H1 (Step 1c 완료 후)
- **잔여 작업:** Phase D (인적분할 ~500건), H5 재벌 명단 (수작업)

---

## 우선순위 및 권고

1. ~~Step 3 재수집~~ ✅ 완료 (2026-04-26)
2. ~~카나리아 L158–159 수정~~ ✅ 완료 (2026-04-22)
3. ~~Step 1b (KRX 상장일)~~ ✅ 완료
4. ~~Step 8/1c 자동 체인 완성~~ ✅ 완료 (2026-04-24)
5. ~~Step 8 (재무데이터)~~ ✅ 완료 (2026-04-27)
6. ~~Step 9 (KRX 시총)~~ ✅ 완료
7. **Step 10 (Tobin Q 계산)** — `step10-tobin-q.yml` 수동 트리거 (즉시 가능)
8. **H4 분석** — `step6-analyze.yml` 진행 중, 완료 후 결과 확인
9. **Step 1c 완료 확인** — 자동 트리거됨, Actions 탭 확인
10. **Phase D (인적분할 H2)** — 미구현, ~05/02 착수 예정
11. **H5 재벌 명단** — 수작업, 공정위 기업집단 포털에서 수집 필요

---

## 일일 브리핑 지침 (Claude Code 운영 원칙)

**매일 하루의 첫 메시지를 받을 때마다 다음을 먼저 보고한다:**

1. **수집 현황**: Step 3 진행도(예상 누적 건수 / 58,542), 완료 예정일
2. **금일 to-do 목록**: 우선순위 순, 블로커 명시
3. **일정 단축 가능 여지**: 있으면 구체적 제안 포함
4. **대기 중인 결정 사항**: 리더 결정이 필요한 항목

---

## 의사결정 기록 (2026-04-22)

### 연구 설계 지침(독창성 평가 반영) 반영 결정

| 항목 | 결정 내용 |
|---|---|
| `friendly_pct` 공식 | **현행 유지** (largest + related + esop + treasury). `foundation_pct` 신규 컬럼 추가하되 합계 불변. KCMI 비교 컬럼 나란히 제공 |
| LCA 구현 방법 | **옵션 B: `stepmix` 패키지** 사용 (diagonal covariance, local independence 가정) |
| `esop_pct` 처리 | `related_pct`에서 분리 유지 + `friendly_pct`에 포함 유지 (KCMI 24-20 호환) |
| `foundation_pct` | ownership_raw.csv의 `relate="공익법인"` 행에서 추출 (추가 API 호출 0건) |
| H4 클러스터링 | GMM(메인) + Ward + LCA(stepmix) 3종 병행, ARI 교차 검증 행렬 |
| H4 전처리 | 소유지분율 **로짓 변환** (0.5/99.5% 윈저라이징 후) → StandardScaler |
| K 범위 | **3~8** (기존 2~6에서 확장) |
| Markov 시기 분할 | 전체 / 2015–2023 / 2024 (자사주 규제 전후) |
| Functional Clustering + HMM | Phase B (4/28 이후, `scikit-fda` + `hmmlearn`) |
| RESEARCH_PLAN.md §10 독창성 | "최초/가장 긴 시계열" 주장 삭제 → KCMI 24-20 확장·운용화로 재포지셔닝 |
| RESEARCH_PLAN.md §2.1 | `trmend_rate` 없음 주장 ❌ 삭제 (DART 실제 제공 확인, 수집 완료) |

---

## 테스트 데이터 품질 원칙
- `tests/fixtures/*.csv` 는 반드시 실제 DART API 응답 스냅샷 기반으로 작성
- 코드 내부 컬럼명에 맞춘 수작업 가상 데이터 금지 (필드명 오류를 숨김)
- 카나리아 검증 통과 후 첫 응답을 픽스처로 저장하는 워크플로 권장

---

## CI 감사 기록 (2026-04-24)

### test.yml 지속 실패 — 근본 원인 분석 및 수정 완료

| 항목 | 내용 |
|---|---|
| **실패 증상** | `ModuleNotFoundError: No module named 'sklearn'` (TestAnalyze 2건) |
| **근본 원인** | `pykrx 1.2.4`가 `numpy<2.0` 제약 강제 → pip이 numpy 2.x→1.26.4로 다운그레이드 → scikit-learn 1.8.0 import 실패 |
| **2차 원인** | pykrx는 Step 9 재작성(KRX OpenAPI 직접 호출) 이후 코드에서 미사용 — requirements.txt에만 잔존 |
| **추가 버그** | 스모크 테스트 `if: ${{ secrets.X != '' }}` — GitHub Actions에서 secrets를 표현식에 직접 사용 불가 (보안 정책) |
| **수정** | ① requirements.txt에서 `pykrx` 제거 ② `pip install --upgrade pip` 선행 추가 ③ 스모크 테스트 조건을 `env.DART_API_KEY != ''` 패턴으로 수정 |
| **검증** | 로컬 `pytest tests/ -v`: **25/25 PASSED** |

### 의존성 관리 원칙 (이번 이슈 반영)
- **신규 외부 패키지 추가 시**: 기존 패키지와 numpy/scipy 버전 호환성 반드시 확인
- **사용 중단된 패키지**: requirements.txt에서 즉시 제거 (잔존하면 버전 충돌 잠복)
- **Heavy ML 패키지** (`hmmlearn`, `scikit-fda`): pip 설치 순서 및 네이티브 컴파일 의존성 주의
- GitHub Actions secret 조건부 실행은 반드시 `env:` 블록 경유 패턴 사용

---

## CI 감사 기록 (2026-04-27) — Step 8 6h Timeout

### 증상
- step8-financial.yml: `The job has exceeded the maximum execution time of 6h0m0s` 반복

### 근본 원인 (3가지 복합)
| 원인 | 영향 |
|---|---|
| `pip install -r requirements.txt` 전체 설치 | scikit-fda/hmmlearn 네이티브 컴파일에 **5~10분 낭비** (collection 스크립트엔 불필요) |
| Step 8 = CFS+OFS 2-call 패턴 | API 응답이 느릴 때 1 task당 평균 1.2~2 calls × 1~2초 → 10,000 calls가 4~6h 소요 |
| 스크립트 내부 runtime guard 없음 | 6h 도달 시 GH Actions 강제 kill → `finally` 블록 정상 실행 보장 부족 |

### 수정 (commit f15e2f2)
1. **경량 install**: `pip install requests pandas python-dotenv tqdm` (전체 requirements 대체)
2. **MAX_RUNTIME_SEC = 5h25m**: 스크립트 내부 안전 종료 → 25분 여유로 finally + upload + auto-trigger
3. **timeout-minutes: 350**: 워크플로우 명시 (5h50m, GH 기본 6h 미만)
4. **schedule 활성화**: 매일 UTC 03:00 — 다음날 자동 재개 (수동 트리거 불필요)
5. **step1c도 동일 패턴 적용**: 동일 DART 수집 패턴 미연 방지

### 다른 워크플로우 점검 결과
- **Step 3 (treasury+total_shares)**: 1 call/task 패턴, 일일 10,000 calls = ~2.8h. 6h 여유. **수정 불필요**
- **Step 4 (minority)**: 1 call/task. 6h 여유. 수정 불필요
- **Step 5/6/7 (정제·분석·시각화)**: 분 단위 실행. timeout 무관
- **Step 9 (KRX)**: 연도별 일괄 호출 (11회 호출), 매우 빠름. timeout 무관
