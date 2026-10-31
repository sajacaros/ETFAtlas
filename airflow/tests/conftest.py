"""airflow 테스트 공용 설정: DAG 폴더(라이브러리 모듈)와 backend(app.utils 등 공용 모듈)를 import 경로에 둔다.

컨테이너의 PYTHONPATH=/opt/airflow/dags:/opt/backend 와 같은 구성이다. airflow 패키지 없이 돈다.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "airflow" / "dags", ROOT / "backend"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
