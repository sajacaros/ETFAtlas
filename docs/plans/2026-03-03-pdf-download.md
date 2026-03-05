# PDF 다운로드 기능 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 포트폴리오 대시보드와 공유 포트폴리오 상세 페이지에서 데이터를 PDF로 다운로드하는 기능 추가.

**Architecture:** 프론트엔드에서 jsPDF + jspdf-autotable로 데이터 기반 PDF 생성. 차트 제외, 수치 데이터와 테이블로만 구성. 한글 폰트(Noto Sans KR)를 public 폴더에 배치하여 런타임 로드.

**Tech Stack:** jspdf, jspdf-autotable, Noto Sans KR font

---

### Task 1: 의존성 설치

**Files:**
- Modify: `frontend/package.json`

**Step 1: jspdf와 jspdf-autotable 설치**

Run:
```bash
cd /home/sajacaros/workspace/etf-atlas/frontend && npm install jspdf jspdf-autotable
```

**Step 2: 타입 설치**

Run:
```bash
cd /home/sajacaros/workspace/etf-atlas/frontend && npm install -D @types/jspdf
```

Note: jspdf-autotable은 자체 타입 포함. @types/jspdf가 없으면 jspdf 자체 타입으로 충분하므로 이 단계는 생략 가능.

**Step 3: 커밋**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "chore: add jspdf and jspdf-autotable dependencies"
```

---

### Task 2: 한글 폰트 준비

**Files:**
- Create: `frontend/public/fonts/NotoSansKR-Regular.ttf`

**Step 1: Noto Sans KR 폰트 다운로드**

Google Fonts에서 Noto Sans KR Regular를 다운로드하여 `frontend/public/fonts/` 에 배치.

Run:
```bash
mkdir -p /home/sajacaros/workspace/etf-atlas/frontend/public/fonts
curl -L -o /home/sajacaros/workspace/etf-atlas/frontend/public/fonts/NotoSansKR-Regular.ttf \
  "https://github.com/google/fonts/raw/main/ofl/notosanskr/NotoSansKR%5Bwght%5D.ttf"
```

Note: 파일이 크면 (variable font ~5MB) 대안으로 subset된 정적 폰트 사용:
```bash
curl -L -o /home/sajacaros/workspace/etf-atlas/frontend/public/fonts/NotoSansKR-Regular.ttf \
  "https://github.com/google/fonts/raw/main/ofl/notosanskr/static/NotoSansKR-Regular.ttf"
```

**Step 2: .gitignore에 폰트 제외 확인**

폰트 파일이 너무 크면 `.gitignore`에 추가하고 별도 관리. 적절한 크기(<3MB)라면 커밋.

**Step 3: 커밋**

```bash
git add frontend/public/fonts/
git commit -m "chore: add Noto Sans KR font for PDF generation"
```

---

### Task 3: PDF 공통 유틸리티 생성

**Files:**
- Create: `frontend/src/lib/pdfExport.ts`

**Step 1: 공통 유틸리티 작성**

```typescript
import jsPDF from 'jspdf'
import 'jspdf-autotable'

// jspdf-autotable 타입 확장
declare module 'jspdf' {
  interface jsPDF {
    autoTable: (options: unknown) => jsPDF
    lastAutoTable: { finalY: number }
  }
}

const FONT_NAME = 'NotoSansKR'
const PAGE_MARGIN = 20
const COLORS = {
  primary: [30, 41, 59] as [number, number, number],      // slate-800
  secondary: [100, 116, 139] as [number, number, number],  // slate-500
  positive: [239, 68, 68] as [number, number, number],     // red-500
  negative: [59, 130, 246] as [number, number, number],    // blue-500
  border: [226, 232, 240] as [number, number, number],     // slate-200
  headerBg: [241, 245, 249] as [number, number, number],   // slate-100
}

let fontLoaded = false

async function loadKoreanFont(doc: jsPDF): Promise<void> {
  if (fontLoaded) {
    doc.setFont(FONT_NAME)
    return
  }

  const response = await fetch('/fonts/NotoSansKR-Regular.ttf')
  const buffer = await response.arrayBuffer()
  const base64 = btoa(
    new Uint8Array(buffer).reduce((data, byte) => data + String.fromCharCode(byte), '')
  )

  doc.addFileToVFS('NotoSansKR-Regular.ttf', base64)
  doc.addFont('NotoSansKR-Regular.ttf', FONT_NAME, 'normal')
  doc.setFont(FONT_NAME)
  fontLoaded = true
}

