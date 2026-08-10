import { useState, useEffect } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { CheckSquare, Square, Trash2 } from "lucide-react";
import type { Character, Foreshadow, Outline, WorldSetting, Faction, FactionRelationship, CharacterRelationship, Monster, Instance, EntityAppearance } from "@/types";

interface ParsedData {
  world_settings: Partial<WorldSetting>[];
  factions: Partial<Faction>[];
  faction_relationships: Partial<FactionRelationship>[];
  character_relationships: Partial<CharacterRelationship>[];
  characters: Partial<Character>[];
  foreshadows: Partial<Foreshadow>[];
  outlines: Partial<Outline>[];
  monsters: Partial<Monster>[];
  instances?: Partial<Instance>[];
  appearances?: Partial<EntityAppearance>[];
}

interface ImportPreviewDialogProps {
  open: boolean;
  data: ParsedData;
  onClose: () => void;
  onImport: (data: ParsedData) => void;
}

type ItemType = "world_settings" | "factions" | "faction_relationships" | "character_relationships" | "characters" | "foreshadows" | "outlines" | "monsters" | "instances" | "appearances";

function keyFor(type: ItemType, item: any) {
  if (type === "world_settings") return `world-${item.category}-${item.title}`;
  if (type === "factions") return `faction-${item.name}`;
  if (type === "faction_relationships") return `facrel-${item.source_faction_id}-${item.target_faction_id}-${item.relation_type}`;
  if (type === "character_relationships") return `charrel-${item.source_character}-${item.target_character}-${item.relation_type}`;
  if (type === "characters") return `char-${item.name}`;
  if (type === "foreshadows") return `fore-${item.foreshadow_id}`;
  if (type === "monsters") return `monster-${item.name}`;
  if (type === "instances") return `inst-${item.name}`;
  if (type === "appearances") return `app-${item.entity_type}-${item.entity_id}-${item.chapter}`;
  return `out-${item.order}-${item.title}`;
}

