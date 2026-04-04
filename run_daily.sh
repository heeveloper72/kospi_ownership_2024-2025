#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# run_daily.sh — DART 소유구조 파이프라인 일일 실행 스크립트
#
# 사용법:
#   ./run_daily.sh          # 자동 판단 (권장)
#   ./run_daily.sh --step 2 # 특정 스텝만 강제 실행
#   ./run_daily.sh --status # 현재 진행 현황만 출력
#
# 매일 한 번 실행하면 API 한도(10,000건/일) 내에서 자동 진행.
# 모든 수집 스크립트(02/03/04)가 공유 카운터를 사용하므로
# 한 스크립트가 한도에 도달하면 당일 나머지도 실행되지 않음.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python}"
LOG_DIR="logs"
mkdir -p "$LOG_DIR"
TODAY=$(date +%Y-%m-%d)
LOG_FILE="$LOG_DIR/run_${TODAY}.log"

RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

log()   { echo -e "${CYAN}[$(date +%H:%M:%S)]${RESET} $*" | tee -a "$LOG_FILE"; }
ok()    { echo -e "${GREEN}✓${RESET} $*" | tee -a "$LOG_FILE"; }
warn()  { echo -e "${YELLOW}⚠${RESET}  $*" | tee -a "$LOG_FILE"; }
err()   { echo -e "${RED}✗${RESET}  $*" | tee -a "$LOG_FILE"; }
header(){ echo -e "\n${BOLD}${CYAN}══ $* ══${RESET}" | tee -a "$LOG_FILE"; }

# ── 현황 표시 함수 ─────────────────────────────────────────────────────────

show_status() {
    header "파이프라인 현황 ($TODAY)"

    # API 일일 카운터
    COUNTER_FILE="data/raw/.api_daily_counter.json"
    if [ -f "$COUNTER_FILE" ]; then
        CALLS=$(python -c "import json; d=json.load(open('$COUNTER_FILE')); print(d.get('calls',0) if d.get('date')=='$TODAY' else 0)" 2>/dev/null || echo 0)
        log "오늘 API 호출: ${CALLS}/10,000"
    else
        log "오늘 API 호출: 0/10,000 (첫 실행)"
    fi

    # Step 1: listed_corps.csv
    if [ -f "data/raw/listed_corps.csv" ]; then
        CORP_CNT=$(tail -n +2 data/raw/listed_corps.csv | wc -l | tr -d ' ')
        ok "Step 1 완료: 상장사 ${CORP_CNT}개"
    else
        warn "Step 1 미완료: listed_corps.csv 없음"
    fi

    # Step 2: ownership
    if [ -f "data/raw/ownership_checkpoint.json" ]; then
        $PYTHON - <<'EOF'
import json, sys
try:
    cp = json.load(open("data/raw/ownership_checkpoint.json"))
    done = sum(len(v) for v in cp.get("completed", {}).values())
    print(f"  Step 2 진행중: {done}건 완료")
except: print("  Step 2 체크포인트 읽기 실패")
EOF
    else
        warn "Step 2 미시작: ownership_checkpoint.json 없음"
    fi

    # Step 3: treasury
    if [ -f "data/raw/treasury_checkpoint.json" ]; then
        $PYTHON - <<'EOF'
import json
try:
    cp = json.load(open("data/raw/treasury_checkpoint.json"))
    done = sum(len(v) for v in cp.get("completed", {}).values())
    print(f"  Step 3 진행중: {done}건 완료")
except: print("  Step 3 체크포인트 읽기 실패")
EOF
    else
        warn "Step 3 미시작"
    fi

    # Step 4: minority
    if [ -f "data/raw/minority_checkpoint.json" ]; then
        $PYTHON - <<'EOF'
import json
try:
    cp = json.load(open("data/raw/minority_checkpoint.json"))
    done = sum(len(v) for v in cp.get("completed", {}).values())
    print(f"  Step 4 진행중: {done}건 완료")
except: print("  Step 4 체크포인트 읽기 실패")
EOF
    else
        warn "Step 4 미시작"
    fi

    # Step 5~7: 결과 파일
    [ -f "data/processed/ownership_panel.csv" ] && ok "Step 5 완료: ownership_panel.csv" || warn "Step 5 미완료"
    [ -f "data/output/yearly_stats_total.csv" ] && ok "Step 6 완료: yearly_stats_*.csv" || warn "Step 6 미완료"
    [ -f "data/output/chart1_stacked_area.png" ] && ok "Step 7 완료: 차트 5종" || warn "Step 7 미완료"
}

# ── 스텝 실행 함수 ─────────────────────────────────────────────────────────

run_step() {
    local step=$1 script=$2 label=$3
    header "Step $step: $label"
    if $PYTHON "src/$script" 2>&1 | tee -a "$LOG_FILE"; then
        ok "Step $step 완료"
        return 0
    else
        err "Step $step 실패 — 로그: $LOG_FILE"
        return 1
    fi
}

