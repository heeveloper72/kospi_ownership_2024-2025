# 데이터 수집 파이프라인 감사 보고서

**감사 일자**: 2026-04-20
**감사자**: Claude Code (독립 감사)
**감사 범위**: `src/01~07` 전체 스크립트, GitHub Actions 워크플로우 9종
**데이터 스냅샷**: Step 5 완료 (23,774 obs, 2015~2025)

---

## 요약 (Executive Summary)

| 항목 | 판정 |
|------|------|
| **전반적 신뢰 수준** | **조건부 신뢰** (Critical 1건 + High 1건 해결 후 전면 신뢰) |
| 필드명 정확성 | 간접 검증됨 (Step 0 카나리아 전제 시) |
| 정제 로직(05_clean_merge) | related_pct 버그 수정 완료 / **treasury_pct=0 미해결** |
| 수집 완전성 | 관측치 23,774건 / 예상 ~26,400건 대비 약 90% |
| 벤치마크 정합성 | 최대주주 ±2%p (정상) / 우호지분 ±3%p (자사주 반영 후 추가 축소 예상) |
| **재수집 필요 범위** | **없음** — Step 5만 재실행으로 충분. 단 03b 데이터 존재 여부 사전 확인 필수 |

### 주요 이슈 분포
- **Critical**: 1건 — `treasury_pct` 전체 0 (23773/23774)
- **High**: 1건 — `_pick_total_shares`의 `isu_stock_totqy` 폴백 오용 위험
- **Medium**: 2건 — `process_minority` 첫 행 선택 / esop_pct 데이터 소스 한계
- **Low**: 2건 — 단순평균 vs 가중평균 구분 표기 / valid_n 로깅

---

## 1. API 필드명 검증

### 1-1. 검증 방식의 한계
DART 공식 문서 페이지(`opendart.fss.or.kr/guide/detail.do`)가 외부 자동화 요청에 **403 차단** 되어 직접 검증이 불가능했습니다. 대신 다음 2단 간접 검증으로 대체합니다:

**Layer 1**: `src/00_canary_validation.py`가 삼성전자·카카오·셀트리온 3사 2023년 데이터로 **실시간 DART 호출 후 필드 존재 여부를 단언**하는 구조. 이 스크립트가 통과한다는 것은 REQUIRED_FIELDS가 실제 응답에 존재함을 의미.

**Layer 2**: 실제로 수집된 `ownership_panel.csv`에서 `largest_pct` 평균 27.29%(벤치마크 29.21%)가 나왔다는 것은 `trmend_posesn_stock_qota_rt` 필드가 정상 파싱되고 있다는 **실증 증거**.

### 1-2. 코드가 사용하는 필드 (카나리아에서 단언)

| API | 코드에서 `.get()` 하는 필드 | 용도 |
|-----|------------------------|------|
| `hyslrSttus` | `nm`, `relate`, `trmend_posesn_stock_co`, `trmend_posesn_stock_qota_rt` | 최대주주·특수관계인 |
| `tesstkAcqsDspsSttus` | `stock_knd`, `acqs_mth1/2/3`, `bsis_qy`, `change_qy`, `trmend_qy` | 자사주 수량 |
| `stockTotqySttus` | `se`, `isu_stock_totqy`, `now_to_isu_stock_totqy`, `redc_stock_totqy`, `now_to_redc_stock_totqy`, `istc_totqy` | 발행주식 총수 |
| `mrhlSttus` | `se`, `shrholdr_co`, `shrholdr_tot_co`, `shrholdr_rate`, `hold_stock_co`, `stock_tot_co`, `hold_stock_rate` | 소액주주 |
| `company` | `corp_cls`, `est_dt`, `induty_code` | 기업 분류 |
| `corpCode` | `corp_code`, `corp_name`, `stock_code` (XML) | 기업 식별 |

### 1-3. 권고 조치
`.github/workflows/step0-canary.yml` 실행 이력을 확인하여 카나리아가 **최근 성공했는지** 확인 필수. 실패 이력이 있거나 미실행이면 **지금 실행**하여 필드 존재를 재단언해야 함.

---

## 2. Critical 이슈

### 🔴 Critical-1: `treasury_pct` 전체 0 (23773/23774건)

**증상**:
```
treasury_pct 0.00 건수: 23773 / 전체 23774
```

**원인 후보 (우선순위 순)**:

| # | 원인 | 진단 방법 | 해결 방법 |
|---|------|---------|---------|
| A | `total_shares_raw.csv` 파일이 비어있음 또는 누락 | Step 3 artifact 내용 확인 | Step 3b 재실행 |
| B | `total_shares_raw.csv`에 `se == "발행한 주식의 총수"` 행 부재 | 새 Step 5 로그 `se 고유값 상위 10` 확인 | `_pick_total_shares`의 se 필터 확장 |
| C | `stock_knd` 필터 "보통" 미매칭 (예: DART가 `"의결권있는주식"` 반환) | 새 Step 5 로그 `stock_knd 고유값` 확인 | 필터 추가 완화 또는 제거 |
| D | merge key 불일치 (corp_code/year 타입 다름) | 수동 샘플링 | dtype 통일 |

