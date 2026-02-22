#!/bin/bash

# SonarQube Issue Fetcher Script
# Usage: ./fetch_issues.sh [project_key]
#
# Handles the SonarQube API 10,000 issue hard limit by splitting queries:
#   Level 1: by type (BUG, VULNERABILITY, CODE_SMELL)
#   Level 2: by impactSeverity (HIGH, MEDIUM, LOW)
#   Level 3: by rules (via facets API)
#   Level 4: by date range (binary split, last resort)

set -euo pipefail

# ---------------------------------------------------------------------------
# Project directory setup
# ---------------------------------------------------------------------------

if [[ -z "${SONAR_PROJECT_DIR:-}" ]]; then
    echo "Error: SONAR_PROJECT_DIR 환경변수가 설정되지 않았습니다"
    echo "Usage: SONAR_PROJECT_DIR=projects/<name> ./fetch_issues.sh"
    exit 1
fi

if [[ ! -d "$SONAR_PROJECT_DIR" ]]; then
    echo "Error: 프로젝트 디렉토리가 존재하지 않습니다: $SONAR_PROJECT_DIR"
    exit 1
fi

# 상대 경로를 절대 경로로 변환
SONAR_PROJECT_DIR="$(cd "$SONAR_PROJECT_DIR" && pwd)"

ENV_FILE="$SONAR_PROJECT_DIR/.env"
DATA_DIR="$SONAR_PROJECT_DIR/data"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "Error: .env file not found at $ENV_FILE"
    exit 1
fi
source "$ENV_FILE" 2>/dev/null || { echo "Error: .env 로드 실패"; exit 1; }

if [[ -z "$SONARQUBE_TOKEN" ]]; then
    echo "Error: SONARQUBE_TOKEN not found in .env file"
    exit 1
fi

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SONARQUBE_URL="${SONARQUBE_URL:-https://sonarqube-001.hanpda.com}"
PROJECT_KEY="${SONARQUBE_PROJECT_KEY:-}"
if [[ -z "$PROJECT_KEY" ]]; then
    echo "Error: SONARQUBE_PROJECT_KEY not found in .env file"
    exit 1
fi
PAGE_SIZE=500
MAX_RESULTS=10000
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

PROJECT_DIR="$DATA_DIR/${PROJECT_KEY}_${TIMESTAMP}"
mkdir -p "$PROJECT_DIR"/{by_severity,by_quality,by_type,by_attribute}

OUTPUT_FILE="$PROJECT_DIR/all_issues.json"
CURL_STDERR=$(mktemp)
trap 'rm -f "$CURL_STDERR"' EXIT

echo "Fetching issues for project: $PROJECT_KEY"
echo "SonarQube URL: $SONARQUBE_URL"
echo "Output directory: $PROJECT_DIR"

# ---------------------------------------------------------------------------
# API helper: call SonarQube and return body, validate HTTP status
# ---------------------------------------------------------------------------

api_call() {
    local url="$1"
    local response http_code body

    response=$(curl -sS -w "\n%{http_code}" \
        -u "$SONARQUBE_TOKEN:" \
        "$url" 2>"$CURL_STDERR") || {
        echo "Error: curl 실행 실패 (네트워크 오류)" >&2
        cat "$CURL_STDERR" >&2
        return 1
    }

    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')

    if [[ -z "$http_code" || "$http_code" -lt 200 || "$http_code" -ge 300 ]]; then
        echo "Error: SonarQube API 실패 (HTTP $http_code)" >&2
        echo "$body" >&2
        return 1
    fi

    echo "$body"
}

# ---------------------------------------------------------------------------
# get_total: query total count for given extra params
# ---------------------------------------------------------------------------

get_total() {
    local extra_params="${1:-}"
    local url="$SONARQUBE_URL/api/issues/search?componentKeys=$PROJECT_KEY&resolved=false&ps=1${extra_params:+&$extra_params}"
    local body total

    body=$(api_call "$url") || return 1
    total=$(echo "$body" | jq '.total // 0') || {
        echo "Error: total 필드 파싱 실패" >&2
        return 1
    }
    echo "$total"
}

# ---------------------------------------------------------------------------
# get_rules_facet: get list of rules and issue counts for given params
#   Uses facets=rules to get per-rule breakdown without fetching issues.
# ---------------------------------------------------------------------------