function formatNumber(n: number): string {
  return new Intl.NumberFormat('ko-KR').format(Math.round(n))
}

function formatRate(rate: number): string {
  const sign = rate >= 0 ? '+' : ''
  return `${sign}${rate.toFixed(2)}%`
}

function addHeader(doc: jsPDF, title: string, date: string): number {
  let y = PAGE_MARGIN

  doc.setFontSize(18)
  doc.setTextColor(...COLORS.primary)
  doc.text(title, PAGE_MARGIN, y)
  y += 8

  doc.setFontSize(10)
  doc.setTextColor(...COLORS.secondary)
  doc.text(`생성일: ${date}`, PAGE_MARGIN, y)
  y += 4

  // divider line
  doc.setDrawColor(...COLORS.border)
  doc.setLineWidth(0.5)
  doc.line(PAGE_MARGIN, y, doc.internal.pageSize.getWidth() - PAGE_MARGIN, y)
  y += 8

  return y
}

function addSectionTitle(doc: jsPDF, title: string, y: number): number {
  doc.setFontSize(13)
  doc.setTextColor(...COLORS.primary)
  doc.text(title, PAGE_MARGIN, y)
  return y + 7
}

function addKeyValue(doc: jsPDF, label: string, value: string, y: number, color?: [number, number, number]): number {
  doc.setFontSize(10)
  doc.setTextColor(...COLORS.secondary)
  doc.text(label, PAGE_MARGIN, y)
  doc.setTextColor(...(color ?? COLORS.primary))
  doc.text(value, PAGE_MARGIN + 60, y)
  return y + 6
}

function addFooter(doc: jsPDF): void {
  const pageCount = doc.getNumberOfPages()
  for (let i = 1; i <= pageCount; i++) {
    doc.setPage(i)
    doc.setFontSize(8)
    doc.setTextColor(...COLORS.secondary)
    const pageHeight = doc.internal.pageSize.getHeight()
    doc.text(
      `ETF Atlas - ${i} / ${pageCount}`,
      doc.internal.pageSize.getWidth() / 2,
      pageHeight - 10,
      { align: 'center' }
    )
  }
}

function getValueColor(value: number): [number, number, number] {
  return value >= 0 ? COLORS.positive : COLORS.negative
}

function downloadPdf(doc: jsPDF, filename: string): void {
  addFooter(doc)
  doc.save(filename)
}

export {
  loadKoreanFont,
  formatNumber,
  formatRate,
  addHeader,
  addSectionTitle,
  addKeyValue,
  addFooter,
  downloadPdf,
  getValueColor,
  FONT_NAME,
  PAGE_MARGIN,
  COLORS,
}
```

**Step 2: 빌드 확인**

Run:
```bash
cd /home/sajacaros/workspace/etf-atlas/frontend && npx tsc --noEmit
```
Expected: 에러 없음

**Step 3: 커밋**

```bash
git add frontend/src/lib/pdfExport.ts
git commit -m "feat: add PDF export common utilities"
```

---

### Task 4: 대시보드 PDF 생성 함수

**Files:**
- Create: `frontend/src/lib/dashboardPdf.ts`

**Step 1: 대시보드 PDF 생성 함수 작성**

```typescript
import jsPDF from 'jspdf'
import 'jspdf-autotable'
import type { DashboardSummary, TotalHoldingsResponse, RiskAnalysisResponse } from '@/types/api'
import {
  loadKoreanFont,
  formatNumber,
  formatRate,
  addHeader,
  addSectionTitle,
  addKeyValue,
  downloadPdf,
  getValueColor,
  FONT_NAME,
  PAGE_MARGIN,
  COLORS,
} from './pdfExport'

interface DashboardPdfParams {
  title: string           // 포트폴리오명 또는 "통합 대시보드"
  summary: DashboardSummary
  riskData?: RiskAnalysisResponse | null
  totalHoldings?: TotalHoldingsResponse | null
  isTotal: boolean
}

