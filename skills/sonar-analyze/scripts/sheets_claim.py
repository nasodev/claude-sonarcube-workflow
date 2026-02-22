#!/usr/bin/env python3
"""
DEPRECATED: claim 단계가 제거되었습니다. run 명령어가 NEW 상태의 이슈를 직접 처리합니다.
이 스크립트는 하위 호환성을 위해 유지되지만 더 이상 워크플로우에서 호출되지 않습니다.

스프레드시트에서 N개 이슈를 claim하거나 전체 이슈를 팀에게 분배하는 스크립트
Usage:
  python sheets_claim.py -n 5 -a "담당자이름" -s SPREADSHEET_ID
  python sheets_claim.py --distribute -s SPREADSHEET_ID
  python sheets_claim.py --distribute --members "a,b,c" -s SPREADSHEET_ID
"""

import argparse
import json
import logging
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COMMON_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(SCRIPT_DIR)), 'sonar-common', 'scripts')
sys.path.insert(0, COMMON_SCRIPTS)

from env_loader import load_env
from sheets_client import SheetsClient

# 환경변수 로드
load_env()

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description='Claim issues from spreadsheet')
    parser.add_argument('-n', '--count', type=int, help='Number of issues to claim')
    parser.add_argument('-a', '--assignee', help='Assignee name')
    parser.add_argument('-s', '--spreadsheet', required=True, help='Spreadsheet ID')
    parser.add_argument('-w', '--worksheet', help='Worksheet name (optional)')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--distribute', action='store_true', help='Distribute all waiting issues to team members')
    parser.add_argument('--members', help='Comma-separated member names (default: TEAM_MEMBERS env)')
    args = parser.parse_args()

    # 모드 검증: --distribute 또는 -n/-a 중 하나 필수
    if args.distribute:
        if args.count is not None:
            parser.error('--distribute and -n are mutually exclusive')
        members_str = args.members or os.environ.get('TEAM_MEMBERS', '')
        if not members_str:
            parser.error('--members or TEAM_MEMBERS env required for --distribute')
        members = [m.strip() for m in members_str.split(',') if m.strip()]
        if len(members) < 2:
            parser.error('At least 2 team members required for --distribute')
        _distribute_mode(args, members)
    else:
        if args.count is None:
            parser.error('-n/--count is required when not using --distribute')
        if args.assignee is None:
            parser.error('-a/--assignee is required when not using --distribute')
        _claim_mode(args)


def _claim_mode(args):
    """기존 claim 모드"""
    client = SheetsClient(args.spreadsheet, args.worksheet)
    claimed = client.claim_issues(args.count, args.assignee)

    # ── SQLite 추적: claim 전이 기록 ──
    if claimed:
        try:
            from tracking_db import get_tracker
            tracker = get_tracker()
            for issue in claimed:
                tracker.record_transition(
                    issue_key=issue.get('SonarQube키', ''),
                    from_status='대기',
                    to_status='CLAIMED',
                    triggered_by='sheets_claim.py'
                )
        except Exception as e:
            logger.warning(f"Tracking DB write failed: {e}")

    if args.json:
        print(json.dumps({
            'status': 'success',
            'claimed_count': len(claimed),
            'issues': [{'row': i['_row'], 'file': i.get('파일'), 'line': i.get('라인')} for i in claimed]
        }, ensure_ascii=False))
    else:
        if not claimed:
            print("No issues available to claim")
        else:
            print(f"Claimed {len(claimed)} issues:")
            for issue in claimed:
                print(f"  - [{issue.get('심각도')}] {issue.get('파일')}:{issue.get('라인')}")
                print(f"    {issue.get('메시지')[:60]}...")

    sys.exit(0)


def _distribute_mode(args, members):
    """분배 모드: 전체 대기 이슈를 팀 멤버에게 균등 분배"""
    client = SheetsClient(args.spreadsheet, args.worksheet)
    result = client.distribute_issues(members)

    total = sum(len(v) for v in result.values())

    # ── SQLite 추적: distribute 전이 기록 ──
    if total > 0:
        try:
            from tracking_db import get_tracker
            tracker = get_tracker()
            for member, issues in result.items():
                for issue in issues:
                    tracker.record_transition(
                        issue_key=issue.get('SonarQube키', ''),
                        from_status='대기',
                        to_status='CLAIMED',
                        triggered_by=f'sheets_claim.py --distribute ({member})'
                    )
        except Exception as e:
            logger.warning(f"Tracking DB write failed: {e}")

    if args.json:
        print(json.dumps({
            'status': 'success',
            'total_distributed': total,
            'distribution': {
                m: {
                    'count': len(issues),
                    'issues': [{'row': i['_row'], 'file': i.get('파일'), 'line': i.get('라인'), 'severity': i.get('심각도')} for i in issues]
                }
                for m, issues in result.items()
            }
        }, ensure_ascii=False))
    else:
        if total == 0:
            print("No waiting issues to distribute")
        else:
            print(f"Distributed {total} issues to {len(members)} members:")
            for member, issues in result.items():
                print(f"\n  {member} ({len(issues)} issues):")
                for issue in issues:
                    print(f"    - [{issue.get('심각도')}] {issue.get('파일')}:{issue.get('라인')}")

    sys.exit(0)


if __name__ == '__main__':
    main()
