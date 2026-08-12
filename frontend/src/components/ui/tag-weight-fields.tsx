import { Input } from "@/components/ui/input";

interface TagWeightFieldsProps {
  tags: string[];
  weight: number;
  onTags: (tags: string[]) => void;
  onWeight: (weight: number) => void;
  compact?: boolean;
}

/**
 * P0-2 标签+权重双机制输入区（设定库各资产表单共用）。
 * - 标签=什么时候用：命中本章剧情的标签条目会被注入正文
 * - 权重=排多前/多重要：0-100，高权重靠前占更大篇幅（默认 50 中）
 */
export function TagWeightFields({ tags, weight, onTags, onWeight, compact }: TagWeightFieldsProps) {
  return (
    <div className={`flex flex-wrap items-center gap-2 ${compact ? "" : ""}`}>
      <Input
        className="flex-1 min-w-40"
        placeholder="标签（逗号分隔，如：宗门,战斗 ｜ 命中本章剧情即注入）"
        value={(tags || []).join(",")}
        onChange={(e) =>
          onTags(
            e.target.value
              .split(/[,，]/)
              .map((s) => s.trim())
              .filter(Boolean)
          )
        }
      />
      <div className="flex items-center gap-1.5">
        <Input
          type="number"
          min={0}
          max={100}
          className="w-20"
          value={weight ?? 50}
          onChange={(e) => onWeight(Number(e.target.value))}
        />
        <span className="text-xs text-muted whitespace-nowrap">权重(0-100)</span>
      </div>
    </div>
  );
}
