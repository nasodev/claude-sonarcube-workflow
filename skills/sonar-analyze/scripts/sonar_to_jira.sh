#!/bin/bash

# SonarQube Issues to Jira Creator
# Usage: ./sonar_to_jira.sh -f issues.json [-p JIRA_PROJECT] [-n max_count] [--dry-run]
# Example: ./sonar_to_jira.sh -f data/odin-addsvc-extsvc-backend_xxx/by_severity/HIGH.json -n 5

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

ENV_FILE="$SONAR_PROJECT_DIR/.env"

# Load credentials from .env
if [[ ! -f "$ENV_FILE" ]]; then
    echo "Error: .env file not found at $ENV_FILE"
    exit 1
fi
source "$ENV_FILE" 2>&1 || { echo "Error: .env 로드 실패"; exit 1; }

if [[ -z "$JIRA_URL" || -z "$JIRA_ID" || -z "$JIRA_PASSWORD" ]]; then
    echo "Error: JIRA_URL, JIRA_ID, JIRA_PASSWORD must be set in .env file"
    exit 1
fi

# Default values from .env
MAX_COUNT=0
PROJECT_KEY="${PROJECT_KEY:-}"
DRY_RUN=false
INPUT_FILE=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -p) PROJECT_KEY="$2"; shift 2 ;;
        -f) INPUT_FILE="$2"; shift 2 ;;
        -n) MAX_COUNT="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        -h|--help)
            echo "Usage: $0 -p JIRA_PROJECT -f issues.json [-n max_count] [--dry-run]"
            echo ""
            echo "Options:"
            echo "  -p          Jira Project Key (required)"
            echo "  -f          SonarQube issues JSON file (required)"
            echo "  -n          Max number of issues to create (default: all)"
            echo "  --dry-run   Preview without creating issues"
            echo ""
            echo "Example:"
            echo "  $0 -p ODIN -f data/xxx/by_severity/HIGH.json -n 5 --dry-run"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Validate required arguments
if [[ -z "$PROJECT_KEY" ]]; then
    echo "Error: PROJECT_KEY not set. Use -p option or set in .env file"
    exit 1
fi

if [[ -z "$INPUT_FILE" ]]; then
    echo "Error: INPUT_FILE (-f) is required"
    echo "Use -h for help"
    exit 1
fi

if [[ ! -f "$INPUT_FILE" ]]; then
    echo "Error: File not found: $INPUT_FILE"
    exit 1
fi

# Check if file has .issues array or is just an array
HAS_ISSUES_KEY=$(jq 'has("issues")' "$INPUT_FILE")
if [[ "$HAS_ISSUES_KEY" == "true" ]]; then
    JQ_PREFIX=".issues"
else
    JQ_PREFIX="."
fi

TOTAL=$(jq "$JQ_PREFIX | length" "$INPUT_FILE")
echo "Found $TOTAL issues in $INPUT_FILE"

if [[ "$MAX_COUNT" -gt 0 ]]; then
    PROCESS_COUNT=$MAX_COUNT
else
    PROCESS_COUNT=$TOTAL
fi

echo "Processing $PROCESS_COUNT issues..."
echo ""

if [[ "$DRY_RUN" == true ]]; then
    echo "=== DRY RUN MODE - No issues will be created ==="
    echo ""
fi

# Map SonarQube severity to Jira issue type
get_issue_type() {
    local severity="$1"
    local type="$2"

    if [[ "$type" == "BUG" ]]; then
        echo "Bug"
    elif [[ "$type" == "VULNERABILITY" ]]; then
        echo "Bug"
    else
        echo "Task"
    fi
}

# Process each issue
CREATED=0
FAILED=0

for ((i=0; i<PROCESS_COUNT; i++)); do
    ISSUE=$(jq -c "$JQ_PREFIX[$i]" "$INPUT_FILE")

    RULE=$(echo "$ISSUE" | jq -r '.rule')
    MESSAGE=$(echo "$ISSUE" | jq -r '.message')
    COMPONENT=$(echo "$ISSUE" | jq -r '.component' | sed 's/.*://')
    LINE=$(echo "$ISSUE" | jq -r '.line // "N/A"')
    SEVERITY=$(echo "$ISSUE" | jq -r '.impacts[0].severity // .severity')
    TYPE=$(echo "$ISSUE" | jq -r '.type')
    QUALITY=$(echo "$ISSUE" | jq -r '.impacts[0].softwareQuality // "N/A"')
    SONAR_KEY=$(echo "$ISSUE" | jq -r '.key')

    # Create summary
    SUMMARY="[SonarQube][$SEVERITY] $MESSAGE"
    # Truncate if too long
    SUMMARY="${SUMMARY:0:250}"

    # Create description
    DESCRIPTION="h3. SonarQube Issue

*Rule:* $RULE
*Severity:* $SEVERITY
*Quality:* $QUALITY
*Type:* $TYPE

*File:* $COMPONENT
*Line:* $LINE

*Message:*
{quote}$MESSAGE{quote}

----
_SonarQube Issue Key: $SONAR_KEY_"

    ISSUE_TYPE=$(get_issue_type "$SEVERITY" "$TYPE")

    echo "[$((i+1))/$PROCESS_COUNT] $COMPONENT:$LINE"
    echo "  Summary: ${SUMMARY:0:80}..."
    echo "  Type: $ISSUE_TYPE"

    if [[ "$DRY_RUN" == true ]]; then
        echo "  [DRY RUN] Would create issue"
        CREATED=$((CREATED+1))
    else
        # Create JSON payload
        JSON_PAYLOAD=$(jq -n \
            --arg project "$PROJECT_KEY" \
            --arg summary "$SUMMARY" \
            --arg desc "$DESCRIPTION" \
            --arg type "$ISSUE_TYPE" \
            '{
                fields: {
                    project: { key: $project },
                    summary: $summary,
                    description: $desc,
                    issuetype: { name: $type }
                }
            }')

        # Make API request
        RESPONSE=$(curl -w "\n%{http_code}" \
            -u "$JIRA_ID:$JIRA_PASSWORD" \
            -X POST \
            -H "Content-Type: application/json" \
            -d "$JSON_PAYLOAD" \
            "$JIRA_URL/rest/api/2/issue" 2>&1)

        if [[ $? -ne 0 ]]; then
            echo "  FAILED (네트워크 오류)"
            FAILED=$((FAILED+1))
            continue
        fi

        HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
        BODY=$(echo "$RESPONSE" | sed '$d')

        if [[ "$HTTP_CODE" -ge 200 && "$HTTP_CODE" -lt 300 ]]; then
            JIRA_KEY=$(echo "$BODY" | jq -r '.key')
            echo "  Created: $JIRA_URL/browse/$JIRA_KEY"
            CREATED=$((CREATED+1))
        else
            echo "  FAILED (HTTP $HTTP_CODE)"
            FAILED=$((FAILED+1))
        fi

        # Rate limiting - small delay between requests
        sleep 0.5
    fi
    echo ""
done

echo "==============================================="
echo "                    RESULT                     "
echo "==============================================="
echo "Created: $CREATED"
echo "Failed: $FAILED"
echo "Total: $PROCESS_COUNT"

if [[ "$DRY_RUN" == true ]]; then
    echo ""
    echo "This was a dry run. Remove --dry-run to create issues."
fi
