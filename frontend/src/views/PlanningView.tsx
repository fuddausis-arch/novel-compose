import { useEffect, useState } from "react";
import { Loader2, Play, CheckCircle, XCircle, Globe, Users, AlertCircle, AlertTriangle, Info, Lightbulb, Target, Layers, Sparkles, ChevronDown, ChevronRight } from "lucide-react";
import { api } from "@/api";
import { useAppStore } from "@/store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { PipelinePanel } from "@/components/pipeline-panel";
import { Select } from "@/components/ui/select";
import { useToast } from "@/hooks/useToast";
import type { PlanningResult, PlannedCharacter, PlannedWorldSetting, PlanningIssue, GoldenFinger, GenreTemplate, Protagonist } from "@/types";

const GOLDEN_FINGER_TYPES = ["系统流", "血脉传承", "异能天赋", "神秘宝物", "重生穿越", "签到抽奖", "模拟器", "修炼功法", "其他"];

export function PlanningView({ setLoading: setGlobalLoading }: { setLoading?: (loading: boolean) => void }) {
  const project = useAppStore((s) => s.currentProject);
  const loadProject = useAppStore((s) => s.loadProject);
  const refreshAssets = useAppStore((s) => s.refreshAssets);
  const store = useAppStore();
  const { showSuccess, showError } = useToast();

  const [templates, setTemplates] = useState<GenreTemplate[]>([]);
  const [templateKey, setTemplateKey] = useState("");
  const [targetVolumes, setTargetVolumes] = useState(3);
  const [targetAudience, setTargetAudience] = useState("");
  const [wordCountTarget, setWordCountTarget] = useState(0);
  const [constitution, setConstitution] = useState("");
  const [customPrompt, setCustomPrompt] = useState("");
  const [goldenFinger, setGoldenFinger] = useState<GoldenFinger>({ name: "", type: "系统流", core_ability: "", limitation: "", growth: "", origin: "" });
  const [protagonist, setProtagonist] = useState<Protagonist>({ name: "", identity: "", core_contradiction: "", sensory_memories: "", absolute_taboos: "", motivation: "", initial_state: "" });
  const [conceptPrefill, setConceptPrefill] = useState({ core_hook: "", protagonist_goal: "", taboos: "" });
  const [showGolden, setShowGolden] = useState(false);
  const [showProtagonist, setShowProtagonist] = useState(false);
  const [showConcept, setShowConcept] = useState(false);

  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<PlanningResult | null>(null);
  const [edits, setEdits] = useState("");
  const [reviewLoading, setReviewLoading] = useState(false);
  const [detectedIssues, setDetectedIssues] = useState<PlanningIssue[]>([]);
  const [detectLoading, setDetectLoading] = useState(false);

  // 加载模板列表 + 从项目初始化字段
  useEffect(() => {
    api.listGenreTemplates().then(setTemplates).catch(() => {});
  }, []);

  useEffect(() => {
    if (!project) return;
    setTargetAudience(project.target_audience || "");
    setWordCountTarget(project.word_count_target || 0);
    setConstitution(project.constitution || "");
    setTargetVolumes(project.target_volumes || 3);
    // 解析金手指
    try {
      if (project.golden_finger) {
        const gf = JSON.parse(project.golden_finger);
        setGoldenFinger({ name: gf.name || "", type: gf.type || "系统流", core_ability: gf.core_ability || "", limitation: gf.limitation || "", growth: gf.growth || "", origin: gf.origin || "" });
        if (gf.name || gf.core_ability) setShowGolden(true);
      }
    } catch { /* ignore */ }
    // 解析主角设定
    try {
      if (project.protagonist) {
        const p = JSON.parse(project.protagonist);
        setProtagonist({
          name: p.name || "",
          identity: p.identity || "",
          core_contradiction: p.core_contradiction || "",
          sensory_memories: p.sensory_memories || "",
          absolute_taboos: p.absolute_taboos || "",
          motivation: p.motivation || "",
          initial_state: p.initial_state || "",
        });
        if (p.name) setShowProtagonist(true);
      }
    } catch { /* ignore */ }
    // 解析立意预填
    try {
      if (project.central_concept) {
        const c = JSON.parse(project.central_concept);
        setConceptPrefill({ core_hook: c.core_hook || "", protagonist_goal: c.protagonist_goal || "", taboos: Array.isArray(c.taboos) ? c.taboos.join("、") : (c.taboos || "") });
      }
    } catch { /* ignore */ }
  }, [project?.id]);

  const handleTemplateChange = async (key: string) => {
    setTemplateKey(key);
    if (!key || !project) return;
    try {
      const tpl = templates.find((t) => t.key === key);
      if (!tpl) return;
      // 选中模板后更新项目 genre（用模板 title）和 style（追加模板内容由后端处理 genre，这里只设 genre）
      await api.updateProject(project.id, { genre: tpl.title });
      await loadProject(project.id);
      // 题材变更后刷新 genreContext，AI 生成使用新题材
      store.refreshGenreContext();
      showSuccess(`已切换题材模板：${tpl.title}`);
    } catch (e: any) {
      showError("切换模板失败：" + e.message);
    }
  };

  const persistProjectFields = async () => {
    if (!project) return;
    // 持久化规划页填写的项目级字段
    const gfJson = goldenFinger.name || goldenFinger.core_ability ? JSON.stringify(goldenFinger) : "";
    const protagonistJson = protagonist.name ? JSON.stringify(protagonist) : "";
    const conceptJson = conceptPrefill.core_hook || conceptPrefill.protagonist_goal || conceptPrefill.taboos
      ? JSON.stringify({ core_hook: conceptPrefill.core_hook, protagonist_goal: conceptPrefill.protagonist_goal, taboos: conceptPrefill.taboos ? conceptPrefill.taboos.split(/[、,，\n]/).map((s) => s.trim()).filter(Boolean) : [] })
      : "";
    try {
      await api.updateProject(project.id, {
        target_volumes: targetVolumes,
        target_audience: targetAudience,
        word_count_target: wordCountTarget,
        constitution,
        golden_finger: gfJson,
        protagonist: protagonistJson,
        central_concept: conceptJson,
      });
      await loadProject(project.id);
    } catch (e) {
      showError("项目字段保存失败，规划可能未应用你的约束：" + (e instanceof Error ? e.message : String(e)));
    }
  };

  const handleRun = async () => {
    if (!project) return;
    if (!project.title?.trim() || !project.genre?.trim()) {
      showError("项目标题和类型不能为空，请先在工作台填写项目基本信息");
      return;
    }
    await persistProjectFields();
    setLoading(true);
    setGlobalLoading?.(true);
    setResult(null);
    setEdits("");
    setDetectedIssues([]);
    const tid = crypto.randomUUID();
    store.startPipeline("开始全书规划…", "planning");
    // 金手指/立意/纲领 作为约束传给后端
    const gfStr = goldenFinger.name || goldenFinger.core_ability ? JSON.stringify(goldenFinger) : "";
    const constStr = constitution;
    // chapterCount 仅作兜底，全书规划后端按 target_volumes 决定每卷章数
    const wct = project?.word_count_target || wordCountTarget || 0;
    const tv = targetVolumes || 0;
    const computedChapterCount = wct > 0 && tv > 0
      ? Math.max(10, Math.min(80, Math.round(wct / tv / 3000)))
      : 30;
    // volume 参数为历史参数，全书规划不再使用，保留 "卷一" 以兼容签名
    const protagonistStr = protagonist.name ? JSON.stringify(protagonist) : "";
    const es = api.runPlanningStream(project.id, "卷一", computedChapterCount, tid, customPrompt, targetVolumes, gfStr, constStr, protagonistStr);
    es.addEventListener("node", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      const nodeLabels: Record<string, string> = {
        plan: "总编规划卷次结构与立意…",
        design: "设定师设计世界观/角色/金手指体系…",
        review: "等待人审…",
        apply: "写入圣经（卷大纲+设定+角色）…",
      };
      store.addPipelineEvent(nodeLabels[data.node] || `节点：${data.node}`, data.progress ?? store.pipelineProgress);
    });
    es.addEventListener("error", (e) => {
      const data = JSON.parse((e as MessageEvent).data || "{}");
      store.addPipelineEvent(`错误：${data.error || "规划失败"}`);
      store.setPipelineStatus("error");
      setTimeout(() => store.clearPipeline(), 5000);
      showError("规划失败：" + (data.error || "SSE 错误"));
      setLoading(false);
      setGlobalLoading?.(false);
      es.close();
    });
    es.addEventListener("done", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      store.addPipelineEvent("规划完成", 100);
      store.setPipelineStatus("done");
      setResult(data);
      showSuccess("全书规划已完成，请审核");
      setLoading(false);
      setGlobalLoading?.(false);
      es.close();
    });
    es.onerror = async () => {
      store.addPipelineEvent("连接错误");
      store.setPipelineStatus("error");
      setTimeout(() => store.clearPipeline(), 5000);
      // 主动检测后端状态，给出更准确的提示
      let hint = "规划连接错误";
      try {
        const res = await fetch("/api/projects", { method: "GET" });
        if (!res.ok) {
          hint = `后端返回异常状态：${res.status}，请稍后重试或重启应用`;
        } else {
          hint = "规划端点连接失败，但后端在线。可能是 SSE 流被中断，请稍后重试";
        }
      } catch {
        hint = "后端服务不可达，请稍候 10 秒后重试；若持续失败请重启应用并将日志发回开发方（日志位置：%APPDATA%/NovelCompose/logs/backend.log）";
      }
      showError(hint);
      setLoading(false);
      setGlobalLoading?.(false);
      es.close();
    };
  };

  const runDetect = async (currentResult: PlanningResult) => {
    if (!project) return;
    setDetectLoading(true);
    try {
      const res = await api.detectPlanningIssues(project.id, currentResult);
      setDetectedIssues(res.issues);
    } catch (e: any) {
      showError("导入检测失败：" + e.message);
    } finally {
      setDetectLoading(false);
    }
  };

  useEffect(() => {
    if (result && result.status !== "approved") {
      runDetect(result);
    }
  }, [result]);

  if (!project) {
    return (
      <div className="flex h-full items-center justify-center text-muted">
        请先选择一个项目
      </div>
    );
  }

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
    setDetectedIssues([]);
  };

  const plan = result?.volume_plan;
  const settings = result?.settings;
  const isReviewing = result && result.status !== "approved" && result.status !== "rejected";
  const canImport = result && result.status !== "approved";
  const hasErrors = detectedIssues.some((i) => i.severity === "error");

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

  // 从卷规划中提取立意
  const concept = plan?.central_concept;

  return (
    <div className="h-full space-y-6 overflow-y-auto p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold">全书规划</h1>
          <p className="mt-1 text-sm text-muted">AI 总编规划立意与卷次结构 → 设定师生成世界观/角色/金手指体系 → 人审 → 落库卷大纲与设定（章纲请去「大纲管理」生成）</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {canImport && (
            <Button onClick={handleImport} disabled={reviewLoading || hasErrors}>
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
              启动全书规划
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            {/* 题材模板选择 */}
            <div className="space-y-2">
              <label className="text-sm font-medium">题材模板</label>
              <Select value={templateKey} onChange={(e) => handleTemplateChange(e.target.value)}>
                <option value="">— 不使用模板 / 保持现有题材 —</option>
                {templates.map((t) => (
                  <option key={t.key} value={t.key}>{t.title}{t.description ? `（${t.description}）` : ""}</option>
                ))}
              </Select>
              <p className="text-xs text-muted">选择模板会更新项目题材，后续所有 AI 生成都遵循该题材约束。当前题材：<span className="font-medium">{project.genre || "未设置"}</span></p>
            </div>

            {/* 卷数 / 目标读者 / 目标字数 */}
            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <div className="space-y-2">
                <label className="text-sm font-medium">目标卷数</label>
                <Input type="number" min={1} max={20} value={targetVolumes} onChange={(e) => setTargetVolumes(Number(e.target.value))} />
                <p className="text-xs text-muted">AI 按此卷数拆分全书，每卷章数由 AI 根据卷定位决定</p>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">目标读者（可选）</label>
                <Input placeholder="如 男频18-30" value={targetAudience} onChange={(e) => setTargetAudience(e.target.value)} />
                <p className="text-xs text-muted">影响 AI 语气与尺度</p>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">目标字数（可选）</label>
                <Input type="number" min={0} step={10000} placeholder="如 2000000" value={wordCountTarget} onChange={(e) => setWordCountTarget(Number(e.target.value))} />
                <p className="text-xs text-muted">AI 据此校准卷数密度</p>
              </div>
            </div>

            {/* 金手指设定（折叠） */}
            <div className="rounded-lg border border-border">
              <button type="button" onClick={() => setShowGolden((v) => !v)} className="flex w-full items-center justify-between px-4 py-3 text-left">
                <span className="flex items-center gap-2 text-sm font-medium">
                  <Sparkles className="h-4 w-4 text-warning" />
                  金手指设定（可选）
                </span>
                {showGolden ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
              </button>
              {showGolden && (
                <div className="space-y-3 border-t border-border p-4">
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <div className="space-y-1">
                      <label className="text-xs text-muted">金手指名称</label>
                      <Input placeholder="如 签到系统" value={goldenFinger.name} onChange={(e) => setGoldenFinger({ ...goldenFinger, name: e.target.value })} />
                    </div>
                    <div className="space-y-1">
                      <label className="text-xs text-muted">类型</label>
                      <Select value={goldenFinger.type} onChange={(e) => setGoldenFinger({ ...goldenFinger, type: e.target.value })}>
                        {GOLDEN_FINGER_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                      </Select>
                    </div>
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted">核心能力（能做什么）</label>
                    <Textarea placeholder="如 每天签到获得随机奖励，连续签到有额外大奖，签到点可兑换技能" rows={2} value={goldenFinger.core_ability} onChange={(e) => setGoldenFinger({ ...goldenFinger, core_ability: e.target.value })} />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted">限制 / 代价</label>
                    <Textarea placeholder="如 签到不可中断，中断重置；高阶奖励需消耗寿命" rows={2} value={goldenFinger.limitation} onChange={(e) => setGoldenFinger({ ...goldenFinger, limitation: e.target.value })} />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted">成长路径（如何升级）</label>
                    <Textarea placeholder="如 系统从青铜→白银→黄金→钻石，每级解锁新功能" rows={2} value={goldenFinger.growth} onChange={(e) => setGoldenFinger({ ...goldenFinger, growth: e.target.value })} />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted">获得来源</label>
                    <Textarea placeholder="如 主角穿越时被异世界法则绑定" rows={2} value={goldenFinger.origin} onChange={(e) => setGoldenFinger({ ...goldenFinger, origin: e.target.value })} />
                  </div>
                  <p className="text-xs text-muted">填写后，AI 会把金手指作为全书核心爽点引擎，卷次结构与力量体系围绕它展开。</p>
                </div>
              )}
            </div>

            {/* 主角设定（折叠） */}
            <div className="rounded-lg border border-border">
              <button type="button" onClick={() => setShowProtagonist((v) => !v)} className="flex w-full items-center justify-between px-4 py-3 text-left">
                <span className="flex items-center gap-2 text-sm font-medium">
                  <Users className="h-4 w-4 text-primary" />
                  主角设定（可选）
                </span>
                {showProtagonist ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
              </button>
              {showProtagonist && (
                <div className="space-y-3 border-t border-border p-4">
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <div className="space-y-1">
                      <label className="text-xs text-muted">主角姓名</label>
                      <Input placeholder="如 陆恒" value={protagonist.name} onChange={(e) => setProtagonist({ ...protagonist, name: e.target.value })} />
                    </div>
                    <div className="space-y-1">
                      <label className="text-xs text-muted">身份 / 背景</label>
                      <Input placeholder="如 没落家族私生子，前世是顶级杀手" value={protagonist.identity} onChange={(e) => setProtagonist({ ...protagonist, identity: e.target.value })} />
                    </div>
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted">承重矛盾（他是___的人，但同时___）</label>
                    <Textarea placeholder="如：他是个杀人不眨眼的杀手，但每次杀人后会给目标家属匿名汇一笔钱" rows={2} value={protagonist.core_contradiction} onChange={(e) => setProtagonist({ ...protagonist, core_contradiction: e.target.value })} />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted">感官瞬间（3-4个带感官细节的第一人称记忆片段，用分号分隔）</label>
                    <Textarea placeholder="如：柴油味至今让我饿——爸爸的船烧这个；12岁葬礼那天我记得自己烦神父把我们姓念错了" rows={2} value={protagonist.sensory_memories} onChange={(e) => setProtagonist({ ...protagonist, sensory_memories: e.target.value })} />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted">绝对禁令（2-3条这个角色绝对不会做的事）</label>
                    <Textarea placeholder="如：绝不会在别人面前哭；绝不会先说对不起；绝不会拒绝食物——小时候饿怕了" rows={2} value={protagonist.absolute_taboos} onChange={(e) => setProtagonist({ ...protagonist, absolute_taboos: e.target.value })} />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted">核心驱动力</label>
                    <Textarea placeholder="如：查清家族灭门真相，向当年袖手旁观的势力逐一讨还" rows={2} value={protagonist.motivation} onChange={(e) => setProtagonist({ ...protagonist, motivation: e.target.value })} />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted">开局状态</label>
                    <Textarea placeholder="如：被逐出家族，身无分文，只剩母亲留下的一枚生锈戒指" rows={2} value={protagonist.initial_state} onChange={(e) => setProtagonist({ ...protagonist, initial_state: e.target.value })} />
                  </div>
                  <p className="text-xs text-muted">填写后，AI 会把该角色作为全书主角进行卷次结构、角色关系与世界观设计。</p>
                </div>
              )}
            </div>

            {/* 立意预填（折叠） */}
            <div className="rounded-lg border border-border">
              <button type="button" onClick={() => setShowConcept((v) => !v)} className="flex w-full items-center justify-between px-4 py-3 text-left">
                <span className="flex items-center gap-2 text-sm font-medium">
                  <Lightbulb className="h-4 w-4 text-warning" />
                  立意预填（可选）
                </span>
                {showConcept ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
              </button>
              {showConcept && (
                <div className="space-y-3 border-t border-border p-4">
                  <div className="space-y-1">
                    <label className="text-xs text-muted">核心爽点</label>
                    <Input placeholder="如 签到变强+打脸逆袭" value={conceptPrefill.core_hook} onChange={(e) => setConceptPrefill({ ...conceptPrefill, core_hook: e.target.value })} />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted">主角长期目标</label>
                    <Input placeholder="如 查清家族灭门真相并登顶至尊" value={conceptPrefill.protagonist_goal} onChange={(e) => setConceptPrefill({ ...conceptPrefill, protagonist_goal: e.target.value })} />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted">立意禁忌（顿号/逗号分隔）</label>
                    <Input placeholder="如 不写后宫、主角不能死、不虐主" value={conceptPrefill.taboos} onChange={(e) => setConceptPrefill({ ...conceptPrefill, taboos: e.target.value })} />
                  </div>
                  <p className="text-xs text-muted">留空则由 AI 自主生成立意；预填后 AI 会遵循你的立意框架。</p>
                </div>
              )}
            </div>

            {/* 设定纲领 */}
            <div className="space-y-2">
              <label className="text-sm font-medium">设定纲领 / 硬约束（可选）</label>
              <Textarea
                placeholder={"全书不得违反的铁律，如：\n- 主角不能死\n- 单女主\n- 不写后宫\n- 力量体系不可崩\n- 逻辑必须自洽"}
                value={constitution}
                onChange={(e) => setConstitution(e.target.value)}
                rows={3}
              />
              <p className="text-xs text-muted">作为所有 AI 生成（规划/设定/章节）的硬性约束</p>
            </div>

            {/* 规划要求 */}
            <div className="space-y-2">
              <label className="text-sm font-medium">规划要求（可选）</label>
              <Textarea
                placeholder={
                  "补充对全书的核心要求，如：\n" +
                  "- 核心冲突：家族灭门→复仇→发现更大阴谋\n" +
                  "- 卷次要求：第一卷校园觉醒，第二卷都市争霸\n" +
                  "- 主角性格：腹黑、记仇、重情义"
                }
                value={customPrompt}
                onChange={(e) => setCustomPrompt(e.target.value)}
                rows={4}
              />
              <p className="text-xs text-muted">金手指/立意/纲领已单独填写；此处填其他补充要求</p>
            </div>

            {project && (
              <div className="rounded-lg border border-border bg-surface/50 p-3 text-sm">
                <span className="text-muted">当前项目：</span>
                <span className="font-medium">{project.title}</span>
                <span className="ml-2 text-muted">| {project.genre}</span>
                {project.summary && (
                  <p className="mt-1 text-xs text-muted">{project.summary}</p>
                )}
              </div>
            )}

            <Button onClick={handleRun} disabled={loading} className="w-full md:w-auto">
              {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
              开始全书规划
            </Button>
          </CardContent>
        </Card>
      )}

      {loading && (
        <div className="space-y-4">
          <PipelinePanel
            events={store.pipelineEvents}
            status={store.pipelineStatus}
            progress={store.pipelineProgress}
          />
          <div className="flex items-center justify-center gap-2 py-2 text-muted">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span className="text-sm">AI 正在进行全书规划（总编→设定师），请稍候…</span>
          </div>
        </div>
      )}

      {result && !loading && (
        <div className="space-y-6">
          <div className="flex items-center gap-3">
            <Badge className={result.status === "approved" ? "bg-success text-primary-foreground" : result.status === "rejected" ? "bg-danger text-primary-foreground" : "bg-secondary text-secondary-foreground"}>
              {result.status === "approved" ? "已写入" : result.status === "rejected" ? "已拒绝" : "待审核"}
            </Badge>
          </div>

          {result.status !== "approved" && (
            <Card className={hasErrors ? "border-danger" : detectedIssues.length > 0 ? "border-warning" : "border-success"}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-sm">
                  {detectLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : hasErrors ? (
                    <AlertCircle className="h-4 w-4 text-danger" />
                  ) : detectedIssues.length > 0 ? (
                    <AlertTriangle className="h-4 w-4 text-warning" />
                  ) : (
                    <Info className="h-4 w-4 text-success" />
                  )}
                  导入检测
                </CardTitle>
              </CardHeader>
              <CardContent>
                {detectLoading ? (
                  <p className="text-sm text-muted">正在检测潜在冲突…</p>
                ) : detectedIssues.length === 0 ? (
                  <p className="text-sm text-success">未检测到冲突或错误</p>
                ) : (
                  <ul className="space-y-1">
                    {detectedIssues.map((issue, idx) => (
                      <li
                        key={idx}
                        className={`text-sm flex items-start gap-2 ${
                          issue.severity === "error" ? "text-danger" : issue.severity === "warning" ? "text-warning" : "text-muted"
                        }`}
                      >
                        {issue.severity === "error" ? (
                          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                        ) : issue.severity === "warning" ? (
                          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                        ) : (
                          <Info className="h-4 w-4 shrink-0 mt-0.5" />
                        )}
                        {issue.message}
                      </li>
                    ))}
                  </ul>
                )}
                {hasErrors && <p className="mt-2 text-xs text-danger">存在错误，请先修正或重新规划后再导入。</p>}
              </CardContent>
            </Card>
          )}

          {/* 全书立意 */}
          {concept && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Lightbulb className="h-5 w-5 text-warning" />
                  全书立意
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                  <div className="rounded-lg border border-border bg-surface/50 p-3">
                    <div className="text-xs text-muted">核心爽点</div>
                    <div className="mt-1 text-sm font-medium">{concept.core_hook || "—"}</div>
                  </div>
                  <div className="rounded-lg border border-border bg-surface/50 p-3">
                    <div className="text-xs text-muted">主角长期目标</div>
                    <div className="mt-1 text-sm font-medium">{concept.protagonist_goal || "—"}</div>
                  </div>
                  <div className="rounded-lg border border-border bg-surface/50 p-3">
                    <div className="text-xs text-muted">立意禁忌</div>
                    <div className="mt-1 text-sm font-medium">
                      {concept.taboos?.length ? concept.taboos.join("、") : "—"}
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* 主角设定 */}
          {(protagonist.name || settings?.characters?.some((c: any) => (c.role || c.importance) === "主角")) && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Users className="h-5 w-5 text-primary" />
                  主角设定
                </CardTitle>
              </CardHeader>
              <CardContent>
                {protagonist.name ? (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <span className="text-lg font-semibold">{protagonist.name}</span>
                      {protagonist.identity && <Badge variant="default">{protagonist.identity}</Badge>}
                    </div>
                    {protagonist.core_contradiction && <p className="text-sm text-muted"><span className="font-medium">承重矛盾：</span>{protagonist.core_contradiction}</p>}
                    {protagonist.sensory_memories && <p className="text-sm text-muted"><span className="font-medium">感官瞬间：</span>{protagonist.sensory_memories}</p>}
                    {protagonist.absolute_taboos && <p className="text-sm text-muted"><span className="font-medium">绝对禁令：</span>{protagonist.absolute_taboos}</p>}
                    {protagonist.motivation && <p className="text-sm text-muted"><span className="font-medium">核心驱动力：</span>{protagonist.motivation}</p>}
                    {protagonist.initial_state && <p className="text-sm text-muted"><span className="font-medium">开局状态：</span>{protagonist.initial_state}</p>}
                  </div>
                ) : (
                  <p className="text-sm text-muted">AI 生成的角色列表中暂无明确标注为「主角」的角色。</p>
                )}
              </CardContent>
            </Card>
          )}

          {/* 卷次结构 */}
          {plan?.volumes && plan.volumes.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Layers className="h-5 w-5" />
                  卷次结构（{plan.volumes.length} 卷）
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {plan.volumes.map((v, i) => (
                    <div key={i} className="rounded-lg border border-border bg-surface/50 p-3">
                      <div className="flex items-center justify-between">
                        <div className="flex min-w-0 items-center gap-2">
                          <Badge className="shrink-0">{v.name}</Badge>
                          <span className="min-w-0 truncate text-sm font-medium">{v.theme || ""}</span>
                        </div>
                        <span className="shrink-0 text-sm text-muted">{v.chapters} 章</span>
                      </div>
                      {v.summary && <p className="mt-2 text-sm text-muted">{v.summary}</p>}
                      <div className="mt-2 flex flex-wrap gap-3 text-xs text-muted">
                        {v.climax && <span>高潮：{v.climax}</span>}
                        {v.end_hook && <span>钩子：{v.end_hook}</span>}
                      </div>
                    </div>
                  ))}
                </div>
                <p className="mt-3 text-xs text-muted">提示：通过审核后，卷大纲会写入「大纲管理」的卷大纲列表；章纲请到「大纲管理」按卷生成。</p>
              </CardContent>
            </Card>
          )}

          {/* 世界设定 */}
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

          {/* 角色设计 */}
          {settings && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Users className="h-5 w-5" />
                  角色设计
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
                <CardTitle className="flex items-center gap-2">
                  <Target className="h-5 w-5" />
                  人审确认
                </CardTitle>
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
                <div className="flex flex-col gap-3 sm:flex-row">
                  <Button
                    variant="default"
                    onClick={() => handleReview(true)}
                    disabled={reviewLoading || hasErrors}
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
      {(character as any).core_contradiction && (
        <p className="mt-1 text-xs text-muted">承重矛盾：{(character as any).core_contradiction}</p>
      )}
    </div>
  );
}

function WorldSettingCard({ setting }: { setting: PlannedWorldSetting }) {
  return (
    <div className="rounded-xl border border-border p-4">
      <div className="mb-1 flex items-center gap-2">
        <Badge className="shrink-0 border-border-strong bg-transparent text-foreground">{setting.category}</Badge>
        <span className="min-w-0 truncate font-semibold">{setting.title}</span>
      </div>
      <p className="text-sm text-muted whitespace-pre-wrap">{setting.content}</p>
    </div>
  );
}
