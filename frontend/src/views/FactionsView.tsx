import { useMemo, useState } from "react";
import { Plus, Shield, Sparkles, Swords } from "lucide-react";
import { api } from "@/api";
import { useToast } from "@/hooks/useToast";
import type { AssetType, Faction, Project } from "@/types";
import { AiSuggestionDialog } from "@/components/ai-suggestion-dialog";
import { Button } from "@/components/ui/button";
import { SearchInput } from "@/components/ui/search-input";
import { FilterSelect } from "@/components/ui/filter-select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EntityCard } from "@/components/entity/entity-card";

interface FactionsViewProps {
  project: Project | null;
  factions: Faction[];
  refresh: () => Promise<void>;
  setLoading?: (loading: boolean) => void;
  onSelectAsset?: (type: AssetType, id: string) => void;
}

export function FactionsView({ project, factions, refresh, setLoading, onSelectAsset }: FactionsViewProps) {
  if (!project) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted text-sm">
        请先选择或创建一个项目
      </div>
    );
  }

  const { showSuccess, showError } = useToast();
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [alignmentFilter, setAlignmentFilter] = useState("");
  const [suggestOpen, setSuggestOpen] = useState(false);

  const types = useMemo(() => Array.from(new Set(factions.map((f) => f.type).filter(Boolean))), [factions]);
  const alignments = useMemo(() => Array.from(new Set(factions.map((f) => f.alignment).filter(Boolean))), [factions]);

  const filtered = useMemo(() => {
    return factions.filter((f) => {
      const matchSearch =
        !search ||
        f.name.toLowerCase().includes(search.toLowerCase()) ||
        f.alias.toLowerCase().includes(search.toLowerCase());
      const matchType = !typeFilter || f.type === typeFilter;
      const matchAlignment = !alignmentFilter || f.alignment === alignmentFilter;
      return matchSearch && matchType && matchAlignment;
    });
  }, [factions, search, typeFilter, alignmentFilter]);

  const handleCreate = async () => {
    setLoading?.(true);
    try {
      const f = await api.createFaction(project.id, { name: "新势力", type: "其他", alignment: "中立" });
      await refresh();
      showSuccess("已创建势力");
      onSelectAsset?.("faction", String(f.id));
    } catch (e: any) {
      showError("创建失败：" + e.message);
    } finally {
      setLoading?.(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col gap-3 min-h-0 overflow-hidden">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Shield className="h-4 w-4 text-primary" />
              势力组织
            </CardTitle>
            <Button size="sm" variant="default" onClick={() => setSuggestOpen(true)}>
              <Sparkles className="h-3.5 w-3.5 mr-1" /> AI 建议势力
            </Button>
            <Button size="sm" onClick={handleCreate}>
              <Plus className="h-3.5 w-3.5 mr-1" /> 新建势力
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <SearchInput
              value={search}
              onChange={setSearch}
              placeholder="搜索名称/别名…"
              className="flex-1 min-w-[200px]"
            />
            <FilterSelect value={typeFilter} onChange={setTypeFilter} options={types} placeholder="全部类型" />
            <FilterSelect value={alignmentFilter} onChange={setAlignmentFilter} options={alignments} placeholder="全部阵营" />
          </div>
        </CardContent>
      </Card>

      <div className="flex-1 overflow-y-auto pr-1">
        {filtered.length === 0 && (
          <div className="text-center text-sm text-muted py-10">暂无势力，点击右上角新建。</div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {filtered.map((f) => (
            <EntityCard
              key={f.id}
              onClick={() => onSelectAsset?.("faction", String(f.id))}
              title={f.name}
              badge={f.type && <Badge variant="primary">{f.type}</Badge>}
              description={f.description}
              footer={(f.territories || f.resources) && (
                <div className="flex flex-wrap gap-1 text-xs text-muted">
                  {f.territories && <Badge variant="default">领地</Badge>}
                  {f.resources && <Badge variant="default">资源</Badge>}
                </div>
              )}
            >
              {f.alias && <p className="text-xs text-muted">别名：{f.alias}</p>}
              {f.alignment && (
                <div className="flex items-center gap-1 text-xs text-muted">
                  <Swords className="h-3 w-3" /> 阵营：{f.alignment}
                </div>
              )}
              {f.tags && f.tags.length > 0 && (
                <p className="text-xs text-muted">
                  <span className="text-foreground">标签：</span>
                  {f.tags.join("、")}
                </p>
              )}
              {f.weight !== undefined && (
                <p className="text-xs text-muted">
                  <span className="text-foreground">权重：</span>
                  {f.weight}
                </p>
              )}
            </EntityCard>
          ))}
        </div>
      </div>

      <AiSuggestionDialog
        open={suggestOpen}
        project={project}
        contextType="faction"
        contextId=""
        defaultSuggestType="faction"
        onClose={() => setSuggestOpen(false)}
        onAdopted={(created) => {
          refresh();
          const first = created.factions?.[0];
          if (first && onSelectAsset) onSelectAsset("faction", String(first.id));
          showSuccess("建议已采纳");
        }}
      />
    </div>
  );
}
