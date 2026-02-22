#!/usr/bin/env python3
"""
이슈 키 검증 스크립트 — ROW의 SonarQube키가 사용할 issue_key와 일치하는지 확인
Usage:
    python validate_issue_key.py -r ROW -k ISSUE_KEY -s SPREADSHEET_ID
    python validate_issue_key.py -r ROW -k ISSUE_KEY -s SPREADSHEET_ID -w WORKSHEET

Exit codes:
    0: 일치 (검증 통과)
    1: 불일치 또는 오류 (검증 실패)
"""

import argparse
import json
import logging
import sys

from env_loader import load_env
from sheets_client import SheetsClient, COL_SONAR_KEY

load_env()

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description='Validate issue key against spreadsheet row')
    parser.add_argument('-r', '--row', type=int, required=True, help='Spreadsheet row number (2-based)')
    parser.add_argument('-k', '--key', required=True, help='Expected issue key (SonarQube키)')
    parser.add_argument('-s', '--spreadsheet', required=True, help='Spreadsheet ID')
    parser.add_argument('-w', '--worksheet', help='Worksheet name (optional)')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    args = parser.parse_args()

    try:
        client = SheetsClient(args.spreadsheet, args.worksheet)
        all_values = client.worksheet.get_all_values()
    except Exception as e:
        _output(args.json, False, f"Spreadsheet access failed: {e}", args.row, args.key, '')
        sys.exit(1)

    if args.row < 2 or args.row > len(all_values):
        _output(args.json, False,
                f"Row {args.row} out of range (valid: 2-{len(all_values)})",
                args.row, args.key, '')
        sys.exit(1)

    row_data = all_values[args.row - 1]  # 0-based index

    if COL_SONAR_KEY >= len(row_data):
        _output(args.json, False,
                f"Row {args.row} has no SonarQube키 column (columns: {len(row_data)})",
                args.row, args.key, '')
        sys.exit(1)

    actual_key = row_data[COL_SONAR_KEY].strip()
    expected_key = args.key.strip()

    if actual_key == expected_key:
        _output(args.json, True, 'OK', args.row, expected_key, actual_key)
        sys.exit(0)
    else:
        _output(args.json, False,
                f"MISMATCH: row {args.row} SonarQube키='{actual_key}', expected='{expected_key}'",
                args.row, expected_key, actual_key)
        sys.exit(1)


def _output(as_json: bool, valid: bool, message: str, row: int, expected: str, actual: str):
    if as_json:
        print(json.dumps({
            'valid': valid,
            'message': message,
            'row': row,
            'expected_key': expected,
            'actual_key': actual
        }, ensure_ascii=False))
    else:
        prefix = 'PASS' if valid else 'FAIL'
        print(f"[{prefix}] {message}")


if __name__ == '__main__':
    main()
