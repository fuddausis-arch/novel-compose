/** 全局设置 · 概览页：以卡片网格展示所有管理模块，点击跳转对应子页面 */
import { useNavigate } from "react-router-dom";
import {
  Archive,
  BookOpen,
  Bot,
  Boxes,
  Clock,
  Cpu,
  FileCode,
  FlaskConical,
  FolderOpen,
  LayoutDashboard,
  ScrollText,
  type LucideIcon,
} from "lucide-react";
import { Card } from "@/components/ui/card";

interface OverviewCard {
  title: string;
  description: string;
  icon: LucideIcon;
  path: string;
}

const CARDS: OverviewCard[] = [
  { title: "模型管理", description: "配置 LLM 供应商、API 密钥与模型优先级", icon: Cpu, path: "/settings/models" },
  { title: "Agent 定义", description: "管理各 Agent 类型的参数与默认行为", icon: Bot, path: "/settings/agents" },
  { title: "Prompt 编排", description: "编排提示词 Sections、工具与用户注入", icon: FileCode, path: "/settings/orchestration" },
  { title: "Skills 管理", description: "管理可复用的知识与行为模块", icon: BookOpen, path: "/settings/skills" },
  { title: "Rules 管理", description: "管理注入 system prompt 的创作规则", icon: ScrollText, path: "/settings/rules" },
  { title: "插件管理", description: "安装、启停与卸载扩展插件", icon: Boxes, path: "/settings/plugins" },
  { title: "定时任务", description: "调度 Agent 定时执行提示词任务", icon: Clock, path: "/settings/cron" },
  { title: "压缩监控", description: "查看上下文压缩统计与历史日志", icon: Archive, path: "/settings/compression" },
  { title: "工作区", description: "浏览与管理项目工作区文件", icon: FolderOpen, path: "/settings/workspace" },
  { title: "蒸馏技能", description: "从优质作品蒸馏写作技能，去除 AI 味", icon: FlaskConical, path: "/settings/distillation" },
];

export default function SettingsOverview() {
  const navigate = useNavigate();

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-6 p-6">
        {/* 标题栏 */}
        <div className="flex items-center gap-3">
          <div className="rounded-lg border border-border bg-primary-muted p-2 text-primary">
            <LayoutDashboard className="h-5 w-5" />
          </div>
          <div>
            <h2 className="text-lg font-semibold">设置概览</h2>
            <p className="text-sm text-muted">选择一个模块进入详细配置</p>
          </div>
        </div>

        {/* 卡片网格 */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" role="list">
          {CARDS.map((card) => {
            const Icon = card.icon;
            return (
              <Card
                key={card.title}
                role="listitem"
                className="cursor-pointer transition-colors hover:border-primary/40 hover:bg-surface-hover"
                onClick={() => navigate(card.path)}
              >
                <div className="flex items-start gap-3">
                  <div className="rounded-lg border border-border bg-primary-muted p-2 text-primary">
                    <Icon className="h-5 w-5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <h3 className="text-sm font-semibold">{card.title}</h3>
                    <p className="mt-1 text-xs text-muted">{card.description}</p>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      </div>
    </div>
  );
}
