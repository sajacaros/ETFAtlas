/**
 * 차트 레지스트리: view.kind → ECharts 옵션. 새 차트는 여기에 빌더 하나를 더하면 된다.
 * 레지스트리에 없는 kind나 빌드에 실패한 차트는 ChartView가 같은 데이터셋을 표로 보여준다.
 */
import type { EChartsCoreOption } from 'echarts/core'
import type { DataContent, DataField, DataRow, DataView } from '@/types/api'
import { axisFormatter, formatValue } from './format'

export interface ChartTheme {
  palette: string[]
  tileText: string  // 색칠한 칸(트리맵) 위의 글씨
  scale: [string, string]  // 트리맵: 작은 값 → 큰 값 색 (한 색의 진하기로 크기를 보인다)
  other: string  // '기타' 칸: 다른 칸보다 눈에 덜 띄게
  text: string
  muted: string
  border: string
  up: string  // 국내 관례: 상승 빨강
  down: string
  font: string
}

/** 화면에서 고르는 값 — 봉차트의 보조지표 칸 번호, 볼린저 밴드 표시 */
export interface BuildOptions {
  panel?: number
  bands?: boolean  // 볼린저 밴드를 그린다 (기본은 숨김 — 이평선과 겹쳐 어지럽다)
}

type Builder<K extends DataView['kind']> = (
  view: Extract<DataView, { kind: K }>, content: DataContent, theme: ChartTheme, opts: BuildOptions,
) => EChartsCoreOption

const fieldOf = (content: DataContent, key: string): DataField =>
  content.dataset.fields.find((f) => f.key === key) ?? { key, label: key, format: 'number' }

const num = (v: unknown): number | null => (typeof v === 'number' ? v : null)

const xLabels = (content: DataContent, key: string): string[] => {
  const labels = content.dataset.rows.map((r) => String(r[key]))
  return fieldOf(content, key).format === 'date' ? dateLabels(labels) : labels
}

function base(theme: ChartTheme): EChartsCoreOption {
  return {
    color: theme.palette,
    textStyle: { color: theme.text, fontFamily: theme.font },
    tooltip: { backgroundColor: 'rgba(20,20,20,0.9)', borderWidth: 0, textStyle: { color: '#fff', fontSize: 12 } },
    animationDuration: 400,
  }
}

function legend(theme: ChartTheme, show: boolean) {
  return show ? { legend: { top: 0, type: 'scroll', textStyle: { color: theme.muted } } } : {}
}

function categoryAxis(theme: ChartTheme, data: string[], extra: object = {}) {
  return {
    type: 'category', data,
    axisLine: { lineStyle: { color: theme.border } },
    axisLabel: { color: theme.muted, hideOverlap: true },
    ...extra,
  }
}

function valueAxis(theme: ChartTheme, field: DataField, extra: object = {}) {
  return {
    type: 'value', scale: field.format === 'price',
    axisLabel: { color: theme.muted, formatter: axisFormatter(field.format) },
    splitLine: { lineStyle: { color: theme.border, type: 'dashed' } },
    ...extra,
  }
}

/** 날짜 축 라벨: 한 해 안의 데이터면 연도를 뺀다 (2026-10-07 → 10-07) */
function dateLabels(dates: string[]): string[] {
  const sameYear = dates.length > 0 && dates.every((d) => d.slice(0, 4) === dates[0].slice(0, 4))
  return sameYear ? dates.map((d) => d.slice(5)) : dates
}

const line: Builder<'line'> = (view, content, theme) => {
  const rows = content.dataset.rows
  const yField = fieldOf(content, view.y[0])
  return {
    ...base(theme),
    ...legend(theme, view.y.length > 1),
    grid: { left: 8, right: 24, top: view.y.length > 1 ? 32 : 12, bottom: 8, containLabel: true },
    tooltip: { ...base(theme).tooltip as object, trigger: 'axis', valueFormatter: (v: unknown) => formatValue(v, yField.format) },
    xAxis: categoryAxis(theme, xLabels(content, view.x), { boundaryGap: false }),
    yAxis: valueAxis(theme, yField),
    series: view.y.map((key) => ({
      type: 'line', name: fieldOf(content, key).label, data: rows.map((r) => num(r[key])),
      connectNulls: true, showSymbol: rows.length <= 30, smooth: false,
    })),
  }
}

