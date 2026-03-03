import jsPDF from 'jspdf'
import { applyPlugin } from 'jspdf-autotable'
import type { UserOptions } from 'jspdf-autotable'

// Register autoTable plugin on jsPDF prototype
applyPlugin(jsPDF)

// jspdf-autotable type augmentation
declare module 'jspdf' {
  interface jsPDF {
    autoTable: (options: UserOptions) => jsPDF
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

let cachedFontBase64: string | null = null

async function loadKoreanFont(doc: jsPDF): Promise<void> {
  if (!cachedFontBase64) {
    const response = await fetch('/fonts/NotoSansKR-Regular.ttf')
    if (!response.ok) {
      throw new Error(`Failed to load Korean font: ${response.status}`)
    }
    const buffer = await response.arrayBuffer()
    cachedFontBase64 = btoa(
      new Uint8Array(buffer).reduce((data, byte) => data + String.fromCharCode(byte), '')
    )
  }

  doc.addFileToVFS('NotoSansKR-Regular.ttf', cachedFontBase64)
  doc.addFont('NotoSansKR-Regular.ttf', FONT_NAME, 'normal')
  doc.setFont(FONT_NAME)
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
