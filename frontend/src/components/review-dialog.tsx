import { useEffect, useState } from "react";
import { Check, X, AlertCircle, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { ReviewPendingData } from "@/hooks/useGeneration";

interface ReviewDialogProps {
  data: ReviewPendingData;
  onApprove: (feedback: string) => void;
  onReject: (feedback: string) => void;
}

export function ReviewDialog({ data, onApprove, onReject }: ReviewDialogProps) {
  const [open, setOpen] = useState(true);
  const [feedback, setFeedback] = useState("");
  const scoreColor = data.overall_score >= 80 ? "text-green-500" : data.overall_score >= 60 ? "text-yellow-500" : "text-red-500";

  // 父级以条件渲染方式使用本组件（无 open prop）；data 变化（新一轮审校）时重新打开
  useEffect(() => {
    setOpen(true);
  }, [data]);

  const handleApprove = () => onApprove(feedback);
  const handleReject = () => onReject(feedback);

  // 人审检查点必须由用户通过"通过/驳回"结束，不允许 Esc/遮罩关闭，
  // 否则父级 reviewPending 仍非空会导致生成流程悬挂（保持重构前强制弹窗行为）。
  const lockOpen = (next: boolean) => {
    if (next) setOpen(true);
  };

  return (
    <Dialog open={open} onOpenChange={lockOpen}>
      <DialogContent className="flex max-h-[85vh] w-[700px] max-w-[700px] flex-col gap-0 overflow-hidden p-0">
        <DialogHeader className="flex flex-row items-center gap-3 space-y-0 border-b border-border px-5 py-4 pr-12 text-left">
          <AlertCircle className="h-5 w-5 shrink-0 text-primary" />
          <div className="flex-1">
            <DialogTitle className="text-sm font-semibold leading-snug">
              人审检查点 — 第{data.chapter}章 {data.title}
            </DialogTitle>
            <p className="mt-0.5 text-xs text-muted">审校完成，请确认是否接受本章内容</p>
          </div>
          <div className="text-right">
            <div className={`text-2xl font-bold ${scoreColor}`}>{data.overall_score}</div>
            <div className="text-[10px] text-muted">综合评分</div>
          </div>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          <div className="space-y-4">
            {data.polished && (
              <div className="flex items-center gap-2 rounded-lg bg-green-500/10 px-3 py-2 text-green-600">
                <Sparkles className="h-4 w-4 shrink-0" />
                <span className="text-sm font-medium">润色已完成，请重新审阅新版本</span>
              </div>
            )}

            {data.summary && (
              <div>
                <h4 className="mb-1 text-xs font-medium text-muted">审校摘要</h4>
                <p className="text-sm">{data.summary}</p>
              </div>
            )}

            {data.issues && data.issues.length > 0 && (
              <div>
                <h4 className="mb-2 text-xs font-medium text-muted">问题清单（{data.issues.length}条）</h4>
                <div className="space-y-2">
                  {data.issues.map((issue, i) => (
                    <div key={i} className="flex gap-2 rounded-lg bg-foreground/5 px-3 py-2 text-sm">
                      <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${
                        issue.severity === "critical" ? "bg-red-500/10 text-red-500" :
                        issue.severity === "important" ? "bg-orange-500/10 text-orange-500" :
                        "bg-yellow-500/10 text-yellow-500"
                      }`}>
                        {issue.severity}
                      </span>
                      <span className="shrink-0 text-xs text-muted">[{issue.dimension}]</span>
                      <span className="flex-1">{issue.message}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {data.draft_preview && (
              <div>
                <h4 className="mb-1 text-xs font-medium text-muted">正文预览（前2000字）</h4>
                <div className="max-h-[200px] overflow-y-auto whitespace-pre-wrap rounded-lg bg-foreground/5 p-3 text-sm leading-relaxed">
                  {data.draft_preview}
                </div>
              </div>
            )}

            {/* 用户意见输入框 */}
            <div>
              <h4 className="mb-1 text-xs font-medium text-muted">
                你的意见（可选）
              </h4>
              <p className="mb-2 text-[11px] text-muted">
                驳回时意见会作为最高优先级指令注入重写 prompt；通过时作为备注记录。
              </p>
              <textarea
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                placeholder="例：主角反应太平淡需要更激烈；结尾钩子不够悬念；某某对话不像活人说的……"
                rows={4}
                className="w-full resize-y rounded-lg border border-border bg-foreground/5 px-3 py-2 text-sm leading-relaxed focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-4">
          <Button variant="outline" size="sm" onClick={handleReject}>
            <X className="mr-1 h-4 w-4" />
            驳回重写
          </Button>
          <Button size="sm" onClick={handleApprove}>
            <Check className="mr-1 h-4 w-4" />
            通过，继续生成
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