const bar: Builder<'bar'> = (view, content, theme) => {
  const rows = content.dataset.rows
  const yField = fieldOf(content, view.y[0])
  const single = view.y.length === 1
  const signed = rows.some((r) => (num(r[view.y[0]]) ?? 0) < 0)
  const categories = categoryAxis(theme, rows.map((r) => String(r[view.x])), view.horizontal ? { inverse: true } : {})
  const values = valueAxis(theme, yField)
  return {
    ...base(theme),
    ...legend(theme, !single),
    grid: { left: 8, right: 24, top: single ? 12 : 32, bottom: 8, containLabel: true },
    tooltip: { ...base(theme).tooltip as object, trigger: 'axis', axisPointer: { type: 'shadow' },
      valueFormatter: (v: unknown) => formatValue(v, yField.format) },
    xAxis: view.horizontal ? values : categories,
    yAxis: view.horizontal ? categories : values,
    series: view.y.map((key) => ({
      type: 'bar', name: fieldOf(content, key).label, data: rows.map((r) => num(r[key])), barMaxWidth: 28,
      ...(view.stacked ? { stack: 'total' } : {}),
      // 계열이 하나이고 음수가 섞이면 상승·하락 색으로
      ...(single && signed
        ? { itemStyle: { color: (p: { value: number }) => (p.value < 0 ? theme.down : theme.up) } }
        : {}),
    })),
  }
}

const OTHER = '기타'

const nameValue = (rows: DataRow[], name: string, value: string, theme: ChartTheme) =>
  rows.map((r) => {
    const d = { name: String(r[name]), value: num(r[value]) ?? 0 }
    return d.name === OTHER ? { ...d, itemStyle: { color: theme.other } } : d
  })

const donut: Builder<'donut'> = (view, content, theme) => {
  const format = fieldOf(content, view.value).format
  return {
    ...base(theme),
    tooltip: { ...base(theme).tooltip as object, trigger: 'item', valueFormatter: (v: unknown) => formatValue(v, format) },
    series: [{
      type: 'pie', radius: ['38%', '62%'], avoidLabelOverlap: true,
      itemStyle: { borderColor: 'transparent', borderWidth: 1 },
      // 좁은 영역에서도 이름이 잘리지 않게: 라벨은 줄바꿈 없이 그대로, 작은 조각(3% 미만)은 툴팁으로만
      label: {
        color: theme.text, overflow: 'none',
        formatter: (p: { name: string; value: number }) => `${p.name}\n${formatValue(p.value, format)}`,
      },
      labelLine: { length: 8, length2: 6 },
      labelLayout: { hideOverlap: true },
      data: nameValue(content.dataset.rows, view.name, view.value, theme).map((d) => (
        d.value < 3 ? { ...d, label: { show: false }, labelLine: { show: false } } : d
      )),
    }],
  }
}

const TREEMAP_LABEL_MIN = 1.2  // 전체의 이 비율(%)보다 작은 칸은 글씨가 조각나므로 숨기고 툴팁으로만

const treemap: Builder<'treemap'> = (view, content, theme) => {
  const format = fieldOf(content, view.value).format
  const data = nameValue(content.dataset.rows, view.name, view.value, theme)
  const total = data.reduce((sum, d) => sum + d.value, 0)
  return {
    ...base(theme),
    tooltip: { ...base(theme).tooltip as object, formatter: (p: { name: string; value: number }) => `${p.name}: ${formatValue(p.value, format)}` },
    series: [{
      type: 'treemap', roam: false, nodeClick: false, breadcrumb: { show: false },
      width: '100%', height: '100%', top: 0, left: 0,
      // 받은 순서(비중 큰 순, '기타'는 맨 끝)대로 놓는다. 값으로 다시 정렬하면 '기타'가 가장 큰 칸이 된다
      sort: false,
      // 칸 색이 밝든 어둡든 읽히도록 글씨에 그림자
      label: {
        formatter: (p: { name: string; value: number }) => `${p.name}\n${formatValue(p.value, format)}`,
        fontSize: 12, color: theme.tileText, textShadowColor: 'rgba(0,0,0,0.85)', textShadowBlur: 3,
      },
      itemStyle: { borderColor: theme.border, borderWidth: 1, gapWidth: 1 },
      levels: [{ color: theme.scale, colorMappingBy: 'value' }],
      data: data.map((d) => (total > 0 && d.value / total * 100 < TREEMAP_LABEL_MIN ? { ...d, label: { show: false } } : d)),
    }],
  }
}

