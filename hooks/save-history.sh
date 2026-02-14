#!/bin/bash
# Save conversation history when DEBUG_MODE is enabled
# This hook is triggered on Stop, SubagentStop, and SessionEnd events
#
# Issue key extraction:
#   Sub-agent transcripts contain reports/{key}/ or worktrees/{key}/ paths
#   from tool calls (Read, Write, Bash). We extract the most frequent key
#   as the issue identifier. This is reliable because each sub-agent handles
#   exactly one issue (1:1 mapping enforced by orchestrator).
#
# DO NOT use set -e — individual failures should be logged, not cause silent exit

# Log hook invocation for debugging
echo "[HOOK] save-history.sh invoked at $(date)" >> /tmp/claude-hook-debug.log

# Load .env file
ENV_FILE="$CLAUDE_PROJECT_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
    # Remove full-line comments and inline comments, then export
    export $(grep -v '^#' "$ENV_FILE" | sed 's/#.*//' | xargs)
fi

# Check DEBUG_MODE
echo "[HOOK] DEBUG_MODE=$DEBUG_MODE, CLAUDE_PROJECT_DIR=$CLAUDE_PROJECT_DIR" >> /tmp/claude-hook-debug.log
if [[ "$DEBUG_MODE" != "true" ]]; then
    echo "[HOOK] DEBUG_MODE is not true, exiting" >> /tmp/claude-hook-debug.log
    exit 0
fi
echo "[HOOK] DEBUG_MODE is true, proceeding..." >> /tmp/claude-hook-debug.log

# Read JSON input from stdin
INPUT=$(cat)

# Extract information from hook input
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
HOOK_EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // empty')

# Sub-agent specific fields
AGENT_TRANSCRIPT=$(echo "$INPUT" | jq -r '.agent_transcript_path // empty')
AGENT_TYPE=$(echo "$INPUT" | jq -r '.agent_type // empty')
AGENT_ID=$(echo "$INPUT" | jq -r '.agent_id // empty')

# ── Issue key extraction from transcript content ──
# Searches for reports/{key}/ or worktrees/{key}/ patterns in transcript.
# These paths appear in tool calls (Read, Write, Bash) that sub-agents make
# while working on an issue.
#
# IMPORTANT: SKILL.md templates contain example paths like reports/ODIN-123/
# that pollute extraction. We validate extracted keys against actual directories
# (reports/ or worktrees/) to filter out false positives from documentation.
# Sub-agents that fail before creating any files fall back to session_id.
extract_issue_key_from_content() {
    local transcript_file="$1"
    if [[ ! -f "$transcript_file" ]]; then
        return
    fi

    # Extract all candidate keys from reports/{key} or worktrees/{key} patterns
    # Sorted by frequency (most frequent = most likely the real issue)
    local candidates
    candidates=$(grep -oE '(reports|worktrees)/[A-Za-z0-9_-]{5,}' "$transcript_file" 2>/dev/null \
        | sed 's|^reports/||; s|^worktrees/||' \
        | sort | uniq -c | sort -rn | awk '{print $2}')

    if [[ -z "$candidates" ]]; then
        return
    fi

    # Validate candidates against actual directories to filter out SKILL.md examples
    local key
    while IFS= read -r key; do
        [[ -z "$key" ]] && continue
        if [[ -d "$CLAUDE_PROJECT_DIR/reports/$key" ]] || [[ -d "$CLAUDE_PROJECT_DIR/worktrees/$key" ]]; then
            echo "$key"
            return
        fi
    done <<< "$candidates"

    # No validated key found (all candidates were from SKILL.md examples)
}

# Determine issue key
ISSUE_KEY=""

# 1) For SubagentStop: extract from agent transcript (each sub-agent works on exactly one issue)
if [[ "$HOOK_EVENT" == "SubagentStop" ]] && [[ -n "$AGENT_TRANSCRIPT" ]]; then
    ISSUE_KEY=$(extract_issue_key_from_content "$AGENT_TRANSCRIPT")
    echo "[HOOK] Extracted issue key from agent transcript content: ${ISSUE_KEY:-not found}" >> /tmp/claude-hook-debug.log
fi

# 2) Fallback: try main transcript (for Stop/SessionEnd, or if agent transcript had no key)
if [[ -z "$ISSUE_KEY" ]] && [[ -n "$TRANSCRIPT_PATH" ]]; then
    ISSUE_KEY=$(extract_issue_key_from_content "$TRANSCRIPT_PATH")
    echo "[HOOK] Extracted issue key from main transcript content: ${ISSUE_KEY:-not found}" >> /tmp/claude-hook-debug.log
fi

# 3) Final fallback: use session ID (no ls -t — it's unreliable in parallel execution)
if [[ -z "$ISSUE_KEY" ]]; then
    ISSUE_KEY="session_${SESSION_ID:-unknown}"
    echo "[HOOK] Fallback to session ID: $ISSUE_KEY" >> /tmp/claude-hook-debug.log
fi

