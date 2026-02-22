#!/usr/bin/env python3
"""
내 담당 이슈 중 처리할 이슈를 가져오는 스크립트
Usage: python sheets_get_issue.py -a "담당자이름" -s SPREADSHEET_ID [--status NEW]
"""

import argparse
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COMMON_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(SCRIPT_DIR)), 'sonar-common', 'scripts')
sys.path.insert(0, COMMON_SCRIPTS)

from env_loader import load_env
from sheets_client import SheetsClient

# 환경변수 로드
load_env()


def main():
    parser = argparse.ArgumentParser(description='Get my issue from spreadsheet')
    parser.add_argument('-a', '--assignee', required=True, help='Assignee name')
    parser.add_argument('-s', '--spreadsheet', required=True, help='Spreadsheet ID')
    parser.add_argument('-w', '--worksheet', help='Worksheet name (optional)')
    parser.add_argument('--status', nargs='+', default=['NEW', 'ANALYZING', 'REVIEW_ANALYSIS',
                                                         'JIRA_CREATED', 'DEVELOPING', 'REVIEW_FIX', 'TESTING'],
                        help='Status filter')
    parser.add_argument('--all', action='store_true', help='Get all matching issues')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    args = parser.parse_args()

    client = SheetsClient(args.spreadsheet, args.worksheet)
    issues = client.get_my_issues(args.assignee, args.status)

    if not issues:
        if args.json:
            print(json.dumps({'status': 'empty', 'issues': []}))
        else:
            print("No issues found")
        sys.exit(1)

    if args.all:
        output_issues = issues
    else:
        output_issues = [issues[0]]

    if args.json:
        print(json.dumps({'status': 'success', 'issues': output_issues}, ensure_ascii=False, indent=2))
    else:
        for issue in output_issues:
            print(f"Issue found:")
            print(f"  Row: {issue['_row']}")
            print(f"  Status: {issue.get('상태')}")
            print(f"  Severity: {issue.get('심각도')}")
            print(f"  File: {issue.get('파일')}:{issue.get('라인')}")
            print(f"  Message: {issue.get('메시지')}")
            print(f"  Rule: {issue.get('규칙')}")
            print(f"  SonarQube Key: {issue.get('SonarQube키')}")
            if issue.get('Jira키'):
                print(f"  Jira Key: {issue.get('Jira키')}")
            print()

    sys.exit(0)


if __name__ == '__main__':
    main()
