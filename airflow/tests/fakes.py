"""DB 연결 가짜 — 실행한 SQL을 남기고, 정해 둔 결과를 돌려준다."""


class FakeCursor:
    def __init__(self, results=None):
        # results: SQL 조각 → fetchall 결과. 먼저 맞는 것을 쓴다
        self.results = results or {}
        self.sql = []
        self._rows = []

    def execute(self, sql, params=None):
        self.sql.append((" ".join(sql.split()), params))
        self._rows = next((rows for key, rows in self.results.items() if key in sql), [])

    def executemany(self, sql, rows):
        self.sql.append((" ".join(sql.split()), list(rows)))

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, cur=None):
        self.cur = cur or FakeCursor()
        self.commits = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass
