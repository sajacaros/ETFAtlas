import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Plus } from 'lucide-react'
import { etfsApi } from '@/lib/api'

interface AddTickerDialogProps {
  onAdd: (ticker: string, targetWeight: number, quantity: number) => void
}

export default function AddTickerDialog({ onAdd }: AddTickerDialogProps) {
  const [open, setOpen] = useState(false)
  const [ticker, setTicker] = useState('')
  const [targetWeight, setTargetWeight] = useState('')
  const [quantity, setQuantity] = useState('')
  const [searchResults, setSearchResults] = useState<{ code: string; name: string }[]>([])
  const [searching, setSearching] = useState(false)
  const [validated, setValidated] = useState(false)
  const [tickerName, setTickerName] = useState('')

  const reset = () => {
    setTicker('')
    setTargetWeight('')
    setQuantity('')
    setSearchResults([])
    setValidated(false)
    setTickerName('')
  }

  const handleSearch = async (query: string) => {
    setTicker(query)
    setValidated(false)
    setTickerName('')

    if (query.toUpperCase() === 'CASH') {
      setValidated(true)
      setTickerName('현금')
      setSearchResults([])
      return
    }

    if (query.length < 2) {
      setSearchResults([])
      return
    }

    setSearching(true)
    try {
      const results = await etfsApi.search(query, 5)
      setSearchResults(results.map((r) => ({ code: r.code, name: r.name })))
    } catch {
      setSearchResults([])
    } finally {
      setSearching(false)
    }
  }

  const handleSelectTicker = (code: string, name: string) => {
    setTicker(code)
    setTickerName(name)
    setValidated(true)
    setSearchResults([])
  }

  const handleSubmit = () => {
    if (!validated || !targetWeight) return
    const tickerValue = ticker.toUpperCase() === 'CASH' ? 'CASH' : ticker
    onAdd(tickerValue, parseFloat(targetWeight), parseFloat(quantity || '0'))
    reset()
    setOpen(false)
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        setOpen(v)
        if (!v) reset()
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm">
          <Plus className="w-4 h-4 mr-2" />
          종목 추가
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>종목 추가</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label>ETF 코드 (또는 CASH)</Label>
            <Input
              placeholder="종목코드 또는 이름 검색"
              value={ticker}
              onChange={(e) => handleSearch(e.target.value)}
            />
            {searching && <p className="text-xs text-muted-foreground">검색 중...</p>}
            {searchResults.length > 0 && (
              <div className="border rounded-md max-h-40 overflow-y-auto">
                {searchResults.map((r) => (
                  <button
                    key={r.code}
                    className="w-full text-left px-3 py-2 hover:bg-muted text-sm flex justify-between"
                    onClick={() => handleSelectTicker(r.code, r.name)}
                  >
                    <span className="font-mono">{r.code}</span>
                    <span className="text-muted-foreground">{r.name}</span>
                  </button>
                ))}
              </div>
            )}
            {validated && tickerName && (
              <p className="text-sm text-green-600">{tickerName}</p>
            )}
          </div>
          <div className="space-y-2">
            <Label>목표 비중 (%)</Label>
            <Input
              type="number"
              step="0.01"
              min="0"
              max="100"
              placeholder="예: 30"
              value={targetWeight}
              onChange={(e) => setTargetWeight(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label>초기 보유 수량 (선택)</Label>
            <Input
              type="number"
              step="1"
              min="0"
              placeholder="0"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
            />
          </div>
          <Button
            onClick={handleSubmit}
            className="w-full"
            disabled={!validated || !targetWeight}
          >
            추가
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
