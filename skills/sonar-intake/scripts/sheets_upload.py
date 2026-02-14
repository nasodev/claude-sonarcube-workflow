#!/usr/bin/env python3
"""
CSV를 Google Sheets에 업로드하는 스크립트
Usage: python sheets_upload.py -f input.csv -s SPREADSHEET_ID
"""

import argparse
import csv
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


def get_client():
    """Google Sheets 클라이언트 반환"""
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, SCOPES)
    return gspread.authorize(creds)


def format_header_row(worksheet, num_cols: int):
    """헤더 행에 배경색과 볼드 서식 적용"""
    # 컬럼 수에 맞는 범위 계산 (A1:N1 등)
    end_col = chr(ord('A') + num_cols - 1) if num_cols <= 26 else 'Z'
    header_range = f'A1:{end_col}1'

    worksheet.format(header_range, {
        'backgroundColor': {
            'red': 0.85,
            'green': 0.92,
            'blue': 0.98
        },
        'textFormat': {
            'bold': True
        },
        'horizontalAlignment': 'CENTER'
    })


def upload_csv(csv_path: str, spreadsheet_id: str, worksheet_name: str = None):
    """CSV 파일을 Google Sheets에 업로드"""
    client = get_client()
    spreadsheet = client.open_by_key(spreadsheet_id)

    # 워크시트 선택 또는 생성
    if worksheet_name:
        try:
            worksheet = spreadsheet.worksheet(worksheet_name)
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=20)
    else:
        worksheet = spreadsheet.sheet1

    # CSV 읽기
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        logger.error("CSV file is empty")
        return False, 0, 0

    # CSV 헤더
    csv_headers = rows[0]

    # 기존 데이터의 SonarQube 키 가져오기 (중복 방지)
    existing_data = worksheet.get_all_values()
    existing_keys = set()
    has_headers = False

    if existing_data and len(existing_data) > 0:
        first_row = existing_data[0]
        # 첫 행이 헤더인지 확인 (SonarQube키 컬럼이 있는지)
        if 'SonarQube키' in first_row:
            has_headers = True
            try:
                key_idx = first_row.index('SonarQube키')
                existing_keys = {row[key_idx] for row in existing_data[1:] if len(row) > key_idx}
            except ValueError:
                pass

    # 새 데이터 필터링 (중복 제거)
    try:
        new_key_idx = csv_headers.index('SonarQube키')
    except ValueError:
        new_key_idx = -1

    new_rows = []
    duplicates = 0
    for row in rows[1:]:
        if new_key_idx >= 0 and len(row) > new_key_idx:
            if row[new_key_idx] in existing_keys:
                duplicates += 1
                continue
        new_rows.append(row)

    if not new_rows:
        logger.info(f"No new issues to add (found {duplicates} duplicates)")
        return True, 0, duplicates

    # 헤더가 없으면 헤더 추가 후 데이터 추가
    if not has_headers:
        worksheet.update('A1', [csv_headers] + new_rows)
        # 헤더 행에 배경색 적용 (연한 파란색)
        format_header_row(worksheet, len(csv_headers))
        logger.info(f"Added headers and {len(new_rows)} new issues")
    else:
        # 기존 데이터 다음 행에 추가
        next_row = len(existing_data) + 1
        worksheet.update(f'A{next_row}', new_rows)
        logger.info(f"Appended {len(new_rows)} new issues starting at row {next_row}")

    logger.info(f"Uploaded {len(new_rows)} new issues (skipped {duplicates} duplicates)")
    return True, len(new_rows), duplicates


def main():
    parser = argparse.ArgumentParser(description='Upload CSV to Google Sheets')
    parser.add_argument('-f', '--file', required=True, help='CSV file path')
    parser.add_argument('-s', '--spreadsheet', required=True, help='Spreadsheet ID')
    parser.add_argument('-w', '--worksheet', help='Worksheet name (optional)')
    args = parser.parse_args()

    if not os.path.exists(args.file):
        logger.error(f"File not found: {args.file}")
        sys.exit(1)

    if not os.path.exists(CREDENTIALS_FILE):
        logger.error(f"Credentials file not found: {CREDENTIALS_FILE}")
        sys.exit(1)

    success, added, skipped = upload_csv(args.file, args.spreadsheet, args.worksheet)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
