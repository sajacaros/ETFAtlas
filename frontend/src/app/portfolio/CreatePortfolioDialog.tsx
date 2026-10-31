import { useState } from 'react'
import { Plus } from 'lucide-react'
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
import { AccountTypePicker } from '@/components/AccountType'
import { DEFAULT_ACCOUNT_TYPES } from '@/lib/accountType'
import type { AccountType, CalculationBase } from '@/types/api'

export interface NewPortfolioParams {
  name: string
  account_types: AccountType[]
  calculation_base: CalculationBase
  target_total_amount: number | null
}

/** 새 포트폴리오 생성 다이얼로그. onCreate가 성공하면(true) 입력을 비우고 닫는다 */
export default function CreatePortfolioDialog({
  open,
  onOpenChange,
  onCreate,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreate: (params: NewPortfolioParams) => Promise<boolean>
}) {
  const [newName, setNewName] = useState('')
  const [newBase, setNewBase] = useState<CalculationBase>('CURRENT_TOTAL')
  const [newAccountTypes, setNewAccountTypes] = useState<AccountType[]>(DEFAULT_ACCOUNT_TYPES)
  const [newAmount, setNewAmount] = useState('')

  const handleCreate = async () => {
    if (!newName.trim()) return
    const ok = await onCreate({
      name: newName,
      account_types: newAccountTypes,
      calculation_base: newBase,
      target_total_amount: newAmount ? parseFloat(newAmount) : null,
    })
    if (!ok) return
    setNewName('')
    setNewBase('CURRENT_TOTAL')
    setNewAccountTypes(DEFAULT_ACCOUNT_TYPES)
    setNewAmount('')
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button>
          <Plus className="w-4 h-4 mr-2" />
          새 포트폴리오
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>새 포트폴리오 생성</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label>포트폴리오 이름</Label>
            <Input
              placeholder="포트폴리오 이름"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
            />
          </div>
          <div className="space-y-2">
            <Label>계좌 유형</Label>
            <AccountTypePicker value={newAccountTypes} onChange={setNewAccountTypes} />
          </div>
          <div className="space-y-2">
            <Label>계산 기준</Label>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant={newBase === 'CURRENT_TOTAL' ? 'default' : 'outline'}
                onClick={() => setNewBase('CURRENT_TOTAL')}
                className="flex-1"
              >
                보유 총액
              </Button>
              <Button
                size="sm"
                variant={newBase === 'TARGET_AMOUNT' ? 'default' : 'outline'}
                onClick={() => setNewBase('TARGET_AMOUNT')}
                className="flex-1"
              >
                목표 금액
              </Button>
            </div>
          </div>
          {newBase === 'TARGET_AMOUNT' && (
            <div className="space-y-2">
              <Label>목표 금액</Label>
              <Input
                type="number"
                placeholder="예: 10000000"
                value={newAmount}
                onChange={(e) => setNewAmount(e.target.value)}
              />
            </div>
          )}
          <Button onClick={handleCreate} className="w-full">
            생성
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
