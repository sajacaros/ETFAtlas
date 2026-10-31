# 주간 매수 의견 (`app/services/weekly_opinion.py`)

토요일 아침 ETF가 담은 주식 전체(약 570종목)에 챗봇의 '살까 말까'(`stock_opinion`)를 돌리고, '사 볼 만하다' 상위 10개를 디스코드로 알린다.

## 흐름

1. **언제**: 백엔드 프로세스 안에서 10분마다 깨어나 토요일 07:00(KST) 뒤 한 번 돈다. 토요일에 백엔드가 내려가 있었으면 일요일에 돈다. `opinion_runs`에 그 주 토요일 날짜로 한 행을 넣어 맡고, 맡은 프로세스가 30분 넘게 소식이 없으면 다른 프로세스(다시 뜬 백엔드)가 이어 맡는다.
2. **종목마다**: 챗봇 '살까 말까' 답과 같은 영역 — `stock_technical`(차트), `company_financials`(분기 8개), `company_valuation`, `company_type`, `company_report`(개요) — 을 스킬로 채우고, 그 요약으로 `stock_opinion.judge`가 관점별(차트·재무·보고서) 판정을 낸다. 종합 의견은 `domain/opinion.py` 규칙. 동시 3종목(챗봇과 LLM을 나눠 쓴다). 판정한 종목은 바로 `stock_opinions`에 남겨 다시 뜬 백엔드가 건너뛴다.
3. **순위**: '사 볼 만하다'만, 점수(관점 평균 −2~+2) → 재무 판정 → 시가총액 순으로 10개. 10개가 안 되면 있는 만큼만. 순위는 `stock_opinions.rank`.
4. **회사 소개**: 뽑힌 종목만 최신 보고서 개요의 '사업 구조'로 50자 한 줄을 만들어 `stock_reports.tagline`에 남긴다 (보고서마다 한 번). 개요는 `dart_report_index`의 `make_overviews`가 미리 만든다.
5. **발송**: 비중 변화 알림과 같은 웹훅(관리자 페이지 디스코드 설정, 꺼 두면 보내지 않음). 2,000자 제한에 맞게 종목 단위로 나눠 보낸다. 지난 차례에 없던 종목은 🆕. `discord_notification_logs`(kind=`weekly_opinion`)에 성공 기록이 있으면 다시 보내지 않는다.

## 메시지

```
📊 주간 매수 의견 2026-10-31 — ETF가 담은 주식 570종목
사 볼 만하다 12 · 지켜본다 300 · 사지 않는 편이 낫다 200 · 판단 보류 50 · 실패 8
'사 볼 만하다' 상위 10개 (점수는 차트·재무·보고서 판정 평균, 긍정 +2 ~ 부정 −2)

1. SK하이닉스 `000660` +1.0점 🆕
DRAM과 NAND Flash 등 메모리 반도체를 생산하는 기업
차트 중립 · 재무 긍정 · 보고서 다소 긍정 | 턴어라운드주
└ (판정이 가장 좋은 관점의 첫 근거)
```

## 손으로 돌리기

```bash
docker exec etf-atlas-backend python -m app.services.weekly_opinion --codes 005930,000660 --dry-run  # 저장·발송 없이 출력
docker exec etf-atlas-backend python -m app.services.weekly_opinion --date 2026-10-31               # 그 차례를 맡아 끝까지
```

`--limit`·`--codes`는 `--dry-run`과 함께만 쓴다 (일부만 돌고 차례를 마치면 그 주는 다시 돌지 않는다). 다시 돌리려면 `opinion_runs`의 그 날짜 행을 지운다 (`stock_opinions`는 CASCADE).