export async function generateDashboardPdf(params: DashboardPdfParams): Promise<void> {
  const { title, summary, riskData, totalHoldings, isTotal } = params
  const doc = new jsPDF('p', 'mm', 'a4')
  await loadKoreanFont(doc)

  const today = new Date().toISOString().slice(0, 10)
  let y = addHeader(doc, title, today)

  // 평가금액
  y = addSectionTitle(doc, '평가금액', y)
  y = addKeyValue(doc, '현재 평가금액', `${formatNumber(summary.current_value)}원`, y)
  if (summary.daily) {
    const dailyColor = getValueColor(summary.daily.rate)
    const sign = summary.daily.amount >= 0 ? '+' : ''
    y = addKeyValue(doc, '전일 대비', `${sign}${formatNumber(summary.daily.amount)}원 (${formatRate(summary.daily.rate)})`, y, dailyColor)
  }
  y += 4

  // 투자 정보 (개별 포트폴리오만)
  if (!isTotal) {
    y = addSectionTitle(doc, '투자 정보', y)
    if (summary.invested_amount != null) {
      y = addKeyValue(doc, '투자금액', `${formatNumber(summary.invested_amount)}원`, y)
    }
    if (summary.investment_return) {
      const retColor = getValueColor(summary.investment_return.rate)
      const retSign = summary.investment_return.amount >= 0 ? '+' : ''
      y = addKeyValue(doc, '투자 수익률', `${retSign}${formatNumber(summary.investment_return.amount)}원 (${formatRate(summary.investment_return.rate)})`, y, retColor)
    }
    y += 4
  }

  // 수익률 요약 테이블
  y = addSectionTitle(doc, '수익률 요약', y)
  const summaryItems = [
    { label: '전일대비', item: summary.daily },
    { label: '전달대비', item: summary.monthly },
    { label: '전년대비', item: summary.yearly },
    { label: 'YTD', item: summary.ytd },
  ]

  doc.autoTable({
    startY: y,
    margin: { left: PAGE_MARGIN, right: PAGE_MARGIN },
    head: [summaryItems.map(s => s.label)],
    body: [
      summaryItems.map(s => s.item ? `${formatRate(s.item.rate)}\n${s.item.amount >= 0 ? '+' : ''}${formatNumber(s.item.amount)}원` : '-'),
    ],
    styles: { font: FONT_NAME, fontSize: 9, halign: 'center', cellPadding: 4 },
    headStyles: { fillColor: COLORS.headerBg, textColor: COLORS.primary, fontStyle: 'normal' },
    theme: 'grid',
  })
  y = doc.lastAutoTable.finalY + 8

  // 리스크 분석 (개별 포트폴리오만)
  if (!isTotal && riskData) {
    y = addSectionTitle(doc, '포트폴리오 리스크', y)
    doc.autoTable({
      startY: y,
      margin: { left: PAGE_MARGIN, right: PAGE_MARGIN },
      head: [['MDD', '변동성', '샤프비율']],
      body: [[
        `${riskData.mdd.toFixed(2)}%`,
        `${riskData.volatility.toFixed(2)}%`,
        riskData.sharpe_ratio?.toFixed(2) ?? '-',
      ]],
      styles: { font: FONT_NAME, fontSize: 10, halign: 'center', cellPadding: 4 },
      headStyles: { fillColor: COLORS.headerBg, textColor: COLORS.primary, fontStyle: 'normal' },
      theme: 'grid',
    })
    y = doc.lastAutoTable.finalY + 8
  }

  // 종목 비중 테이블 (통합 대시보드만)
  if (isTotal && totalHoldings && totalHoldings.holdings.length > 0) {
    y = addSectionTitle(doc, '종목 비중', y)
    doc.autoTable({
      startY: y,
      margin: { left: PAGE_MARGIN, right: PAGE_MARGIN },
      head: [['종목', '수량', '현재가', '평가금액', '비중']],
      body: totalHoldings.holdings.map(h => [
        `${h.name}\n${h.ticker}`,
        formatNumber(h.quantity),
        `${formatNumber(h.current_price)}원`,
        `${formatNumber(h.value)}원`,
        `${h.weight.toFixed(1)}%`,
      ]),
      styles: { font: FONT_NAME, fontSize: 9, cellPadding: 3 },
      headStyles: { fillColor: COLORS.headerBg, textColor: COLORS.primary, fontStyle: 'normal' },
      columnStyles: {
        0: { halign: 'left' },
        1: { halign: 'right' },
        2: { halign: 'right' },
        3: { halign: 'right' },
        4: { halign: 'right' },
      },
      theme: 'grid',
    })
  }

  const filename = isTotal
    ? `통합_대시보드_${today}.pdf`
    : `${title}_대시보드_${today}.pdf`
  downloadPdf(doc, filename)
}
```

**Step 2: 빌드 확인**

Run:
```bash
cd /home/sajacaros/workspace/etf-atlas/frontend && npx tsc --noEmit
```
Expected: 에러 없음

**Step 3: 커밋**

```bash
git add frontend/src/lib/dashboardPdf.ts
git commit -m "feat: add dashboard PDF generation function"
```

---

### Task 5: 공유 포트폴리오 PDF 생성 함수

**Files:**
- Create: `frontend/src/lib/sharedPdf.ts`

**Step 1: 공유 포트폴리오 PDF 생성 함수 작성**

```typescript
import jsPDF from 'jspdf'
import 'jspdf-autotable'
import type { SharedPortfolioDetail, SharedReturnsSummary } from '@/types/api'
import {
  loadKoreanFont,
  addHeader,
  addSectionTitle,
  downloadPdf,
  FONT_NAME,
  PAGE_MARGIN,
  COLORS,
} from './pdfExport'

