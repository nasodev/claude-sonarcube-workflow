#!/usr/bin/env python3
"""
이슈 상태를 업데이트하는 스크립트 (Sheets + SQLite 자동 추적)

상태값에 따라 실행 추적이 자동으로 관리됩니다:
  ANALYZING       → start_execution(phase='analyze') 자동
  JIRA_CREATED    → complete_execution(phase='analyze', 'success') 자동
  REPORT_CREATED  → complete_execution(phase='analyze', 'success') 자동
  DEVELOPING      → start_execution(phase='develop') 자동
  DONE            → complete_execution(phase='develop', 'success') 자동
  BLOCKED         → complete_running_for_issue('blocked') 자동

--issue-key 생략 시 스프레드시트 ROW에서 SonarQube키를 자동 추출합니다.

Usage:
  python sheets_update.py -r ROW -s SPREADSHEET_ID --status ANALYZING
  python sheets_update.py -r ROW -s SPREADSHEET_ID --status BLOCKED --error "4 fails"

Legacy (하위 호환, 자동 추적이 우선):
  python sheets_update.py -r ROW -s SPREADSHEET_ID --start-exec --issue-key KEY --phase analyze
  python sheets_update.py -r ROW -s SPREADSHEET_ID --complete-exec success --issue-key KEY --phase analyze
"""

import argparse
import logging
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COMMON_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(SCRIPT_DIR)), 'sonar-common', 'scripts')
sys.path.insert(0, COMMON_SCRIPTS)

from env_loader import load_env
from sheets_client import SheetsClient, COL_SONAR_KEY

# 환경변수 로드
load_env()

logger = logging.getLogger(__name__)

# ── 상태 기반 자동 추적 매핑 ──
# 'start': (phase,) → start_execution 호출
# 'complete': (phase, status) → complete_execution 호출
# 'complete_all': (status,) → complete_running_for_issue 호출 (phase 무관)
_STATUS_AUTO_TRACKING = {
    'ANALYZING':      ('start', 'analyze'),
    'JIRA_CREATED':   ('complete', 'analyze', 'success'),
    'REPORT_CREATED': ('complete', 'analyze', 'success'),
    'DEVELOPING':     ('start', 'develop'),
    'DONE':           ('complete', 'develop', 'success'),
    'BLOCKED':        ('complete_all', 'blocked'),
}


def _get_tracker():
    """TrackingDB 싱글톤을 안전하게 가져옴. 실패 시 None."""
    try:
        from tracking_db import get_tracker
        return get_tracker()
    except Exception as e:
        logger.warning(f"Could not load tracking_db: {e}")
        return None


def _resolve_issue_key(client, args):
    """issue_key를 결정. 명시적 인자 → 스프레드시트 ROW fallback."""
    if args.issue_key:
        return args.issue_key
    # fallback: 스프레드시트에서 SonarQube키 읽기
    try:
        all_values = client.worksheet.get_all_values()
        if args.row < 2 or args.row > len(all_values):
            return None
        row_data = all_values[args.row - 1]
        if COL_SONAR_KEY < len(row_data):
            key = row_data[COL_SONAR_KEY].strip()
            if key:
                return key
    except Exception as e:
        logger.warning(f"Failed to read issue key from row {args.row}: {e}")
    return None


def _auto_track(tracker, issue_key, status, args):
    """상태값에 따라 자동으로 실행 추적 수행."""
    rule = _STATUS_AUTO_TRACKING.get(status)
    if not rule:
        return

    action = rule[0]

    if action == 'start':
        phase = rule[1]
        exec_id = tracker.start_execution(
            issue_key=issue_key,
            sheet_row=args.row,
            phase=phase,
            attempt=args.attempt or 1
        )
        if exec_id is not None:
            print(f"auto_track: start_execution({phase}) -> exec_id={exec_id}")

    elif action == 'complete':
        phase = rule[1]
        completion_status = rule[2]
        ok = tracker.complete_execution(
            issue_key=issue_key,
            phase=phase,
            attempt=args.attempt,
            status=completion_status,
            error_message=args.error
        )
        if ok:
            print(f"auto_track: complete_execution({phase}, {completion_status})")
        else:
            # running 레코드가 없으면 경고만 (start가 누락된 경우)
            logger.warning(f"auto_track: no running {phase} execution for {issue_key}")

    elif action == 'complete_all':
        completion_status = rule[1]
        closed = tracker.complete_running_for_issue(
            issue_key=issue_key,
            status=completion_status,
            error_message=args.error
        )
        if closed > 0:
            print(f"auto_track: complete_running_for_issue({completion_status}) -> closed {closed}")


