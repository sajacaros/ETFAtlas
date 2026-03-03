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
