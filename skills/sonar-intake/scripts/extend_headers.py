#!/usr/bin/env python3
"""
스프레드시트에 워크플로우용 컬럼을 추가하는 스크립트
Usage: python extend_headers.py -s SPREADSHEET_ID
"""

import argparse
import os
import sys
import logging

import gspread
from oauth2client.service_account import ServiceAccountCredentials

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COMMON_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(SCRIPT_DIR)), 'sonar-common', 'scripts')
sys.path.insert(0, COMMON_SCRIPTS)

from env_loader import load_env
from sheets_client import CREDENTIALS_FILE, SCOPES

# 환경변수 로드
load_env()

# 추가할 헤더
NEW_HEADERS = ['할당시각', '분석시도', '수정시도', '보고서', '에러', '승인자', '승인시각']


def extend_headers(spreadsheet_id: str, worksheet_name: str = None):
    """스프레드시트에 새 헤더 추가"""
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(spreadsheet_id)

    if worksheet_name:
        worksheet = spreadsheet.worksheet(worksheet_name)
    else:
        worksheet = spreadsheet.sheet1

    current_headers = worksheet.row_values(1)
    headers_to_add = [h for h in NEW_HEADERS if h not in current_headers]

    if not headers_to_add:
        logger.info("All headers already exist")
        return

    start_col = len(current_headers) + 1
    for i, header in enumerate(headers_to_add):
        worksheet.update_cell(1, start_col + i, header)
        logger.info(f"Added header: {header}")

    logger.info(f"Added {len(headers_to_add)} new headers")


def main():
    parser = argparse.ArgumentParser(description='Extend spreadsheet headers')
    parser.add_argument('-s', '--spreadsheet', required=True, help='Spreadsheet ID')
    parser.add_argument('-w', '--worksheet', help='Worksheet name (optional)')
    args = parser.parse_args()

    extend_headers(args.spreadsheet, args.worksheet)


if __name__ == '__main__':
    main()
