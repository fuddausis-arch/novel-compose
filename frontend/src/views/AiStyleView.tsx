// AI 味检测窗口：选章节 → 检测 → 报告 → 润色（规则/LLM 流式）→ 复检对比 → 应用到章节。
// 数据走 /api/audit/ai-style/*，达标线 AI 率 ≤30%（后端 ai_pass_ai_rate 可配置，前端读 report.pass_line）。

import { useCallback, useEffect, useRef, useState } from "react";
import {
  CheckCircle2,
  Copy,
  Download,
  Loader2,
  Save,
  ScanSearch,
  ShieldOff,
  Square,
  Wand2,
  X,
  XCircle,
} from "lucide-react";
import { api } from "@/api";
import type { AiModelStatus, AiStyleReport, AiStyleRepairResult, ChapterListItem, DeepAiStyleReport } from "@/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Select } from "@/components/ui/select";
import { useCurrentProject } from "@/hooks/useCurrentProject";
import { useToast } from "@/hooks/useToast";
import { bumpDataVersion } from "@/store/slices/dataVersion";
import { cn } from "@/lib/utils";

// 统计信号 → 中文标签
const DIMENSION_LABELS: Record<string, string> = {
  burstiness: "句长突发性",
  adj_density: "形容词密度",
  dash_density: "破折号密度",
  connector_density: "连接词密度",
  para_cv: "段落均匀度",
  repetition: "重复词",
  dialog_ratio: "对话占比",
};
const DIMENSION_ORDER = [
  "burstiness",
  "adj_density",
  "dash_density",
  "connector_density",
  "para_cv",
  "repetition",
  "dialog_ratio",
];

interface HitGroup {
  key: string;
  label: string;
  items: any[];
  color: string;
}

