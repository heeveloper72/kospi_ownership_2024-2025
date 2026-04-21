# 국내 상장사 지배구조 변동 분석 — 마스터 플랜

> 작성일: 2026-04-13  
> 상태: 확정 (감사팀·경제경영통계팀 검토 완료)

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [감사 결과: 기존 코드 실패 원인](#2-감사-결과-기존-코드-실패-원인)
3. [코드 수정 사항](#3-코드-수정-사항)
4. [검증 우선(Validation-First) 수집 방식](#4-검증-우선validation-first-수집-방식)
5. [데이터 수집 계획](#5-데이터-수집-계획)
6. [연구 가설](#6-연구-가설)
7. [지배구조 클러스터링 방법론](#7-지배구조-클러스터링-방법론)
8. [샘플링 및 검증 계획](#8-샘플링-및-검증-계획)
9. [전체 실행 순서](#9-전체-실행-순서)
10. [독창성 및 학술 기여](#10-독창성-및-학술-기여)

---

## 1. 프로젝트 개요

### 1.1 분석 목표

KOSPI·KOSDAQ 상장사(약 2,400개)의 소유구조(최대주주 지분율, 우호지분, 자사주 등)를
2015~2025년 패널로 구축하고, 다음 두 규제 이벤트를 자연실험으로 활용해 지배구조
변동 원인을 규명한다.

| 규제 이벤트 | 시행일 | 내용 |
|---|---|---|
| 공정거래법 개정 | 2014.07 | 신규 순환출자 전면 금지 |
| 자본시장법 개정 | 2024.12.31 | 인적분할 시 자사주 신주배정 금지 |

### 1.2 벤치마크 (자본시장연구원, 2024 — 2023년말 기준)

| 구분 | 최대주주 지분율 | 우호지분 |
|---|---|---|
| 전체 | 29.21% | 43.07% |
| KOSPI | — | 49.34% |
| KOSDAQ | — | 39.93% |

### 1.3 기술 스택

- Python 3.10+ / requests / pandas / scikit-learn / matplotlib, plotly
- DART OpenAPI (일 10,000건 제한), KRX KIND API
- GitHub Actions (스케줄 자동수집), 체크포인트/재개 패턴

---

## 2. 감사 결과: 기존 코드 실패 원인

### 2.1 핵심 버그 — DART API 응답 필드명 불일치

Step 2~5 결과(최대주주 0%, 우호지분 0%)의 근본 원인은
`src/02_collect_ownership.py`에서 존재하지 않는 필드명을 사용한 것이다.

#### hyslrSttus (최대주주현황) 필드명 대조

| 항목 | 코드가 사용한 키 | DART 실제 응답 키 | 상태 |
|---|---|---|---|
| 성명 | `nm` | `nm` | ✅ 정상 |
| 관계 | `relate` | `relate` | ✅ 정상 |
| 기말 주식수 | `stock_cnt` | `trmend_posesn_stock_co` | ❌ **오류** |
| 기말 지분율 | `stock_rate` | `trmend_posesn_stock_qota_rt` | ❌ **오류** |
| 기초 주식수 | — | `bsis_posesn_stock_co` | (미수집) |
| 기초 지분율 | — | `bsis_posesn_stock_qota_rt` | (미수집) |

**오류 전파 경로:**
```
item.get("stock_rate", "")  →  ""  →  parse_rate("") = NaN
→  pandas .sum(all-NaN) = 0.0  →  largest_pct = 0  →  friendly_pct = 0
```

#### tesstkAcqsDspsSttus (자기주식취득처분현황) 필드명 대조

| 항목 | 코드가 사용한 키 | DART 실제 응답 키 | 상태 |
|---|---|---|---|
| 주식종류 | `stock_knd` | `stock_knd` | ✅ 정상 |
| 기초수량 | `bsis_qy` | `bsis_qy` | ✅ 정상 |
| 기말수량 | `trmend_qy` | `trmend_qy` | ✅ 정상 |
| **기말비율** | `trmend_rate` | `trmend_rate` | ✅ **정상 — DART 실제 제공 확인** |

> **[2026-04-21 정정]** 기존 이 문서는 `trmend_rate`가 API에 없다고 기술했으나,
> DART OpenAPI 공식 가이드 및 실제 수집 결과 `trmend_rate`(기말소유비율)은 정상 제공됨.
> `03_collect_treasury.py`와 카나리아 스크립트는 이미 수정 완료.
> 1순위: `trmend_rate` (DART 직접 계산값), 2순위: `trmend_qy` / `total_shares`.

#### mrhlSttus (소액주주현황) 필드명 대조

| 항목 | 코드가 사용한 키 | DART 실제 응답 키 | 상태 |
|---|---|---|---|
| 구분 | `se` | `se` | ✅ 정상 |
| 주주수 | `shrholdr_co` | `shrholdr_co` | ✅ 정상 |
| 보유비율 | `hold_stock_rate` | `hold_stock_rate` | ✅ 정상 |

**소액주주 데이터(Step 4)는 필드명이 모두 정확하다 — 재수집 불필요.**

### 2.2 테스트가 버그를 잡지 못한 이유

`tests/fixtures/ownership_raw.csv`는 실제 DART API를 호출해서 만든 것이 아니라
코드 내부 컬럼명(`stock_rate`, `stock_cnt`)에 맞춰 수작업으로 작성한 가상 데이터다.
따라서 테스트는 통과해도 실 API 응답과 전혀 다른 데이터로 검증한 것이었다.

### 2.3 기존 데이터 처리 방향

| 파일 | 상태 | 처리 |
|---|---|---|
| `listed_corps.csv` | 정상 | ✅ 유지 |
| `ownership_raw.csv` | 지분율 전부 공란 | ❌ 삭제 후 재수집 |
| `ownership_checkpoint.json` | "완료" 표시가 모두 허위 | ❌ 초기화 후 재수집 |
| `treasury_raw.csv` | `trmend_rate` 공란, 비율 계산 방식 변경 필요 | ❌ 삭제 후 재수집 |
| `treasury_checkpoint.json` | 동일 | ❌ 초기화 |
| `minority_raw.csv` | 필드명 정상 | ✅ 유지 |
| `minority_checkpoint.json` | 유효 | ✅ 유지 |

---

## 3. 코드 수정 사항

### 3.1 `src/02_collect_ownership.py` — 필드명 수정

```python
# 수정 전 (오류)
"stock_cnt":  item.get("stock_cnt", ""),
"stock_rate": item.get("stock_rate", ""),

# 수정 후 (정확한 DART 필드명)
"stock_cnt":  item.get("trmend_posesn_stock_co", ""),
"stock_rate": item.get("trmend_posesn_stock_qota_rt", ""),
```

CSV 컬럼명(`stock_cnt`, `stock_rate`)은 내부 별칭으로 유지해도 무방하다.
오직 `.get()` 키만 변경하면 된다.

### 3.2 `src/03_collect_treasury.py` — 비율 수집 전략 (2026-04-21 정정)

> **[정정]** 기존 계획(trmend_rate 제거, 수량 기반 계산)에서 변경됨.

DART `trmend_rate`가 실제 제공되므로 1순위로 사용한다.

```python
# 현행 수집 필드 (tesstkAcqsDspsSttus 응답) — 모두 정상 수집 중
"stock_knd":    item.get("stock_knd", ""),
"acqs_mth1":    item.get("acqs_mth1", ""),
"acqs_mth2":    item.get("acqs_mth2", ""),
"acqs_mth3":    item.get("acqs_mth3", ""),
"bsis_qy":      item.get("bsis_qy", ""),
"trmend_qy":    item.get("trmend_qy", ""),
"trmend_rate":  item.get("trmend_rate", ""),  # ✅ 1순위 — DART 직접 계산값

# Step 5(clean_merge)에서:
# treasury_pct 1순위: trmend_rate
# treasury_pct 2순위: trmend_qy / total_issued_shares (stockTotqySttus)
```

`03b_collect_total_shares.py`: 2순위 폴백용으로 유지.

### 3.3 테스트 픽스처 교체

`tests/fixtures/ownership_raw.csv` — `stock_rate` 컬럼에 실제 값이 들어가도록 수정.  
또는 `stock_rate` 컬럼 값을 실 DART 응답 기반 샘플로 교체.

---

## 4. 검증 우선(Validation-First) 수집 방식

**전체 26,400건 수집 전에 반드시 아래 3단계를 통과해야 한다.**

### 단계 1 — 카나리아 수집 (3개사 × 1년 = ~3건)

```python
CANARY_CORPS = [
    ("00126380", "삼성전자",  "KOSPI"),   # 대형 KOSPI
    ("00401731", "카카오",    "KOSDAQ"),  # 대형 KOSDAQ
    ("00131577", "셀트리온",  "KOSDAQ"),  # 중형 KOSDAQ
]
CANARY_YEAR = "2023"
```

응답 1건의 raw JSON을 통째로 로깅:
```python
logger.info(f"RAW RESPONSE: {json.dumps(data, ensure_ascii=False)}")
```

### 단계 2 — 필드 존재 여부 확인

```python
REQUIRED_FIELDS = {
    "hyslrSttus":            ["nm", "relate", "trmend_posesn_stock_co",
                               "trmend_posesn_stock_qota_rt"],
    "tesstkAcqsDspsSttus":   ["stock_knd", "trmend_qy"],
    "mrhlSttus":             ["se", "hold_stock_rate"],
}
for item in data["list"]:
    missing = [f for f in REQUIRED_FIELDS[endpoint] if f not in item]
    if missing:
        logger.error(f"필드 누락: {missing}. 전체 키: {sorted(item.keys())}")
        sys.exit(1)
```

### 단계 3 — 비율 필드 비-공란 비율 게이트

```python
rates = [item.get("trmend_posesn_stock_qota_rt", "") for item in data["list"]]
non_empty = sum(1 for r in rates if r not in ("", "-", None))
if non_empty / len(rates) < 0.8:
    logger.error(f"비율 필드 비-공란 비율 {non_empty/len(rates):.1%} < 80%. 수집 중단.")
    sys.exit(1)
```

**3단계 모두 통과한 후에만 전체 수집 시작.**

---

## 5. 데이터 수집 계획

### 5.1 기존 수집 항목 (수정 후 재수집)

| Step | 스크립트 | API | 수집 내용 | 연도당 호출 |
|---|---|---|---|---|
| 2 | `02_collect_ownership.py` | `hyslrSttus` | 최대주주·특수관계인·우리사주 기말 지분율 | ~2,400 |
| 3 | `03_collect_treasury.py` | `tesstkAcqsDspsSttus` | 자사주 기말 수량 | ~2,400 |
| 3b | `03b_collect_total_shares.py` | `stockTotqySttus` | 총발행주식수 (자사주 비율 계산용) | ~2,400 |
| 4 | `04_collect_minority.py` | `mrhlSttus` | 소액주주 지분율 (**재수집 불필요**) | ~2,400 |

기준연도: 2015~2025 (11개년), 사업보고서 `reprt_code=11011`

### 5.2 신규 수집 항목

#### A. 기업 기본정보 (`company.json` — Step 1 보완)

| 필드 | 항목 |
|---|---|
| `est_dt` | 설립일 (형식: `YYYYMMDD`) |
| `induty_code` | 업종코드 (산업 FE용) |
| `acc_mt` | 결산월 |

#### B. 상장일 (KRX KIND — DART에 없음)

DART `company.json`에는 `isu_dt`(상장일)가 없다.  
출처: KRX KIND `corpList.do?method=download` 또는 PyKRX.  
H1의 `post2014` 더미 생성에 필수.

#### C. 재무제표 (`fnlttSinglAcntAll`)

필터: `sj_div="IS"`, `account_nm IN ("매출액","영업이익","자산총계","부채총계")`  
비XBRL 소형사: `fnlttSinglAcnt` fallback.

#### D. 임직원수 (`empSttus`)

필드: `sm` (합계), `fo_bbm="합계"` 행 필터

#### E. 인적분할 이벤트 (DART 주요사항보고서)

H2 DiD 처리집단 식별용. 보고서 유형 `majorReport` 중 인적분할 검색.

#### F. 공정위 대기업집단 지정 (수동 크로스레퍼런스)

공정거래위원회 기업집단포털 연도별 지정 목록 → H5 재벌 더미 (시간변동형).

---

## 6. 연구 가설

### H1 — 2014년 이후 상장사, 최대주주 지분율 낮음

| | |
|---|---|
| **DV** | `largest_pct` (상장 후 3년 평균) |
| **IV** | `post2014` (상장연도 ≥ 2015이면 1) |
| **통제** | log(자산), ROA, 레버리지, 기업연령, 시장더미, 업종 FE, 상장연도 FE |
| **검정** | OLS + PSM t-검정 |
| **예상** | β(post2014) < 0, 3~6%p 낮을 것 |

### H2 — 2024년 12월 이후 인적분할 기업, 자사주 비율 감소

| | |
|---|---|
| **DV** | `treasury_pct` (연말) |
| **IV** | `post_reform × spin_off_firm` (DiD) |
| **통제** | log(자산), ROA, 레버리지, 시장더미, 업종 FE, 연도 FE |
| **검정** | DiD |
| **예상** | DiD 계수 < 0 (1~3%p 감소); 2025년 첫 관찰 → 예비적 결과 |

### H3 — 우호지분 높을수록 소수주주 가치 할인

| | |
|---|---|
| **DV** | Tobin's Q |
| **IV** | `friendly_pct`, `friendly_pct²` |
| **통제** | log(자산), 자산성장률, 레버리지, R&D, 배당성향, 업종·연도 FE |
| **검정** | 기업·연도 이중 FE 패널 OLS; 도구변수: 지연값, 업종-연도 중위값 |
| **예상** | 역U형 또는 단조감소 (우호지분 >50% 구간에서 Q 하락) |

### H4 — 지배구조 클러스터 소속의 시간적 지속성

| | |
|---|---|
| **DV** | t+1년 클러스터 소속 |
| **IV** | t년 클러스터 소속 |
| **검정** | Markov 전이행렬, χ² 검정 |
| **예상** | 연간 유지율 >75%; KOSPI > KOSDAQ |

### H5 — 재벌 계열사, 개혁 이후에도 우호지분 유지

| | |
|---|---|
| **DV** | `friendly_pct` |
| **IV** | `chaebol × post2014`, `chaebol × post2024` |
| **통제** | log(그룹매출), 계열사수, 레버리지, ROA, 연도 FE |
| **검정** | 3중 DiD |
| **예상** | 비재벌 β(post2014) < 0; 재벌 β ≈ 0 (규제 효과 비대칭) |

---

## 7. 지배구조 클러스터링 방법론

### 7.1 클러스터링 특징 변수 (시계열 요약 — 2015~2025)

| 변수 | 계산 | 의미 |
|---|---|---|
| `mean_largest_pct` | largest_pct 시계열 평균 | 지배주주 직접 보유 수준 |
| `mean_related_pct` | related_pct 시계열 평균 | 가족 네트워크 의존도 |
| `mean_treasury_pct` | treasury_pct 시계열 평균 | 자사주 활용 정도 |
| `mean_friendly_pct` | friendly_pct 시계열 평균 | 전체 지배력 수준 |
| `trend_largest_pct` | largest_pct ~ year OLS 기울기 | 지분 집중·분산 추세 |
| `trend_friendly_pct` | friendly_pct ~ year OLS 기울기 | 우호지분 추세 |
| `vol_largest_pct` | largest_pct 표준편차 | 구조적 안정성 |
| `friendly_minus_largest` | mean_friendly - mean_largest | 특수관계인 의존도 |
| `treasury_share` | mean_treasury / mean_friendly | 자사주의 우호지분 기여율 |

**전처리:** 1·99 백분위수 윈저라이징 → z-score 표준화 → 결측 ≥3개 연도 시 선형보간, 미충족 시 클러스터링 제외(별도 표시)

### 7.2 차원 축소

PCA 적용 후 분산 누적 80% 이상 주성분 유지(통상 3~4개).  
UMAP(2D)은 시각화 전용 — 실제 클러스터링은 PCA 공간에서 수행.

### 7.3 알고리즘 선택

| 알고리즘 | 용도 | 비고 |
|---|---|---|
| **계층적 군집(Ward)** | k 개수 탐색 | 덴드로그램으로 자연 분기점 확인 |
| **GMM** | 메인 알고리즘 | 타원형 클러스터 허용, 소속 확률 제공 |
| **k-means** | 기준선 비교 | 결과 안정성 교차 검증(ARI > 0.7 목표) |

**최적 k 결정:** BIC 최소화 (k=3~6), 실루엣 점수 참조

### 7.4 예상 클러스터 유형 (5개 내외)

| 클러스터 | 특징 | 대표 기업 유형 |
|---|---|---|
| 창업자 직접지배 | mean_largest >40%, 특수관계인 낮음 | 중소 KOSDAQ 테크 창업사 |
| 가족연합지배 | largest 20~35%, related_pct 높음, 안정적 | 중대형 KOSPI 가족기업 |
| 대기업집단 | largest 10~25%, friendly >55%, 자사주 활용 | 삼성·SK·LG 계열사 |
| 분산소유 | largest <15%, friendly <30% | 금융사, 사후 민영화 국영기업 |
| 기관지배 | 기관·법인이 최대주주, 중간 수준 | 외국인 투자기업, PE 피투자사 |

### 7.5 클러스터 검증

- **내부:** 실루엣 점수, Davies-Bouldin 지수, BIC
- **외부:** 공정위 대기업집단 지정 교차 검증 (재벌은 하나의 클러스터에 집중되어야)
- **안정성:** 80% 무작위 부분집합 100회 반복 → ARI 평균 >0.75 목표

---

## 8. 샘플링 및 검증 계획

### 8.1 검증 대상 규모

클러스터당 20개사 × 5클러스터 = **총 100개사** (전체의 약 4.2%).

### 8.2 층화 기준 (클러스터 내)

| 층화 변수 | 방법 |
|---|---|
| 시장 (KOSPI/KOSDAQ) | 클러스터 내 비율에 비례, 최소 3개사 |
| 기업규모 사분위 | 사분위당 최소 2개사 |
| 클러스터 거리 | 중심부 50%, 경계부 50% |
| 변동성 | 고변동 기업 3~5개 포함 (클러스터 내 이상치 검증) |

**난수 시드 고정 → 재현 가능성 확보.**

### 8.3 샘플링 제외 기준 (프레임 정의)

- 포함: 비결측 연도 ≥5개, 2023년 기준 상장 유지
- 제외: 관리종목·상장폐지 예정, 순수지주회사(지배구조 규제에 의해 클러스터링 왜곡), REITs·특수목적법인

### 8.4 수동 검증 프로토콜

1. DART 사업보고서 → 주요주주현황 → API 수치와 비교 (2%p 초과 차이 시 "데이터 품질 이슈" 플래그)
2. 자사주 현황 교차 확인
3. 클러스터 배정 vs 질적 판단 비교
4. **목표:** 오배정률 <10%; >20% 시 특징 변수 재설계 후 재클러스터링

---

## 9. 전체 실행 순서

```
[Phase 0] 코드 수정 + 카나리아 검증 (1일)
  ├─ 02_collect_ownership.py 필드명 수정
  ├─ 03_collect_treasury.py trmend_rate 제거 + 03b 신규 작성
  ├─ 카나리아 3개사 수집 → raw JSON 로그 확인
  └─ 필드 존재·비공란 비율 게이트 통과 확인

[Phase 1] 기업 목록 보완 (Step 1)
  ├─ listed_corps.csv 유지
  ├─ company.json에서 est_dt, induty_code 보완 수집
  └─ KRX에서 상장일(isu_dt) 수집 → listed_corps에 merge

[Phase 2] 소유구조 재수집 (Step 2) — 약 3일
  └─ ownership_raw.csv 재수집 (체크포인트 초기화 후)

[Phase 3] 자사주 재수집 (Step 3 + 3b) — 약 3일
  ├─ treasury_raw.csv 재수집 (trmend_qy 기반)
  └─ total_shares_raw.csv 수집 (stockTotqySttus)

[Phase 4] 재무·임직원 수집 (Step 5 추가) — 약 3일
  ├─ financial_raw.csv (fnlttSinglAcntAll)
  └─ employee_raw.csv (empSttus)

[Phase 5] 정제·병합 (Step 5 수정)
  ├─ ownership_panel.csv 생성 (수정된 필드 기반)
  ├─ treasury_pct = trmend_qy / total_issued_shares
  └─ 재무·임직원 merge

[Phase 6] 클러스터링 (Step 6 신규)
  ├─ 시계열 요약 특징 생성
  ├─ PCA → GMM
  └─ 클러스터 레이블 저장

[Phase 7] 검증 샘플링 (Step 6 검증)
  ├─ 층화 샘플 100개사 추출
  └─ 수동 DART 검증 → 오배정률 확인

[Phase 8] 가설 검증 (Step 7)
  ├─ H1: PSM + OLS
  ├─ H2: DiD (인적분할 이벤트 활용)
  ├─ H3: 패널 FE + IV
  ├─ H4: Markov 전이행렬
  └─ H5: 3중 DiD

[Phase 9] 시각화·보고서 (Step 8)
  ├─ 시계열 추이 차트 (벤치마크 비교)
  ├─ 클러스터 분포 시각화 (UMAP 2D)
  └─ 가설 검증 결과 테이블
```

### API 호출 예산

| 단계 | 대상 | 연도 | 건수 | 소요 일수 |
|---|---|---|---|---|
| Step 2 (ownership) | 2,400개사 | 11개년 | 26,400 | ~3일 |
| Step 3+3b (treasury) | 2,400개사 | 11개년 | 52,800 | ~6일 |
| Step 재무 | 2,400개사 | 11개년 | 26,400 | ~3일 |
| Step 임직원 | 2,400개사 | 11개년 | 26,400 | ~3일 |
| **합계** | | | **~132,000** | **~15일** |

일 10,000건 한도 / GitHub Actions 스케줄 자동수집으로 약 2~3주 소요.

---

## 10. 독창성 및 학술 기여 (2026-04-22 재포지셔닝)

> **[중요 정정]** KCMI 이슈보고서 24-20(이성복, 2024)이 이미 전체 상장사 2,407개사 ×
> 12개년(2012–2023) 동일 변수 패널을 구축하였음. "최초/가장 긴 시계열" 주장은 사실과 다름.
> 아래 독창성 주장으로 전면 대체.

### 독창성 우선순위 (4→1 순)

1. **(최우선) 2024년 12월 자사주 규제의 전 세계 최초 실증 분석 (H2, H5)**
   - 2024-12-31 시행 → 2025 데이터로 최초 분석 가능. 예비적 결과만으로도 기여.
2. **(핵심) 전체 상장 유니버스 GMM + Markov 전이로 Bebchuk-Roe 경로의존성 최초 직접 검증 (H4)**
   - 동아시아 지배구조 경로의존성을 정량 검증한 선행연구 전무.
3. **(부차) 2014년 순환출자 금지의 IPO 코호트 설계 효과 (H1)**
4. **(기반) DART OpenAPI 기반 재현 가능 파이프라인 — KCMI 24-20 시간적 확장·운용화**

### 적절한 포지셔닝 표현

- "KCMI 24-20의 기술적(descriptive) 패널을 2024–2025년까지 확장하고"
- "DART OpenAPI 직접 수집 기반의 재현 가능한(reproducible) 파이프라인을 구축하며"
- "KCMI가 명시적으로 범위 밖으로 표시한 인과 추론(causal inference) 프레임을 제공한다"

### 논문 한계 섹션 필수 기재

- 패널 자체는 KCMI 24-20과 상당 부분 중복
- H2 사후 관찰 기간 1개년(2025) → "예비적 결과"로 명시
- H3 지배권-현금흐름 괴리 → 가치 할인 관계는 기확립된 결과

---

*문서 끝 — 다음 작업: Phase 0 코드 수정 및 카나리아 검증 실행*

---
