#!/usr/bin/env python3
"""
환경변수 로더 - 모든 스킬에서 공통 사용
Usage:
    from env_loader import load_env, get_env
    load_env()
    token = get_env('SONARCUBE_TOKEN')
"""

import os
import logging
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    # python-dotenv가 없으면 수동으로 .env 파싱
    def load_dotenv(dotenv_path):
        if not dotenv_path.exists():
            return False
        with open(dotenv_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())
        return True

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# 프로젝트 루트 경로 계산
# 1. CLAUDE_PROJECT_DIR (hooks 컨텍스트)
# 2. 스크립트 위치에서 상위 탐색 (로컬 .claude/skills 환경)
# 3. CWD에서 .claude 탐색 (플러그인 Bash 실행 컨텍스트 — CWD가 프로젝트 루트)
SCRIPT_DIR = Path(__file__).parent
if os.environ.get('CLAUDE_PROJECT_DIR'):
    ROOT_DIR = Path(os.environ['CLAUDE_PROJECT_DIR'])
else:
    # sonar-common/scripts/ → sonar-common/ → skills/ → .claude/ → 프로젝트 루트
    _candidate = SCRIPT_DIR.parent.parent.parent.parent
    if (_candidate / '.claude').is_dir():
        ROOT_DIR = _candidate
    else:
        # 플러그인 환경: CWD가 프로젝트 루트
        ROOT_DIR = Path.cwd()

_env_loaded = False


def load_env(env_path: Path = None) -> bool:
    """
    .env 파일 로드

    Args:
        env_path: .env 파일 경로 (기본값: 프로젝트 루트/.env)

    Returns:
        로드 성공 여부
    """
    global _env_loaded

    if _env_loaded:
        return True

    if env_path is None:
        env_path = ROOT_DIR / '.env'

    if not env_path.exists():
        logger.warning(f".env file not found: {env_path}")
        logger.info(f"Copy .env.example to {env_path} and configure it")
        return False

    load_dotenv(env_path)
    _env_loaded = True
    logger.info(f"Loaded environment from: {env_path}")
    return True


def get_env(key: str, required: bool = True, default: str = None) -> str:
    """
    환경변수 가져오기

    Args:
        key: 환경변수 이름
        required: 필수 여부 (True이면 없을 때 예외 발생)
        default: 기본값 (required=False일 때 사용)

    Returns:
        환경변수 값

    Raises:
        ValueError: required=True이고 환경변수가 없을 때
    """
    value = os.environ.get(key, default)

    if required and not value:
        raise ValueError(f"Required environment variable not set: {key}")

    return value


def get_root_dir() -> Path:
    """프로젝트 루트 디렉토리 반환"""
    return ROOT_DIR


def get_credentials_path() -> Path:
    """Google 인증 파일 경로 반환"""
    creds_file = get_env('GOOGLE_CREDENTIALS', required=False, default='credentials.json')
    return ROOT_DIR / creds_file
