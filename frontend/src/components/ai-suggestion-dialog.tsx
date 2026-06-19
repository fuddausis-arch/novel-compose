import { useEffect, useState } from "react";
import { Sparkles, Loader2, CheckSquare, Square } from "lucide-react";
import { api } from "@/api";
import { useToast } from "@/hooks/useToast";
import type { Project, SuggestionItem } from "@/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

const TABS = [
  { key: "plot", label: "后续剧情" },
  { key: "monster", label: "怪物" },
  { key: "faction", label: "势力" },
  { key: "relationship", label: "关系" },
];

interface Props {
  open: boolean;
  project: Project;
  contextType: string;
  contextId: string | number;
  defaultSuggestType: string;
  onClose: () => void;
  onAdopted: (created: Record<string, { id: number; title?: string; name?: string }[]>) => void;
}

export function AiSuggestionDialog({ open, project, contextType, contextId, defaultSuggestType, onClose, onAdopted }: Props) {
  const { showSuccess, showError } = useToast();
  const [suggestType, setSuggestType] = useState(defaultSuggestType);
  const [count, setCount] = useState(3);
  const [customPrompt, setCustomPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<SuggestionItem[]>([]);
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<Partial<SuggestionItem>>({});

  useEffect(() => {
    if (open) {
      setSuggestType(defaultSuggestType);
      setSuggestions([]);
      setSelectedKeys(new Set());
      setEditingKey(null);
    }
  }, [open, defaultSuggestType]);

  const keyOf = (s: SuggestionItem, i: number) => `${s.type}-${i}`;

  const handleGenerate = async () => {
    setLoading(true);
    try {
      const r = await api.suggest(project.id, contextType, contextId, suggestType, count, customPrompt);
      setSuggestions(r.suggestions);
      setSelectedKeys(new Set(r.suggestions.map((s, i) => keyOf(s, i))));
    } catch (e: any) {
      showError("生成失败：" + e.message);
    } finally {
      setLoading(false);
    }
  };

  const toggleOne = (key: string) => {
    const next = new Set(selectedKeys);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setSelectedKeys(next);
  };

  const startEdit = (s: SuggestionItem, key: string) => {
    setEditingKey(key);
    setEditForm({ ...s });
  };

  const saveEdit = () => {
    if (!editingKey) return;
    const idx = Number(editingKey.split("-").pop());
    setSuggestions((prev) => prev.map((s, i) => (i === idx ? { ...s, ...editForm } as SuggestionItem : s)));
    setEditingKey(null);
  };

  const handleAdopt = async (status: "adopted" | "partial") => {
    const selected = suggestions.filter((_, i) => selectedKeys.has(keyOf(suggestions[i], i)));
    if (selected.length === 0) return;
    setLoading(true);
    try {
      const r = await api.adoptSuggestions(project.id, {
        context_type: contextType,
        context_id: contextId,
        suggest_type: suggestType,
        prompt: customPrompt,
        raw_response: JSON.stringify(suggestions),
        status,
        suggestions: selected,
      });
      onAdopted(r.created);
      showSuccess(`已采纳 ${selected.length} 项`);
      onClose();
    } catch (e: any) {
      showError("采纳失败：" + e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleReject = async () => {
    await api.adoptSuggestions(project.id, {
      context_type: contextType,
      context_id: contextId,
      suggest_type: suggestType,
      prompt: customPrompt,
      raw_response: JSON.stringify(suggestions),
      status: "rejected",
      suggestions: [],
    });
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-3xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>AI 建议</DialogTitle>
        </DialogHeader>

        <div className="flex items-center gap-2 py-2">
          {TABS.map((t) => (
            <Button
              key={t.key}
              size="sm"
              variant={suggestType === t.key ? "primary" : "ghost"}
              onClick={() => setSuggestType(t.key)}
            >
              {t.label}
            </Button>
          ))}
          <Input type="number" className="w-20 ml-auto" value={count} onChange={(e) => setCount(Number(e.target.value))} />
        </div>

        <Input
          className="mb-3"
          placeholder="自定义要求（可选）"
          value={customPrompt}
          onChange={(e) => setCustomPrompt(e.target.value)}
        />

        <Button onClick={handleGenerate} disabled={loading} className="mb-3">
          {loading ? <Loader2 className="animate-spin h-4 w-4 mr-1" /> : <Sparkles className="h-4 w-4 mr-1" />}
          {loading ? "生成中…" : "生成建议"}
        </Button>

        <div className="flex-1 overflow-y-auto space-y-3 pr-1">
          {suggestions.map((s, i) => {
            const key = keyOf(s, i);
            const selected = selectedKeys.has(key);
            if (editingKey === key) {
              return (
                <div key={key} className="border rounded-xl p-3 space-y-2">
                  <Input value={editForm.title ?? ""} onChange={(e) => setEditForm({ ...editForm, title: e.target.value })} />
                  <Textarea value={editForm.summary ?? ""} onChange={(e) => setEditForm({ ...editForm, summary: e.target.value })} rows={3} />
                  <div className="flex justify-end gap-2">
                    <Button size="sm" variant="ghost" onClick={() => setEditingKey(null)}>取消</Button>
                    <Button size="sm" variant="primary" onClick={saveEdit}>保存</Button>
                  </div>
                </div>
              );
            }
            return (
              <div key={key} className={`border rounded-xl p-3 flex gap-3 ${selected ? "border-primary bg-primary/5" : "opacity-60"}`}>
                <button onClick={() => toggleOne(key)} className="mt-1 shrink-0">
                  {selected ? <CheckSquare className="h-5 w-5 text-primary" /> : <Square className="h-5 w-5 text-muted" />}
                </button>
                <div className="flex-1 min-w-0">
                  <div className="font-medium">{s.title}</div>
                  <div className="text-sm text-muted whitespace-pre-wrap">{s.summary}</div>
                </div>
                <Button size="sm" variant="ghost" onClick={() => startEdit(s, key)}>编辑</Button>
              </div>
            );
          })}
        </div>

        <div className="flex justify-end gap-2 pt-3 border-t mt-3">
          <Button variant="ghost" onClick={handleReject} disabled={loading}>不采纳</Button>
          <Button variant="default" onClick={() => handleAdopt("partial")} disabled={loading || selectedKeys.size === 0}>编辑后采纳</Button>
          <Button variant="primary" onClick={() => handleAdopt("adopted")} disabled={loading || selectedKeys.size === 0}>采纳选中项</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