const radar: Builder<'radar'> = (view, content, theme) => {
  const rows = content.dataset.rows
  return {
    ...base(theme),
    ...legend(theme, true),
    tooltip: {
      ...base(theme).tooltip as object, trigger: 'item',
      // 점수와 함께 원값을 보여준다 (_raw)
      formatter: (p: { seriesIndex: number; name: string }) => {
        const key = view.series[p.seriesIndex]
        const lines = rows.map((r) => {
          const raw = r._raw?.[key]
          const rawText = raw === undefined ? '' : ` (${formatValue(raw, r._format ?? 'number')})`
          return `${String(r[view.axis])}: ${formatValue(r[key], 'number')}점${rawText}`
        })
        return [`<b>${p.name}</b>`, ...lines].join('<br/>')
      },
    },
    radar: {
      indicator: rows.map((r) => ({ name: String(r[view.axis]), max: view.max })),
      radius: '62%', center: ['50%', '56%'],
      axisName: { color: theme.muted },
      splitLine: { lineStyle: { color: theme.border } },
      splitArea: { show: false },
      axisLine: { lineStyle: { color: theme.border } },
    },
    series: [{
      type: 'radar',
      data: view.series.map((key) => ({
        name: fieldOf(content, key).label, value: rows.map((r) => num(r[key]) ?? 0), areaStyle: { opacity: 0.15 },
      })),
    }],
  }
}

const BAND = '볼린저 밴드'  // 상단·하단 두 선을 범례 하나로 켜고 끈다

