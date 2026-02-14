#!/bin/bash

# Jira Issue Creator Script
# Usage: ./create_jira_issue.sh -s "Summary" -d "Description" [-p PROJECT_KEY] [-t issue_type]
# Example: ./create_jira_issue.sh -s "Fix code smell" -d "Details here" -t Bug

set -euo pipefail

# 프로젝트 루트 동적 취득 (CLAUDE_PROJECT_DIR 우선, 플러그인 환경 호환)
if [[ -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
    PROJECT_ROOT="$CLAUDE_PROJECT_DIR"
else
    PROJECT_ROOT=$(git rev-parse --show-toplevel 2>&1) || {
        echo "Error: Git 프로젝트가 아닙니다: $PROJECT_ROOT"
        exit 1
    }
fi
if [[ ! -d "$PROJECT_ROOT/.claude" ]]; then
    echo "Error: 프로젝트 루트를 찾을 수 없습니다 (현재: $(pwd))"
    exit 1
fi

ENV_FILE="$PROJECT_ROOT/.env"

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
ISSUE_TYPE="Task"
PROJECT_KEY="${PROJECT_KEY:-}"
SUMMARY=""
DESCRIPTION=""

# Parse arguments
while getopts "p:s:d:t:h" opt; do
    case $opt in
        p) PROJECT_KEY="$OPTARG" ;;
        s) SUMMARY="$OPTARG" ;;
        d) DESCRIPTION="$OPTARG" ;;
        t) ISSUE_TYPE="$OPTARG" ;;
        h)
            echo "Usage: $0 -p PROJECT_KEY -s \"Summary\" -d \"Description\" [-t issue_type]"
            echo ""
            echo "Options:"
            echo "  -p  Jira Project Key (required)"
            echo "  -s  Issue Summary/Title (required)"
            echo "  -d  Issue Description (required)"
            echo "  -t  Issue Type: Bug, Task, Story, etc. (default: Task)"
            echo ""
            echo "Example:"
            echo "  $0 -p ODIN -s \"Fix unused variable\" -d \"Remove unused variable in login.py\" -t Bug"
            exit 0
            ;;
        *)
            echo "Use -h for help"
            exit 1
            ;;
    esac
done

# Validate required arguments
if [[ -z "$PROJECT_KEY" || -z "$SUMMARY" || -z "$DESCRIPTION" ]]; then
    echo "Error: PROJECT_KEY (-p), SUMMARY (-s), and DESCRIPTION (-d) are required"
    echo "Use -h for help"
    exit 1
fi

echo "Creating Jira issue..."
echo "  Project: $PROJECT_KEY"
echo "  Type: $ISSUE_TYPE"
echo "  Summary: $SUMMARY"

# Create JSON payload
JSON_PAYLOAD=$(cat <<EOF
{
    "fields": {
        "project": {
            "key": "$PROJECT_KEY"
        },
        "summary": "$SUMMARY",
        "description": "$DESCRIPTION",
        "issuetype": {
            "name": "$ISSUE_TYPE"
        }
    }
}
EOF
)

# Make API request
RESPONSE=$(curl -w "\n%{http_code}" \
    -u "$JIRA_ID:$JIRA_PASSWORD" \
    -X POST \
    -H "Content-Type: application/json" \
    -d "$JSON_PAYLOAD" \
    "$JIRA_URL/rest/api/2/issue" 2>&1)

if [[ $? -ne 0 ]]; then
    echo "Error: curl 실행 실패 (네트워크 오류)"
    echo "$RESPONSE"
    exit 1
fi

# Extract HTTP status code
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [[ "$HTTP_CODE" -ge 200 && "$HTTP_CODE" -lt 300 ]]; then
    ISSUE_KEY=$(echo "$BODY" | jq -r '.key')
    ISSUE_ID=$(echo "$BODY" | jq -r '.id')
    echo ""
    echo "Success! Issue created:"
    echo "  Key: $ISSUE_KEY"
    echo "  URL: $JIRA_URL/browse/$ISSUE_KEY"
else
    echo ""
    echo "Error creating issue (HTTP $HTTP_CODE):"
    echo "$BODY" | jq '.' 2>/dev/null || echo "$BODY"
    exit 1
fi
