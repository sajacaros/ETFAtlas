export interface HoldingsMarkdownRow {
  name: string
  ticker: string
  weight: number
}

/** 종목·심볼·비중을 마크다운 표로 만든다. */
export function holdingsMarkdown(rows: HoldingsMarkdownRow[]): string {
  const cell = (v: string) => v.replace(/\|/g, '\\|')
  return [
    '| 종목 | 심볼 | 비중 |',
    '| --- | --- | ---: |',
    ...rows.map((r) => `| ${cell(r.name)} | ${cell(r.ticker)} | ${Number(r.weight).toFixed(1)}% |`),
  ].join('\n')
}
