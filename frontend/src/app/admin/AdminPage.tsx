import { useAuth } from '@/hooks/useAuth'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ShieldAlert } from 'lucide-react'
import ExamplesTab, { CODE_EXAMPLES, LAYOUT_EXAMPLES } from './ExamplesTab'
import ChatLogsTab from './ChatLogsTab'
import ETFTagsTab from './ETFTagsTab'
import DiscordSettingsTab from './DiscordSettingsTab'
import AISettingsTab from './AISettingsTab'
import DartSettingsTab from './DartSettingsTab'
import MembersTab from './MembersTab'
import InvitationsTab from './InvitationsTab'

export default function AdminPage() {
  const { user } = useAuth()

  if (!user?.is_admin) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
        <ShieldAlert className="w-16 h-16 mb-4" />
        <h2 className="text-xl font-semibold mb-2">접근 권한이 없습니다</h2>
        <p>관리자 권한이 필요합니다.</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">관리자</h1>
      <Tabs defaultValue="code-examples">
        <TabsList>
          <TabsTrigger value="code-examples">코드 예제</TabsTrigger>
          <TabsTrigger value="layout-examples">레이아웃 예제</TabsTrigger>
          <TabsTrigger value="chat-logs">채팅 로그</TabsTrigger>
          <TabsTrigger value="etf-tags">ETF 태그</TabsTrigger>
          <TabsTrigger value="notifications">알림</TabsTrigger>
          <TabsTrigger value="ai">AI</TabsTrigger>
          <TabsTrigger value="dart">DART</TabsTrigger>
          <TabsTrigger value="members">멤버</TabsTrigger>
          <TabsTrigger value="invitations">멤버 초대</TabsTrigger>
        </TabsList>
        <TabsContent value="code-examples">
          <ExamplesTab kind={CODE_EXAMPLES} />
        </TabsContent>
        <TabsContent value="layout-examples">
          <ExamplesTab kind={LAYOUT_EXAMPLES} />
        </TabsContent>
        <TabsContent value="chat-logs">
          <ChatLogsTab />
        </TabsContent>
        <TabsContent value="etf-tags">
          <ETFTagsTab />
        </TabsContent>
        <TabsContent value="notifications">
          <DiscordSettingsTab />
        </TabsContent>
        <TabsContent value="ai">
          <AISettingsTab />
        </TabsContent>
        <TabsContent value="dart">
          <DartSettingsTab />
        </TabsContent>
        <TabsContent value="members">
          <MembersTab />
        </TabsContent>
        <TabsContent value="invitations">
          <InvitationsTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
