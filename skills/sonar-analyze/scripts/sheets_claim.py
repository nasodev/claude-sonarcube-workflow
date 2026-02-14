#!/usr/bin/env python3
"""
스프레드시트에서 N개 이슈를 claim하는 스크립트
Usage: python sheets_claim.py -n 5 -a "담당자이름" -s SPREADSHEET_ID
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
    parser.add_argument('-n', '--count', type=int, required=True, help='Number of issues to claim')
    parser.add_argument('-a', '--assignee', required=True, help='Assignee name')
    parser.add_argument('-s', '--spreadsheet', required=True, help='Spreadsheet ID')
    parser.add_argument('-w', '--worksheet', help='Worksheet name (optional)')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    args = parser.parse_args()

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


if __name__ == '__main__':
    main()
