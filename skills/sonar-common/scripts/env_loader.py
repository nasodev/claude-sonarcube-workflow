#!/usr/bin/env python3
"""
환경변수 로더 - 모든 스킬에서 공통 사용
Usage:
    from env_loader import load_env, get_env
    load_env()
    token = get_env('SONARQUBE_TOKEN')

2단계 .env 로딩:
    Stage 1: $SONAR_PROJECT_DIR/.env (프로젝트별 값 - 우선)
    Stage 2: 플러그인 루트/.env (공통 값 - 기존 키 덮어쓰지 않음)
"""

import os
import logging
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    # python-dotenv가 없으면 수동으로 .env 파싱
    def load_dotenv(dotenv_path, override=False, **kwargs):
        if not dotenv_path.exists():
            return False
        with open(dotenv_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    if override:
                        os.environ[key.strip()] = value.strip()
                    else:
                        os.environ.setdefault(key.strip(), value.strip())
        return True

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# 프로젝트 경로 계산 (backward compat: ROOT_DIR)
# 1. SONAR_PROJECT_DIR (프로젝트별 디렉토리: projects/<name>/)
# 2. CLAUDE_PROJECT_DIR (플러그인 루트)
# 3. 스크립트 위치에서 상위 탐색
# 4. CWD
SCRIPT_DIR = Path(__file__).parent
if os.environ.get('SONAR_PROJECT_DIR'):
    ROOT_DIR = Path(os.environ['SONAR_PROJECT_DIR'])
elif os.environ.get('CLAUDE_PROJECT_DIR'):
    ROOT_DIR = Path(os.environ['CLAUDE_PROJECT_DIR'])
else:
    _candidate = SCRIPT_DIR.parent.parent.parent.parent
    if (_candidate / '.claude').is_dir():
        ROOT_DIR = _candidate
    else:
        ROOT_DIR = Path.cwd()

_env_loaded = False


def get_plugin_root_dir() -> Path:
    """
    프로젝트 루트 디렉토리 반환 (루트 .env, projects/ 가 있는 곳)

    결정 순서:
      1. SONAR_PROJECT_DIR 설정됨 → 2단계 상위 (projects/NAME/ → root/)
      2. CLAUDE_PROJECT_DIR 설정됨 → 그 경로 자체
      3. 스크립트 위치에서 상위 탐색
      4. CWD

    주의: 플러그인 모드에서 CLAUDE_PLUGIN_ROOT는 플러그인 캐시 경로이므로
    프로젝트 루트(.env 위치)와 다릅니다. 여기서는 프로젝트 루트를 반환합니다.
    """
    if os.environ.get('SONAR_PROJECT_DIR'):
        return Path(os.environ['SONAR_PROJECT_DIR']).parent.parent

    if os.environ.get('CLAUDE_PROJECT_DIR'):
        return Path(os.environ['CLAUDE_PROJECT_DIR'])

    # 직접 설치: .claude/skills/sonar-common/scripts/ → 3단계 상위 = .claude/ → .parent = 프로젝트 루트
    candidate = SCRIPT_DIR.parent.parent.parent
    if candidate.name == '.claude':
        return candidate.parent

    # 플러그인 모드: 스크립트 위치에서 프로젝트 루트 결정 불가 → CWD 사용
    return Path.cwd()


def load_env(env_path: Path = None) -> bool:
    """
    .env 파일 로드 (2단계 로딩)

    env_path가 명시적으로 지정되면 해당 파일만 로드.
    지정되지 않으면 2단계 로딩:
      Stage 1: $SONAR_PROJECT_DIR/.env (프로젝트별 값 - 우선)
      Stage 2: 플러그인 루트/.env (공통 값 - 기존 키 덮어쓰지 않음)

    Args:
        env_path: .env 파일 경로 (명시하면 해당 파일만 로드)

    Returns:
        로드 성공 여부 (하나 이상의 .env 로드 시 True)
    """
    global _env_loaded

    if _env_loaded:
        return True

    # 명시적 경로가 주어지면 해당 파일만 로드 (기존 동작 유지)
    if env_path is not None:
        if not env_path.exists():
            logger.warning(f".env file not found: {env_path}")
            logger.info(f"Copy .env.example to {env_path} and configure it")
            return False
        load_dotenv(env_path)
        _env_loaded = True
        logger.info(f"Loaded environment from: {env_path}")
        return True

    # --- 2단계 로딩 ---
    loaded_any = False

    # Stage 1: 프로젝트별 .env (SONAR_PROJECT_DIR/.env)
    project_dir = os.environ.get('SONAR_PROJECT_DIR')
    if project_dir:
        project_env = Path(project_dir) / '.env'
        if project_env.exists():
            load_dotenv(project_env)
            logger.info(f"[Stage 1] Loaded project env: {project_env}")
            loaded_any = True
        else:
            logger.debug(f"[Stage 1] Project .env not found: {project_env}")

    # Stage 2: 플러그인 루트 .env (공통 값, 기존 키 덮어쓰지 않음)
    plugin_root_env = get_plugin_root_dir() / '.env'
    if plugin_root_env.exists():
        # Stage 1에서 이미 설정된 키는 덮어쓰지 않음
        load_dotenv(plugin_root_env, override=False)
        logger.info(f"[Stage 2] Loaded plugin root env: {plugin_root_env}")
        loaded_any = True
    else:
        logger.debug(f"[Stage 2] Plugin root .env not found: {plugin_root_env}")

    if not loaded_any:
        # 둘 다 없으면 기존 방식으로 ROOT_DIR/.env 시도 (backward compat)
        fallback_env = ROOT_DIR / '.env'
        if fallback_env.exists():
            load_dotenv(fallback_env)
            logger.info(f"[Fallback] Loaded env from ROOT_DIR: {fallback_env}")
            loaded_any = True
        else:
            logger.warning(f"No .env file found. Checked:")
            if project_dir:
                logger.warning(f"  - {Path(project_dir) / '.env'}")
            logger.warning(f"  - {plugin_root_env}")
            logger.warning(f"  - {fallback_env}")
            logger.info("Copy .env.example and configure it")
            return False

    _env_loaded = True
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
