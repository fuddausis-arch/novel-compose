import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface PipelinePanelProps {
  events: string[];
  status: "idle" | "running" | "done" | "error";
}

export function PipelinePanel({ events, status }: PipelinePanelProps) {
  return (
    <div className="w-full h-full">
      <Card className="h-full flex flex-col">
        <CardHeader className="pb-2">
          <CardTitle>AI 流水线</CardTitle>
        </CardHeader>
        <CardContent className="flex-1 overflow-y-auto font-mono text-xs space-y-1">
          {events.length === 0 && <span className="text-muted">暂无事件</span>}
          {events.map((ev, i) => (
            <div key={i} className="text-muted break-words">{ev}</div>
          ))}
        </CardContent>
        <div className="p-3 border-t border-border">
          <Badge className={status === "running" ? "text-primary border-primary" : status === "error" ? "text-danger border-danger" : status === "done" ? "text-success border-success" : ""}>
            {status === "idle" ? "待机" : status === "running" ? "生成中" : status === "done" ? "已完成" : "错误"}
          </Badge>
        </div>
      </Card>
    </div>
  );
}
