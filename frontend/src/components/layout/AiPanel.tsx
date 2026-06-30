import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const QUICK_ACTIONS = [
  { key: "continue", label: "续写" },
  { key: "polish", label: "润色" },
  { key: "foreshadow", label: "生成伏笔" },
  { key: "review", label: "审校" },
];

export function AiPanel() {
  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-3">
      <Card className="flex-1">
        <CardHeader>
          <CardTitle>AI 助手</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="rounded-xl bg-primary-muted p-3 text-sm text-foreground">
            选中章节或资产后，我可以帮你续写、润色、生成伏笔或审校内容。
          </div>

          <div className="grid grid-cols-2 gap-2">
            {QUICK_ACTIONS.map((action) => (
              <Button
                key={action.key}
                variant="outline"
                size="sm"
                onClick={() => {}}
              >
                {action.label}
              </Button>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>状态检查</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted">一致性</span>
            <span className="font-medium text-success">正常</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted">伏笔数量</span>
            <span className="font-medium text-foreground">0</span>
          </div>
          <Button variant="default" size="sm" className="w-full" onClick={() => {}}>
            重新检查
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
