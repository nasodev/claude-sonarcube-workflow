#!/bin/bash

# SonarQube Issue Fetcher Script
# Usage: ./fetch_issues.sh [project_key]

set -euo pipefail

# 프로젝트 루트 동적 취득 (CLAUDE_PROJECT_DIR → git rev-parse → SCRIPT_DIR 순)
if [[ -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
    PROJECT_ROOT="$CLAUDE_PROJECT_DIR"
elif git rev-parse --show-toplevel >/dev/null 2>&1; then
    PROJECT_ROOT=$(git rev-parse --show-toplevel)
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
fi
if [[ ! -d "$PROJECT_ROOT/.claude" ]]; then
    echo "Error: 프로젝트 루트를 찾을 수 없습니다 (현재: $(pwd))"
    exit 1
fi

ENV_FILE="$PROJECT_ROOT/.env"
DATA_DIR="$PROJECT_ROOT/data"

# Load token from .env
if [[ ! -f "$ENV_FILE" ]]; then
    echo "Error: .env file not found at $ENV_FILE"
    exit 1
fi
source "$ENV_FILE" 2>&1 || { echo "Error: .env 로드 실패"; exit 1; }

if [[ -z "$SONARCUBE_TOKEN" ]]; then
    echo "Error: SONARCUBE_TOKEN not found in .env file"
    exit 1
fi

# Configuration
SONARQUBE_URL="${SONARQUBE_URL:-https://sonarqube-001.hanpda.com}"
PROJECT_KEY="${1:-odin-addsvc-extsvc-backend}"
PAGE_SIZE=500
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Create project directory
PROJECT_DIR="$DATA_DIR/${PROJECT_KEY}_${TIMESTAMP}"
mkdir -p "$PROJECT_DIR"
mkdir -p "$PROJECT_DIR/by_severity"
mkdir -p "$PROJECT_DIR/by_quality"
mkdir -p "$PROJECT_DIR/by_type"
mkdir -p "$PROJECT_DIR/by_attribute"

OUTPUT_FILE="$PROJECT_DIR/all_issues.json"

echo "Fetching issues for project: $PROJECT_KEY"
echo "SonarQube URL: $SONARQUBE_URL"
echo "Output directory: $PROJECT_DIR"

# Get total count first
RESPONSE=$(curl -sS -w "\n%{http_code}" \
    -u "$SONARCUBE_TOKEN:" \
    "$SONARQUBE_URL/api/issues/search?componentKeys=$PROJECT_KEY&ps=1" 2>&1)

if [[ $? -ne 0 ]]; then
    echo "Error: curl 실행 실패 (네트워크 오류)"
    echo "$RESPONSE"
    exit 1
fi

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [[ -z "$HTTP_CODE" || "$HTTP_CODE" -lt 200 || "$HTTP_CODE" -ge 300 ]]; then
    echo "Error: SonarQube API 실패 (HTTP $HTTP_CODE)"
    echo "$BODY"
    exit 1
fi

TOTAL=$(echo "$BODY" | jq '.total' 2>&1) || true
if [[ -z "$TOTAL" || "$TOTAL" == "null" ]]; then
    echo "Error: 응답에서 total 필드를 파싱할 수 없습니다"
    echo "$BODY"
    exit 1
fi
echo "Total issues: $TOTAL"

# Calculate pages needed
PAGES=$(( (TOTAL + PAGE_SIZE - 1) / PAGE_SIZE ))
echo "Pages to fetch: $PAGES"

# Initialize output file with array start
echo '{"issues": [' > "$OUTPUT_FILE"

FIRST=true
for ((page=1; page<=PAGES; page++)); do
    echo "Fetching page $page of $PAGES..."

    RESPONSE=$(curl -sS -w "\n%{http_code}" \
        -u "$SONARCUBE_TOKEN:" \
        "$SONARQUBE_URL/api/issues/search?componentKeys=$PROJECT_KEY&ps=$PAGE_SIZE&p=$page" 2>&1)

    if [[ $? -ne 0 ]]; then
        echo "Error: curl 실행 실패 (page $page)"
        echo "$RESPONSE"
        exit 1
    fi

    HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
    PAGE_BODY=$(echo "$RESPONSE" | sed '$d')

    if [[ -z "$HTTP_CODE" || "$HTTP_CODE" -lt 200 || "$HTTP_CODE" -ge 300 ]]; then
        echo "Error: SonarQube API 실패 (HTTP $HTTP_CODE, page $page)"
        echo "$PAGE_BODY"
        exit 1
    fi

    # Extract issues array and append
    ISSUES=$(echo "$PAGE_BODY" | jq '.issues' 2>&1) || true
    if [[ -z "$ISSUES" || "$ISSUES" == "null" ]]; then
        echo "Error: JSON 파싱 실패 (page $page): $ISSUES"
        exit 1
    fi

    if [[ "$FIRST" == true ]]; then
        FIRST=false
    else
        echo "," >> "$OUTPUT_FILE"
    fi

    # Remove array brackets and append (단계별 검증)
    FORMATTED=$(echo "$ISSUES" | jq -c '.[]' 2>&1) || true
    if [[ -z "$FORMATTED" ]]; then
        echo "Error: 이슈 포매팅 실패 (page $page)"
        exit 1
    fi
    echo "$FORMATTED" | paste -sd ',' - >> "$OUTPUT_FILE"
done

# Close the JSON array and add metadata
echo '],' >> "$OUTPUT_FILE"
echo "\"metadata\": {" >> "$OUTPUT_FILE"
echo "  \"project\": \"$PROJECT_KEY\"," >> "$OUTPUT_FILE"
echo "  \"total\": $TOTAL," >> "$OUTPUT_FILE"
echo "  \"fetchedAt\": \"$(date -Iseconds)\"," >> "$OUTPUT_FILE"
echo "  \"sonarqubeUrl\": \"$SONARQUBE_URL\"" >> "$OUTPUT_FILE"
echo "}" >> "$OUTPUT_FILE"
echo "}" >> "$OUTPUT_FILE"

# Format the JSON properly
jq '.' "$OUTPUT_FILE" > "${OUTPUT_FILE}.tmp" && mv "${OUTPUT_FILE}.tmp" "$OUTPUT_FILE"

echo ""
echo "Creating category files..."

# Split by Severity (UI 기준)
echo "  - By Severity..."
for severity in HIGH MEDIUM LOW BLOCKER INFO; do
    jq --arg sev "$severity" '[.issues[] | select(.impacts[0].severity == $sev)]' "$OUTPUT_FILE" > "$PROJECT_DIR/by_severity/${severity}.json"
    COUNT=$(jq 'length' "$PROJECT_DIR/by_severity/${severity}.json")
    echo "    ${severity}: ${COUNT}"
done

# Split by Software Quality
echo "  - By Software Quality..."
for quality in MAINTAINABILITY RELIABILITY SECURITY; do
    jq --arg qual "$quality" '[.issues[] | select(.impacts[0].softwareQuality == $qual)]' "$OUTPUT_FILE" > "$PROJECT_DIR/by_quality/${quality}.json"
    COUNT=$(jq 'length' "$PROJECT_DIR/by_quality/${quality}.json")
    echo "    ${quality}: ${COUNT}"
done

# Split by Type
echo "  - By Type..."
for type in CODE_SMELL BUG VULNERABILITY; do
    jq --arg t "$type" '[.issues[] | select(.type == $t)]' "$OUTPUT_FILE" > "$PROJECT_DIR/by_type/${type}.json"
    COUNT=$(jq 'length' "$PROJECT_DIR/by_type/${type}.json")
    echo "    ${type}: ${COUNT}"
done

# Split by Clean Code Attribute
echo "  - By Clean Code Attribute..."
ATTRIBUTES=$(jq -r '[.issues[].cleanCodeAttribute] | unique | .[]' "$OUTPUT_FILE")
for attr in $ATTRIBUTES; do
    jq --arg a "$attr" '[.issues[] | select(.cleanCodeAttribute == $a)]' "$OUTPUT_FILE" > "$PROJECT_DIR/by_attribute/${attr}.json"
    COUNT=$(jq 'length' "$PROJECT_DIR/by_attribute/${attr}.json")
    echo "    ${attr}: ${COUNT}"
done

echo ""
echo "==============================================="
echo "                    SUMMARY                    "
echo "==============================================="
echo ""

# New Impact-based Severity (UI 기준)
echo "=== Severity (UI 표시 기준) ==="
jq -r '
  .issues |
  map(.impacts[0].severity // "UNKNOWN") |
  group_by(.) |
  map({severity: .[0], count: length}) |
  sort_by(
    if .severity == "HIGH" then 0
    elif .severity == "MEDIUM" then 1
    elif .severity == "LOW" then 2
    else 3 end
  ) |
  .[] | "\(.severity): \(.count)"
' "$OUTPUT_FILE"

echo ""

# Software Quality 분류
echo "=== Software Quality ==="
jq -r '
  .issues |
  map(.impacts[0].softwareQuality // "UNKNOWN") |
  group_by(.) |
  map({quality: .[0], count: length}) |
  sort_by(.count) | reverse |
  .[] | "\(.quality): \(.count)"
' "$OUTPUT_FILE"

echo ""

# Clean Code Attribute 분류
echo "=== Clean Code Attribute ==="
jq -r '
  .issues |
  map(.cleanCodeAttribute // "UNKNOWN") |
  group_by(.) |
  map({attr: .[0], count: length}) |
  sort_by(.count) | reverse |
  .[] | "\(.attr): \(.count)"
' "$OUTPUT_FILE"

echo ""

# Type 분류
echo "=== Type ==="
jq -r '
  .issues |
  map(.type // "UNKNOWN") |
  group_by(.) |
  map({type: .[0], count: length}) |
  sort_by(.count) | reverse |
  .[] | "\(.type): \(.count)"
' "$OUTPUT_FILE"

echo ""

# Status 분류
echo "=== Status ==="
jq -r '
  .issues |
  map(.issueStatus // .status // "UNKNOWN") |
  group_by(.) |
  map({status: .[0], count: length}) |
  sort_by(.count) | reverse |
  .[] | "\(.status): \(.count)"
' "$OUTPUT_FILE"

echo ""
echo "==============================================="
echo ""
echo "Files created:"
echo "  $PROJECT_DIR/"
echo "  ├── all_issues.json"
echo "  ├── by_severity/"
echo "  │   ├── HIGH.json"
echo "  │   ├── MEDIUM.json"
echo "  │   ├── LOW.json"
echo "  │   ├── BLOCKER.json"
echo "  │   └── INFO.json"
echo "  ├── by_quality/"
echo "  │   ├── MAINTAINABILITY.json"
echo "  │   ├── RELIABILITY.json"
echo "  │   └── SECURITY.json"
echo "  ├── by_type/"
echo "  │   ├── CODE_SMELL.json"
echo "  │   ├── BUG.json"
echo "  │   └── VULNERABILITY.json"
echo "  └── by_attribute/"
echo "      └── [각 Clean Code Attribute].json"