check_daily_limit() {
    COUNTER_FILE="data/raw/.api_daily_counter.json"
    if [ ! -f "$COUNTER_FILE" ]; then return 0; fi
    CALLS=$($PYTHON -c "
import json
d = json.load(open('$COUNTER_FILE'))
print(d.get('calls', 0) if d.get('date') == '$TODAY' else 0)
" 2>/dev/null || echo 0)
    if [ "$CALLS" -ge 10000 ]; then
        warn "오늘 API 한도(10,000건) 도달. 내일 재실행하세요."
        return 1
    fi
    return 0
}

collection_done() {
    local checkpoint=$1
    [ ! -f "$checkpoint" ] && return 1
    $PYTHON - "$checkpoint" <<'EOF'
import json, sys
try:
    cp = json.load(open(sys.argv[1]))
    done = sum(len(v) for v in cp.get("completed", {}).values())
    # listed_corps.csv 기업수 × 11년 = 총 작업수 추정
    import csv
    with open("data/raw/listed_corps.csv") as f:
        corp_count = sum(1 for _ in f) - 1
    total = corp_count * 11
    sys.exit(0 if done >= total else 1)
except:
    sys.exit(1)
EOF
}

# ── 메인 로직 ──────────────────────────────────────────────────────────────

FORCE_STEP=""

# 인자 파싱
while [[ $# -gt 0 ]]; do
    case "$1" in
        --status) show_status; exit 0 ;;
        --step)   FORCE_STEP="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

header "DART 소유구조 파이프라인 ($TODAY)"
log "로그: $LOG_FILE"

# .env 확인
if [ ! -f ".env" ]; then
    err ".env 파일이 없습니다. cp .env.example .env 후 API 키를 입력하세요."
    exit 1
fi

# ── 강제 스텝 지정 ─────────────────────────────────────────────────────────
if [ -n "$FORCE_STEP" ]; then
    case "$FORCE_STEP" in
        1) run_step 1 "01_get_corp_list.py"  "상장사 목록 수집" ;;
        2) run_step 2 "02_collect_ownership.py" "최대주주 데이터 수집" ;;
        3) run_step 3 "03_collect_treasury.py"  "자사주 데이터 수집" ;;
        4) run_step 4 "04_collect_minority.py"  "소액주주 데이터 수집" ;;
        5) run_step 5 "05_clean_merge.py"        "데이터 정제 & 병합" ;;
        6) run_step 6 "06_analyze.py"            "통계 분석" ;;
        7) run_step 7 "07_visualize.py"          "시각화" ;;
        *) err "알 수 없는 스텝: $FORCE_STEP (1~7)"; exit 1 ;;
    esac
    show_status
    exit 0
fi

# ── 자동 판단 실행 ─────────────────────────────────────────────────────────

# Step 1: 상장사 목록 (최초 한 번, 또는 미완료 시)
if [ ! -f "data/raw/listed_corps.csv" ] || \
   [ -f "data/raw/corp_cls_checkpoint.json" ]; then
    # corp_cls_checkpoint.json이 남아있으면 아직 분류 미완료
    CORP_COUNT=0
    if [ -f "data/raw/listed_corps.csv" ]; then
        CORP_COUNT=$(tail -n +2 data/raw/listed_corps.csv | wc -l | tr -d ' ')
    fi
    if [ "$CORP_COUNT" -lt 100 ]; then
        check_daily_limit || { show_status; exit 0; }
        run_step 1 "01_get_corp_list.py" "상장사 목록 수집"
    fi
fi

# Step 2: 최대주주 수집 (완료될 때까지 매일)
if ! collection_done "data/raw/ownership_checkpoint.json"; then
    check_daily_limit || { show_status; exit 0; }
    run_step 2 "02_collect_ownership.py" "최대주주 데이터 수집"
    check_daily_limit || { show_status; exit 0; }
fi

# Step 3: 자사주 수집
if ! collection_done "data/raw/treasury_checkpoint.json"; then
    check_daily_limit || { show_status; exit 0; }
    run_step 3 "03_collect_treasury.py" "자사주 데이터 수집"
    check_daily_limit || { show_status; exit 0; }
fi

# Step 4: 소액주주 수집
if ! collection_done "data/raw/minority_checkpoint.json"; then
    check_daily_limit || { show_status; exit 0; }
    run_step 4 "04_collect_minority.py" "소액주주 데이터 수집"
    check_daily_limit || { show_status; exit 0; }
fi

# Step 5~7: 수집 완료 후 분석 및 시각화
if collection_done "data/raw/ownership_checkpoint.json"; then
    [ ! -f "data/processed/ownership_panel.csv" ] && \
        run_step 5 "05_clean_merge.py" "데이터 정제 & 병합"

    [ ! -f "data/output/yearly_stats_total.csv" ] && \
        run_step 6 "06_analyze.py" "통계 분석"

    [ ! -f "data/output/chart1_stacked_area.png" ] && \
        run_step 7 "07_visualize.py" "시각화"
fi

show_status
