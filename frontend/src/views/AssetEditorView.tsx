import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { AssetType, Character, Foreshadow, Outline } from "@/types";

const IMPORTANCE_OPTIONS = ["主角", "配角", "关键人物", "小人物", "NPC"];

interface AssetEditorViewProps {
  type: AssetType;
  character: Partial<Character>;
  setCharacter: (form: Partial<Character>) => void;
  foreshadow: Partial<Foreshadow>;
  setForeshadow: (form: Partial<Foreshadow>) => void;
  outline: Partial<Outline>;
  setOutline: (form: Partial<Outline>) => void;
  onSave: () => void;
  onDelete: () => void;
  onGenerateCharacter?: () => void;
  generatingCharacter?: boolean;
}

export function AssetEditorView({
  type,
  character,
  setCharacter,
  foreshadow,
  setForeshadow,
  outline,
  setOutline,
  onSave,
  onDelete,
  onGenerateCharacter,
  generatingCharacter,
}: AssetEditorViewProps) {
  return (
    <Card className="flex-1 overflow-y-auto">
      <CardHeader>
        <CardTitle>{type === "character" ? "角色" : type === "foreshadow" ? "伏笔" : "大纲"} 编辑</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {type === "character" && (
          <>
            <div className="grid grid-cols-2 gap-3">
              <Input placeholder="姓名" value={character.name || ""} onChange={(e) => setCharacter({ ...character, name: e.target.value })} />
              <Input placeholder="身份" value={character.role || ""} onChange={(e) => setCharacter({ ...character, role: e.target.value })} />
              <Input placeholder="年龄" value={character.age || ""} onChange={(e) => setCharacter({ ...character, age: e.target.value })} />
              <Input placeholder="性别" value={character.gender || ""} onChange={(e) => setCharacter({ ...character, gender: e.target.value })} />
              <Select value={character.importance || ""} onChange={(e) => setCharacter({ ...character, importance: e.target.value })}>
                <option value="">重要程度</option>
                {IMPORTANCE_OPTIONS.map((i) => (
                  <option key={i} value={i}>{i}</option>
                ))}
              </Select>
            </div>
            <Textarea placeholder="外貌" value={character.appearance || ""} onChange={(e) => setCharacter({ ...character, appearance: e.target.value })} />
            <Textarea placeholder="性格" value={character.personality || ""} onChange={(e) => setCharacter({ ...character, personality: e.target.value })} />
            <Textarea placeholder="动机" value={character.motivation || ""} onChange={(e) => setCharacter({ ...character, motivation: e.target.value })} />
            <Textarea placeholder="背景" value={character.background || ""} onChange={(e) => setCharacter({ ...character, background: e.target.value })} />
            <Textarea placeholder="角色弧线" value={character.arc || ""} onChange={(e) => setCharacter({ ...character, arc: e.target.value })} />
            <Textarea placeholder="关系" value={character.relationships || ""} onChange={(e) => setCharacter({ ...character, relationships: e.target.value })} />
            <Textarea placeholder="秘密" value={character.secrets || ""} onChange={(e) => setCharacter({ ...character, secrets: e.target.value })} />
            {onGenerateCharacter && (!character.name || (!character.role && !character.personality && !character.background)) && (
              <Button
                variant="primary"
                onClick={onGenerateCharacter}
                disabled={generatingCharacter}
              >
                <Sparkles className="h-3.5 w-3.5 mr-1" />
                {generatingCharacter ? "生成中…" : "AI 生成角色"}
              </Button>
            )}
          </>
        )}
        {type === "foreshadow" && (
          <>
            <Input placeholder="伏笔 ID" value={foreshadow.foreshadow_id || ""} onChange={(e) => setForeshadow({ ...foreshadow, foreshadow_id: e.target.value })} />
            <Input placeholder="层级" value={foreshadow.tier || ""} onChange={(e) => setForeshadow({ ...foreshadow, tier: e.target.value })} />
            <Textarea placeholder="描述" value={foreshadow.description || ""} onChange={(e) => setForeshadow({ ...foreshadow, description: e.target.value })} />
            <div className="grid grid-cols-2 gap-3">
              <Input type="number" placeholder="埋下章节" value={foreshadow.plant_chapter || ""} onChange={(e) => setForeshadow({ ...foreshadow, plant_chapter: Number(e.target.value) })} />
              <Input type="number" placeholder="回收章节" value={foreshadow.planned_resolve_chapter || ""} onChange={(e) => setForeshadow({ ...foreshadow, planned_resolve_chapter: Number(e.target.value) })} />
            </div>
          </>
        )}
        {type === "outline" && (
          <>
            <Input placeholder="标题" value={outline.title || ""} onChange={(e) => setOutline({ ...outline, title: e.target.value })} />
            <div className="grid grid-cols-3 gap-3">
              <Input type="number" placeholder="顺序" value={outline.order || ""} onChange={(e) => setOutline({ ...outline, order: Number(e.target.value) })} />
              <Select value={outline.act || ""} onChange={(e) => setOutline({ ...outline, act: e.target.value })}>
                <option value="">节拍</option>
                {["开端", "发展", "小高潮", "转折", "大高潮", "结局"].map((a) => (
                  <option key={a} value={a}>{a}</option>
                ))}
              </Select>
              <Select value={outline.strand || ""} onChange={(e) => setOutline({ ...outline, strand: e.target.value as Outline["strand"] })}>
                <option value="">主线</option>
                <option value="quest">主线</option>
                <option value="fire">感情</option>
                <option value="constellation">世界观</option>
              </Select>
            </div>
            <Textarea placeholder="摘要" value={outline.summary || ""} onChange={(e) => setOutline({ ...outline, summary: e.target.value })} />
          </>
        )}
        <div className="flex gap-2">
          <Button onClick={onSave}>保存</Button>
          <Button variant="danger" onClick={onDelete}>删除</Button>
        </div>
      </CardContent>
    </Card>
  );
}
