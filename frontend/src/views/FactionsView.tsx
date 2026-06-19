import { useMemo, useState } from "react";
import { Plus, Search, Shield, Sparkles, Swords } from "lucide-react";
import { api } from "@/api";
import { useToast } from "@/hooks/useToast";
import type { AssetType, Faction, Project } from "@/types";
import { AiSuggestionDialog } from "@/components/ai-suggestion-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

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
            <div className="relative flex-1 min-w-[200px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted" />
              <Input
                className="pl-8"
                placeholder="搜索名称/别名…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="h-10 rounded-xl border border-border-strong bg-surface px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
            >
              <option value="">全部类型</option>
              {types.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
            <select
              value={alignmentFilter}
              onChange={(e) => setAlignmentFilter(e.target.value)}
              className="h-10 rounded-xl border border-border-strong bg-surface px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
            >
              <option value="">全部阵营</option>
              {alignments.map((a) => (
                <option key={a} value={a}>{a}</option>
              ))}
            </select>
          </div>
        </CardContent>
      </Card>

      <div className="flex-1 overflow-y-auto pr-1">
        {filtered.length === 0 && (
          <div className="text-center text-sm text-muted py-10">暂无势力，点击右上角新建。</div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {filtered.map((f) => (
            <Card
              key={f.id}
              className="cursor-pointer hover:border-primary/50 transition-colors"
              onClick={() => onSelectAsset?.("faction", String(f.id))}
            >
              <CardContent className="p-4 space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <h4 className="font-medium text-foreground">{f.name}</h4>
                  {f.type && <Badge variant="primary">{f.type}</Badge>}
                </div>
                {f.alias && <p className="text-xs text-muted">别名：{f.alias}</p>}
                {f.alignment && (
                  <div className="flex items-center gap-1 text-xs text-muted">
                    <Swords className="h-3 w-3" /> 阵营：{f.alignment}
                  </div>
                )}
                {f.description && (
                  <p className="text-sm text-muted line-clamp-3 whitespace-pre-wrap">{f.description}</p>
                )}
                {(f.territories || f.resources) && (
                  <div className="flex flex-wrap gap-1 text-xs text-muted">
                    {f.territories && <Badge variant="default">领地</Badge>}
                    {f.resources && <Badge variant="default">资源</Badge>}
                  </div>
                )}
              </CardContent>
            </Card>
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