# Create history directory
HISTORY_DIR="$CLAUDE_PROJECT_DIR/history/$ISSUE_KEY"
mkdir -p "$HISTORY_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DATETIME=$(date '+%Y-%m-%d %H:%M:%S')

# Function to extract summary from transcript
extract_summary() {
    local transcript_file="$1"
    local output_file="$2"

    if [[ ! -f "$transcript_file" ]]; then
        return
    fi

    # Extract skill name from first user message (Base directory for this skill: .../skill-name)
    local skill_name=$(head -1 "$transcript_file" | jq -r '.message.content // ""' 2>/dev/null | grep -oE 'skills/[^/[:space:]]+' | sed 's/skills\///' | head -1)

    # Extract tool calls (name only)
    local tools_used=$(jq -r 'select(.type == "assistant") | .message.content[]? | select(.type == "tool_use") | .name' "$transcript_file" 2>/dev/null | sort | uniq -c | sort -rn | head -10)

    # Extract Bash commands executed
    local bash_commands=$(jq -r 'select(.type == "assistant") | .message.content[]? | select(.type == "tool_use" and .name == "Bash") | .input.command' "$transcript_file" 2>/dev/null | head -10)

    # Extract final assistant text response (last text block, max 1000 chars)
    local final_response=$(jq -r 'select(.type == "assistant") | .message.content[]? | select(.type == "text") | .text' "$transcript_file" 2>/dev/null | tail -1 | head -c 1000)

    # Extract real errors from tool results (exclude script content)
    local errors=$(jq -r 'select(.type == "user") | .message.content[]? | select(.type == "tool_result") | .content' "$transcript_file" 2>/dev/null | grep -iE "^(error|failed|exception|traceback)" | head -5)

    # Count total tool calls
    local tool_count=$(jq -r 'select(.type == "assistant") | .message.content[]? | select(.type == "tool_use") | .name' "$transcript_file" 2>/dev/null | wc -l | tr -d ' ')

    # Write summary
    cat > "$output_file" << EOF
# 작업 요약

| 항목 | 값 |
|-----|-----|
| 시간 | $DATETIME |
| 스킬 | ${skill_name:-알 수 없음} |
| 이벤트 | $HOOK_EVENT |
| 이슈 키 | $ISSUE_KEY |
| 도구 호출 횟수 | ${tool_count:-0} |

## 사용된 도구

\`\`\`
${tools_used:-없음}
\`\`\`

## 실행된 명령어

\`\`\`bash
${bash_commands:-없음}
\`\`\`

## 최종 결과

${final_response:-응답 없음}

EOF

    # Add errors section if any
    if [[ -n "$errors" ]]; then
        cat >> "$output_file" << EOF
## 오류

\`\`\`
$errors
\`\`\`

EOF
    fi
}

# ── Save transcripts based on event type ──
SUMMARY_TRANSCRIPT=""

if [[ "$HOOK_EVENT" == "SubagentStop" ]]; then
    # SubagentStop: save only the sub-agent transcript to {issue_key}/
    # The main transcript contains ALL issues and will be saved on Stop/SessionEnd
    if [[ -n "$AGENT_TRANSCRIPT" ]] && [[ -f "$AGENT_TRANSCRIPT" ]]; then
        AGENT_NAME="${AGENT_TYPE:-subagent}"
        AGENT_SHORT_ID="${AGENT_ID:0:7}"

        cp "$AGENT_TRANSCRIPT" "$HISTORY_DIR/${TIMESTAMP}_${AGENT_NAME}_${AGENT_SHORT_ID}.jsonl"
        echo "[DEBUG] Saved subagent transcript: $HISTORY_DIR/${TIMESTAMP}_${AGENT_NAME}_${AGENT_SHORT_ID}.jsonl" >&2
        SUMMARY_TRANSCRIPT="$AGENT_TRANSCRIPT"
    fi
else
    # Stop/SessionEnd: save the orchestrator's main transcript
    if [[ -n "$TRANSCRIPT_PATH" ]] && [[ -f "$TRANSCRIPT_PATH" ]]; then
        cp "$TRANSCRIPT_PATH" "$HISTORY_DIR/${TIMESTAMP}_main_${HOOK_EVENT}.jsonl"
        echo "[DEBUG] Saved main transcript: $HISTORY_DIR/${TIMESTAMP}_main_${HOOK_EVENT}.jsonl" >&2
        SUMMARY_TRANSCRIPT="$TRANSCRIPT_PATH"
    fi
fi

# Create human-readable summary
if [[ -n "$SUMMARY_TRANSCRIPT" ]] && [[ -f "$SUMMARY_TRANSCRIPT" ]]; then
    extract_summary "$SUMMARY_TRANSCRIPT" "$HISTORY_DIR/${TIMESTAMP}_summary.md"
    echo "[DEBUG] Created summary: ${TIMESTAMP}_summary.md" >&2
fi

# Save hook input metadata for debugging
echo "$INPUT" | jq '.' > "$HISTORY_DIR/${TIMESTAMP}_hook_metadata.json" 2>/dev/null

exit 0