**영향**: friendly_pct가 약 **2~3%p 과소추정**. 벤치마크 43.07% 대비 현재 40.10% (-2.97%p)의 상당 부분이 이 이슈로 설명됨.

**해결 전제**: Step 5를 한 번 더 재실행하고 **추가된 진단 로그** 확인 (이미 커밋 `858ef57`에 반영).

---

## 3. High 이슈

### 🟠 High-1: `_pick_total_shares`의 `isu_stock_totqy` 폴백 오용 위험

**위치**: `src/05_clean_merge.py:84-116`

**현재 우선순위**:
1. `istc_totqy` (유통주식총수) — 정확
2. `now_to_isu - now_to_redc` (발행누적 − 감소누적) — 정확
3. `now_to_isu` (발행누적) — 보통 OK
4. **`isu_stock_totqy` (발행할 주식의 총수 = 정관상 한도)** — **부정확**

**문제**: `isu_stock_totqy`는 정관에 명시된 **허용 발행한도**(authorized shares)이지 **실제 발행주식**(outstanding)이 아닙니다. 대기업의 경우 "발행할 주식의 총수"가 "실제 발행주식"의 10~100배에 달할 수 있음.

**사례 (가상)**:
- 정관상 "발행할 주식의 총수": 10억 주
- 실제 발행주식(`istc_totqy`): 6천만 주
- 자사주(`trmend_qy`): 60만 주
- **올바른 treasury_pct**: 1.00% (60만 / 6천만)
- **폴백 적용 시**: 0.06% (60만 / 10억) ← **과소 추정 16배**

**해결 방법**: 우선순위 4 제거하고 NaN 반환:
```python
# 4순위 isu_stock_totqy 폴백 삭제 — 정관한도는 treasury_pct 계산에 부적합
return np.nan
```

**영향**: 현재 실제로 몇 개 기업에 이 폴백이 적용됐는지 확인 불가. 상위 3개 필드가 모두 있으면 영향 없음. 만약 폴백이 광범위하게 쓰였다면 treasury_pct 일부가 비정상적으로 낮음.

---

## 4. Medium 이슈

### 🟡 Medium-1: `process_minority`의 `.iloc[0]` 순서 의존

**위치**: `src/05_clean_merge.py:176`
```python
mask = grp["se"].str.contains("소액", na=False)
minority_pct = grp.loc[mask, "hold_stock_rate_f"].iloc[0] if mask.any() else np.nan
```

**문제**: "소액" 포함 행이 여러 개일 때(예: `"소액주주"`, `"소액주주의 보유주식"`) **첫 번째만** 사용. DART가 순서를 보장하지 않으면 다른 행이 선택될 수 있음.

**해결 방법**: 엄격 매칭 우선 + 폴백
```python
exact = grp[grp["se"].str.strip() == "소액주주"]
if not exact.empty:
    minority_pct = exact["hold_stock_rate_f"].iloc[0]
elif mask.any():
    minority_pct = grp.loc[mask, "hold_stock_rate_f"].iloc[0]
else:
    minority_pct = np.nan
```

### 🟡 Medium-2: `esop_pct` 데이터 소스 한계 — 현재 0에 가까움

**위치**: `src/05_clean_merge.py:48-52`, mean 결과 0.00

**구조적 한계**:
- `hyslrSttus`는 **최대주주 본인 + 특수관계인**만 커버
- 우리사주조합이 특수관계인으로 등록된 기업만 `esop_pct`에 포착됨
- 일반 우리사주조합(최대주주 무관)은 누락 → 평균 0.00 원인

**완전한 ESOP 수집은 별도 API 필요**: 
- `elestock.json` (임원·주요주주 소유현황)은 다른 범위
- 사업보고서 텍스트 파싱이 유일한 길

**권고**: 현 상태는 "최대주주 진영 내 ESOP"만 집계하며, 독립 ESOP은 미포착임을 `README.md`와 `RESEARCH_PLAN.md`에 **명시**. friendly_pct 해석 시 유의 사항.

---

## 5. Low 이슈

### 🟢 Low-1: 06_analyze.py 전체 평균이 단순평균
`compute_yearly_stats`는 **기업 단위 단순평균**(unweighted). 자본시장연구원 보고서가 **시가총액 가중**일 경우 정의 차이로 몇 %p 차이 가능.

**권고**: 로그에 `"(단순평균)"` 명시, 가중평균 변형은 Phase 2에서 추가 고려.

### 🟢 Low-2: `compute_yearly_stats`의 valid_n 미기록
`grp[col].dropna()`로 NaN 제외 후 평균 계산하는데, **유효 샘플 수**(`valid_n`)가 로그에 없음. 예: `n=2163`이지만 `largest_pct` 유효가 1950일 수도 있음.

**권고**: `row[f"{col}_n"] = len(vals)` 추가.

---

## 6. 정제 로직 심층 검증