get_rules_facet() {
    local extra_params="${1:-}"
    local url="$SONARQUBE_URL/api/issues/search?componentKeys=$PROJECT_KEY&resolved=false&ps=1&facets=rules${extra_params:+&$extra_params}"
    local body
    body=$(api_call "$url") || return 1
    echo "$body" | jq -c '.facets[] | select(.property == "rules") | .values[] | select(.count > 0)' || {
        echo "Error: rules facet 파싱 실패" >&2
        return 1
    }
}

# ---------------------------------------------------------------------------
# fetch_with_pagination: paginate through results for a single query
#   Writes issue JSON lines (one object per line) to stdout.
#   Args: $1 = extra query params (e.g. "types=BUG&impactSeverities=HIGH")
# ---------------------------------------------------------------------------

fetch_with_pagination() {
    local extra_params="${1:-}"
    local base_url="$SONARQUBE_URL/api/issues/search?componentKeys=$PROJECT_KEY&resolved=false&ps=$PAGE_SIZE"
    if [[ -n "$extra_params" ]]; then
        base_url="${base_url}&${extra_params}"
    fi

    local total pages page_body issues_json
    total=$(get_total "$extra_params") || return 1

    if [[ "$total" -eq 0 ]]; then
        return 0
    fi

    if [[ "$total" -gt "$MAX_RESULTS" ]]; then
        echo "Warning: 쿼리 결과 $total 건이 10,000건 제한을 초과합니다 (params: $extra_params)" >&2
        return 2  # signal caller to split further
    fi

    pages=$(( (total + PAGE_SIZE - 1) / PAGE_SIZE ))
    echo "  Paginating: $total issues, $pages pages (params: ${extra_params:-none})" >&2

    for ((page=1; page<=pages; page++)); do
        page_body=$(api_call "${base_url}&p=$page") || return 1

        issues_json=$(echo "$page_body" | jq -c '.issues // []') || {
            echo "Error: issues 배열 파싱 실패 (page $page)" >&2
            return 1
        }

        # Empty page — stop early
        local count
        count=$(echo "$issues_json" | jq 'length')
        if [[ "$count" -eq 0 ]]; then
            echo "  Page $page returned 0 issues, stopping pagination" >&2
            break
        fi

        # Output one JSON object per line
        echo "$issues_json" | jq -c '.[]'
    done
}

# ---------------------------------------------------------------------------
# split_by_date_range: binary-split a date range to get under 10k per chunk
#   Args: $1=extra_params, $2=start_date(YYYY-MM-DD), $3=end_date(YYYY-MM-DD)
# ---------------------------------------------------------------------------

split_by_date_range() {
    local extra_params="$1"
    local start_date="$2"
    local end_date="$3"

    local start_epoch end_epoch mid_epoch mid_date
    start_epoch=$(date -j -f "%Y-%m-%d" "$start_date" "+%s" 2>/dev/null || date -d "$start_date" "+%s")
    end_epoch=$(date -j -f "%Y-%m-%d" "$end_date" "+%s" 2>/dev/null || date -d "$end_date" "+%s")

    # Base case: range is a single day — split by rules instead of truncating
    if [[ $((end_epoch - start_epoch)) -le 86400 ]]; then
        # If already split by rules, this is the absolute last resort — fetch what we can
        if [[ "$extra_params" == *"rules="* ]]; then
            echo "  Warning: 단일 일자($start_date) + 단일 룰에 10,000건 초과, 가능한 만큼 수집합니다" >&2
            local params="${extra_params:+$extra_params&}createdAfter=${start_date}T00:00:00%2B0900&createdBefore=${end_date}T23:59:59%2B0900"
            local base_url="$SONARQUBE_URL/api/issues/search?componentKeys=$PROJECT_KEY&resolved=false&ps=$PAGE_SIZE"
            base_url="${base_url}&${params}"
            local pages=$(( MAX_RESULTS / PAGE_SIZE ))
            for ((page=1; page<=pages; page++)); do
                local page_body
                page_body=$(api_call "${base_url}&p=$page") || return 1
                echo "$page_body" | jq -c '.issues // [] | .[]'
            done
            return 0
        fi

        echo "  단일 일자($start_date)에 10,000건 초과, rules로 추가 분할합니다" >&2
        local date_params="${extra_params:+$extra_params&}createdAfter=${start_date}T00:00:00%2B0900&createdBefore=${end_date}T23:59:59%2B0900"
        split_by_rules "$date_params"
        return $?
    fi

    mid_epoch=$(( (start_epoch + end_epoch) / 2 ))
    mid_date=$(date -j -f "%s" "$mid_epoch" "+%Y-%m-%d" 2>/dev/null || date -d "@$mid_epoch" "+%Y-%m-%d")

    echo "  Date split: $start_date ~ $mid_date | $(date -j -f "%s" $((mid_epoch + 86400)) "+%Y-%m-%d" 2>/dev/null || date -d "@$((mid_epoch + 86400))" "+%Y-%m-%d") ~ $end_date" >&2

    # First half
    local params1="${extra_params:+$extra_params&}createdAfter=${start_date}T00:00:00%2B0900&createdBefore=${mid_date}T23:59:59%2B0900"
    fetch_with_pagination "$params1"
    local rc=$?
    if [[ $rc -eq 2 ]]; then
        split_by_date_range "$extra_params" "$start_date" "$mid_date"
    elif [[ $rc -ne 0 ]]; then
        return 1
    fi

    # Second half
    local next_day
    next_day=$(date -j -f "%s" $((mid_epoch + 86400)) "+%Y-%m-%d" 2>/dev/null || date -d "@$((mid_epoch + 86400))" "+%Y-%m-%d")
    local params2="${extra_params:+$extra_params&}createdAfter=${next_day}T00:00:00%2B0900&createdBefore=${end_date}T23:59:59%2B0900"
    fetch_with_pagination "$params2"
    rc=$?
    if [[ $rc -eq 2 ]]; then
        split_by_date_range "$extra_params" "$next_day" "$end_date"
    elif [[ $rc -ne 0 ]]; then
        return 1
    fi
}

