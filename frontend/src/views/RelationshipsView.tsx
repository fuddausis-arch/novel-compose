import { useMemo, useState } from "react";
import { Plus, Network, Sparkles } from "lucide-react";
import { api } from "@/api";
import { useToast } from "@/hooks/useToast";
import type { AssetType, Character, CharacterRelationship, Project } from "@/types";
import { AiSuggestionDialog } from "@/components/ai-suggestion-dialog";
import { Button } from "@/components/ui/button";
import { SearchInput } from "@/components/ui/search-input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface RelationshipsViewProps {
  project: Project | null;
  characters: Character[];
  relationships: CharacterRelationship[];
  refresh: () => Promise<void>;
  setLoading?: (loading: boolean) => void;
  onSelectAsset?: (type: AssetType, id: string) => void;
  onGenerateRelationship?: () => void;
  generatingRelationship?: boolean;
}

export function RelationshipsView({ project, characters, relationships, refresh, setLoading, onSelectAsset, onGenerateRelationship, generatingRelationship }: RelationshipsViewProps) {
  if (!project) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted text-sm">
        请先选择或创建一个项目
      </div>
    );
  }

  const { showSuccess, showError } = useToast();
  const [search, setSearch] = useState("");
  const [suggestOpen, setSuggestOpen] = useState(false);

  const filtered = useMemo(() => {
    if (!search) return relationships;
    const s = search.toLowerCase();
    return relationships.filter(
      (r) =>
        r.source_character.toLowerCase().includes(s) ||
        r.target_character.toLowerCase().includes(s)
    );
  }, [relationships, search]);

  const handleCreate = async () => {
    setLoading?.(true);
    try {
      const names = characters.map((c) => c.name).filter(Boolean);
      const source = names[0] || "角色A";
      const target = names[1] || "角色B";
      const r = await api.createCharacterRelationship(project.id, {
        source_character: source,
        target_character: target,
        relation_type: "其他",
        strength: 0,
      });
      await refresh();
      showSuccess("已创建关系");
      onSelectAsset?.("characterRelationship", String(r.id));
    } catch (e: any) {
      showError("创建失败：" + e.message);
    } finally {
      setLoading?.(false);
    }
  };

  const strengthPercent = (v: number) => {
    const clamped = Math.max(-10, Math.min(10, v));
    return ((clamped + 10) / 20) * 100;
  };

  const strengthColor = (v: number) => {
    if (v > 0) return "bg-success";
    if (v < 0) return "bg-danger";
    return "bg-muted";
  };

  return (
    <div className="flex-1 flex flex-col gap-3 min-h-0 overflow-hidden">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Network className="h-4 w-4 text-primary" />
              人物关系网
            </CardTitle>
            <div className="flex gap-2">
              {onGenerateRelationship && (
                <Button size="sm" variant="primary" onClick={onGenerateRelationship} disabled={generatingRelationship}>
                  <Sparkles className="h-3.5 w-3.5 mr-1" />
                  {generatingRelationship ? "生成中…" : "AI 生成关系"}
                </Button>
              )}
              <Button size="sm" variant="default" onClick={() => setSuggestOpen(true)}>
                <Sparkles className="h-3.5 w-3.5 mr-1" /> AI 建议关系
              </Button>
              <Button size="sm" onClick={handleCreate}>
                <Plus className="h-3.5 w-3.5 mr-1" /> 新建关系
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <SearchInput
            value={search}
            onChange={setSearch}
            placeholder="按源/目标角色名筛选…"
          />
        </CardContent>
      </Card>

      <div className="flex-1 overflow-y-auto pr-1 space-y-3">
        {filtered.length === 0 && (
          <div className="text-center text-sm text-muted py-10">暂无人际关系，点击右上角新建。</div>
        )}
        {filtered.map((r) => (
          <Card
            key={r.id}
            className="cursor-pointer hover:border-primary/50 transition-colors"
            onClick={() => onSelectAsset?.("characterRelationship", String(r.id))}
          >
            <CardContent className="p-4 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-sm">
                  <span className="font-medium">{r.source_character}</span>
                  <span className="text-muted">→</span>
                  <span className="font-medium">{r.target_character}</span>
                </div>
                <Badge variant={r.strength > 0 ? "success" : r.strength < 0 ? "danger" : "default"}>
                  {r.relation_type}
                </Badge>
              </div>
              {r.relation_subtype && <p className="text-xs text-muted">子类型：{r.relation_subtype}</p>}
              <div className="flex items-center gap-2">
                <div className="flex-1 h-2 bg-foreground/10 rounded-full overflow-hidden">
                  <div
                    className={`h-full ${strengthColor(r.strength)}`}
                    style={{ width: `${strengthPercent(r.strength)}%` }}
                  />
                </div>
                <span className="text-xs text-muted w-8 text-right">{r.strength}</span>
              </div>
              <div className="flex items-center gap-2 text-xs text-muted">
                <span>状态：{r.status || "active"}</span>
                {r.is_bidirectional && <Badge variant="default">双向</Badge>}
                {r.since_chapter > 0 && <span>始于第{r.since_chapter}章</span>}
              </div>
              {r.description && <p className="text-sm text-muted line-clamp-2 whitespace-pre-wrap">{r.description}</p>}
            </CardContent>
          </Card>
        ))}
      </div>

      <AiSuggestionDialog
        open={suggestOpen}
        project={project}
        contextType="relationship"
        contextId=""
        defaultSuggestType="relationship"
        onClose={() => setSuggestOpen(false)}
        onAdopted={() => {
          refresh();
          showSuccess("建议已采纳");
        }}
      />
    </div>
  );
}