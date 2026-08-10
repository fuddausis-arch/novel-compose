import { useMemo, useState } from "react";
import { Plus, Skull, Sparkles } from "lucide-react";
import { api } from "@/api";
import { useToast } from "@/hooks/useToast";
import type { AssetType, Monster, Project } from "@/types";
import { AiSuggestionDialog } from "@/components/ai-suggestion-dialog";
import { Button } from "@/components/ui/button";
import { SearchInput } from "@/components/ui/search-input";
import { FilterSelect } from "@/components/ui/filter-select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EntityCard } from "@/components/entity/entity-card";

interface MonstersViewProps {
  project: Project | null;
  monsters: Monster[];
  refresh: () => Promise<void>;
  setLoading?: (loading: boolean) => void;
  onSelectAsset?: (type: AssetType, id: string) => void;
}

export function MonstersView({ project, monsters, refresh, setLoading, onSelectAsset }: MonstersViewProps) {
  if (!project) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted text-sm">
        请先选择或创建一个项目
      </div>
    );
  }

  const { showSuccess, showError } = useToast();
  const [search, setSearch] = useState("");
  const [rankFilter, setRankFilter] = useState("");
  const [speciesFilter, setSpeciesFilter] = useState("");
  const [habitatFilter, setHabitatFilter] = useState("");
  const [suggestOpen, setSuggestOpen] = useState(false);

  const ranks = useMemo(() => Array.from(new Set(monsters.map((m) => m.rank).filter(Boolean))), [monsters]);
  const species = useMemo(() => Array.from(new Set(monsters.map((m) => m.species).filter(Boolean))), [monsters]);
  const habitats = useMemo(
    () => Array.from(new Set(monsters.flatMap((m) => m.habitats.split(",").map((h) => h.trim()).filter(Boolean)))),
    [monsters]
  );

  const filtered = useMemo(() => {
    return monsters.filter((m) => {
      const matchSearch =
        !search ||
        m.name.toLowerCase().includes(search.toLowerCase()) ||
        m.alias.toLowerCase().includes(search.toLowerCase());
      const matchRank = !rankFilter || m.rank === rankFilter;
      const matchSpecies = !speciesFilter || m.species === speciesFilter;
      const matchHabitat = !habitatFilter || m.habitats.toLowerCase().includes(habitatFilter.toLowerCase());
      return matchSearch && matchRank && matchSpecies && matchHabitat;
    });
  }, [monsters, search, rankFilter, speciesFilter, habitatFilter]);

  const handleCreate = async () => {
    setLoading?.(true);
    try {
      const m = await api.createMonster(project.id, { name: "新怪物", species: "未知", rank: "普通" });
      await refresh();
      showSuccess("已创建怪物");
      onSelectAsset?.("monster", String(m.id));
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
              <Skull className="h-4 w-4 text-primary" />
              怪物图鉴
            </CardTitle>
            <Button size="sm" variant="default" onClick={() => setSuggestOpen(true)}>
              <Sparkles className="h-3.5 w-3.5 mr-1" /> AI 建议怪物
            </Button>
            <Button size="sm" onClick={handleCreate}>
              <Plus className="h-3.5 w-3.5 mr-1" /> 新建怪物
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
            <FilterSelect value={rankFilter} onChange={setRankFilter} options={ranks} placeholder="全部等级" />
            <FilterSelect value={speciesFilter} onChange={setSpeciesFilter} options={species} placeholder="全部种族" />
            <FilterSelect value={habitatFilter} onChange={setHabitatFilter} options={habitats} placeholder="全部栖息地" />
          </div>
        </CardContent>
      </Card>

      <div className="flex-1 overflow-y-auto pr-1">
        {filtered.length === 0 && (
          <div className="text-center text-sm text-muted py-10">暂无怪物，点击右上角新建。</div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {filtered.map((m) => (
            <EntityCard
              key={m.id}
              onClick={() => onSelectAsset?.("monster", String(m.id))}
              title={m.name}
              badge={m.rank && <Badge variant="danger">{m.rank}</Badge>}
              description={m.behavior}
              footer={m.first_appearance > 0 && (
                <p className="text-xs text-muted">首次出场：第{m.first_appearance}章</p>
              )}
            >
              {m.alias && <p className="text-xs text-muted">别名：{m.alias}</p>}
              <div className="flex flex-wrap gap-1 text-xs text-muted">
                {m.species && <Badge variant="default">{m.species}</Badge>}
                {m.habitats && <Badge variant="default">{m.habitats}</Badge>}
              </div>
            </EntityCard>
          ))}
        </div>
      </div>

      <AiSuggestionDialog
        open={suggestOpen}
        project={project}
        contextType="monster"
        contextId=""
        defaultSuggestType="monster"
        onClose={() => setSuggestOpen(false)}
        onAdopted={(created) => {
          refresh();
          const first = created.monsters?.[0];
          if (first && onSelectAsset) onSelectAsset("monster", String(first.id));
          showSuccess("建议已采纳");
        }}
      />
    </div>
  );
}