# ---------------------------------------------------------------------------
# split_by_rules: split query by individual rules to get under 10k per chunk
#   Uses facets API to discover rules, then fetches each separately.
#   Args: $1=extra_params (e.g. "types=CODE_SMELL&impactSeverities=HIGH")
# ---------------------------------------------------------------------------

split_by_rules() {
    local extra_params="$1"
    echo "    Splitting by rules (params: ${extra_params:-none})..." >&2

    local rules_data
    rules_data=$(get_rules_facet "$extra_params") || return 1

    if [[ -z "$rules_data" ]]; then
        echo "    Warning: rules facet가 비어있습니다 (params: $extra_params)" >&2
        return 0
    fi

    local rules_total=0
    while IFS= read -r rule_line; do
        local rule_key rule_count
        rule_key=$(echo "$rule_line" | jq -r '.val')
        rule_count=$(echo "$rule_line" | jq '.count')

        if [[ "$rule_count" -eq 0 ]]; then
            continue
        fi

        rules_total=$((rules_total + rule_count))
        local rule_params="${extra_params:+$extra_params&}rules=$rule_key"
        echo "      Rule $rule_key: $rule_count issues" >&2

        if [[ "$rule_count" -le "$MAX_RESULTS" ]]; then
            fetch_with_pagination "$rule_params" || return 1
        else
            # Single rule still >10k — split by date range for this rule
            echo "      Rule $rule_key still exceeds 10k, splitting by date range..." >&2
            local today
            today=$(date "+%Y-%m-%d")
            split_by_date_range "$rule_params" "2000-01-01" "$today" || return 1
        fi
    done <<< "$rules_data"

    echo "    Rules split total: $rules_total issues across rules" >&2
}

# ---------------------------------------------------------------------------
# fetch_all_issues: orchestrate fetching, splitting when needed
#   Writes deduplicated issue JSON lines to a temp file, then builds final JSON.
# ---------------------------------------------------------------------------

