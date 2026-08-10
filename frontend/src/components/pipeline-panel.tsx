import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useAppStore } from "@/store";
import { ChevronDown, ChevronRight } from "lucide-react";

interface PipelinePanelProps {
  events: string[];
  status: "idle" | "running" | "done" | "error";
  progress?: number;
}

export function PipelinePanel({ events, status, progress = 0 }: PipelinePanelProps) {
  const normalized = Math.max(0, Math.min(100, progress));
  const styleAnalysis = useAppStore((s) => s.styleAnalysis);
  const styleBenchmark = useAppStore((s) => s.styleBenchmark);
  const [showAnalysis, setShowAnalysis] = useState(true);
  const [showBenchmark, setShowBenchmark] = useState(false);

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

          {styleAnalysis && (
            <div className="mt-3 border border-primary/30 rounded-lg overflow-hidden">
              <button
                onClick={() => setShowAnalysis(!showAnalysis)}
                className="w-full flex items-center gap-1 px-2 py-1.5 bg-primary/10 text-primary text-xs font-medium hover:bg-primary/20"
              >
                {showAnalysis ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                人类样本写法分析
              </button>
              {showAnalysis && (
                <div className="px-2 py-2 text-xs leading-relaxed whitespace-pre-wrap break-words max-h-[300px] overflow-y-auto">
                  {styleAnalysis}
                </div>
              )}
              {styleBenchmark && (
                <>
                  <button
                    onClick={() => setShowBenchmark(!showBenchmark)}
                    className="w-full flex items-center gap-1 px-2 py-1.5 bg-muted/30 text-muted text-xs hover:bg-muted/50 border-t border-border"
                  >
                    {showBenchmark ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                    人类样本原文
                  </button>
                  {showBenchmark && (
                    <div className="px-2 py-2 text-xs leading-relaxed whitespace-pre-wrap break-words text-muted max-h-[200px] overflow-y-auto">
                      {styleBenchmark}
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </CardContent>
        <div className="p-3 border-t border-border space-y-2">
          {status === "running" && (
            <div className="w-full">
              <div className="flex justify-between text-xs text-muted mb-1">
                <span>进度</span>
                <span>{normalized}%</span>
              </div>
              <div className="w-full h-2 rounded-full bg-border overflow-hidden">
                <div
                  className="h-full bg-primary transition-all duration-300"
                  style={{ width: `${normalized}%` }}
                />
              </div>
            </div>
          )}
          <Badge className={status === "running" ? "text-primary border-primary" : status === "error" ? "text-danger border-danger" : status === "done" ? "text-success border-success" : ""}>
            {status === "idle" ? "待机" : status === "running" ? "生成中" : status === "done" ? "已完成" : "错误"}
          </Badge>
        </div>
      </Card>
    </div>
  );
}