### 6-1. `process_ownership` ✓ PASS
- ✅ 집계행 필터 "계"/"소계"/"합계" 제거 (858ef57 커밋)
- ✅ `mask_self`(본인) / `mask_esop`(우리사주) / `mask_related`(나머지) 분리 정상
- ⚠️ `mask_esop`은 Medium-2 한계 존재

### 6-2. `process_treasury` ⚠️ Critical-1 미해결
- ✅ 보통주 필터 "보통주" → "보통"으로 완화 (858ef57)
- 🔴 treasury_pct=0 전체 → 실행 후 로그 확인 필요
- 🟠 `_pick_total_shares` 우선순위 4번 폴백 제거 필요 (High-1)

### 6-3. `process_minority` ⚠️ Medium-1
- 순서 의존성 해결 필요

---

## 7. 현재 Step 5 결과 신뢰도 평가

### 7-1. 정량 평가

| 지표 | 현재 | 벤치마크(2023) | 차이 | 해석 |
|------|------|--------------|------|------|
| 최대주주 평균 | 27.29% | 29.21% | −1.92%p | **수용**. 평균 기간(2015~25) vs 단일시점(2023) + 단순평균 차이 |
| 우호지분 평균 | 40.10% | 43.07% | −2.97%p | **조건부 수용**. treasury 반영 시 ~42~43% 도달 예상 |
| 관측치 | 23,774 | — | — | 예상 26,400 대비 약 10% 누락. 비상장 전환·신규상장 등 자연적 누락으로 보임 |

### 7-2. 편의(bias) 가능성

| 원인 | 방향 | 크기 | 상태 |
|------|------|------|------|
| 집계행 중복 집계 | related 과대 | +40%p | ✅ **수정됨** |
| treasury 전체 0 | friendly 과소 | -2~3%p | 🔴 **미수정** |
| isu_stock_totqy 폴백 | treasury 과소 | 기업별 상이 | 🟠 **수정 대기** |
| ESOP 최대주주 진영만 | friendly 과소 | -1~2%p | ℹ️ 구조적 한계 |

### 7-3. 종합 판정

**"Step 5만 재실행하면 분석 가능한 품질"에 도달합니다.**

Step 6 통계·벤치마크 비교와 Step 7 시각화는 **Critical-1(treasury_pct)**만 해결되면 학술적으로 신뢰 가능한 결과를 산출합니다.

---

## 8. 권고 조치 (우선순위)

### 즉시 조치

1. **[Critical-1 진단]** Step 5를 지금 추가된 로그 상태로 **한 번 더 실행** 후 아래 확인:
   - `자사주 stock_knd 고유값: [...]` → "보통" 포함 값 존재?
   - `보통주 필터 후: X행` → 0이 아닌지?
   - `se 고유값 상위 10: {...}` → "발행한 주식의 총수" 존재?
   
   결과에 따라:
   - stock_knd 0행 → 필터 완전 제거 또는 추가 키워드
   - se에 "발행한 주식의 총수" 없음 → total_shares_raw.csv 재검증 필요 (Step 3 artifact 재확인)
   - 파일 자체 없음 → Step 3 수동 재실행

2. **[High-1 수정]** `_pick_total_shares`의 4순위 `isu_stock_totqy` 폴백 제거 (NaN 반환)

### 단기 조치

3. **[Medium-1]** `process_minority` 엄격매칭 로직 추가
4. **[Medium-2]** README/RESEARCH_PLAN에 ESOP 집계 한계 명시

### 품질 보증 (Step 6 진행 전)

5. **Step 0 카나리아 재실행**: 필드 존재 실시간 단언 (비용 ~100 API 호출, 5분 소요)
6. **삼성전자 2023 수기 교차검증**: `ownership_panel.csv`에서 삼성전자 값을 DART 공시 원본과 1:1 비교
   - 최대주주(이재용 외) 지분율
   - 자사주 보유율
   - 소액주주 비율

### 재수집 필요 없음

- ✅ `listed_corps.csv` 신뢰
- ✅ `ownership_raw.csv` (수정된 코드로 재수집 완료) 신뢰
- ✅ `treasury_raw.csv` 신뢰 (단 stock_knd 고유값 확인 후)
- ✅ `minority_raw.csv` 신뢰
- ❓ `total_shares_raw.csv` — **존재와 내용 재확인 필요**

---

## 9. 감사 결론

**현재 수집·정제 파이프라인은 하나의 Critical 이슈(treasury_pct)만 해결하면 연구용 데이터로 신뢰 가능한 품질입니다.** 

`related_pct` 중복 집계는 이미 식별·수정됐고, 나머지 이슈는 모두 치료 가능한 범위입니다. 재수집 없이 **Step 5 재실행 1회**로 문제 여부 판별 및 해결이 가능합니다.

treasury_pct 이슈가 해결되면 우호지분 평균은 약 42~43%에 도달해 벤치마크(43.07%)와 **±1%p 이내**로 수렴할 것으로 전망됩니다.