const candlestick: Builder<'candlestick'> = (view, content, theme, opts) => {
  const rows = content.dataset.rows
  const dates = xLabels(content, view.x)
  const priceField = fieldOf(content, view.close)
  const hasVolume = view.volume !== null
  const panels = view.panels ?? []
  const panel = panels.length ? panels[Math.min(opts.panel ?? 0, panels.length - 1)] : undefined
  const overlays = (view.overlays ?? []).filter((k) => opts.bands || !k.startsWith('bb_'))
  const tooltipBase = base(theme).tooltip as object
  const series = (key: string) => rows.map((r) => num(r[key]))
  // 칸: 가격 → 거래량 → 보조지표. 날짜 라벨은 맨 아래 칸에만
  const top = overlays.length ? 28 : 12  // 겹친 선이 있으면 위에 범례
  const grids = panel
    ? [{ top, height: '50%' }, { top: '60%', height: '10%' }, { top: '74%', bottom: 8 }]
    : hasVolume ? [{ top, height: '58%' }, { top: '76%', bottom: 8 }] : [{ top, bottom: 8 }]
  const volumeGrid = hasVolume ? 1 : -1
  const panelGrid = panel ? grids.length - 1 : -1
  const lastGrid = grids.length - 1
  const lineSeries = (key: string, extra: object) => ({
    type: 'line', name: fieldOf(content, key).label, data: series(key), showSymbol: false, connectNulls: false,
    lineStyle: { width: 1 }, tooltip: { valueFormatter: (v: unknown) => formatValue(v, fieldOf(content, key).format) },
    ...extra,
  })
  return {
    ...base(theme),
    ...(overlays.length ? {
      legend: { top: 0, type: 'scroll', textStyle: { color: theme.muted }, itemWidth: 14, itemHeight: 8,
        data: [...new Set(overlays.map((k) => (k.startsWith('bb_') ? BAND : fieldOf(content, k).label)))] },
    } : {}),
    tooltip: { ...tooltipBase, trigger: 'axis', axisPointer: { type: 'cross' } },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: grids.map((g) => ({ left: 8, right: 16, containLabel: true, ...g })),
    xAxis: grids.map((_, i) => categoryAxis(theme, dates, {
      gridIndex: i, axisLabel: { show: i === lastGrid, color: theme.muted, hideOverlap: true },
    })),
    yAxis: [
      valueAxis(theme, priceField, { gridIndex: 0 }),
      ...(hasVolume ? [valueAxis(theme, fieldOf(content, view.volume as string), { gridIndex: volumeGrid, splitNumber: 2,
        axisLabel: { color: theme.muted, formatter: (v: number) => (v ? `${Math.round(v / 1e4).toLocaleString('ko-KR')}만` : '0') } })] : []),
      ...(panel ? [{
        ...valueAxis(theme, fieldOf(content, panel.lines[0]), { gridIndex: panelGrid, splitNumber: 2 }),
        // 칸 이름은 넘김 버튼에 보인다
        scale: panel.min === null, ...(panel.min !== null ? { min: panel.min } : {}), ...(panel.max !== null ? { max: panel.max } : {}),
      }] : []),
    ],
    series: [
      {
        type: 'candlestick', name: '가격',
        // ECharts 순서: 시가, 종가, 저가, 고가
        data: rows.map((r) => [r[view.open], r[view.close], r[view.low], r[view.high]].map(num)),
        itemStyle: { color: theme.up, color0: theme.down, borderColor: theme.up, borderColor0: theme.down },
      },
      ...overlays.map((key, i) => (key.startsWith('bb_')
        ? lineSeries(key, { name: BAND, color: theme.muted, lineStyle: { width: 1, type: 'dashed' } })
        : lineSeries(key, { color: theme.palette[(i + 1) % theme.palette.length] }))),
      ...(hasVolume ? [{
        type: 'bar', name: '거래량', xAxisIndex: volumeGrid, yAxisIndex: volumeGrid,
        data: rows.map((r) => ({
          value: num(r[view.volume as string]),
          itemStyle: { color: (num(r[view.close]) ?? 0) >= (num(r[view.open]) ?? 0) ? theme.up : theme.down, opacity: 0.6 },
        })),
      }] : []),
      ...(panel?.bars ? [{
        type: 'bar', name: fieldOf(content, panel.bars).label, xAxisIndex: panelGrid, yAxisIndex: panelGrid,
        data: series(panel.bars).map((v) => ({ value: v, itemStyle: { color: (v ?? 0) >= 0 ? theme.up : theme.down, opacity: 0.6 } })),
      }] : []),
      ...(panel ? panel.lines.map((key, i) => lineSeries(key, {
        xAxisIndex: panelGrid, yAxisIndex: panelGrid, color: theme.palette[i % theme.palette.length],
        // 기준선(RSI 30·70 등)은 첫 선에만 한 번
        ...(i === 0 && panel.levels.length ? {
          markLine: { silent: true, symbol: 'none', label: { show: false },
            lineStyle: { color: theme.muted, type: 'dashed', width: 1 }, data: panel.levels.map((y) => ({ yAxis: y })) },
        } : {}),
      })) : []),
    ],
  }
}

const BUILDERS: { [K in DataView['kind']]?: Builder<K> } = { line, bar, donut, treemap, radar, candlestick }

/** 차트 높이(px). 스켈레톤도 같은 높이를 써서 내용이 들어올 때 화면이 흔들리지 않는다 */
export const CHART_HEIGHT: Record<string, number> = { treemap: 320, candlestick: 340, radar: 300 }
export const DEFAULT_CHART_HEIGHT = 280
export const PANEL_CHART_HEIGHT = 460  // 보조지표 칸이 있는 봉차트 (가격·거래량·보조지표 세 칸)

export function buildChartOption(content: DataContent, theme: ChartTheme, opts: BuildOptions = {}): EChartsCoreOption | null {
  const builder = BUILDERS[content.view.kind] as Builder<DataView['kind']> | undefined
  return builder ? builder(content.view, content, theme, opts) : null
}