interface SharedPdfParams {
  detail: SharedPortfolioDetail
  summary: SharedReturnsSummary | null
}

function formatReturn(value: number | null): string {
  if (value === null) return '-'
  const sign = value >= 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

export async function generateSharedPdf(params: SharedPdfParams): Promise<void> {
  const { detail, summary } = params
  const doc = new jsPDF('p', 'mm', 'a4')
  await loadKoreanFont(doc)

  const today = new Date().toISOString().slice(0, 10)
  let y = addHeader(doc, detail.portfolio_name, today)

  // 가상 수익률 요약
  if (summary) {
    y = addSectionTitle(doc, '가상 수익률 (1,000만원 기준)', y)
    doc.autoTable({
      startY: y,
      margin: { left: PAGE_MARGIN, right: PAGE_MARGIN },
      head: [['1주', '1개월', '3개월']],
      body: [[
        formatReturn(summary.returns_1w),
        formatReturn(summary.returns_1m),
        formatReturn(summary.returns_3m),
      ]],
      styles: { font: FONT_NAME, fontSize: 11, halign: 'center', cellPadding: 5 },
      headStyles: { fillColor: COLORS.headerBg, textColor: COLORS.primary, fontStyle: 'normal' },
      theme: 'grid',
    })
    y = doc.lastAutoTable.finalY + 8
  }

  // 종목 비중 테이블
  y = addSectionTitle(doc, '종목 비중', y)
  const totalWeight = detail.allocations.reduce((sum, a) => sum + a.weight, 0)

  doc.autoTable({
    startY: y,
    margin: { left: PAGE_MARGIN, right: PAGE_MARGIN },
    head: [['종목', '티커', '비중']],
    body: [
      ...detail.allocations.map(a => [a.name, a.ticker, `${a.weight.toFixed(1)}%`]),
      [{ content: '합계', colSpan: 2, styles: { fontStyle: 'bold' } }, `${totalWeight.toFixed(1)}%`],
    ],
    styles: { font: FONT_NAME, fontSize: 10, cellPadding: 3 },
    headStyles: { fillColor: COLORS.headerBg, textColor: COLORS.primary, fontStyle: 'normal' },
    columnStyles: {
      0: { halign: 'left' },
      1: { halign: 'left' },
      2: { halign: 'right' },
    },
    theme: 'grid',
  })

  const filename = `${detail.portfolio_name}_포트폴리오_${today}.pdf`
  downloadPdf(doc, filename)
}
```

**Step 2: 빌드 확인**

Run:
```bash
cd /home/sajacaros/workspace/etf-atlas/frontend && npx tsc --noEmit
```
Expected: 에러 없음

**Step 3: 커밋**

```bash
git add frontend/src/lib/sharedPdf.ts
git commit -m "feat: add shared portfolio PDF generation function"
```

---

### Task 6: 대시보드 페이지에 PDF 다운로드 버튼 추가

**Files:**
- Modify: `frontend/src/app/PortfolioDashboardPage.tsx`

**Step 1: import 추가**

파일 상단에 추가:
```typescript
import { ArrowLeft, ChevronDown, ChevronUp, Download } from 'lucide-react'
import { generateDashboardPdf } from '@/lib/dashboardPdf'
```
(기존 `ArrowLeft, ChevronDown, ChevronUp` import에 `Download` 추가)

**Step 2: 다운로드 핸들러 + 상태 추가**

`PortfolioDashboardPage` 컴포넌트 내부, `riskDialogOpen` state 아래에 추가:
```typescript
const [pdfLoading, setPdfLoading] = useState(false)

const handleDownloadPdf = async () => {
  if (!dashboard) return
  setPdfLoading(true)
  try {
    await generateDashboardPdf({
      title: isTotal ? '통합 대시보드' : '대시보드',
      summary: dashboard.summary,
      riskData: riskData ?? null,
      totalHoldings: totalHoldings ?? null,
      isTotal,
    })
  } catch (err) {
    console.error('PDF generation failed', err)
  } finally {
    setPdfLoading(false)
  }
}
```

**Step 3: 헤더에 다운로드 버튼 추가**

대시보드 헤더 영역의 `</div>` (평가금액 영역 닫는 div) 바로 뒤에 추가:
```tsx
<Button
  variant="outline"
  size="sm"
  onClick={handleDownloadPdf}
  disabled={pdfLoading}
  className="shrink-0"
>
  <Download className="w-4 h-4 mr-1" />
  {pdfLoading ? '생성 중...' : 'PDF'}
</Button>
```

**Step 4: 빌드 확인**

Run:
```bash
cd /home/sajacaros/workspace/etf-atlas/frontend && npx tsc --noEmit
```
Expected: 에러 없음

**Step 5: 커밋**

```bash
git add frontend/src/app/PortfolioDashboardPage.tsx
git commit -m "feat: add PDF download button to dashboard page"
```

---

### Task 7: 공유 포트폴리오 페이지에 PDF 다운로드 버튼 추가

**Files:**
- Modify: `frontend/src/app/SharedPortfolioDetailPage.tsx`

**Step 1: import 추가**

파일 상단에 추가:
```typescript
import { ArrowLeft, ChevronDown, ChevronUp, Download } from 'lucide-react'
import { generateSharedPdf } from '@/lib/sharedPdf'
```
(기존 `ArrowLeft, ChevronDown, ChevronUp` import에 `Download` 추가)

**Step 2: 다운로드 핸들러 + 상태 추가**

`SharedPortfolioDetailPage` 컴포넌트 내부, `chartOpen` state 아래에 추가:
```typescript
const [pdfLoading, setPdfLoading] = useState(false)

const handleDownloadPdf = async () => {
  if (!detail) return
  setPdfLoading(true)
  try {
    await generateSharedPdf({
      detail,
      summary: summary ?? null,
    })
  } catch (err) {
    console.error('PDF generation failed', err)
  } finally {
    setPdfLoading(false)
  }
}
```

**Step 3: 헤더에 다운로드 버튼 추가**

포트폴리오 이름 옆에 버튼 추가. 기존 헤더 `<div>` 구조를 수정:
```tsx
<div className="flex items-center gap-4">
  <Link to="/shared">
    <Button variant="ghost" size="sm"><ArrowLeft className="w-4 h-4 mr-1" />목록</Button>
  </Link>
  <div className="flex-1">
    <h1 className="text-2xl font-bold">{detail.portfolio_name}</h1>
  </div>
  <Button
    variant="outline"
    size="sm"
    onClick={handleDownloadPdf}
    disabled={pdfLoading}
    className="shrink-0"
  >
    <Download className="w-4 h-4 mr-1" />
    {pdfLoading ? '생성 중...' : 'PDF'}
  </Button>
</div>
```

**Step 4: 빌드 확인**

Run:
```bash
cd /home/sajacaros/workspace/etf-atlas/frontend && npx tsc --noEmit
```
Expected: 에러 없음

**Step 5: 커밋**

```bash
git add frontend/src/app/SharedPortfolioDetailPage.tsx
git commit -m "feat: add PDF download button to shared portfolio page"
```

---

### Task 8: 수동 테스트 및 최종 커밋

**Step 1: 프론트엔드 빌드 확인**

Run:
```bash
cd /home/sajacaros/workspace/etf-atlas/frontend && npm run build
```
Expected: 빌드 성공

**Step 2: 수동 테스트 체크리스트**

- [ ] 포트폴리오 대시보드 → PDF 버튼 클릭 → PDF 다운로드 확인
- [ ] 통합 대시보드 → PDF 버튼 클릭 → PDF 다운로드 확인 (종목 비중 포함)
- [ ] 공유 포트폴리오 → PDF 버튼 클릭 → PDF 다운로드 확인
- [ ] PDF 내 한글 정상 표시 확인
- [ ] 수익률 색상(양수 빨강/음수 파랑) 확인