fetch_all_issues() {
    local tmp_issues
    tmp_issues=$(mktemp)
    trap 'rm -f "$CURL_STDERR" "$tmp_issues"' EXIT

    local overall_total
    overall_total=$(get_total "") || exit 1
    echo "Total issues (unresolved): $overall_total"

    # --- Case 1: No issues ---
    if [[ "$overall_total" -eq 0 ]]; then
        echo "No issues found."
        echo '{"issues": [], "metadata": {' > "$OUTPUT_FILE"
        echo "  \"project\": \"$PROJECT_KEY\"," >> "$OUTPUT_FILE"
        echo "  \"total\": 0," >> "$OUTPUT_FILE"
        echo "  \"fetchedAt\": \"$(date -Iseconds)\"," >> "$OUTPUT_FILE"
        echo "  \"sonarqubeUrl\": \"$SONARQUBE_URL\"" >> "$OUTPUT_FILE"
        echo '}}'  >> "$OUTPUT_FILE"
        jq '.' "$OUTPUT_FILE" > "${OUTPUT_FILE}.tmp" && mv "${OUTPUT_FILE}.tmp" "$OUTPUT_FILE"
        return 0
    fi

    # --- Case 2: Within 10k limit ---
    if [[ "$overall_total" -le "$MAX_RESULTS" ]]; then
        echo "Within 10k limit, using simple pagination..."
        fetch_with_pagination "" >> "$tmp_issues" || exit 1
    else
        # --- Case 3: Over 10k — split by type ---
        echo "Total $overall_total exceeds 10k limit, splitting by type..."
        local types=("BUG" "VULNERABILITY" "CODE_SMELL")
        for t in "${types[@]}"; do
            local type_total
            type_total=$(get_total "types=$t") || exit 1
            echo "  Type $t: $type_total issues"

            if [[ "$type_total" -eq 0 ]]; then
                continue
            fi

            if [[ "$type_total" -le "$MAX_RESULTS" ]]; then
                fetch_with_pagination "types=$t" >> "$tmp_issues" || exit 1
            else
                # Split further by impactSeverities
                echo "  Type $t exceeds 10k, splitting by impactSeverities..."
                local severities=("HIGH" "MEDIUM" "LOW")
                for sev in "${severities[@]}"; do
                    local sev_total
                    sev_total=$(get_total "types=$t&impactSeverities=$sev") || exit 1
                    echo "    Type $t / Severity $sev: $sev_total issues"

                    if [[ "$sev_total" -eq 0 ]]; then
                        continue
                    fi

                    local rc=0
                    fetch_with_pagination "types=$t&impactSeverities=$sev" >> "$tmp_issues" || rc=$?
                    if [[ $rc -eq 2 ]]; then
                        # Still over 10k — split by rules first (more reliable than date range)
                        echo "    Type $t / Severity $sev exceeds 10k, splitting by rules..."
                        split_by_rules "types=$t&impactSeverities=$sev" >> "$tmp_issues" || exit 1
                    elif [[ $rc -ne 0 ]]; then
                        exit 1
                    fi
                done
            fi
        done
    fi

    # --- Deduplicate by key and build final JSON ---
    local fetched_count
    fetched_count=$(wc -l < "$tmp_issues" | tr -d ' ')
    echo "Raw fetched: $fetched_count issue lines"

    # Deduplicate using jq (by .key field)
    echo '{"issues": [' > "$OUTPUT_FILE"
    if [[ "$fetched_count" -gt 0 ]]; then
        jq -s 'unique_by(.key)' "$tmp_issues" | jq -c '.[]' | paste -sd ',' - >> "$OUTPUT_FILE"
    fi
    echo '],' >> "$OUTPUT_FILE"
    echo '"metadata": {' >> "$OUTPUT_FILE"
    echo "  \"project\": \"$PROJECT_KEY\"," >> "$OUTPUT_FILE"
    echo "  \"total\": $overall_total," >> "$OUTPUT_FILE"
    echo "  \"fetchedAt\": \"$(date -Iseconds)\"," >> "$OUTPUT_FILE"
    echo "  \"sonarqubeUrl\": \"$SONARQUBE_URL\"" >> "$OUTPUT_FILE"
    echo '}' >> "$OUTPUT_FILE"
    echo '}' >> "$OUTPUT_FILE"

    # Validate and format JSON
    jq '.' "$OUTPUT_FILE" > "${OUTPUT_FILE}.tmp" && mv "${OUTPUT_FILE}.tmp" "$OUTPUT_FILE"

    local final_count
    final_count=$(jq '.issues | length' "$OUTPUT_FILE")
    echo "Deduplicated: $final_count unique issues"
}

# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------

fetch_all_issues

echo ""
echo "Creating category files..."

# Split by Severity (Clean Code Taxonomy)
echo "  - By Severity..."
for severity in HIGH MEDIUM LOW; do
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
ATTRIBUTES=$(jq -r '[.issues[].cleanCodeAttribute] | unique | .[]' "$OUTPUT_FILE" 2>/dev/null) || true
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

# Impact-based Severity (Clean Code Taxonomy)
echo "=== Severity (Impact 기준) ==="
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

# Software Quality
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

# Clean Code Attribute
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

# Type
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

# Status
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
echo "  │   └── LOW.json"
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
