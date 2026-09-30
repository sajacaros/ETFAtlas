FROM apache/airflow:3.3.2-python3.14

USER root
RUN ln -snf /usr/share/zoneinfo/Asia/Seoul /etc/localtime && echo 'Asia/Seoul' > /etc/timezone \
    # SimpleAuthManager 비밀번호 파일용 (named volume이 이 소유권을 이어받음)
    && mkdir -p /opt/airflow/auth && chown airflow:0 /opt/airflow/auth
USER airflow

# airflow 버전을 고정한 채 DAG 의존성 설치 (기동 시 pip install 하지 않음)
COPY airflow/requirements.txt /requirements.txt
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" -r /requirements.txt

# DAG 간 공용 모듈(age_utils 등)과 backend 코드(app.utils.encryption) import 경로
ENV PYTHONPATH=/opt/airflow/dags:/opt/backend
