import { useState } from "react";
import { Loader2, Play, CheckCircle, XCircle, FileText, Users, Globe, BookOpen, AlertCircle } from "lucide-react";
import { api } from "@/api";
import { useAppStore } from "@/store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/hooks/useToast";
import type { PlanningResult, PlannedChapter, PlannedCharacter, PlannedWorldSetting } from "@/types";

export function PlanningView({ setLoading: setGlobalLoading }: { setLoading?: (loading: boolean) => void }) {
  const project = useAppStore((s) => s.currentProject);
  const refreshAssets = useAppStore((s) => s.refreshAssets);
  const { showSuccess, showError } = useToast();

  const [volume, setVolume] = useState("卷一");
  const [chapterCount, setChapterCount] = useState(30);
  const [threadId, setThreadId] = useState<string>(() => crypto.randomUUID());
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<PlanningResult | null>(null);
  const [edits, setEdits] = useState("");
  const [reviewLoading, setReviewLoading] = useState(false);

  if (!project) {
    return (
      <div className="flex h-full items-center justify-center text-muted">
        请先选择一个项目
      </div>
    );
  }

  const handleRun = async () => {
    setLoading(true);
    setGlobalLoading?.(true);
    setResult(null);
    setEdits("");
    try {
      const tid = threadId || crypto.randomUUID();
      setThreadId(tid);
      const res = await api.runPlanning(project.id, volume, chapterCount, tid);
      setResult(res);
      showSuccess("卷级规划已完成，请审核");
    } catch (e: any) {
      showError("规划失败：" + e.message);
    } finally {
      setLoading(false);
      setGlobalLoading?.(false);
    }
  };

  const handleReview = async (approved: boolean) => {
    if (!result?.thread_id) return;
    setReviewLoading(true);
    setGlobalLoading?.(true);
    try {
      const res = await api.resumePlanning(project.id, result.thread_id, approved, edits);
      setResult(res);
      if (approved) {
        await refreshAssets();
        showSuccess("规划已写入圣经");
      } else {
        showSuccess("已拒绝，可修改后重新启动规划");
      }
    } catch (e: any) {
      showError("审核提交失败：" + e.message);
    } finally {
      setReviewLoading(false);
      setGlobalLoading?.(false);
    }
  };

  const handleReset = () => {
    setResult(null);
    setEdits("");
    setThreadId(crypto.randomUUID());
  };

  const plan = result?.volume_plan;
  const settings = result?.settings;
  const outline = result?.outline;
  const isReviewing = result && result.status !== "approved" && result.status !== "rejected";

  const canImport = result && result.status !== "approved";

  const handleImport = async () => {
    if (!result?.thread_id) return;
    setReviewLoading(true);
    setGlobalLoading?.(true);
    try {
      const res = await api.resumePlanning(project.id, result.thread_id, true, "");
      setResult(res);
      await refreshAssets();
      showSuccess("规划已一键导入圣经");
    } catch (e: any) {
      showError("导入失败：" + e.message);
    } finally {
      setReviewLoading(false);
      setGlobalLoading?.(false);
    }
  };

  return (
    <div className="h-full space-y-6 overflow-y-auto p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">卷级规划</h1>
        <div className="flex items-center gap-2">
          {canImport && (
            <Button onClick={handleImport} disabled={reviewLoading}>
              {reviewLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <CheckCircle className="mr-2 h-4 w-4" />}
              一键采纳并导入
            </Button>
          )}
          {result && (
            <Button variant="outline" onClick={handleReset}>
              重新规划
            </Button>
          )}
        </div>
      </div>

      {!result && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Play className="h-5 w-5" />
              启动规划
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <div className="space-y-2">
                <label className="text-sm font-medium">卷名</label>
                <Input value={volume} onChange={(e) => setVolume(e.target.value)} />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">章节数</label>
                <Input
                  type="number"
                  min={1}
                  max={200}
                  value={chapterCount}
                  onChange={(e) => setChapterCount(Number(e.target.value))}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">Thread ID</label>
                <Input value={threadId} onChange={(e) => setThreadId(e.target.value)} readOnly />
              </div>
            </div>
            <Button onClick={handleRun} disabled={loading} className="w-full md:w-auto">
              {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
              开始规划
            </Button>
          </CardContent>
        </Card>
      )}

      {loading && (
        <div className="flex items-center justify-center gap-2 py-12 text-muted">
          <Loader2 className="h-5 w-5 animate-spin" />
          AI 正在生成卷级规划，请稍候…
        </div>
      )}

      {result && !loading && (
        <div className="space-y-6">
          <div className="flex items-center gap-3">
            <Badge className={result.status === "approved" ? "bg-success text-primary-foreground" : result.status === "rejected" ? "bg-danger text-primary-foreground" : "bg-secondary text-secondary-foreground"}>
              {result.status === "approved" ? "已写入" : result.status === "rejected" ? "已拒绝" : "待审核"}
            </Badge>
            <span className="text-sm text-muted">Thread: {result.thread_id}</span>
          </div>

          {plan?.volumes && plan.volumes.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <BookOpen className="h-5 w-5" />
                  卷级计划
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="list-disc space-y-1 pl-5">
                  {plan.volumes.map((v, i) => (
                    <li key={i}>
                      {v.name} · {v.chapters} 章
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          {settings && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Users className="h-5 w-5" />
                  角色设定
                </CardTitle>
              </CardHeader>
              <CardContent>
                {settings.characters?.length ? (
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    {settings.characters.map((c, i) => (
                      <CharacterCard key={i} character={c} />
                    ))}
                  </div>
                ) : (
                  <p className="text-muted">无新增角色</p>
                )}
              </CardContent>
            </Card>
          )}

          {settings?.world_settings && settings.world_settings.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Globe className="h-5 w-5" />
                  世界设定
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {settings.world_settings.map((ws, i) => (
                  <WorldSettingCard key={i} setting={ws} />
                ))}
              </CardContent>
            </Card>
          )}

          {outline?.chapters && outline.chapters.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <FileText className="h-5 w-5" />
                  章节大纲
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {outline.chapters.map((ch) => (
                  <ChapterItem key={ch.chapter} chapter={ch} />
                ))}
              </CardContent>
            </Card>
          )}

          {result.errors && result.errors.length > 0 && (
            <Card className="border-destructive">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-destructive">
                  <AlertCircle className="h-5 w-5" />
                  写入异常
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="list-disc space-y-1 pl-5 text-sm text-destructive">
                  {result.errors.map((err, i) => (
                    <li key={i}>{err}</li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          {isReviewing && (
            <Card>
              <CardHeader>
                <CardTitle>人审①</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium">修改意见（可选）</label>
                  <Textarea
                    placeholder="如需调整，请在此填写具体修改意见；通过则留空。"
                    value={edits}
                    onChange={(e) => setEdits(e.target.value)}
                    rows={4}
                  />
                </div>
                <div className="flex gap-3">
                  <Button
                    variant="default"
                    onClick={() => handleReview(true)}
                    disabled={reviewLoading}
                    className="flex-1"
                  >
                    {reviewLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <CheckCircle className="mr-2 h-4 w-4" />}
                    通过并写入圣经
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => handleReview(false)}
                    disabled={reviewLoading}
                    className="flex-1"
                  >
                    <XCircle className="mr-2 h-4 w-4" />
                    拒绝
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}

function CharacterCard({ character }: { character: PlannedCharacter }) {
  return (
    <div className="rounded-xl border border-border p-4">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-semibold">{character.name}</span>
        <Badge className="border-border-strong bg-transparent text-foreground">{character.role}</Badge>
      </div>
      <p className="text-sm text-muted">{character.personality}</p>
      {character.motivation && (
        <p className="mt-2 text-sm text-muted">动机：{character.motivation}</p>
      )}
    </div>
  );
}

function WorldSettingCard({ setting }: { setting: PlannedWorldSetting }) {
  return (
    <div className="rounded-xl border border-border p-4">
      <div className="mb-1 flex items-center gap-2">
        <Badge className="border-border-strong bg-transparent text-foreground">{setting.category}</Badge>
        <span className="font-semibold">{setting.title}</span>
      </div>
      <p className="text-sm text-muted">{setting.content}</p>
    </div>
  );
}

function ChapterItem({ chapter }: { chapter: PlannedChapter }) {
  return (
    <div className="rounded-xl border border-border p-4">
      <div className="mb-2 flex items-center gap-2">
        <Badge>第 {chapter.chapter} 章</Badge>
        <span className="font-semibold">{chapter.title}</span>
      </div>
      <p className="text-sm text-muted">{chapter.summary}</p>
      {chapter.foreshadows && chapter.foreshadows.length > 0 && (
        <div className="mt-3 space-y-1">
          {chapter.foreshadows.map((f) => (
            <div key={f.id} className="text-xs text-muted">
              伏笔 [{f.id}]：{f.description}（{f.plant_chapter}→{f.resolve_chapter}）
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