def main():
    parser = argparse.ArgumentParser(description='Update issue status')
    parser.add_argument('-r', '--row', type=int, required=True, help='Row number')
    parser.add_argument('-s', '--spreadsheet', required=True, help='Spreadsheet ID')
    parser.add_argument('-w', '--worksheet', help='Worksheet name (optional)')
    parser.add_argument('--status', help='New status')
    parser.add_argument('--jira', help='Jira key')
    parser.add_argument('--error', help='Error message')
    parser.add_argument('--report-url', help='Report URL')
    parser.add_argument('--attempt-analysis', type=int, help='Analysis attempt count')
    parser.add_argument('--attempt-fix', type=int, help='Fix attempt count')
    parser.add_argument('--approve', help='Approver name (sets status to APPROVED)')
    # 추적 DB 인자 (하위 호환)
    parser.add_argument('--issue-key', help='이슈 키 (생략 시 ROW에서 자동 추출)')
    parser.add_argument('--phase', help='실행 단계 (legacy, 자동 추적 시 불필요)')
    parser.add_argument('--attempt', type=int, help='시도 횟수 (추적용)')
    parser.add_argument('--start-exec', action='store_true', help='[legacy] 실행 시작 기록')
    parser.add_argument('--complete-exec', choices=['success', 'failed', 'blocked'],
                        help='[legacy] 실행 완료 기록')
    parser.add_argument('--error-type', help='에러 유형 (추적용)')
    parser.add_argument('--from-status', help='이전 상태 (전이 기록용)')
    args = parser.parse_args()

    # ── Sheets 업데이트 (기존 로직) ──
    client = SheetsClient(args.spreadsheet, args.worksheet)

    if args.status:
        client.update_status(args.row, args.status)
        print(f"Updated status to: {args.status}")

    if args.jira:
        client.update_jira_key(args.row, args.jira)
        print(f"Updated Jira key to: {args.jira}")

    if args.error:
        client.update_error(args.row, args.error)
        print(f"Updated error message")

    if args.report_url:
        client.update_report_url(args.row, args.report_url)
        print(f"Updated report URL")

    if args.attempt_analysis is not None:
        client.update_attempt(args.row, 'analysis', args.attempt_analysis)
        print(f"Updated analysis attempt to: {args.attempt_analysis}")

    if args.attempt_fix is not None:
        client.update_attempt(args.row, 'fix', args.attempt_fix)
        print(f"Updated fix attempt to: {args.attempt_fix}")

    if args.approve:
        client.approve_issue(args.row, args.approve)
        print(f"Approved by: {args.approve}")

    # ── SQLite 추적 (자동 + legacy) ──
    try:
        tracker = _get_tracker()
        if tracker is None:
            sys.exit(0)

        # issue_key 결정: 명시적 → ROW fallback
        issue_key = _resolve_issue_key(client, args)
        if not issue_key:
            # issue_key를 어디서도 얻을 수 없으면 추적 스킵
            sys.exit(0)

        # stale 실행 정리 (30분 이상 running)
        tracker.cleanup_stale(threshold_minutes=30)

        # 상태 전이 기록
        if args.status:
            from_status = args.from_status or ''
            tracker.record_transition(
                issue_key=issue_key,
                from_status=from_status,
                to_status=args.status,
                triggered_by='sheets_update.py',
                attempt=args.attempt
            )

        # 에러 기록
        if args.error:
            tracker.log_error(
                issue_key=issue_key,
                phase=args.phase or 'unknown',
                attempt=args.attempt or 1,
                error_type=args.error_type or 'general',
                error_message=args.error
            )

        # ── 자동 추적 (상태값 기반) ──
        if args.status:
            _auto_track(tracker, issue_key, args.status, args)

        # ── Legacy 추적 (하위 호환, 자동 추적이 이미 처리한 경우 중복 방지) ──
        if args.start_exec and args.status not in _STATUS_AUTO_TRACKING:
            exec_id = tracker.start_execution(
                issue_key=issue_key,
                sheet_row=args.row,
                phase=args.phase or 'unknown',
                attempt=args.attempt or 1
            )
            if exec_id is not None:
                print(f"exec_id={exec_id}")

        if args.complete_exec and args.status not in _STATUS_AUTO_TRACKING:
            tracker.complete_execution(
                issue_key=issue_key,
                phase=args.phase or 'unknown',
                attempt=args.attempt,
                status=args.complete_exec,
                error_message=args.error
            )

    except Exception as e:
        logger.warning(f"Tracking DB write failed: {e}")

    sys.exit(0)


if __name__ == '__main__':
    main()
