import { useMemo, useState } from "react";
import { Plus, Map } from "lucide-react";
import { api } from "@/api";
import { useToast } from "@/hooks/useToast";
import type { AssetType, Instance, Project } from "@/types";
import { Button } from "@/components/ui/button";
import { SearchInput } from "@/components/ui/search-input";
import { FilterSelect } from "@/components/ui/filter-select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EntityCard } from "@/components/entity/entity-card";

interface InstancesViewProps {
  project: Project | null;
  instances: Instance[];
  refresh: () => Promise<void>;
  setLoading?: (loading: boolean) => void;
  onSelectAsset?: (type: AssetType, id: string) => void;
}

export function InstancesView({ project, instances, refresh, setLoading, onSelectAsset }: InstancesViewProps) {
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
  const [difficultyFilter, setDifficultyFilter] = useState("");

  const instanceTypes = useMemo(() => Array.from(new Set(instances.map((i) => i.instance_type).filter(Boolean))), [instances]);
  const difficulties = useMemo(() => Array.from(new Set(instances.map((i) => i.difficulty).filter(Boolean))), [instances]);

  const filtered = useMemo(() => {
    return instances.filter((i) => {
      const matchSearch = !search || i.name.toLowerCase().includes(search.toLowerCase());
      const matchType = !typeFilter || i.instance_type === typeFilter;
      const matchDifficulty = !difficultyFilter || i.difficulty === difficultyFilter;
      return matchSearch && matchType && matchDifficulty;
    });
  }, [instances, search, typeFilter, difficultyFilter]);

  const handleCreate = async () => {
    setLoading?.(true);
    try {
      const i = await api.createInstance(project.id, { name: "新副本", instance_type: "其他" });
      await refresh();
      showSuccess("已创建副本");
      onSelectAsset?.("instance", String(i.id));
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
              <Map className="h-4 w-4 text-primary" />
              副本图鉴
            </CardTitle>
            <Button size="sm" onClick={handleCreate}>
              <Plus className="h-3.5 w-3.5 mr-1" /> 新建副本
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <SearchInput
              value={search}
              onChange={setSearch}
              placeholder="搜索副本名称…"
              className="flex-1 min-w-[200px]"
            />
            <FilterSelect value={typeFilter} onChange={setTypeFilter} options={instanceTypes} placeholder="全部类型" />
            <FilterSelect value={difficultyFilter} onChange={setDifficultyFilter} options={difficulties} placeholder="全部难度" />
          </div>
        </CardContent>
      </Card>

      <div className="flex-1 overflow-y-auto pr-1">
        {filtered.length === 0 && (
          <div className="text-center text-sm text-muted py-10">暂无副本，点击右上角新建。</div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {filtered.map((i) => (
            <EntityCard
              key={i.id}
              onClick={() => onSelectAsset?.("instance", String(i.id))}
              title={i.name}
              badge={i.instance_type && <Badge variant="primary">{i.instance_type}</Badge>}
              description={i.objective}
              footer={i.rewards && (
                <p className="text-xs text-muted line-clamp-2 whitespace-pre-wrap">奖励：{i.rewards}</p>
              )}
            >
              <div className="flex flex-wrap gap-1 text-xs text-muted">
                {i.chapter_range && <Badge variant="default">{i.chapter_range}</Badge>}
                {i.difficulty && <Badge variant="default">{i.difficulty}</Badge>}
                {i.tone && <Badge variant="default">{i.tone}</Badge>}
              </div>
            </EntityCard>
          ))}
        </div>
      </div>
    </div>
  );
}
