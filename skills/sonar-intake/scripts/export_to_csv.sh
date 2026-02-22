#!/bin/bash

# Export SonarQube Issues to CSV for Google Sheets
# Usage: ./export_to_csv.sh -f issues.json [-o output.csv]
# Example: ./export_to_csv.sh -f data/xxx/by_severity/HIGH.json

set -euo pipefail

# 프로젝트 디렉토리 (SONAR_PROJECT_DIR 필수)
if [[ -z "${SONAR_PROJECT_DIR:-}" ]]; then
    echo "Error: SONAR_PROJECT_DIR 환경변수가 설정되지 않았습니다"
    exit 1
fi
if [[ ! -d "$SONAR_PROJECT_DIR" ]]; then
    echo "Error: 프로젝트 디렉토리가 존재하지 않습니다: $SONAR_PROJECT_DIR"
    exit 1
fi

# 상대 경로를 절대 경로로 변환
SONAR_PROJECT_DIR="$(cd "$SONAR_PROJECT_DIR" && pwd)"

DATA_DIR="$SONAR_PROJECT_DIR/data"

# 변수 초기화 (-u 호환)
INPUT_FILE=""
OUTPUT_FILE=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -f) INPUT_FILE="$2"; shift 2 ;;
        -o) OUTPUT_FILE="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 -f issues.json [-o output.csv]"
            echo ""
            echo "Options:"
            echo "  -f  SonarQube issues JSON file (required)"
            echo "  -o  Output CSV file (default: auto-generated)"
            echo ""
            echo "Example:"
            echo "  $0 -f data/xxx/by_severity/HIGH.json"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "$INPUT_FILE" ]]; then
    echo "Error: INPUT_FILE (-f) is required"
    exit 1
fi

if [[ ! -f "$INPUT_FILE" ]]; then
    echo "Error: File not found: $INPUT_FILE"
    exit 1
fi

# Generate output filename if not specified
if [[ -z "$OUTPUT_FILE" ]]; then
    BASENAME=$(basename "$INPUT_FILE" .json)
    mkdir -p "$DATA_DIR"
    OUTPUT_FILE="$DATA_DIR/${BASENAME}_$(date +%Y%m%d_%H%M%S).csv"
fi

# Check if file has .issues array or is just an array
FILE_TYPE=$(jq 'type' "$INPUT_FILE")
if [[ "$FILE_TYPE" == '"array"' ]]; then
    JQ_PREFIX="."
else
    JQ_PREFIX=".issues"
fi

TOTAL=$(jq "$JQ_PREFIX | length" "$INPUT_FILE")
echo "Exporting $TOTAL issues to CSV..."
echo "Output: $OUTPUT_FILE"

# Create CSV with headers
# Columns designed for collaborative work
cat > "$OUTPUT_FILE" << 'EOF'
상태,담당자,Jira키,심각도,품질,타입,파일,라인,메시지,규칙,CleanCode,SonarQube키,생성일
EOF

# Export each issue
jq -r "$JQ_PREFIX[] | [
    \"대기\",
    \"\",
    \"\",
    (.impacts[0].severity // .severity // \"N/A\"),
    (.impacts[0].softwareQuality // \"N/A\"),
    (.type // \"N/A\"),
    (.component | split(\":\")[1] // .component),
    (.line // \"N/A\" | tostring),
    (.message | gsub(\"\\\"\"; \"'\") | gsub(\"\\n\"; \" \")),
    (.rule // \"N/A\"),
    (.cleanCodeAttribute // \"N/A\"),
    (.key // \"N/A\"),
    (.creationDate // \"N/A\" | split(\"T\")[0])
] | @csv" "$INPUT_FILE" >> "$OUTPUT_FILE"

echo ""
echo "Done! CSV created: $OUTPUT_FILE"
echo ""
echo "=== Google Sheets 사용 가이드 ==="
echo ""
echo "1. Google Sheets에서 파일 > 가져오기 > 업로드"
echo "2. 첫 번째 행을 헤더로 고정 (보기 > 고정 > 행 1개)"
echo "3. '상태' 열에 데이터 유효성 검사 추가:"
echo "   - 대기, 처리중, 완료, 보류"
echo "4. '담당자' 열에 팀원 이름 드롭다운 추가"
echo ""
echo "=== 컬럼 설명 ==="
echo "상태: 대기 → 처리중 → 완료"
echo "담당자: 작업자 이름"
echo "Jira키: 생성된 Jira 이슈 번호"
echo "심각도: HIGH, MEDIUM, LOW, BLOCKER, INFO"
echo "품질: MAINTAINABILITY, RELIABILITY, SECURITY"
echo "타입: CODE_SMELL, BUG, VULNERABILITY"
