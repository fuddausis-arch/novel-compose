/** 预设短语管理面板：分组列表 / CRUD
 * 对接 /api/preset-phrases 系列端点。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { MessageSquareText, Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
import { apiFetch, apiJson } from "./df-api";
import {
  DFConfirmDialog,
  DFCard,
  DFEmpty,
  DFErrorToast,
  DFFormField,
  DFIconButton,
  DFInput,
  DFLoading,
  DFModal,
  DFPrimaryButton,
  DFSearchInput,
  DFSecondaryButton,
  DFTag,
  DFTextarea,
} from "./df-ui";
import { useToast } from "@/hooks/useToast";

/** 预设短语（与后端 PhraseBase + id 对齐） */
interface Phrase {
  id: string;
  category: string;
  text: string;
  shortcut: string;
}

interface PhraseFormState {
  category: string;
  text: string;
  shortcut: string;
}

const EMPTY_FORM: PhraseFormState = { category: "通用指令", text: "", shortcut: "" };

export default function PhrasesPanel() {
  const { showSuccess } = useToast();
  const [phrases, setPhrases] = useState<Phrase[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);

  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Phrase | null>(null);
  const [deleting, setDeleting] = useState<Phrase | null>(null);
  const [form, setForm] = useState<PhraseFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async (initial = false) => {
    if (initial) setLoading(true);
    else setRefreshing(true);
    try {
      const data = await apiFetch<{ phrases: Phrase[] }>("/api/preset-phrases");
      setPhrases(data.phrases || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载预设短语失败");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load(true);
  }, [load]);

  /** 搜索后按分类分组 */
  const grouped = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    const filtered = phrases.filter(
      (p) =>
        !keyword ||
        p.text.toLowerCase().includes(keyword) ||
        p.category.toLowerCase().includes(keyword) ||
        p.shortcut.toLowerCase().includes(keyword),
    );
    const map = new Map<string, Phrase[]>();
    for (const p of filtered) {
      const cat = p.category || "通用指令";
      if (!map.has(cat)) map.set(cat, []);
      map.get(cat)!.push(p);
    }
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [phrases, search]);

  /** 已有分类列表（供新建时参考） */
  const categories = useMemo(
    () => Array.from(new Set(phrases.map((p) => p.category || "通用指令"))),
    [phrases],
  );

  const openCreate = () => {
    setForm(EMPTY_FORM);
    setFormError(null);
    setCreating(true);
  };

  const openEdit = (phrase: Phrase) => {
    setForm({ category: phrase.category, text: phrase.text, shortcut: phrase.shortcut });
    setFormError(null);
    setEditing(phrase);
  };

  const handleSubmit = async () => {
    if (!form.text.trim()) {
      setFormError("请输入短语内容");
      return;
    }
    setSaving(true);
    setFormError(null);
    const payload = {
      category: form.category.trim() || "通用指令",
      text: form.text.trim(),
      shortcut: form.shortcut.trim(),
    };
    try {
      if (creating) {
        await apiJson("/api/preset-phrases", "POST", payload);
        showSuccess("预设短语已创建");
      } else if (editing) {
        await apiJson(`/api/preset-phrases/${encodeURIComponent(editing.id)}`, "PUT", payload);
        showSuccess("预设短语已保存");
      }
      setCreating(false);
      setEditing(null);
      await load();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleting) return;
    setSaving(true);
    try {
      await apiJson(`/api/preset-phrases/${encodeURIComponent(deleting.id)}`, "DELETE");
      showSuccess("预设短语已删除");
      setDeleting(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <DFLoading text="正在加载预设短语..." />;

  return (
    <div className="space-y-3">
      {/* 工具栏 */}
      <div className="flex flex-wrap items-center gap-2">
        <DFSearchInput
          className="w-56"
          placeholder="搜索短语 / 分类 / 快捷键..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="搜索预设短语"
        />
        <div className="ml-auto flex items-center gap-2">
          <DFSecondaryButton onClick={() => void load()} disabled={refreshing}>
            <RefreshCw size={12} className={refreshing ? "animate-spin motion-reduce:animate-none" : ""} aria-hidden="true" />
            刷新
          </DFSecondaryButton>
          <DFPrimaryButton onClick={openCreate}>
            <Plus size={12} aria-hidden="true" />
            新建短语
          </DFPrimaryButton>
        </div>
      </div>

      {/* 分组列表 */}
      {grouped.length === 0 ? (
        <DFEmpty
          title={search ? "未找到匹配的短语" : "暂无预设短语"}
          description={search ? "换个关键词试试" : "预设短语可在对话页快速注入常用指令"}
        />
      ) : (
        <div className="space-y-4">
          {grouped.map(([category, items]) => (
            <section key={category} aria-label={`分类 ${category}`}>
              <div className="mb-2 flex items-center gap-2">
                <MessageSquareText size={14} className="text-indigo-400" aria-hidden="true" />
                <h3 className="text-sm font-semibold text-foreground">{category}</h3>
                <span className="text-xs text-muted tabular-nums">{items.length} 条</span>
              </div>
              <div className="space-y-2" role="list">
                {items.map((p) => (
                  <DFCard key={p.id} role="listitem" className="p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <p className="whitespace-pre-wrap text-sm text-foreground">{p.text}</p>
                        {p.shortcut && (
                          <div className="mt-1.5">
                            <DFTag className="font-mono">{p.shortcut}</DFTag>
                          </div>
                        )}
                      </div>
                      <div className="flex shrink-0 items-center gap-1">
                        <DFIconButton
                          onClick={() => openEdit(p)}
                          title="编辑"
                          aria-label={`编辑短语 ${p.shortcut || p.text.slice(0, 10)}`}
                          className="min-h-[36px] min-w-[36px]"
                        >
                          <Pencil size={14} aria-hidden="true" />
                        </DFIconButton>
                        <DFIconButton
                          onClick={() => setDeleting(p)}
                          title="删除"
                          aria-label="删除该短语"
                          className="min-h-[36px] min-w-[36px] hover:text-red-400"
                        >
                          <Trash2 size={14} aria-hidden="true" />
                        </DFIconButton>
                      </div>
                    </div>
                  </DFCard>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      {/* 新建 / 编辑弹窗 */}
      {(creating || editing) && (
        <DFModal
          title={creating ? "新建预设短语" : "编辑预设短语"}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
          footer={
            <>
              <DFSecondaryButton
                onClick={() => {
                  setCreating(false);
                  setEditing(null);
                }}
                disabled={saving}
              >
                取消
              </DFSecondaryButton>
              <DFPrimaryButton onClick={() => void handleSubmit()} disabled={saving}>
                {saving ? "保存中..." : "保存"}
              </DFPrimaryButton>
            </>
          }
        >
          <div className="space-y-4">
            <DFFormField label="分类" htmlFor="phrase-category" hint={`已有分类：${categories.join(" / ") || "无"}`}>
              <DFInput
                id="phrase-category"
                value={form.category}
                onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
                placeholder="如 写作指令 / 审查指令"
                list="phrase-category-options"
              />
              <datalist id="phrase-category-options">
                {categories.map((c) => (
                  <option key={c} value={c} />
                ))}
              </datalist>
            </DFFormField>
            <DFFormField label="短语内容" required error={formError ?? undefined} htmlFor="phrase-text">
              <DFTextarea
                id="phrase-text"
                rows={5}
                value={form.text}
                onChange={(e) => setForm((f) => ({ ...f, text: e.target.value }))}
                placeholder="注入到用户消息的指令文本"
              />
            </DFFormField>
            <DFFormField label="快捷标识（可选）" htmlFor="phrase-shortcut">
              <DFInput
                id="phrase-shortcut"
                value={form.shortcut}
                onChange={(e) => setForm((f) => ({ ...f, shortcut: e.target.value }))}
                placeholder="如 /polish"
              />
            </DFFormField>
          </div>
        </DFModal>
      )}

      {/* 删除确认 */}
      {deleting && (
        <DFConfirmDialog
          title="删除预设短语"
          message={`确定删除该短语吗？内容：${deleting.text.slice(0, 50)}${deleting.text.length > 50 ? "..." : ""}`}
          loading={saving}
          onCancel={() => setDeleting(null)}
          onConfirm={() => void handleDelete()}
        />
      )}

      <DFErrorToast message={error} onClose={() => setError(null)} />
    </div>
  );
}