export default function AiStyleView() {
  const { projectId } = useCurrentProject();
  const { showSuccess, showError } = useToast();

  const [chapters, setChapters] = useState<ChapterListItem[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [chapterText, setChapterText] = useState<string>("");
  const [chapterTitle, setChapterTitle] = useState<string>("");

  const [report, setReport] = useState<AiStyleReport | null>(null);
  const [checking, setChecking] = useState(false);

  // 深度检测（roberta 中文模型，最准但慢）
  const [deepReport, setDeepReport] = useState<DeepAiStyleReport | null>(null);
  const [deepChecking, setDeepChecking] = useState(false);

  // 深度检测模型：状态 + 一键下载（选装）
  const [modelStatus, setModelStatus] = useState<AiModelStatus | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [downloadProg, setDownloadProg] = useState({ file: "", index: 0, total: 0 });
  const downloadAbortRef = useRef<AbortController | null>(null);

  const refreshModelStatus = useCallback(() => {
    api
      .getAiModelStatus()
      .then(setModelStatus)
      .catch(() => setModelStatus(null));
  }, []);

  useEffect(() => {
    refreshModelStatus();
  }, [refreshModelStatus]);

  const handleDownloadModel = useCallback(() => {
    setDownloading(true);
    setDownloadProg({ file: "", index: 0, total: 0 });
    downloadAbortRef.current = api.downloadAiModelStream(
      (file, index, total) => setDownloadProg({ file, index, total }),
      (ok) => {
        setDownloading(false);
        downloadAbortRef.current = null;
        if (ok) {
          showSuccess("深度检测模型下载完成");
          refreshModelStatus();
        } else {
          showError("模型下载完成但校验未通过，请重试");
        }
      },
      (msg) => {
        setDownloading(false);
        downloadAbortRef.current = null;
        showError(msg);
      },
    );
  }, [showSuccess, showError, refreshModelStatus]);

  const handleStopDownload = useCallback(() => {
    downloadAbortRef.current?.abort();
    downloadAbortRef.current = null;
    setDownloading(false);
    showError("已中断下载");
  }, [showError]);

  // 误判白名单：用户标记为误判的词（角色名/设定词等），检测报告里不再显示
  const [ignoreWords, setIgnoreWords] = useState<Set<string>>(new Set());

  // 加载误判白名单
  useEffect(() => {
    if (!projectId) return;
    api
      .listAiIgnoreWords(projectId)
      .then((data) => setIgnoreWords(new Set(Object.keys(data.words || {}))))
      .catch(() => setIgnoreWords(new Set()));
  }, [projectId]);

  // 标记某个命中词为误判（加入项目白名单）
  const handleMarkFalsePositive = useCallback(
    async (word: string) => {
      if (!projectId) return;
      try {
        await api.addAiIgnoreWord(projectId, word);
        setIgnoreWords((prev) => new Set(prev).add(word));
        showSuccess(`已把「${word}」标记为误判，之后的检测不再报告`);
      } catch (e: any) {
        showError("标记失败：" + (e?.message || "未知错误"));
      }
    },
    [projectId, showSuccess, showError],
  );

  // 撤销误判标记
  const handleUnignore = useCallback(
    async (word: string) => {
      if (!projectId) return;
      try {
        await api.removeAiIgnoreWord(projectId, word);
        setIgnoreWords((prev) => {
          const next = new Set(prev);
          next.delete(word);
          return next;
        });
        showSuccess(`已撤销「${word}」的误判标记`);
      } catch (e: any) {
        showError("撤销失败：" + (e?.message || "未知错误"));
      }
    },
    [projectId, showSuccess, showError],
  );

  const [repairing, setRepairing] = useState(false);
  const [repairMethod, setRepairMethod] = useState<"rule" | "llm" | null>(null);
  const [streamText, setStreamText] = useState("");
  const [streamRound, setStreamRound] = useState(0);
  const [repairResult, setRepairResult] = useState<AiStyleRepairResult | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const [applying, setApplying] = useState(false);
  const [previewTab, setPreviewTab] = useState<"original" | "repaired">("repaired");

  // 加载章节列表
  useEffect(() => {
    if (!projectId) return;
    api
      .listChapters(projectId)
      .then((list) => setChapters(list))
      .catch(() => setChapters([]));
  }, [projectId]);

  const selectedChapter = Number(selected) || 0;

  // 检测：读正文 → 本地检测
  const handleCheck = useCallback(async () => {
    if (!projectId || !selectedChapter) {
      showError("请先选择章节");
      return;
    }
    setChecking(true);
    setReport(null);
    setRepairResult(null);
    setStreamText("");
    try {
      const t = await api.getChapterText(projectId, selectedChapter);
      const text = (t.text || "").trim();
      if (!text) {
        showError("该章节暂无正文");
        setChecking(false);
        return;
      }
      setChapterText(text);
      const ch = chapters.find((c) => c.chapter === selectedChapter);
      setChapterTitle(ch?.title || `第${selectedChapter}章`);
      const r = await api.checkAiStyle(text, projectId);
      setReport(r);
    } catch (e: any) {
      showError("检测失败：" + (e?.message || "未知错误"));
    } finally {
      setChecking(false);
    }
  }, [projectId, selectedChapter, chapters, showError]);

  // 深度检测：roberta 中文模型（最准，CPU 推理较慢，几十秒内返回）
  const handleCheckDeep = useCallback(async () => {
    if (!chapterText) return;
    setDeepChecking(true);
    setDeepReport(null);
    try {
      const r = await api.checkAiStyleDeep(chapterText);
      setDeepReport(r);
      if (!r.available) showError("深度检测模型未就绪：" + (r.error || ""));
    } catch (e: any) {
      showError("深度检测失败：" + (e?.message || "未知错误"));
    } finally {
      setDeepChecking(false);
    }
  }, [chapterText, showError]);

  // 规则级润色（零成本）
  const handleRepairRule = useCallback(async () => {
    if (!chapterText) return;
    setRepairing(true);
    setRepairMethod("rule");
    setRepairResult(null);
    setStreamText("");
    try {
      const r = await api.repairAiStyleRule(chapterText);
      setRepairResult(r);
      setStreamText(r.repaired_text);
    } catch (e: any) {
      showError("规则润色失败：" + (e?.message || "未知错误"));
    } finally {
      setRepairing(false);
      setRepairMethod(null);
    }
  }, [chapterText, showError]);

  // LLM 深度润色（SSE 流式，可中断）
  const handleRepairLlm = useCallback(async () => {
    if (!chapterText) return;
    setRepairing(true);
    setRepairMethod("llm");
    setRepairResult(null);
    setStreamText("");
    setStreamRound(0);
    abortRef.current = api.repairAiStyleStream(
      chapterText,
      (delta) => setStreamText((prev) => prev + delta),
      (round) => setStreamRound(round),
      () => {},
      (result) => {
        setRepairResult(result);
        setStreamText(result.repaired_text);
        setRepairing(false);
        setRepairMethod(null);
        if (result.passed) {
          showSuccess(`润色完成，AI 率 ${result.after.ai_rate}%，已达标`);
        } else {
          showError(`润色完成，AI 率 ${result.after.ai_rate}%（未达达标线，建议人工润色）`);
        }
      },
      (msg) => {
        setRepairing(false);
        setRepairMethod(null);
        showError(msg);
      },
    );
  }, [chapterText, showSuccess, showError]);

  const handleStopLlm = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setRepairing(false);
    setRepairMethod(null);
    showError("已中断润色，当前输出保留");
  }, [showError]);

  // 应用到章节
  const handleApply = useCallback(async () => {
    if (!projectId || !selectedChapter || !repairResult?.repaired_text) return;
    setApplying(true);
    try {
      await api.saveChapterText(
        projectId,
        selectedChapter,
        chapterTitle || `第${selectedChapter}章`,
        repairResult.repaired_text,
      );
      bumpDataVersion("chapters");
      bumpDataVersion("bible");
      showSuccess("已保存到章节");
    } catch (e: any) {
      showError("保存失败：" + (e?.message || "未知错误"));
    } finally {
      setApplying(false);
    }
  }, [projectId, selectedChapter, repairResult, chapterTitle, showSuccess, showError]);

  const handleCopy = useCallback(async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      showSuccess("已复制");
    } catch {
      showError("复制失败");
    }
  }, [showSuccess, showError]);

  const scoreColor = (score: number) => {
    if (score >= 80) return "text-success";
    if (score >= 60) return "text-warning";
    return "text-danger";
  };

  const hitGroups: HitGroup[] = report
    ? [
        {
          key: "word",
          label: "词级",
          // 用户标记为误判的词从报告里剔除
          items: report.word_hits.filter((h) => !h.pattern || !ignoreWords.has(h.pattern)),
          color: "bg-danger",
        },
        { key: "sentence", label: "句级", items: report.sentence_hits, color: "bg-warning" },
        { key: "paragraph", label: "段级", items: report.paragraph_hits, color: "bg-primary" },
        { key: "stat", label: "统计", items: report.stat_hits, color: "bg-muted" },
      ].filter((g) => g.items.length > 0)
    : [];

  // 已标记为误判的词（可撤销）
  const ignoredList = Array.from(ignoreWords);

  return (
    <div className="mx-auto w-full max-w-6xl p-4 md:p-6">
      {/* 标题 + 章节选择 */}
      <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-lg font-semibold text-foreground">AI 味检测</h1>
          <p className="text-sm text-muted">检测 AI 率 → 按报告润色 → 复检对比（接近达标线时建议人工判断）</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={selected} onChange={(e) => setSelected(e.target.value)} className="w-56">
            <option value="">选择章节...</option>
            {chapters.map((c) => (
              <option key={c.chapter} value={c.chapter}>
                第{c.chapter}章 {c.title || ""}
              </option>
            ))}
          </Select>
          <Button variant="primary" onClick={handleCheck} disabled={checking || !selectedChapter}>
            {checking ? <Loader2 className="h-4 w-4 animate-spin" /> : <ScanSearch className="h-4 w-4" />}
            {checking ? "检测中..." : "检测"}
          </Button>
          <Button
            variant="outline"
            onClick={handleCheckDeep}
            disabled={deepChecking || !chapterText}
            title="深度检测：roberta 中文模型判别 AI 概率（最准，CPU 推理较慢）"
          >
            {deepChecking ? <Loader2 className="h-4 w-4 animate-spin" /> : <ScanSearch className="h-4 w-4" />}
            {deepChecking ? "深度检测中..." : "深度检测"}
          </Button>
        </div>
      </div>

      {/* 深度检测模型：选装下载 */}
      {modelStatus && !modelStatus.ready && (
        <Card className="mb-4 border-warning/30">
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle>深度检测模型未安装</CardTitle>
            <Badge variant="warning">选装 · 约 390MB</Badge>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-xs text-muted">
              深度检测使用开源「AI 文本检测模型」（ModelScope 国内源），检测更准、能定位可疑段落。
              下载一次即可永久使用；不下载也能用基础检测（规则 + 统计）。
            </p>
            {downloading ? (
              <div className="space-y-2">
                <div className="flex justify-between text-xs">
                  <span className="text-muted">正在下载 {downloadProg.file || "..."}</span>
                  {downloadProg.total > 0 && (
                    <span className="tabular-nums">
                      {downloadProg.index}/{downloadProg.total}
                    </span>
                  )}
                </div>
                <Progress value={downloadProg.total > 0 ? (downloadProg.index / downloadProg.total) * 100 : 10} />
                <div className="flex items-center justify-between">
                  <p className="text-xs text-muted">文件较大，请耐心等待</p>
                  <Button variant="danger" size="sm" onClick={handleStopDownload}>
                    <Square className="h-3.5 w-3.5" /> 中断
                  </Button>
                </div>
              </div>
            ) : (
              <Button variant="primary" onClick={handleDownloadModel}>
                <Download className="h-4 w-4" /> 下载深度检测模型
              </Button>
            )}
          </CardContent>
        </Card>
      )}
      {modelStatus?.ready && (
        <p className="mb-2 text-right text-xs text-muted">
          深度检测模型已就绪{modelStatus.source === "finetuned" ? "（微调版，更贴合网文）" : "（原版）"}
        </p>
      )}

      {/* 无报告引导 */}
      {!report && !checking && (
        <Card className="flex min-h-[40vh] items-center justify-center border-dashed">
          <div className="text-center text-muted">
            <ScanSearch className="mx-auto mb-2 h-8 w-8" />
            <p className="text-sm">选择章节后点击「检测」，查看该章的 AI 味报告</p>
          </div>
        </Card>
      )}

      {checking && (
        <Card className="flex min-h-[40vh] items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
        </Card>
      )}

      {report && (
        <div className="grid gap-4 lg:grid-cols-2">
          {/* ── 左：检测报告 ── */}
          <div className="space-y-4">
            {/* 深度检测报告（roberta 模型判别） */}
            {deepReport && (
              <Card className={cn(deepReport.available && deepReport.verdict === "AI" && "border-danger/40")}>
                <CardHeader className="flex-row items-center justify-between space-y-0">
                  <CardTitle>深度检测报告（模型判别）</CardTitle>
                  {deepReport.available ? (
                    <Badge variant={deepReport.verdict === "AI" ? "danger" : deepReport.verdict === "Mixed" ? "warning" : "success"}>
                      {deepReport.verdict === "AI" ? "AI 生成" : deepReport.verdict === "Mixed" ? "疑似 AI" : "人类写作"}
                    </Badge>
                  ) : (
                    <Badge variant="default">模型未就绪</Badge>
                  )}
                </CardHeader>
                <CardContent className="space-y-3">
                  {deepReport.available && deepReport.ai_probability !== null ? (
                    <>
                      <div className="flex items-center gap-4">
                        <div className="text-center">
                          <div className={cn(
                            "text-4xl font-bold",
                            deepReport.ai_probability >= 0.65 ? "text-danger" : deepReport.ai_probability >= 0.35 ? "text-warning" : "text-success",
                          )}>
                            {(deepReport.ai_probability * 100).toFixed(0)}
                          </div>
                          <div className="mt-1 text-xs text-muted">AI 概率 %</div>
                        </div>
                        <div className="flex-1">
                          <div className="mb-1 flex justify-between text-xs">
                            <span className="text-muted">模型判定</span>
                            <span className="font-medium">{deepReport.ai_level}</span>
                          </div>
                          <Progress value={deepReport.ai_probability * 100} />
                          <p className="mt-2 text-xs text-muted">{deepReport.summary}</p>
                        </div>
                      </div>
                      {deepReport.segments.length > 0 && (
                        <div>
                          <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-muted">
                            段落 AI 概率（前 {Math.min(deepReport.segments.length, 8)} 段）
                          </div>
                          <ul className="space-y-1">
                            {deepReport.segments.slice(0, 8).map((seg, i) => (
                              <li key={i} className="rounded-md border border-border bg-surface-elevated px-2 py-1.5">
                                <div className="mb-0.5 flex items-center justify-between gap-2">
                                  <span className="min-w-0 flex-1 truncate text-[10px] text-muted">{seg.text}</span>
                                  <span className={cn(
                                    "shrink-0 text-[10px] font-medium tabular-nums",
                                    seg.ai_probability >= 0.65 ? "text-danger" : seg.ai_probability >= 0.35 ? "text-warning" : "text-success",
                                  )}>
                                    {(seg.ai_probability * 100).toFixed(0)}%
                                  </span>
                                </div>
                                <Progress value={seg.ai_probability * 100} />
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </>
                  ) : (
                    <p className="text-xs text-muted">{deepReport.summary || "深度检测模型不可用"}</p>
                  )}
                </CardContent>
              </Card>
            )}

            {/* 评分卡 */}
            <Card>
              <CardHeader className="flex-row items-center justify-between space-y-0">
                <CardTitle>检测报告 · 第{selectedChapter}章</CardTitle>
                {(() => {
                  const nearMiss =
                    !report.passed && report.overall_score >= 100 - (report.pass_line ?? 30) - 10;
                  return (
                    <Badge variant={report.passed ? "success" : nearMiss ? "warning" : "danger"}>
                      {report.passed ? "已达标" : nearMiss ? "接近达标 · 建议人工判断" : "未达标"}
                    </Badge>
                  );
                })()}
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center gap-6">
                  <div className="text-center">
                    <div className={cn("text-4xl font-bold", scoreColor(report.overall_score))}>
                      {report.overall_score}
                    </div>
                    <div className="mt-1 text-xs text-muted">综合分 / 100</div>
                  </div>
                  <div className="flex-1 space-y-2">
                    <div>
                      <div className="flex justify-between text-xs">
                        <span className="text-muted">AI 率</span>
                        <span className={cn("font-medium", report.passed ? "text-success" : "text-danger")}>
                          {report.ai_rate}% {report.passed ? `≤${report.pass_line}% ✓` : `>${report.pass_line}%`}
                        </span>
                      </div>
                      <Progress value={Math.min(100, report.ai_rate)} className={cn(report.passed ? "" : "")} />
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      <Badge>{report.ai_level}</Badge>
                      <Badge variant="default">规则 {report.rule_score}</Badge>
                      <Badge variant="default">统计 {report.stat_score}</Badge>
                      <Badge variant="default">{report.chars} 字</Badge>
                      <Badge variant="warning">{report.total_hits} 处命中</Badge>
                    </div>
                  </div>
                </div>
                <p className="text-xs text-muted">{report.summary}</p>
                {!report.passed && report.verdict_hint && (
                  <p className="rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
                    {report.verdict_hint}
                  </p>
                )}
              </CardContent>
            </Card>

            {/* 维度条形 */}
            <Card>
              <CardHeader>
                <CardTitle>统计维度（对齐检测器信号）</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {DIMENSION_ORDER.map((key) => {
                  const v = report.dimensions?.[key];
                  if (v === undefined) return null;
                  return (
                    <div key={key}>
                      <div className="mb-1 flex justify-between text-xs">
                        <span className="text-muted">{DIMENSION_LABELS[key] || key}</span>
                        <span className={cn("font-medium", scoreColor(v))}>{v}</span>
                      </div>
                      <Progress value={v} />
                    </div>
                  );
                })}
              </CardContent>
            </Card>

            {/* 命中清单 */}
            <Card>
              <CardHeader>
                <CardTitle>命中清单（按报告润色）</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {hitGroups.length === 0 && (
                  <p className="text-sm text-muted">未检测到明显 AI 味问题</p>
                )}
                {hitGroups.map((g) => (
                  <div key={g.key}>
                    <div className="mb-1.5 flex items-center gap-2">
                      <span className={cn("h-2 w-2 rounded-full", g.color)} />
                      <span className="text-xs font-medium text-foreground">
                        {g.label}命中 {g.items.length} 处
                      </span>
                    </div>
                    <ul className="space-y-1.5">
                      {g.items.slice(0, 12).map((h, i) => (
                        <li key={i} className="rounded-lg border border-border bg-surface-elevated px-3 py-2 text-xs">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="font-medium text-foreground">
                              {h.pattern || h.word || h.matched || "命中"}
                            </span>
                            {h.count != null && h.count > 1 && (
                              <Badge variant="default">×{h.count}</Badge>
                            )}
                            {g.key === "word" && h.pattern && (
                              <button
                                type="button"
                                onClick={() => handleMarkFalsePositive(h.pattern)}
                                title="这个词是误判（如角色名/设定词），标记后不再报告"
                                className="ml-auto inline-flex items-center gap-0.5 rounded border border-border px-1 py-0.5 text-[10px] text-muted transition-colors hover:border-danger/40 hover:text-danger"
                              >
                                <ShieldOff className="h-3 w-3" /> 误判
                              </button>
                            )}
                          </div>
                          {(h.sentence || h.paragraph || h.snippet) && (
                            <div className="mt-1 line-clamp-2 text-muted">
                              {h.sentence || h.paragraph || h.snippet}
                            </div>
                          )}
                          <div className="mt-1 text-danger">{h.issue}</div>
                          <div className="text-success">{h.fix}</div>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </CardContent>
            </Card>

            {/* 误判白名单：已标记忽略的词 */}
            {ignoredList.length > 0 && (
              <Card>
                <CardHeader className="flex-row items-center justify-between space-y-0">
                  <CardTitle>已忽略的误判词</CardTitle>
                  <Badge variant="default">{ignoredList.length} 个</Badge>
                </CardHeader>
                <CardContent>
                  <p className="mb-2 text-xs text-muted">这些词被标记为误判，检测时不再报告。点 × 可撤销。</p>
                  <div className="flex flex-wrap gap-1.5">
                    {ignoredList.map((w) => (
                      <span
                        key={w}
                        className="inline-flex items-center gap-1 rounded-md bg-surface-hover px-2 py-1 text-xs text-muted"
                      >
                        <ShieldOff className="h-3 w-3" />
                        {w}
                        <button
                          type="button"
                          onClick={() => handleUnignore(w)}
                          title={`撤销「${w}」的误判标记`}
                          className="text-muted transition-colors hover:text-foreground"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
          <div className="space-y-4">
            <Card>
              <CardHeader className="flex-row items-center justify-between space-y-0">
                <CardTitle>润色与复检</CardTitle>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleRepairRule}
                    disabled={repairing || !chapterText}
                  >
                    {repairing && repairMethod === "rule" ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Wand2 className="h-3.5 w-3.5" />
                    )}
                    规则润色
                  </Button>
                  {repairing && repairMethod === "llm" ? (
                    <Button variant="danger" size="sm" onClick={handleStopLlm}>
                      <Square className="h-3.5 w-3.5" />
                      中断
                    </Button>
                  ) : (
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={handleRepairLlm}
                      disabled={repairing || !chapterText}
                    >
                      {repairing ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Wand2 className="h-3.5 w-3.5" />
                      )}
                      LLM 深度润色
                    </Button>
                  )}
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {/* 复检对比 */}
                {repairResult && (
                  <div className="rounded-lg border border-border bg-surface-elevated p-3">
                    <div className="mb-2 flex items-center gap-2">
                      <span className="text-xs font-medium text-muted">复检对比</span>
                      {repairResult.passed ? (
                        <Badge variant="success">
                          <CheckCircle2 className="mr-1 h-3 w-3" /> 达标
                        </Badge>
                      ) : (
                        <Badge variant="warning">
                          <XCircle className="mr-1 h-3 w-3" /> 未达标
                        </Badge>
                      )}
                      <Badge variant="default">
                        提升 {repairResult.score_delta > 0 ? "+" : ""}{repairResult.score_delta} 分
                      </Badge>
                      {repairMethod === "llm" && repairResult.rounds != null && (
                        <Badge variant="default">{repairResult.rounds} 轮</Badge>
                      )}
                    </div>
                    <div className="space-y-2">
                      <div>
                        <div className="flex justify-between text-xs">
                          <span className="text-muted">润色前 AI 率</span>
                          <span className="text-danger">{repairResult.before.ai_rate}%</span>
                        </div>
                        <Progress value={Math.min(100, repairResult.before.ai_rate)} />
                      </div>
                      <div>
                        <div className="flex justify-between text-xs">
                          <span className="text-muted">润色后 AI 率</span>
                          <span className={cn(repairResult.passed ? "text-success" : "text-warning")}>
                            {repairResult.after.ai_rate}%
                          </span>
                        </div>
                        <Progress value={Math.min(100, repairResult.after.ai_rate)} />
                      </div>
                    </div>
                  </div>
                )}

                {/* 流式输出 / 修复结果 */}
                <div className="relative">
                  <div className="mb-1 flex items-center justify-between">
                      <div className="flex items-center gap-1">
                        <span className="mr-1 text-xs font-medium text-muted">
                          {repairing && repairMethod === "llm"
                            ? `润色中${streamRound ? `（第${streamRound}轮）` : ""}...`
                            : repairResult
                              ? `润色结果（${repairMethod === "rule" ? "规则" : "LLM"}）`
                              : "章节原文"}
                        </span>
                        <button
                          type="button"
                          onClick={() => setPreviewTab("original")}
                          className={cn(
                            "rounded px-1.5 py-0.5 text-[10px] transition-colors",
                            previewTab === "original"
                              ? "bg-surface-hover text-foreground"
                              : "text-muted hover:text-foreground",
                          )}
                        >
                          原文
                        </button>
                        <button
                          type="button"
                          onClick={() => setPreviewTab("repaired")}
                          disabled={!repairResult}
                          className={cn(
                            "rounded px-1.5 py-0.5 text-[10px] transition-colors",
                            previewTab === "repaired"
                              ? "bg-surface-hover text-foreground"
                              : "text-muted hover:text-foreground",
                            !repairResult && "cursor-not-allowed opacity-40",
                          )}
                        >
                          润色后
                        </button>
                      </div>
                    <div className="flex gap-1">
                      {repairResult && (
                        <>
                          <Button variant="ghost" size="sm" onClick={() => handleCopy(streamText)}>
                            <Copy className="h-3.5 w-3.5" /> 复制
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={handleApply}
                            disabled={applying}
                          >
                            {applying ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Save className="h-3.5 w-3.5" />
                            )}
                            应用到章节
                          </Button>
                        </>
                      )}
                    </div>
                  </div>
                  <pre className="max-h-[55vh] overflow-y-auto whitespace-pre-wrap rounded-lg border border-border bg-surface-elevated p-3 font-sans text-xs leading-relaxed text-foreground">
                    {previewTab === "repaired" && repairResult
                      ? streamText
                      : chapterText || "（请先检测章节）"}
                  </pre>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