export function ImportPreviewDialog({ open, data, onClose, onImport }: ImportPreviewDialogProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [items, setItems] = useState<ParsedData>(data);

  useEffect(() => {
    if (open) {
      setItems({ ...data, appearances: data.appearances || [] });
      const all = new Set<string>();
      data.world_settings.forEach((w) => all.add(keyFor("world_settings", w)));
      data.factions.forEach((f) => all.add(keyFor("factions", f)));
      data.faction_relationships.forEach((r) => all.add(keyFor("faction_relationships", r)));
      data.character_relationships.forEach((r) => all.add(keyFor("character_relationships", r)));
      data.characters.forEach((c) => all.add(keyFor("characters", c)));
      data.foreshadows.forEach((f) => all.add(keyFor("foreshadows", f)));
      data.outlines.forEach((o) => all.add(keyFor("outlines", o)));
      data.monsters.forEach((m) => all.add(keyFor("monsters", m)));
      (data.instances || []).forEach((i) => all.add(keyFor("instances", i)));
      (data.appearances || []).forEach((a) => all.add(keyFor("appearances", a)));
      setSelected(all);
    }
  }, [open, data]);

  const counts = {
    world_settings: items.world_settings.length,
    factions: items.factions.length,
    faction_relationships: items.faction_relationships.length,
    character_relationships: items.character_relationships.length,
    characters: items.characters.length,
    foreshadows: items.foreshadows.length,
    outlines: items.outlines.length,
    monsters: items.monsters.length,
    instances: (items.instances || []).length,
    appearances: (items.appearances || []).length,
  };

  const selectedCounts = {
    world_settings: items.world_settings.filter((w) => selected.has(keyFor("world_settings", w))).length,
    factions: items.factions.filter((f) => selected.has(keyFor("factions", f))).length,
    faction_relationships: items.faction_relationships.filter((r) => selected.has(keyFor("faction_relationships", r))).length,
    character_relationships: items.character_relationships.filter((r) => selected.has(keyFor("character_relationships", r))).length,
    characters: items.characters.filter((c) => selected.has(keyFor("characters", c))).length,
    foreshadows: items.foreshadows.filter((f) => selected.has(keyFor("foreshadows", f))).length,
    outlines: items.outlines.filter((o) => selected.has(keyFor("outlines", o))).length,
    monsters: items.monsters.filter((m) => selected.has(keyFor("monsters", m))).length,
    instances: (items.instances || []).filter((i) => selected.has(keyFor("instances", i))).length,
    appearances: (items.appearances || []).filter((a) => selected.has(keyFor("appearances", a))).length,
  };

  const toggle = (type: ItemType, item: any) => {
    const k = keyFor(type, item);
    const next = new Set(selected);
    if (next.has(k)) next.delete(k);
    else next.add(k);
    setSelected(next);
  };

  const remove = (type: ItemType, item: any) => {
    const k = keyFor(type, item);
    setItems((prev) => ({
      ...prev,
      [type]: (prev[type] as any[]).filter((i) => keyFor(type, i) !== k),
    }));
    setSelected((prev) => {
      const next = new Set(prev);
      next.delete(k);
      return next;
    });
  };

  const getList = (type: ItemType) => items[type] || [];

  const toggleAll = (type: ItemType) => {
    const keys = getList(type).map((i) => keyFor(type, i));
    const allSelected = keys.every((k) => selected.has(k));
    const next = new Set(selected);
    keys.forEach((k) => {
      if (allSelected) next.delete(k);
      else next.add(k);
    });
    setSelected(next);
  };

  const handleImport = () => {
    onImport({
      world_settings: items.world_settings.filter((w) => selected.has(keyFor("world_settings", w))),
      factions: items.factions.filter((f) => selected.has(keyFor("factions", f))),
      faction_relationships: items.faction_relationships.filter((r) => selected.has(keyFor("faction_relationships", r))),
      character_relationships: items.character_relationships.filter((r) => selected.has(keyFor("character_relationships", r))),
      characters: items.characters.filter((c) => selected.has(keyFor("characters", c))),
      foreshadows: items.foreshadows.filter((f) => selected.has(keyFor("foreshadows", f))),
      outlines: items.outlines.filter((o) => selected.has(keyFor("outlines", o))),
      monsters: items.monsters.filter((m) => selected.has(keyFor("monsters", m))),
      instances: (items.instances || []).filter((i) => selected.has(keyFor("instances", i))),
      appearances: (items.appearances || []).filter((a) => selected.has(keyFor("appearances", a))),
    });
  };

  const totalSelected = selectedCounts.world_settings + selectedCounts.factions + selectedCounts.faction_relationships + selectedCounts.character_relationships + selectedCounts.characters + selectedCounts.foreshadows + selectedCounts.outlines + selectedCounts.monsters + selectedCounts.instances + selectedCounts.appearances;

  const renderSection = (type: ItemType, title: string, badgeVariant: "default" | "primary" | "warning" | "success" | "danger") => {
    const list = getList(type);
    if (list.length === 0) return null;
    const allSelected = list.every((i) => selected.has(keyFor(type, i)));
    return (
      <div className="border border-border rounded-xl p-3 space-y-2 bg-surface/50">
        <div className="flex items-center justify-between">
          <h4 className="font-medium text-sm flex items-center gap-2">{title} <Badge variant={badgeVariant}>{selectedCounts[type]}/{counts[type]}</Badge></h4>
          <Button variant="ghost" size="sm" onClick={() => toggleAll(type)}>
            {allSelected ? <CheckSquare className="h-4 w-4 mr-1" /> : <Square className="h-4 w-4 mr-1" />}
            {allSelected ? "取消全选" : "全选"}
          </Button>
        </div>
        <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
          {list.map((item: any) => {
            const k = keyFor(type, item);
            const isSelected = selected.has(k);
            return (
              <div key={k} className={`flex items-start gap-2 rounded-lg border p-2 ${isSelected ? "border-primary bg-primary/5" : "border-border bg-surface opacity-60"}`}>
                <button onClick={() => toggle(type, item)} className="mt-0.5 shrink-0">
                  {isSelected ? <CheckSquare className="h-5 w-5 text-primary" /> : <Square className="h-5 w-5 text-muted" />}
                </button>
                <div className="flex-1 min-w-0 text-sm">
                  {type === "characters" && (
                    <>
                      <span className="font-medium">{item.name}</span>
                      {item.role && <Badge className="ml-2 text-xs">{item.role}</Badge>}
                      {item.importance && <Badge variant="primary" className="ml-2 text-xs">{item.importance}</Badge>}
                      <p className="text-muted text-xs mt-0.5 line-clamp-3">{item.personality || item.background || item.motivation || "暂无描述"}</p>
                    </>
                  )}
                  {type === "foreshadows" && (
                    <>
                      <span className="font-medium">{item.foreshadow_id}</span>
                      <span className="text-muted text-xs ml-2">埋下{item.plant_chapter || "-"} · 回收{item.planned_resolve_chapter || "-"}</span>
                      <p className="text-muted text-xs mt-0.5 line-clamp-3">{item.description}</p>
                    </>
                  )}
                  {type === "outlines" && (
                    <>
                      <span className="font-medium">第{item.order}章 {item.title}</span>
                      <p className="text-muted text-xs mt-0.5 line-clamp-3">{item.summary}</p>
                    </>
                  )}
                  {type === "world_settings" && (
                    <>
                      <span className="font-medium">{item.title}</span>
                      {item.category && <Badge className="ml-2 text-xs">{item.category}</Badge>}
                      <p className="text-muted text-xs mt-0.5 line-clamp-3">{item.content || "暂无内容"}</p>
                    </>
                  )}
                  {type === "factions" && (
                    <>
                      <span className="font-medium">{item.name}</span>
                      {item.type && <Badge className="ml-2 text-xs">{item.type}</Badge>}
                      {item.tier && <Badge variant="primary" className="ml-2 text-xs">{item.tier}</Badge>}
                      <p className="text-muted text-xs mt-0.5 line-clamp-3">{item.description || "暂无描述"}</p>
                    </>
                  )}
                  {type === "faction_relationships" && (
                    <>
                      <span className="font-medium">势力 {item.source_faction_id} → {item.target_faction_id}</span>
                      {item.relation_type && <Badge className="ml-2 text-xs">{item.relation_type}</Badge>}
                      <p className="text-muted text-xs mt-0.5 line-clamp-3">{item.description || "强度 " + (item.strength ?? 0)}</p>
                    </>
                  )}
                  {type === "character_relationships" && (
                    <>
                      <span className="font-medium">{item.source_character} → {item.target_character}</span>
                      {item.relation_type && <Badge className="ml-2 text-xs">{item.relation_type}</Badge>}
                      <p className="text-muted text-xs mt-0.5 line-clamp-3">{item.description || "强度 " + (item.strength ?? 0)}</p>
                    </>
                  )}
                  {type === "monsters" && (
                    <>
                      <span className="font-medium">{item.name}</span>
                      {item.rank && <Badge className="ml-2 text-xs">{item.rank}</Badge>}
                      {item.tier && <Badge variant="danger" className="ml-2 text-xs">{item.tier}</Badge>}
                      <p className="text-muted text-xs mt-0.5 line-clamp-3">{item.species || item.behavior || "暂无描述"}</p>
                    </>
                  )}
                  {type === "instances" && (
                    <>
                      <span className="font-medium">{item.name}</span>
                      {item.instance_type && <Badge className="ml-2 text-xs">{item.instance_type}</Badge>}
                      {item.difficulty && <Badge variant="primary" className="ml-2 text-xs">{item.difficulty}</Badge>}
                      <p className="text-muted text-xs mt-0.5 line-clamp-3">{item.objective || item.description || "暂无描述"}</p>
                    </>
                  )}
                  {type === "appearances" && (
                    <>
                      <span className="font-medium">{item.entity_type} #{item.entity_id}</span>
                      <Badge className="ml-2 text-xs">第{item.chapter || "-"}章</Badge>
                      <Badge variant="primary" className="ml-2 text-xs">{item.role_in_chapter || "-"}</Badge>
                      <p className="text-muted text-xs mt-0.5 line-clamp-3">{item.context_snippet || "无上下文"}</p>
                    </>
                  )}
                </div>
                <button onClick={() => remove(type, item)} className="p-1 hover:bg-foreground/5 rounded shrink-0" title="删除">
                  <Trash2 className="h-3.5 w-3.5 text-danger" />
                </button>
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-3xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>AI 提取结果预览与筛选</DialogTitle>
        </DialogHeader>
        <div className="flex-1 overflow-y-auto space-y-3 pr-1">
          {counts.world_settings + counts.factions + counts.faction_relationships + counts.character_relationships + counts.characters + counts.foreshadows + counts.outlines + counts.monsters + counts.instances + counts.appearances === 0 && (
            <div className="text-center text-sm text-muted py-8">未提取到任何内容</div>
          )}
          {renderSection("world_settings", "世界观设定", "primary")}
          {renderSection("factions", "势力", "primary")}
          {renderSection("faction_relationships", "势力关系", "warning")}
          {renderSection("characters", "角色", "success")}
          {renderSection("character_relationships", "人物关系", "warning")}
          {renderSection("foreshadows", "伏笔", "warning")}
          {renderSection("outlines", "大纲", "default")}
          {renderSection("monsters", "怪物", "danger")}
          {renderSection("instances", "副本", "primary")}
          {renderSection("appearances", "出场记录", "primary")}
        </div>
        <div className="flex justify-between items-center pt-3 border-t">
          <span className="text-xs text-muted">已选 {totalSelected} 项</span>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>放弃</Button>
            <Button variant="primary" onClick={handleImport} disabled={totalSelected === 0}>
              导入 {totalSelected} 项到框架
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
