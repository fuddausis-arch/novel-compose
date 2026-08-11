/** 全局设置 · 蒸馏技能页：导入优质作品 → 多轮蒸馏 → Skill 管理 → 技能融合 → 效果对比 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Beaker,
  Check,
  CheckSquare,
  FileText,
  FlaskConical,
  GitMerge,
  Layers,
  Loader2,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Settings2,
  Sparkles,
  Square,
  Trash2,
  Upload,
  User,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Markdown } from "@/components/markdown";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";

// ---------------------------------------------------------------------------
// 类型（与后端 /api/distillation 对齐：id 为 SQLite 整型主键）
// ---------------------------------------------------------------------------

interface DistillWork {
  id: number;
  title: string;
  source_type: string;
  total_chars: number;
  chunk_count: number;
  status: string; // pending | distilling | done | done_with_errors | failed
  created_at: string;
}

interface DistillChunk {
  id: number;
  work_id: number;
  chunk_index: number;
  char_count: number;
  status: string; // pending | distilling | done | failed
  preview?: string;
}

interface DistillSkill {
  id: number;
  work_id: number;
  work_title: string;
  chunk_index: number;
  round_num: number;
  source?: string; // "book-to-skill" 标记拆书技能
  file_name?: string; // 拆书技能的文件名
  name: string;
  description: string;
  content: string;
  tags: string[];
  status: string; // active | archived
  created_at: string;
}

interface FusionPlan {
  id: number;
  name: string;
  skill_ids: number[];
  weights: number[];
  description: string;
  status: string;
  created_at: string;
  skill_file?: string;
}

interface DistillProgress {
  work_id: number;
  status: string;
  total_chunks: number;
  done_chunks: number;
  total_rounds: number;
  done_rounds: number;
  skills_count: number;
}

/** SSE 蒸馏事件（data 负载自带 type 字段） */
interface DistillEvent {
  type?: string;
  chunk_index?: number;
  round_num?: number;
  char_count?: number;
  dimension?: string;
  status?: string;
  error?: string;
  skill_name?: string;
  skills_count?: number;
  // 多级蒸馏（浓缩）事件字段
  level?: number;
  batch?: number;
  total?: number;
  source_count?: number;
  name?: string;
  // 多书并发排队事件字段
  waiting?: number;
  running?: number;
}

/** 蒸馏中单个片段的实时状态 */
interface LiveChunkState {
  status: string;
  currentRound: number;
  dimension?: string;
  rounds: Record<number, string>; // round_num -> running | done | failed
}

/** 蒸馏模型设置：mode 决定走哪套配置。思考模式不再在此单独设置，
 *  统一在「模型管理」页按供应商配置，蒸馏自动继承。 */
interface DistillModelConfig {
  mode: "default" | "provider" | "custom";
  provider: string; // 供应商名（mode=provider）
  model: string; // 供应商模式下的模型名
  customBaseUrl: string; // 自定义模式：接口地址
  customApiKey: string; // 自定义模式：API Key
  customModel: string; // 自定义模式：模型名
}

/** 单本书的蒸馏任务状态（支持多本同时蒸馏，互不阻塞） */
interface DistillJob {
  workId: number;
  status: "queued" | "running"; // queued=排队中（并发满 MAX_CONCURRENT_DISTILL 本）
  controller: AbortController;
  log: string[];
  progress: { done: number; total: number } | null;
  liveChunks: Record<number, LiveChunkState>;
  recovered?: boolean; // 页面切回后从后端恢复进度的任务（无 SSE 连接，轮询更新）
}

/**
 * 多书并发上限（与后端 _MAX_CONCURRENT_DISTILL 一致，这里取更小值用于前端先排队）：
 * 同时蒸馏太多书会让每本内部的并行片段请求叠加，触发 AI 服务商账户级限流（429）。
 * 实测 5 本同时跑容易爆限流，降到 3 本更稳；后端实际上限 5，前端只发 3 个请求。
 */
const MAX_CONCURRENT_DISTILL = 3;

/** 模型管理页供应商数据结构（/api/models/providers 返回，api_key 已脱敏） */
interface ModelProvider {
  name: string;
  base_url: string;
  api_key: string;
  models: string[];
  priority: number;
  is_default: boolean;
}

type BadgeVariant = "default" | "primary" | "danger" | "warning" | "success";

/** 蒸馏候选维度（与后端 ROUND_DIMENSIONS 对齐：1-7 文笔技法，8-12 网文实战，13-15 指纹，16-19 专项写手） */
const DIMENSIONS: Array<{ id: number; name: string; points: string }> = [
  { id: 1, name: "写作风格特征", points: "叙事节奏、对话风格、描写习惯、情感表达" },
  { id: 2, name: "语言特征", points: "用词偏好、句式结构、修辞手法、标点习惯" },
  { id: 3, name: "故事结构特征", points: "情节推进、冲突设计、伏笔埋设、节奏控制" },
  { id: 4, name: "叙事引擎", points: "悬念钩子、信息差、期待感、爽点释放节奏" },
  { id: 5, name: "信息控制", points: "悬念吊法、伏笔深度、视角信息差、反转铺垫" },
  { id: 6, name: "人物塑造技法", points: "角色出场、性格展现、对话辨识度、成长弧线" },
  { id: 7, name: "情感算法", points: "情绪曲线、共情锚点、情感落差、读者情绪引导" },
  { id: 8, name: "世界观与设定", points: "题材融合、力量体系/金手指规则、舞台规则、时代背景" },
  { id: 9, name: "爽点设计", points: "爽点类型、铺垫→释放模式、爽点密度与间隔" },
  { id: 10, name: "章节钩子", points: "断章技巧、结尾悬念、金句钩子、开篇抓人" },
  { id: 11, name: "对话与台词", points: "对话占比、角色语言辨识度、对话推动剧情、潜台词" },
  { id: 12, name: "反派与配角", points: "反派动机自洽、不降智、配角功能、关系张力" },
  { id: 13, name: "节奏与句长指纹", points: "句长分布、对话占比、段落长短变化（AI 检测器第一信号）" },
  { id: 14, name: "禁词与套路词表", points: "原书回避的 AI 高频词与套路句式，生成时禁用" },
  { id: 15, name: "密度目标", points: "形容词/破折号/连接词/重复词密度控制习惯" },
  { id: 16, name: "动作与打斗", points: "打斗节奏（起手→交锋→转折→收束）、动作粒度、力量感、紧张感" },
  { id: 17, name: "内心与心理", points: "内心独白风格（直接/隐喻/意识流）、情绪层次、心理冲突、揭示节奏" },
  { id: 18, name: "环境与描写", points: "氛围营造（光线/声音/气味/温度）、感官细节、环境叙事、克制" },
  { id: 19, name: "过渡与节奏", points: "场景过渡（时间跳转/地点切换/情绪衔接/黑场）、节奏切换、连续性" },
];

/** 全部维度编号 */
const ALL_DIM_IDS = DIMENSIONS.map((d) => d.id);

/** 蒸馏总轮数（当前维度池大小） */
const TOTAL_ROUNDS = DIMENSIONS.length;

const WORK_STATUS_MAP: Record<string, { label: string; variant: BadgeVariant }> = {
  pending: { label: "待蒸馏", variant: "default" },
  distilling: { label: "蒸馏中", variant: "warning" },
  done: { label: "已完成", variant: "success" },
  done_with_errors: { label: "部分完成", variant: "warning" },
  failed: { label: "失败", variant: "danger" },
};

const CHUNK_STATUS_MAP: Record<string, { label: string; variant: BadgeVariant }> = {
  pending: { label: "待蒸馏", variant: "default" },
  distilling: { label: "蒸馏中", variant: "warning" },
  done: { label: "已完成", variant: "success" },
  failed: { label: "失败", variant: "danger" },
};

/** Skill 名称仅允许字母数字下划线横线（与后端校验一致） */
const SKILL_NAME_PATTERN = /^[A-Za-z0-9_-]+$/;

// ---------------------------------------------------------------------------
// 工具函数
// ---------------------------------------------------------------------------

/** 原生 fetch 封装：统一错误信息提取 */
async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    let msg = `请求失败（HTTP ${res.status}）`;
    try {
      const j = JSON.parse(text);
      if (j.detail) msg = String(j.detail);
      else if (j.message) msg = String(j.message);
    } catch {
      /* 非 JSON，忽略 */
    }
    throw new Error(msg);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** 把模型设置转成后端可识别的请求字段（provider 模式 / 自定义模式） */
function modelConfigFields(cfg: DistillModelConfig): Record<string, unknown> {
  if (cfg.mode === "provider" && cfg.provider) {
    return { provider: cfg.provider, model: cfg.model };
  }
  if (cfg.mode === "custom" && (cfg.customBaseUrl || cfg.customModel)) {
    return {
      custom_base_url: cfg.customBaseUrl,
      custom_api_key: cfg.customApiKey,
      custom_model: cfg.customModel,
    };
  }
  return {};
}

/** 当前模型设置的展示文案（按钮 / 日志用） */
function modelConfigLabel(cfg: DistillModelConfig, providers: ModelProvider[]): string {
  if (cfg.mode === "provider" && cfg.provider) {
    const p = providers.find((it) => it.name === cfg.provider);
    return cfg.model ? `${p?.name ?? cfg.provider} · ${cfg.model}` : cfg.provider;
  }
  if (cfg.mode === "custom" && cfg.customModel) return `自定义 · ${cfg.customModel}`;
  return "跟随全局配置";
}

/**
 * 蒸馏 SSE 流（POST 无法用原生 EventSource，改用 fetch + ReadableStream 逐行解析 data: 帧，
 * ping 注释行与非 JSON 帧直接忽略）。
 */
async function streamDistill(
  workId: number,
  levels: number,
  dimensions: number[],
  modelConfig: DistillModelConfig,
  signal: AbortSignal,
  onEvent: (evt: DistillEvent) => void,
  retryFailed = false,
): Promise<void> {
  const res = await fetch(`/api/distillation/works/${workId}/distill`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      rounds: TOTAL_ROUNDS,
      levels,
      dimensions,
      retry_failed: retryFailed,
      // 隔离模式：同一本书多次蒸馏时跳过已完成的维度，旧产物原样保留、不重复不覆盖
      skip_done_rounds: true,
      ...modelConfigFields(modelConfig),
    }),
    signal,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    let msg = `请求失败（HTTP ${res.status}）`;
    try {
      const j = JSON.parse(text);
      if (j.detail) msg = String(j.detail);
    } catch {
      /* 非 JSON，忽略 */
    }
    throw new Error(msg);
  }
  if (!res.body) throw new Error("无法建立流式连接");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      try {
        onEvent(JSON.parse(line.slice(6)) as DistillEvent);
      } catch {
        /* ping 等无法解析的帧，忽略 */
      }
    }
  }
}

function formatChars(n: number): string {
  if (n >= 10000) return `${(n / 10000).toFixed(1)} 万字`;
  return `${n} 字`;
}

/** Skill 来源标签：chunk_index < 0 表示整书浓缩产物（第 rn 级），否则为"片段X·维度Y" */
function skillSourceLabel(chunkIndex: number, roundNum: number): string {
  if (chunkIndex < 0) return `浓缩 · 第 ${roundNum} 级`;
  const dim = DIMENSIONS.find((d) => d.id === roundNum);
  return `片段 ${chunkIndex + 1} · 维度 ${roundNum}${dim ? `（${dim.name}）` : ""}`;
}

function formatDate(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso.slice(0, 10) : d.toLocaleDateString("zh-CN");
}

function workStatusOf(status: string) {
  return WORK_STATUS_MAP[status] ?? { label: status, variant: "default" as BadgeVariant };
}

function chunkStatusOf(status: string) {
  return CHUNK_STATUS_MAP[status] ?? { label: status, variant: "default" as BadgeVariant };
}

function errorMessage(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

// ---------------------------------------------------------------------------
// 页面
// ---------------------------------------------------------------------------

export default function DistillationPage() {
  const { showSuccess, showError } = useToast();

  // 全局数据
  const [works, setWorks] = useState<DistillWork[]>([]);
  // works 的即时镜像：并发判断/补位以后端真实状态为准，避免页面重载后本地计数失效导致超并发
  const worksRef = useRef<DistillWork[]>([]);
  useEffect(() => {
    worksRef.current = works;
  }, [works]);
  const [allSkills, setAllSkills] = useState<DistillSkill[]>([]);
  const [fusions, setFusions] = useState<FusionPlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 选中作品详情
  const [selectedWorkId, setSelectedWorkId] = useState<number | null>(null);
  const [chunks, setChunks] = useState<DistillChunk[]>([]);
  const [workSkills, setWorkSkills] = useState<DistillSkill[]>([]);
  const [progress, setProgress] = useState<DistillProgress | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // 蒸馏级数：1=一次蒸馏（碎片）；2=二次蒸馏（浓缩提炼）；3=三次蒸馏（再浓缩）
  const [distillLevels, setDistillLevels] = useState(3);
  // 蒸馏维度：勾选要分析的维度编号，默认全部
  const [distillDims, setDistillDims] = useState<number[]>(ALL_DIM_IDS);
  const [dimsDialogOpen, setDimsDialogOpen] = useState(false);
  // 蒸馏模型设置（持久化到 localStorage：用户选过的供应商/模型，刷新/重蒸馏后仍生效）
  const [modelProviders, setModelProviders] = useState<ModelProvider[]>([]);
  const [modelConfig, setModelConfig] = useState<DistillModelConfig>(() => {
    try {
      const saved = localStorage.getItem("distill_model_config");
      if (saved) {
        return {
          mode: "default",
          provider: "",
          model: "",
          customBaseUrl: "",
          customApiKey: "",
          customModel: "",
          ...JSON.parse(saved),
        };
      }
    } catch {
      /* 解析失败用默认 */
    }
    return {
      mode: "default",
      provider: "",
      model: "",
      customBaseUrl: "",
      customApiKey: "",
      customModel: "",
    };
  });
  useEffect(() => {
    try {
      localStorage.setItem("distill_model_config", JSON.stringify(modelConfig));
    } catch {
      /* 存储失败不影响使用 */
    }
  }, [modelConfig]);
  const [modelSettingsOpen, setModelSettingsOpen] = useState(false);
  // 多本并发蒸馏：work_id -> 该书的蒸馏任务状态
  const [jobs, setJobs] = useState<Record<number, DistillJob>>({});
  const selectedWorkRef = useRef<number | null>(null);
  const logRef = useRef<HTMLDivElement | null>(null);

  // 并发调度 refs（避免 setState 异步导致的竞态）：
  // - jobsRef：jobs 的即时镜像
  // - activeJobsRef：当前已发起 SSE（running）的任务数，≤ MAX_CONCURRENT_DISTILL
  // - pendingQueueRef：前端本地排队（未发起 SSE）的 work_id 队列
  const jobsRef = useRef<Record<number, DistillJob>>({});
  const activeJobsRef = useRef(0);
  const pendingQueueRef = useRef<number[]>([]);
  useEffect(() => {
    jobsRef.current = jobs;
  }, [jobs]);

  // 导入对话框
  const [importOpen, setImportOpen] = useState(false);
  const [importTitle, setImportTitle] = useState("");
  const [importContent, setImportContent] = useState("");
  const [importing, setImporting] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importMode, setImportMode] = useState<"paste" | "upload">("paste");

  // Skill 编辑对话框
  const [editingSkill, setEditingSkill] = useState<DistillSkill | null>(null);
  const [editForm, setEditForm] = useState({ name: "", description: "", content: "" });
  const [editError, setEditError] = useState<string | null>(null);
  const [savingSkill, setSavingSkill] = useState(false);

  // 通用确认对话框
  const [confirmState, setConfirmState] = useState<{
    title: string;
    description: string;
    actionLabel: string;
    onConfirm: () => Promise<void>;
  } | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  // 技能融合
  const [fusionSelected, setFusionSelected] = useState<Record<number, number>>({});
  const [fusionName, setFusionName] = useState("");
  const [fusionDesc, setFusionDesc] = useState("");
  const [fusing, setFusing] = useState(false);
  const [deleteOriginals, setDeleteOriginals] = useState(false); // 融合成功后删除原 Skill
  // 融合实时进度（SSE 事件驱动）
  const [fusionStage, setFusionStage] = useState("");
  const [fusionBatch, setFusionBatch] = useState<{ batch: number; total: number } | null>(null);
  // 融合产物查看弹窗
  const [viewFusion, setViewFusion] = useState<{
    name: string;
    description: string;
    tags: string[];
    distilled: boolean;
    content: string;
  } | null>(null);
  const [viewFusionLoading, setViewFusionLoading] = useState(false);

  // 效果对比
  const [comparePrompt, setComparePrompt] = useState("");
  const [compareSkillId, setCompareSkillId] = useState("");
  const [comparing, setComparing] = useState(false);
  const [compareResult, setCompareResult] = useState<{ baseline: string; with_skill: string | null } | null>(null);

  // 角色蒸馏
  const [charDistillOpen, setCharDistillOpen] = useState(false);
  const [charDistillName, setCharDistillName] = useState("");
  const [charDistilling, setCharDistilling] = useState(false);
  const [charDistillLog, setCharDistillLog] = useState<string[]>([]);

  // 盲测评估
  const [blindEvalOpen, setBlindEvalOpen] = useState(false);
  const [blindEvalSkillId, setBlindEvalSkillId] = useState<number | null>(null);
  const [blindEvalPrompt, setBlindEvalPrompt] = useState("");
  const [blindEvaluating, setBlindEvaluating] = useState(false);
  const [blindEvalResult, setBlindEvalResult] = useState<any>(null);

  const selectedWork = works.find((w) => w.id === selectedWorkId) ?? null;

  // ------------------------------------------------------------------
  // 数据加载
  // ------------------------------------------------------------------

  const load = useCallback(async (initial = false) => {
    if (initial) setLoading(true);
    else setRefreshing(true);
    setError(null);
    try {
      const [worksRes, skillsRes, fusionsRes] = await Promise.all([
        fetchJson<{ works: DistillWork[] }>("/api/distillation/works"),
        fetchJson<{ skills: DistillSkill[] }>("/api/distillation/skills"),
        fetchJson<{ fusions: FusionPlan[] }>("/api/distillation/fusions"),
      ]);
      setWorks(worksRes.works || []);
      setAllSkills(skillsRes.skills || []);
      setFusions(fusionsRes.fusions || []);
    } catch (e) {
      setError(errorMessage(e, "加载失败"));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load(true);
  }, [load]);

  // 加载模型供应商列表（用于蒸馏模型设置弹窗）
  useEffect(() => {
    fetchJson<{ providers: ModelProvider[] }>("/api/models/providers")
      .then((res) => setModelProviders(res.providers || []))
      .catch(() => setModelProviders([]));
  }, []);

  const loadWorkDetail = useCallback(
    async (workId: number) => {
      setDetailLoading(true);
      try {
        const [detail, skillsRes, prog] = await Promise.all([
          fetchJson<{ work: DistillWork; chunks: DistillChunk[] }>(`/api/distillation/works/${workId}`),
          fetchJson<{ skills: DistillSkill[] }>(`/api/distillation/works/${workId}/skills`),
          fetchJson<DistillProgress>(`/api/distillation/status/${workId}`).catch(() => null),
        ]);
        setChunks(detail.chunks || []);
        setWorkSkills(skillsRes.skills || []);
        setProgress(prog);
      } catch (e) {
        showError(errorMessage(e, "加载作品详情失败"));
        setChunks([]);
        setWorkSkills([]);
        setProgress(null);
      } finally {
        setDetailLoading(false);
      }
    },
    [showError],
  );

  useEffect(() => {
    selectedWorkRef.current = selectedWorkId;
    if (selectedWorkId != null) void loadWorkDetail(selectedWorkId);
  }, [selectedWorkId, loadWorkDetail]);

  // 日志自动滚动到底部（当前选中作品的蒸馏日志）
  const selectedJob = selectedWorkId != null ? jobs[selectedWorkId] : undefined;
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [selectedJob?.log]);

  // 恢复轮询定时器：页面切回后，对后端仍在蒸馏中的书轮询 /status 恢复进度显示
  const recoveryTimersRef = useRef<Record<number, ReturnType<typeof setInterval>>>({});

  // 卸载时断开所有蒸馏流。注意：后端任务不再随连接断开而取消（后台继续跑），
  // 切回页面时通过 loadWorkDetail / status 拉取实时进度。
  useEffect(
    () => () => {
      for (const j of Object.values(jobsRef.current)) j.controller.abort();
      for (const t of Object.values(recoveryTimersRef.current)) clearInterval(t);
    },
    [],
  );

  /** 向某本书的蒸馏日志追加一行（只保留最近 50 行） */
  const appendLog = useCallback((workId: number, msg: string) => {
    setJobs((prev) => {
      const job = prev[workId];
      if (!job) return prev;
      return { ...prev, [workId]: { ...job, log: [...job.log.slice(-49), msg] } };
    });
  }, []);

  /** 更新某本书蒸馏任务的字段（不存在则忽略） */
  const patchJob = useCallback(
    (workId: number, patch: Partial<Omit<DistillJob, "workId" | "controller">>) => {
      setJobs((prev) => {
        const job = prev[workId];
        if (!job) return prev;
        return { ...prev, [workId]: { ...job, ...patch } };
      });
    },
    [],
  );

  /** 移除某本书的蒸馏任务（正常结束后清掉本地状态） */
  const removeJob = useCallback((workId: number) => {
    setJobs((prev) => {
      if (!(workId in prev)) return prev;
      const next = { ...prev };
      delete next[workId];
      return next;
    });
  }, []);

  const stopRecoveryPoll = useCallback((workId: number) => {
    const t = recoveryTimersRef.current[workId];
    if (t) {
      clearInterval(t);
      delete recoveryTimersRef.current[workId];
    }
  }, []);

  /** 为某本"后端仍在蒸馏"的书创建恢复任务（无 SSE，轮询 /status 更新进度） */
  const startRecoveryPoll = useCallback(
    (workId: number) => {
      if (jobsRef.current[workId]) return; // 已有任务（如用户已手动重启），不重复
      stopRecoveryPoll(workId);
      setJobs((prev) =>
        prev[workId]
          ? prev
          : {
              ...prev,
              [workId]: {
                workId,
                status: "running",
                controller: new AbortController(),
                log: ["任务在后台继续蒸馏中，已恢复进度显示..."],
                progress: null,
                liveChunks: {},
                recovered: true,
              },
            },
      );

      const poll = async () => {
        const job = jobsRef.current[workId];
        if (!job?.recovered) return; // 任务已被移除 / 用户已手动重启，停止轮询
        try {
          const p = await fetchJson<DistillProgress>(`/api/distillation/status/${workId}`);
          if (!jobsRef.current[workId]?.recovered) return;
          const progress =
            p.total_rounds > 0
              ? { done: p.done_rounds, total: p.total_rounds }
              : { done: p.done_chunks, total: p.total_chunks };
          patchJob(workId, { progress });
          if (p.status !== "distilling") {
            // 后台任务已结束（完成/部分完成/失败/取消）
            stopRecoveryPoll(workId);
            removeJob(workId);
            void load();
          }
        } catch {
          /* 网络抖动等，忽略，下轮重试 */
        }
      };

      void poll();
      recoveryTimersRef.current[workId] = setInterval(() => void poll(), 5000);
    },
    [stopRecoveryPoll, patchJob, removeJob, load],
  );

  // 每次加载完作品列表后，为"仍在蒸馏"的书自动恢复进度显示（切页回来也能看到实时进度）
  useEffect(() => {
    if (loading) return;
    for (const w of works) {
      if (w.status === "distilling") {
        startRecoveryPoll(w.id);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [works, loading, startRecoveryPoll]);

  /** 更新某本书某个片段的实时状态（在 setJobs 更新器内基于最新快照计算，避免闭包过期） */
  const patchLiveChunk = useCallback(
    (workId: number, ci: number, updater: (cur: LiveChunkState) => LiveChunkState) => {
      setJobs((prev) => {
        const job = prev[workId];
        if (!job) return prev;
        const cur = job.liveChunks[ci] ?? { status: "pending", currentRound: 0, rounds: {} };
        return { ...prev, [workId]: { ...job, liveChunks: { ...job.liveChunks, [ci]: updater(cur) } } };
      });
    },
    [],
  );

  /** 某本书完成一轮：进度 +1（同样基于最新快照） */
  const bumpJobProgress = useCallback((workId: number) => {
    setJobs((prev) => {
      const job = prev[workId];
      if (!job || !job.progress) return prev;
      return {
        ...prev,
        [workId]: {
          ...job,
          progress: { ...job.progress, done: Math.min(job.progress.done + 1, job.progress.total) },
        },
      };
    });
  }, []);

  /** 停止某本书的蒸馏：断开 SSE + 显式请求后端取消（已完成部分保留） */
  const abortDistill = useCallback(
    async (workId: number) => {
      const job = jobsRef.current[workId];
      if (!job) return;
      if (job.status === "queued") {
        // 只是前端本地排队（尚未发起 SSE）：移除队列即可，无需请求后端
        pendingQueueRef.current = pendingQueueRef.current.filter((x) => x !== workId);
        removeJob(workId);
        showSuccess("已取消排队");
        return;
      }
      job.controller.abort();
      try {
        await fetchJson<{ cancelled: boolean }>(
          `/api/distillation/works/${workId}/cancel`,
          { method: "POST" },
        );
        showSuccess("已请求中断蒸馏，已完成的部分会保留");
      } catch (e) {
        showError(errorMessage(e, "中断请求失败"));
      }
      // 注意：不在这里 removeJob / pumpQueue——SSE 被 abort 后 launchDistill 的
      // finally 会统一收尾（减活跃数、删 job、补位启动排队的下一本）
    },
    [removeJob, showSuccess, showError],
  );

  const handleSelectWork = (id: number) => {
    if (id === selectedWorkId) return;
    // 切换作品：只切换查看视角，不中断任何蒸馏任务（各书任务独立继续跑）
    setSelectedWorkId(id);
  };

  // ------------------------------------------------------------------
  // 作品导入
  // ------------------------------------------------------------------

  const handleImport = async () => {
    if (importMode === "upload") {
      // 文件上传模式
      if (!importFile) {
        showError("请选择文件");
        return;
      }
      setImporting(true);
      try {
        const formData = new FormData();
        formData.append("file", importFile);
        formData.append("title", importTitle.trim() || importFile.name.replace(/\.[^.]+$/, ""));
        const res = await fetch("/api/distillation/works/upload", { method: "POST", body: formData });
        if (!res.ok) {
          const text = await res.text().catch(() => "");
          let msg = `导入失败（HTTP ${res.status}）`;
          try { const j = JSON.parse(text); if (j.detail) msg = String(j.detail); } catch {}
          throw new Error(msg);
        }
        const data = await res.json();
        showSuccess(`导入成功：共 ${formatChars(data.work.total_chars)}，拆分为 ${data.work.chunk_count} 个片段`);
        setImportOpen(false);
        setImportTitle("");
        setImportContent("");
        setImportFile(null);
        await load();
        setSelectedWorkId(data.work.id);
      } catch (e) {
        showError(e instanceof Error ? e.message : "导入失败");
      } finally {
        setImporting(false);
      }
      return;
    }

    // 粘贴文本模式
    if (!importTitle.trim()) {
      showError("请输入作品标题");
      return;
    }
    if (!importContent.trim()) {
      showError("请粘贴作品内容");
      return;
    }
    setImporting(true);
    try {
      const res = await fetchJson<{ created: boolean; work: DistillWork }>("/api/distillation/works", {
        method: "POST",
        body: JSON.stringify({ title: importTitle.trim(), content: importContent }),
      });
      showSuccess(`导入成功：共 ${formatChars(res.work.total_chars)}，拆分为 ${res.work.chunk_count} 个片段`);
      setImportOpen(false);
      setImportTitle("");
      setImportContent("");
      await load();
      setSelectedWorkId(res.work.id);
    } catch (e) {
      showError(errorMessage(e, "导入失败"));
    } finally {
      setImporting(false);
    }
  };

  // ------------------------------------------------------------------
  // 蒸馏（SSE）
  // ------------------------------------------------------------------

  /** 真正启动某本书的 SSE 蒸馏（创建 running job，占用一个并发位） */
  const launchDistill = async (workId: number, retryFailed = false) => {
    if (workId == null || jobsRef.current[workId]?.status === "running") return;
    const work = works.find((w) => w.id === workId);
    if (!work || work.chunk_count === 0) {
      showError("该作品没有可蒸馏的片段");
      return;
    }
    if (distillDims.length === 0) {
      showError("请至少勾选一个蒸馏维度");
      return;
    }
    activeJobsRef.current += 1;
    const controller = new AbortController();
    const total = work.chunk_count * distillDims.length;
    setJobs((prev) => ({
      ...prev,
      [workId]: {
        workId,
        status: "running",
        controller,
        log: [],
        progress: { done: 0, total },
        liveChunks: {},
      },
    }));
    setWorks((prev) => prev.map((w) => (w.id === workId ? { ...w, status: "distilling" } : w)));
    appendLog(workId, retryFailed
      ? `补蒸馏：仅重跑失败的片段/轮次（模型：${modelConfigLabel(modelConfig, modelProviders)}）`
      : `开始蒸馏：${work.chunk_count} 个片段 × ${distillDims.length} 个维度${distillLevels > 1 ? `，${distillLevels} 级蒸馏（含浓缩提炼）` : ""}（模型：${modelConfigLabel(modelConfig, modelProviders)}）`);

    /** 蒸馏过程中轻量刷新 Skill 列表（全局 + 当前作品） */
    const refreshSkills = async () => {
      try {
        const res = await fetchJson<{ skills: DistillSkill[] }>("/api/distillation/skills");
        const skills = res.skills || [];
        setAllSkills(skills);
        if (selectedWorkRef.current === workId) {
          setWorkSkills(skills.filter((s) => s.work_id === workId).sort((a, b) => a.id - b.id));
        }
      } catch {
        /* 刷新失败不影响主流程 */
      }
    };

    try {
      await streamDistill(workId, distillLevels, distillDims, modelConfig, controller.signal, (evt) => {
        const ci = Number(evt.chunk_index ?? 0);
        const rn = Number(evt.round_num ?? 0);
        switch (evt.type) {
          case "queued":
            patchJob(workId, { status: "queued" });
            appendLog(workId, `后端排队中${evt.waiting ? `（前面还有 ${evt.waiting} 本）` : ""}...`);
            break;
          case "chunk_start":
            patchJob(workId, { status: "running" });
            patchLiveChunk(workId, ci, () => ({ status: "distilling", currentRound: 0, rounds: {} }));
            appendLog(workId, `片段 ${ci + 1} 开始蒸馏（${formatChars(Number(evt.char_count ?? 0))}）`);
            break;
          case "round_start":
            patchJob(workId, { status: "running" });
            patchLiveChunk(workId, ci, (cur) => ({
              ...cur,
              status: "distilling",
              currentRound: rn,
              dimension: evt.dimension,
              rounds: { ...cur.rounds, [rn]: "running" },
            }));
            appendLog(workId, `片段 ${ci + 1} · 第 ${rn} 轮（${evt.dimension || "综合特征"}）蒸馏中...`);
            break;
          case "round_done":
            patchLiveChunk(workId, ci, (cur) => ({
              ...cur,
              rounds: { ...cur.rounds, [rn]: "done" },
            }));
            bumpJobProgress(workId);
            break;
          case "round_failed":
            patchLiveChunk(workId, ci, (cur) => ({
              ...cur,
              rounds: { ...cur.rounds, [rn]: "failed" },
            }));
            bumpJobProgress(workId);
            appendLog(workId, `片段 ${ci + 1} · 第 ${rn} 轮失败：${evt.error || "未知错误"}`);
            break;
          case "skill_created":
            setProgress((p) => (p ? { ...p, skills_count: p.skills_count + 1 } : p));
            appendLog(workId, `生成 Skill：${evt.skill_name}（片段 ${ci + 1} · 维度 ${rn}）`);
            void refreshSkills();
            break;
          case "chunk_done":
            patchLiveChunk(workId, ci, (cur) => ({
              ...cur,
              status: evt.status || "done",
              currentRound: 0,
            }));
            appendLog(workId, `片段 ${ci + 1} 蒸馏${evt.status === "done" ? "完成" : "失败（存在失败轮次）"}`);
            break;
          case "work_done": {
            const st = workStatusOf(evt.status || "done");
            appendLog(workId, `蒸馏结束：${st.label}，累计生成 ${evt.skills_count ?? 0} 个 Skill`);
            break;
          }
          // 多级蒸馏：浓缩提炼事件
          case "condense_start":
            appendLog(workId, `第 ${evt.level} 级蒸馏（浓缩提炼）开始，来源 ${evt.source_count ?? 0} 个 Skill...`);
            break;
          case "condense_batch_start":
            appendLog(workId, `第 ${evt.level} 级浓缩 · 批次 ${evt.batch}/${evt.total} 提炼中...`);
            break;
          case "condense_batch_done":
            break;
          case "condense_done":
            appendLog(workId, `第 ${evt.level} 级浓缩完成：${evt.skill_name ?? ""}（${evt.name ?? ""}）`);
            setProgress((p) => (p ? { ...p, skills_count: p.skills_count + 1 } : p));
            void refreshSkills();
            break;
          case "condense_failed":
            appendLog(workId, `第 ${evt.level} 级浓缩失败`);
            break;
          case "error":
            appendLog(workId, `蒸馏错误：${evt.error || "未知错误"}`);
            showError(evt.error || "蒸馏失败");
            break;
        }
      }, retryFailed);
    } catch (e) {
      if ((e as Error)?.name === "AbortError") {
        appendLog(workId, "已手动停止蒸馏");
      } else {
        showError(errorMessage(e, "蒸馏连接中断"));
        appendLog(workId, `连接中断：${errorMessage(e, "未知错误")}`);
      }
    } finally {
      // 统一收尾：释放并发位 → 删本地 job → 补位启动排队的下一本
      activeJobsRef.current = Math.max(0, activeJobsRef.current - 1);
      removeJob(workId);
      void pumpQueue();
      // 结束后全量刷新，确保与后端 DB 状态一致
      await load();
      if (selectedWorkRef.current === workId) await loadWorkDetail(workId);
    }
  };

  /** 本地排队补位：以"后端真实在跑数"判断空位，自动启动排队中的下一本。
   *  同样以后端 works 为准，避免重载/切页后本地计数丢失导致超并发。
   *  补位条件必须是「在跑数 < 上限」就启动下一本——不能写成
   *  「在跑数 + 排队数 < 上限」：那在排队数超过空位数时永远不成立，
   *  排队任务永远不被启动（越积越多，之后点什么都显示排队中）。 */
  const pumpQueue = async () => {
    let backendRunning = worksRef.current.filter((w) => w.status === "distilling").length;
    try {
      const ws = await fetchJson<{ works: DistillWork[] }>("/api/distillation/works");
      setWorks(ws.works || []);
      backendRunning = (ws.works || []).filter((w) => w.status === "distilling").length;
    } catch {
      // 拉取失败沿用当前 works
    }
    while (
      backendRunning < MAX_CONCURRENT_DISTILL &&
      pendingQueueRef.current.length > 0
    ) {
      const next = pendingQueueRef.current.shift()!;
      if (jobsRef.current[next]?.status === "running") continue; // 已在跑（理论不会，防御性跳过）
      backendRunning += 1; // 预占一个并发位，保证同一轮只补到上限
      void launchDistill(next, false);
    }
  };

  // 排队任务自动补位：后端任务结束/被取消可能发生在前端之外（如 API 取消、
  // 切页后任务结束），前端收不到任务结束事件就不会触发 pumpQueue。
  // 定时检查保证只要有空位，排队中的书会自动启动，不会一直卡在排队。
  useEffect(() => {
    const timer = setInterval(() => {
      if (pendingQueueRef.current.length > 0) void pumpQueue();
    }, 5000);
    return () => clearInterval(timer);
  }, [pumpQueue]);

  /** 提交某本书开始蒸馏：并发未满直接启动；满了本地排队（显示排队中，等空位自动启动）。
   *  并发判断以后端真实状态（/works 里 distilling 的数量）为准——页面重载/切页后本地计数会丢失，
   *  若只用本地计数会把"后端仍在跑"的任务漏算，导致超并发叠加（并发 3 却 6 本同时跑）。 */
  const handleStartDistill = async (workId: number, retryFailed = false) => {
    if (workId == null) return;
    if (jobsRef.current[workId]?.status === "running") {
      showError("这本书正在蒸馏中，请先停止再重新开始");
      return;
    }
    if (jobsRef.current[workId]?.status === "queued") {
      // 排队中的书再次点击 = 取消排队并重新判断并发（避免"点了没反应"）
      pendingQueueRef.current = pendingQueueRef.current.filter((x) => x !== workId);
      removeJob(workId);
      appendLog(workId, "已取消排队，重新判断并发...");
    }
    const work = works.find((w) => w.id === workId);
    if (!work || work.chunk_count === 0) {
      showError("该作品没有可蒸馏的片段");
      return;
    }
    if (distillDims.length === 0) {
      showError("请至少勾选一个蒸馏维度");
      return;
    }
    // 拉取最新 works，以后端真实在跑数作为并发依据（失败则沿用当前 works）
    let backendRunning = worksRef.current.filter((w) => w.status === "distilling").length;
    try {
      const ws = await fetchJson<{ works: DistillWork[] }>("/api/distillation/works");
      setWorks(ws.works || []);
      backendRunning = (ws.works || []).filter((w) => w.status === "distilling").length;
    } catch {
      // 拉取失败沿用当前 works
    }
    if (backendRunning + pendingQueueRef.current.length >= MAX_CONCURRENT_DISTILL) {
      // 并发已满 → 本地排队（不发起 SSE，避免浏览器并发连接过多导致卡顿、状态失真）
      setJobs((prev) => ({
        ...prev,
        [workId]: {
          workId,
          status: "queued",
          controller: new AbortController(),
          log: [],
          progress: null,
          liveChunks: {},
        },
      }));
      // 注意：不改本地 works 状态为 distilling——排队不是真在跑，改了会污染
      // worksRef 里的并发计数（拉取失败时误算）并误触发恢复轮询
      pendingQueueRef.current.push(workId);
      appendLog(workId, `并发已满（同时最多 ${MAX_CONCURRENT_DISTILL} 本），排队中，等前面的书蒸馏完自动开始...`);
      return;
    }
    void launchDistill(workId, retryFailed);
  };

  // ------------------------------------------------------------------
  // 作品 / Skill 删除
  // ------------------------------------------------------------------

  const runConfirm = async () => {
    if (!confirmState) return;
    setConfirmBusy(true);
    try {
      await confirmState.onConfirm();
      setConfirmState(null);
    } catch (e) {
      showError(errorMessage(e, "操作失败"));
    } finally {
      setConfirmBusy(false);
    }
  };

  const requestDeleteWork = (w: DistillWork) => {
    setConfirmState({
      title: "删除作品",
      description: `确定删除《${w.title}》吗？其全部片段、蒸馏轮次与生成的 Skill 都会被删除，不可恢复。`,
      actionLabel: "删除",
      onConfirm: async () => {
        await fetchJson(`/api/distillation/works/${w.id}`, { method: "DELETE" });
        showSuccess("作品已删除");
        // 清理该书的本地任务（蒸馏中 / 排队中）
        const job = jobsRef.current[w.id];
        if (job) {
          if (job.status === "queued") {
            // 前端本地排队：只移出队列即可
            pendingQueueRef.current = pendingQueueRef.current.filter((x) => x !== w.id);
          } else {
            job.controller.abort();
            void fetchJson(`/api/distillation/works/${w.id}/cancel`, { method: "POST" }).catch(() => {});
          }
          removeJob(w.id);
        }
        if (selectedWorkRef.current === w.id) {
          setSelectedWorkId(null);
          setChunks([]);
          setWorkSkills([]);
          setProgress(null);
        }
        await load();
      },
    });
  };

  const requestDeleteSkill = (s: DistillSkill) => {
    setConfirmState({
      title: "删除 Skill",
      description: `确定删除「${s.name}」吗？Skills 系统中对应的文件也会被移除，不可恢复。`,
      actionLabel: "删除",
      onConfirm: async () => {
        await fetchJson(`/api/distillation/skills/${s.id}`, { method: "DELETE" });
        showSuccess("Skill 已删除");
        await load();
        if (selectedWorkRef.current != null) await loadWorkDetail(selectedWorkRef.current);
      },
    });
  };

  const requestDeleteFusion = (f: FusionPlan) => {
    setConfirmState({
      title: "删除融合方案",
      description: `确定删除「${f.name}」吗？其产物 Skill 文件也会被移除，不可恢复。`,
      actionLabel: "删除",
      onConfirm: async () => {
        await fetchJson(`/api/distillation/fusions/${f.id}`, { method: "DELETE" });
        showSuccess("融合方案已删除");
        await load();
      },
    });
  };

  // ------------------------------------------------------------------
  // Skill 编辑 / 启停
  // ------------------------------------------------------------------

  const openEditSkill = (s: DistillSkill) => {
    setEditingSkill(s);
    setEditForm({ name: s.name, description: s.description, content: s.content });
    setEditError(null);
  };

  const handleSaveSkill = async () => {
    if (!editingSkill) return;
    const name = editForm.name.trim();
    if (!SKILL_NAME_PATTERN.test(name)) {
      setEditError("名称仅允许字母、数字、下划线和横线");
      return;
    }
    setSavingSkill(true);
    try {
      await fetchJson(`/api/distillation/skills/${editingSkill.id}`, {
        method: "PUT",
        body: JSON.stringify({ name, description: editForm.description, content: editForm.content }),
      });
      showSuccess("Skill 已更新");
      setEditingSkill(null);
      await load();
      if (selectedWorkRef.current != null) await loadWorkDetail(selectedWorkRef.current);
    } catch (e) {
      setEditError(errorMessage(e, "保存失败"));
    } finally {
      setSavingSkill(false);
    }
  };

  const handleToggleSkillStatus = async (s: DistillSkill, active: boolean) => {
    const status = active ? "active" : "archived";
    const apply = (list: DistillSkill[]) => list.map((it) => (it.id === s.id ? { ...it, status } : it));
    setWorkSkills(apply);
    setAllSkills(apply);
    try {
      await fetchJson(`/api/distillation/skills/${s.id}`, {
        method: "PUT",
        body: JSON.stringify({ status }),
      });
      showSuccess(active ? "Skill 已激活" : "Skill 已归档");
    } catch (e) {
      const rollback = (list: DistillSkill[]) => list.map((it) => (it.id === s.id ? { ...it, status: s.status } : it));
      setWorkSkills(rollback);
      setAllSkills(rollback);
      showError(errorMessage(e, "状态切换失败"));
    }
  };

  // ------------------------------------------------------------------
  // 技能融合
  // ------------------------------------------------------------------

  const fusionCount = Object.keys(fusionSelected).length;
  /** 当前作品里已勾选加入融合的 Skill 数 */
  const selectedInBook = workSkills.filter((s) => s.id in fusionSelected).length;

  const toggleFusionSkill = (id: number) => {
    setFusionSelected((prev) => {
      const next = { ...prev };
      if (id in next) delete next[id];
      else next[id] = 1;
      return next;
    });
  };

  const setFusionWeight = (id: number, raw: string) => {
    const v = parseFloat(raw);
    setFusionSelected((prev) => ({ ...prev, [id]: Number.isNaN(v) || v < 0 ? 0 : v }));
  };

  /** 「全选」快捷选择：选中所有 Skill（任意数量），等权重融合 */
  const handleNineInOne = () => {
    const all: Record<number, number> = {};
    for (const s of allSkills) all[s.id] = 1;
    setFusionSelected(all);
    if (!fusionName.trim()) setFusionName(`Skill融合（${allSkills.length} 个 Skill）`);
  };

  const handleFuse = async () => {
    const selectedKeys = Object.keys(fusionSelected);
    if (!fusionName.trim()) {
      showError("请输入融合方案名称");
      return;
    }
    if (selectedKeys.length < 2) {
      showError("请至少选择 2 个 Skill 进行融合");
      return;
    }

    // 分离 DB skill (id > 0) 和拆书 skill (id = -1, 用 name 标识)
    const dbIds: number[] = [];
    const fileNames: string[] = [];
    const weights: number[] = [];
    for (const key of selectedKeys) {
      const id = Number(key);
      const weight = fusionSelected[id] ?? 1;
      if (id > 0) {
        dbIds.push(id);
        weights.push(weight);
      } else {
        // id = -1 的拆书 skill，从 allSkills 中找到 name
        const fileSkill = allSkills.find((s) => s.id === id);
        if (fileSkill?.name) {
          fileNames.push(fileSkill.name);
          weights.push(weight);
        }
      }
    }

    setFusing(true);
    setFusionStage("准备中...");
    setFusionBatch(null);
    try {
      // SSE 流式：实时展示 AI 提炼批次进度，最后收到 fuse_done 得到融合结果
      const res = await fetch("/api/distillation/fuse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: fusionName.trim(),
          description: fusionDesc.trim(),
          skill_ids: dbIds,
          skill_files: fileNames,
          weights,
          delete_originals: deleteOriginals,
          ...modelConfigFields(modelConfig),
        }),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        let msg = `请求失败（HTTP ${res.status}）`;
        try {
          const j = JSON.parse(text);
          if (j.detail) msg = String(j.detail);
        } catch {
          /* 非 JSON，忽略 */
        }
        throw new Error(msg);
      }
      if (!res.body) throw new Error("无法建立流式连接");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let doneFusion: { refined?: boolean; deleted_count?: number } | null = null;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          let evt: Record<string, unknown>;
          try {
            evt = JSON.parse(line.slice(6)) as Record<string, unknown>;
          } catch {
            continue; // ping 等无法解析的帧，忽略
          }
          switch (evt.type) {
            case "fuse_start":
              setFusionStage(`开始融合 ${evt.skill_count ?? "?"} 个 Skill`);
              break;
            case "fuse_batch_start":
              setFusionBatch({ batch: Number(evt.batch ?? 1), total: Number(evt.total ?? 1) });
              setFusionStage(`AI 提炼中（批次 ${evt.batch}/${evt.total}）`);
              break;
            case "fuse_batch_done":
              setFusionStage(`批次 ${evt.batch}/${evt.total} 提炼完成`);
              break;
            case "fuse_done":
              doneFusion = evt.fusion as { refined?: boolean; deleted_count?: number };
              break;
            case "error":
              throw new Error(String(evt.error ?? "融合失败"));
          }
        }
      }
      if (!doneFusion) throw new Error("融合未返回结果");
      const tip = doneFusion.refined
        ? "融合方案已创建：多个 Skill 已提炼为一份精炼总纲"
        : "融合方案已创建（模型不可用，已回退为拼接）";
      const deleted = doneFusion.deleted_count ?? 0;
      showSuccess(deleted > 0 ? `${tip}，已删除 ${deleted} 个原 Skill` : tip);
      setFusionSelected({});
      setFusionName("");
      setFusionDesc("");
      setDeleteOriginals(false);
      await load();
    } catch (e) {
      showError(errorMessage(e, "融合失败"));
    } finally {
      setFusing(false);
      setFusionStage("");
      setFusionBatch(null);
    }
  };

  /** 查看融合产物的 Skill 内容 */
  const handleViewFusion = async (f: FusionPlan) => {
    setViewFusionLoading(true);
    try {
      const data = await fetchJson<{
        name: string;
        description: string;
        tags: string[];
        distilled: boolean;
        content: string;
      }>(`/api/distillation/fusions/${f.id}/skill`);
      setViewFusion(data);
    } catch (e) {
      showError(errorMessage(e, "查看融合 Skill 失败"));
    } finally {
      setViewFusionLoading(false);
    }
  };

  // ------------------------------------------------------------------
  // 效果对比
  // ------------------------------------------------------------------

  const handleCompare = async () => {
    if (!comparePrompt.trim()) {
      showError("请输入对比用的写作 Prompt");
      return;
    }
    setComparing(true);
    setCompareResult(null);
    try {
      const body: Record<string, unknown> = { prompt: comparePrompt.trim() };
      if (compareSkillId) body.skill_id = Number(compareSkillId);
      const res = await fetchJson<{ baseline: string; with_skill: string | null }>(
        "/api/distillation/compare",
        { method: "POST", body: JSON.stringify(body) },
      );
      setCompareResult({ baseline: res.baseline, with_skill: res.with_skill });
      showSuccess("对比生成完成");
    } catch (e) {
      showError(errorMessage(e, "对比生成失败"));
    } finally {
      setComparing(false);
    }
  };

  // ------------------------------------------------------------------
  // 角色蒸馏
  // ------------------------------------------------------------------

  const handleCharDistill = async () => {
    if (selectedWorkId == null || !charDistillName.trim()) return;
    setCharDistilling(true);
    setCharDistillLog([]);
    try {
      const res = await fetch("/api/distillation/distill-character", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          work_id: selectedWorkId,
          character_name: charDistillName.trim(),
          ...modelConfigFields(modelConfig),
        }),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        let msg = `请求失败（HTTP ${res.status}）`;
        try { const j = JSON.parse(text); if (j.detail) msg = String(j.detail); } catch {}
        throw new Error(msg);
      }
      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let currentEvent = "";  // 必须在 while 外声明，否则跨 chunk 事件丢失
      while (reader) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (line.startsWith("event:")) {
            currentEvent = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            const dataStr = line.slice(5).trim();
            if (!dataStr) continue;
            let data: any;
            try { data = JSON.parse(dataStr); } catch { continue; }
            if (currentEvent === "character_distill_start") {
              setCharDistillLog((prev) => [...prev, `开始蒸馏角色「${data.character}」，样本 ${data.sample_chars} 字`]);
            } else if (currentEvent === "character_distill_done") {
              setCharDistillLog((prev) => [...prev, `✓ 角色蒸馏完成，已生成 Skill：${data.skill_name}`]);
              showSuccess(`角色「${charDistillName.trim()}」蒸馏完成`);
              setCharDistillOpen(false);
              setCharDistillName("");
              await load();
            } else if (currentEvent === "character_distill_failed") {
              setCharDistillLog((prev) => [...prev, `✗ 蒸馏失败：${data.error}`]);
              showError(`角色蒸馏失败：${data.error}`);
            } else if (currentEvent === "error") {
              setCharDistillLog((prev) => [...prev, `✗ ${data.error}`]);
              showError(data.error);
            }
          }
        }
      }
    } catch (e) {
      showError(e instanceof Error ? e.message : "角色蒸馏失败");
    } finally {
      setCharDistilling(false);
    }
  };

  // ------------------------------------------------------------------
  // 盲测评估
  // ------------------------------------------------------------------

  const handleBlindEval = async () => {
    if (blindEvalSkillId == null || !blindEvalPrompt.trim()) return;
    setBlindEvaluating(true);
    setBlindEvalResult(null);
    try {
      const res = await fetchJson<{
        baseline: string;
        with_style: string;
        judgment: any;
        skill: any;
      }>("/api/distillation/blind-eval", {
        method: "POST",
        body: JSON.stringify({
          skill_id: blindEvalSkillId,
          prompt: blindEvalPrompt.trim(),
        }),
      });
      setBlindEvalResult(res);
      const winner = res.judgment?.winner_label;
      if (winner === "with_style") {
        showSuccess(`盲测结果：Skill 版胜出（置信度 ${Math.round((res.judgment.confidence || 0) * 100)}%）`);
      } else if (winner === "baseline") {
        showError("盲测结果：无 Skill 版胜出，蒸馏效果不显著");
      } else {
        showSuccess("盲测结果：平局");
      }
    } catch (e) {
      showError(errorMessage(e, "盲测评估失败"));
    } finally {
      setBlindEvaluating(false);
    }
  };

  const openBlindEval = (skillId: number) => {
    setBlindEvalSkillId(skillId);
    setBlindEvalPrompt("");
    setBlindEvalResult(null);
    setBlindEvalOpen(true);
  };

  const header = (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-3">
        <div className="rounded-lg border border-border bg-primary-muted p-2 text-primary">
          <FlaskConical className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-lg font-semibold">蒸馏技能</h2>
          <p className="text-sm text-muted">从优质作品中蒸馏写作技能，去除 AI 味</p>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={() => void load()} disabled={refreshing}>
          <RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
          刷新
        </Button>
        <Button variant="primary" size="sm" onClick={() => setImportOpen(true)}>
          <Plus className="h-4 w-4" />
          导入作品
        </Button>
      </div>
    </div>
  );

  const distillingCount = works.filter((w) => w.status === "distilling").length;
  const statCards = (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      <Card className="p-4">
        <div className="text-xs text-muted">已导入作品</div>
        <div className="mt-1 text-2xl font-bold tabular-nums">{works.length}</div>
      </Card>
      <Card className="p-4">
        <div className="text-xs text-muted">蒸馏 Skill</div>
        <div className="mt-1 text-2xl font-bold tabular-nums text-primary">{allSkills.length}</div>
      </Card>
      <Card className="p-4">
        <div className="text-xs text-muted">融合方案</div>
        <div className="mt-1 text-2xl font-bold tabular-nums text-success">{fusions.length}</div>
      </Card>
      <Card className="p-4">
        <div className="text-xs text-muted">蒸馏中</div>
        <div className="mt-1 text-2xl font-bold tabular-nums text-warning">{distillingCount}</div>
      </Card>
    </div>
  );

  // 左侧：作品列表
  const worksPanel = (
    <Card className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold">已导入作品</h3>
        <Badge variant="primary">{works.length}</Badge>
      </div>
      {works.length === 0 ? (
        <div className="flex flex-col items-center py-8 text-center">
          <FileText className="mb-2 h-8 w-8 text-muted" />
          <p className="text-xs text-muted">暂无作品，点击右上角「导入作品」开始</p>
        </div>
      ) : (
        <div className="space-y-2">
          {works.map((w) => {
            const st = workStatusOf(w.status);
            const job = jobs[w.id];
            return (
              <div
                key={w.id}
                role="button"
                tabIndex={0}
                onClick={() => handleSelectWork(w.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") handleSelectWork(w.id);
                }}
                className={cn(
                  "w-full cursor-pointer rounded-lg border p-3 text-left transition-colors",
                  selectedWorkId === w.id
                    ? "border-primary bg-primary-muted"
                    : "border-border bg-surface hover:bg-surface-hover",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium">{w.title}</span>
                  <div className="flex shrink-0 items-center gap-1">
                    {job?.status === "queued" ? (
                      <Badge variant="warning">排队中</Badge>
                    ) : (
                      <Badge variant={st.variant}>{st.label}</Badge>
                    )}
                    {job ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 w-7 px-0 text-danger hover:bg-danger-muted"
                        aria-label={`停止蒸馏 ${w.title}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          void abortDistill(w.id);
                        }}
                      >
                        <Square className="h-3.5 w-3.5" />
                      </Button>
                    ) : (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 w-7 px-0"
                        aria-label={`开始蒸馏 ${w.title}`}
                        title={`开始蒸馏这本书（可多本同时蒸馏，最多 ${MAX_CONCURRENT_DISTILL} 本并发，其余排队）`}
                        disabled={w.chunk_count === 0 || distillDims.length === 0}
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleStartDistill(w.id);
                        }}
                      >
                        <Play className="h-3.5 w-3.5" />
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 w-7 px-0 text-muted hover:text-danger"
                      aria-label={`删除作品 ${w.title}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        requestDeleteWork(w);
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
                <p className="mt-1 text-xs text-muted tabular-nums">
                  {formatChars(w.total_chars)} · {w.chunk_count} 个片段 · {formatDate(w.created_at)}
                </p>
                {job && (
                  <div className="mt-2 space-y-1">
                    <Progress
                      value={
                        job.progress && job.progress.total > 0
                          ? Math.round((job.progress.done / job.progress.total) * 100)
                          : 0
                      }
                      className="h-1.5"
                    />
                    <div className="text-right text-xs text-muted tabular-nums">
                      {job.status === "queued"
                        ? `排队中（并发满 ${MAX_CONCURRENT_DISTILL} 本）...`
                        : job.progress
                          ? `${job.progress.done}/${job.progress.total} 轮`
                          : ""}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );

  // 右侧：作品详情（蒸馏进度 + Skill 列表）
  const overallPercent = (() => {
    if (selectedJob?.progress && selectedJob.progress.total > 0) {
      return Math.round((selectedJob.progress.done / selectedJob.progress.total) * 100);
    }
    if (progress && progress.total_rounds > 0) {
      return Math.round((progress.done_rounds / progress.total_rounds) * 100);
    }
    if (progress && progress.total_chunks > 0) {
      return Math.round((progress.done_chunks / progress.total_chunks) * 100);
    }
    return 0;
  })();

  const activeChunkEntry = Object.entries(selectedJob?.liveChunks ?? {}).find(
    ([, v]) => v.status === "distilling",
  );

  const detailPanel = (
    <Card className="flex min-h-[420px] flex-col p-5">
      {!selectedWork ? (
        <div className="flex flex-1 items-center justify-center text-sm text-muted">
          选择左侧作品查看蒸馏详情
        </div>
      ) : detailLoading ? (
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="mr-2 h-5 w-5 animate-spin text-muted" />
          <span className="text-sm text-muted">加载作品详情...</span>
        </div>
      ) : (
        <>
          {/* 作品头 + 蒸馏操作 */}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-base font-semibold">{selectedWork.title}</h3>
                <Badge variant={workStatusOf(selectedWork.status).variant}>
                  {workStatusOf(selectedWork.status).label}
                </Badge>
              </div>
              <p className="mt-1 text-xs text-muted tabular-nums">
                {formatChars(selectedWork.total_chars)} · {selectedWork.chunk_count} 个片段 · 已生成{" "}
                {workSkills.length} 个 Skill
              </p>
            </div>
            <div className="flex min-w-0 max-w-full flex-col items-end gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-end">
              {/* 蒸馏级数选择：1次=碎片；2次=浓缩提炼；3次=再浓缩 */}
              <div
                className="flex items-center gap-1 rounded-lg border border-border p-0.5"
                title="蒸馏级数：级数越多越精炼，耗时越长"
              >
                {[1, 2, 3].map((lv) => (
                  <button
                    key={lv}
                    type="button"
                    onClick={() => setDistillLevels(lv)}
                    disabled={!!selectedJob}
                    className={cn(
                      "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                      distillLevels === lv
                        ? "bg-primary text-primary-foreground"
                        : "text-muted hover:bg-surface-hover",
                    )}
                  >
                    {lv}次
                  </button>
                ))}
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setDimsDialogOpen(true)}
                disabled={!!selectedJob}
                title="选择要蒸馏的维度，默认分析全部"
              >
                <Layers className="h-4 w-4" />
                维度：{distillDims.length}/{TOTAL_ROUNDS}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setModelSettingsOpen(true)}
                disabled={!!selectedJob}
                title="蒸馏使用的模型，默认跟随全局配置（config.yaml）"
              >
                <Settings2 className="h-4 w-4" />
                模型：{modelConfigLabel(modelConfig, modelProviders)}
              </Button>
              {selectedJob ? (
                <Button variant="danger" size="sm" onClick={() => void abortDistill(selectedWork.id)}>
                  <Square className="h-4 w-4" />
                  {selectedJob.status === "queued" ? "取消排队" : "停止蒸馏"}
                </Button>
              ) : (
                <>
                  {selectedWork &&
                    (selectedWork.status === "done_with_errors" ||
                      selectedWork.status === "failed" ||
                      selectedWork.status === "distilling") && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => void handleStartDistill(selectedWork.id, true)}
                        disabled={chunks.length === 0}
                        title="只重跑失败的片段/轮次，不重复已成功的部分"
                      >
                        <RefreshCw className="h-4 w-4" />
                        补蒸馏（重试失败）
                      </Button>
                    )}
                  <Button variant="primary" size="sm" onClick={() => void handleStartDistill(selectedWork.id)} disabled={chunks.length === 0}>
                    <Play className="h-4 w-4" />
                    开始蒸馏
                  </Button>
                </>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={() => { setCharDistillOpen(true); setCharDistillLog([]); }}
                disabled={chunks.length === 0}
              >
                <User className="h-4 w-4" />
                角色蒸馏
              </Button>
            </div>
          </div>

          {/* 整体进度 */}
          <div className="mt-4 space-y-1.5">
            <div className="flex items-center justify-between text-xs">
              <span className="flex items-center gap-1.5 text-muted">
                <Layers className="h-3.5 w-3.5" />
                整体进度
                {selectedJob?.status === "queued" ? (
                  <span className="text-warning">· 排队中（同时最多 {MAX_CONCURRENT_DISTILL} 本，前面有任务在跑）</span>
                ) : (
                  selectedJob &&
                  activeChunkEntry && (
                    <span className="text-primary">
                      · 正在蒸馏片段 {Number(activeChunkEntry[0]) + 1}
                      {activeChunkEntry[1].currentRound > 0 &&
                        ` · 第 ${activeChunkEntry[1].currentRound} 轮${
                          activeChunkEntry[1].dimension ? `（${activeChunkEntry[1].dimension}）` : ""
                        }`}
                    </span>
                  )
                )}
              </span>
              <span className="tabular-nums text-muted">{overallPercent}%</span>
            </div>
            <Progress value={overallPercent} />
          </div>

          <Tabs key={selectedWork.id} defaultValue="progress" className="mt-4">
            <TabsList>
              <TabsTrigger value="progress">蒸馏进度</TabsTrigger>
              <TabsTrigger value="skills">生成 Skill（{workSkills.length}）</TabsTrigger>
            </TabsList>

            {/* 蒸馏进度：逐片段状态 + 轮次指示 + 实时日志 */}
            <TabsContent value="progress" className="space-y-3 pt-2">
              {chunks.length === 0 ? (
                <p className="py-8 text-center text-xs text-muted">该作品没有片段</p>
              ) : (
                <div className="space-y-2">
                  {chunks.map((c) => {
                    const live = selectedJob?.liveChunks?.[c.chunk_index];
                    const status = live?.status ?? c.status;
                    const st = chunkStatusOf(status);
                    const finishedRounds = Object.values(live?.rounds ?? {}).filter(
                      (s) => s === "done" || s === "failed",
                    ).length;
                    const roundPercent =
                      status === "done" ? 100 : Math.round((finishedRounds / distillDims.length) * 100);
                    const showRounds = status === "distilling" || Object.keys(live?.rounds ?? {}).length > 0;
                    return (
                      <div key={c.id} className="rounded-lg border border-border bg-surface px-3 py-2">
                        <div className="flex items-center justify-between gap-2 text-xs">
                          <div className="flex min-w-0 items-center gap-2">
                            <span className="font-medium">片段 {c.chunk_index + 1}</span>
                            <span className="text-muted tabular-nums">{formatChars(c.char_count)}</span>
                          </div>
                          <Badge variant={st.variant}>{st.label}</Badge>
                        </div>
                        {showRounds && (
                          <div className="mt-2 space-y-1.5">
                            <div className="flex items-center gap-2">
                              {distillDims.map((rn) => {
                                const rs = live?.rounds?.[rn];
                                const dim = DIMENSIONS.find((d) => d.id === rn);
                                return (
                                  <span
                                    key={rn}
                                    title={dim ? `${dim.name}（第 ${rn} 项）` : `第 ${rn} 项`}
                                    className={cn(
                                      "h-2.5 w-2.5 rounded-full",
                                      rs === "done" && "bg-success",
                                      rs === "running" && "animate-pulse bg-primary",
                                      rs === "failed" && "bg-danger",
                                      (!rs || rs === "pending") && "border border-border-strong bg-surface-hover",
                                    )}
                                  />
                                );
                              })}
                              {live?.currentRound ? (
                                <span className="text-xs text-muted">
                                  第 {live.currentRound} 轮{live.dimension ? ` · ${live.dimension}` : ""}
                                </span>
                              ) : null}
                            </div>
                            <Progress value={roundPercent} className="h-1.5" />
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
              {(selectedJob?.log.length ?? 0) > 0 && (
                <div
                  ref={logRef}
                  className="max-h-40 overflow-y-auto rounded-lg border border-border bg-background p-3 font-mono text-xs text-muted"
                >
                  {selectedJob?.log.map((line, i) => (
                    <div key={i}>{line}</div>
                  ))}
                </div>
              )}
            </TabsContent>

            {/* Skill 列表 */}
            <TabsContent value="skills" className="pt-2">
              {workSkills.length === 0 ? (
                <p className="py-8 text-center text-xs text-muted">
                  尚未生成 Skill，点击「开始蒸馏」从作品中提取写作技能
                </p>
              ) : (
                <div className="space-y-2">
                  {/* 顶部：选入融合提示 + 全选本书（可取消，不会反复点击累加） */}
                  <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surface-elevated px-3 py-2">
                    <span className="text-xs text-muted">勾选要融合的 Skill，选好后到下方「技能融合」点创建</span>
                    <span className="flex shrink-0 items-center gap-2">
                      <Badge variant={selectedInBook > 0 ? "primary" : "default"}>{selectedInBook}/{workSkills.length} 已选</Badge>
                      <Button variant="outline" size="sm" onClick={() => toggleSelectBook(workSkills)}>
                        <CheckSquare className="h-3.5 w-3.5 mr-1" />
                        {selectedInBook === workSkills.length && workSkills.length > 0 ? "取消全选" : "全选本书"}
                      </Button>
                    </span>
                  </div>
                  {workSkills.map((s) => {
                    const selected = s.id in fusionSelected;
                    return (
                    <div
                      key={s.id}
                      className={cn(
                        "rounded-lg border p-3 transition-colors",
                        selected ? "border-primary bg-primary-muted" : "border-border bg-surface",
                      )}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="font-mono text-sm font-medium">{s.name}</span>
                            {s.chunk_index < 0 ? (
                              <Badge variant="warning">浓缩 · 第 {s.round_num} 级</Badge>
                            ) : (
                              <>
                                <Badge variant="primary">片段 {s.chunk_index + 1}</Badge>
                                <Badge variant="default">维度 {s.round_num}</Badge>
                              </>
                            )}
                          </div>
                          <p className="mt-1 line-clamp-2 text-xs text-muted">{s.description || "（无描述）"}</p>
                          {s.tags.length > 0 && (
                            <div className="mt-1.5 flex flex-wrap gap-1">
                              {s.tags.map((t) => (
                                <Badge key={t} variant="default">
                                  {t}
                                </Badge>
                              ))}
                            </div>
                          )}
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          <Button
                            variant={selected ? "primary" : "outline"}
                            size="sm"
                            className="h-7 px-2 text-xs"
                            onClick={() => toggleFusionSkill(s.id)}
                            title={selected ? "取消选入融合" : "选入融合"}
                          >
                            {selected ? <Check className="h-3.5 w-3.5 mr-1" /> : <Square className="h-3.5 w-3.5 mr-1" />}
                            {selected ? "已选" : "选入融合"}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2 text-xs"
                            onClick={() => openBlindEval(s.id)}
                            title="盲测评估"
                          >
                            盲测
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 w-7 px-0"
                            aria-label={`编辑 Skill ${s.name}`}
                            onClick={() => openEditSkill(s)}
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 w-7 px-0 text-muted hover:text-danger"
                            aria-label={`删除 Skill ${s.name}`}
                            onClick={() => requestDeleteSkill(s)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </div>
                      <details className="mt-2">
                        <summary className="cursor-pointer text-xs text-muted hover:text-foreground">
                          查看内容
                        </summary>
                        <pre className="mt-1.5 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-background p-3 text-xs text-muted">
                          {s.content || "（无内容）"}
                        </pre>
                      </details>
                      <div className="mt-2 flex items-center justify-between border-t border-border pt-2">
                        <span className="text-xs text-muted">{s.status === "active" ? "已激活" : "已归档"}</span>
                        <Switch
                          checked={s.status === "active"}
                          onCheckedChange={(v) => void handleToggleSkillStatus(s, v)}
                          aria-label={`${s.status === "active" ? "归档" : "激活"} Skill ${s.name}`}
                        />
                      </div>
                    </div>
                    );
                  })}
                </div>
              )}
            </TabsContent>
          </Tabs>
        </>
      )}
    </Card>
  );

  // 技能融合
  /** Skill 按书分组（书=目录）：融合时可按书一键选择，不混入其他书的 Skill */
  const skillGroups = useMemo(() => {
    const map = new Map<string, DistillSkill[]>();
    for (const s of allSkills) {
      const key = s.work_id > 0 ? `work:${s.work_id}` : "book-to-skill";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(s);
    }
    return Array.from(map.entries())
      .map(([key, skills]) => ({
        key,
        label: key === "book-to-skill" ? "拆书导入" : `《${skills[0].work_title}》`,
        skills,
      }))
      .sort((a, b) => (a.key === "book-to-skill" ? 1 : b.key === "book-to-skill" ? -1 : a.label.localeCompare(b.label, "zh")));
  }, [allSkills]);

  /**
   * 全选 / 取消全选某本书（分组）的全部 Skill：
   * - 组内已全部选中 → 清除本书（避免像旧版那样反复点击无脑累加）
   * - 否则 → 加入本书全部（不影响其他书的已选）
   */
  const toggleSelectBook = useCallback((skills: DistillSkill[]) => {
    setFusionSelected((prev) => {
      const ids = new Set(skills.map((s) => s.id));
      const allSelected = skills.every((s) => s.id in prev);
      const next = { ...prev };
      if (allSelected) {
        for (const id of ids) delete next[id];
      } else {
        for (const id of ids) next[id] = 1;
      }
      return next;
    });
  }, []);

  /** 融合面板滚动锚点 */
  const fusionRef = useRef<HTMLDivElement | null>(null);

  const fusionPanel = (
    <Card ref={fusionRef} className="scroll-mt-4 space-y-3 p-4">
      <div className="flex items-center gap-2">
        <div className="rounded-lg border border-border bg-primary-muted p-1.5 text-primary">
          <GitMerge className="h-4 w-4" />
        </div>
        <div>
          <h3 className="text-sm font-semibold">技能融合</h3>
          <p className="text-xs text-muted">选择多个 Skill 按权重融合，支持蒸馏+拆书混合融合</p>
        </div>
      </div>
      {allSkills.length === 0 ? (
        <p className="py-4 text-center text-xs text-muted">暂无可融合 Skill，请先导入作品并蒸馏，或在 Skills 页拆书导入</p>
      ) : (
        <>
          <div className="max-h-56 space-y-2 overflow-y-auto pr-1">
            {skillGroups.map((g) => {
              const groupSelected = g.skills.filter((s) => s.id in fusionSelected).length;
              return (
                <div key={g.key} className="overflow-hidden rounded-lg border border-border">
                  {/* 书分组头 + 全选本书 */}
                  <div className="flex items-center justify-between gap-2 bg-surface-elevated px-2.5 py-1.5">
                    <span className="truncate text-xs font-medium text-muted">{g.label}</span>
                    <span className="flex shrink-0 items-center gap-1.5">
                      <Badge variant="default">{groupSelected}/{g.skills.length}</Badge>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 px-1.5 text-xs"
                        onClick={() => toggleSelectBook(g.skills)}
                        title={`全选/取消全选${g.label}的全部 ${g.skills.length} 个 Skill`}
                      >
                        {groupSelected === g.skills.length ? "取消全选" : "全选本书"}
                      </Button>
                    </span>
                  </div>
                  <div className="space-y-1.5 p-1.5">
                    {g.skills.map((s) => {
                      const selected = s.id in fusionSelected;
                      const isBookSkill = s.source === "book-to-skill";
                      return (
                        <div
                          key={`${s.id}-${s.name}`}
                          className={cn(
                            "flex items-center gap-2 rounded-lg border px-3 py-2 text-xs",
                            selected ? "border-primary bg-primary-muted" : "border-border bg-surface",
                          )}
                        >
                          <button
                            type="button"
                            onClick={() => toggleFusionSkill(s.id)}
                            className="flex min-w-0 flex-1 items-center gap-2 text-left"
                            aria-pressed={selected}
                          >
                            <span
                              className={cn(
                                "flex h-4 w-4 shrink-0 items-center justify-center rounded border",
                                selected ? "border-primary bg-primary text-primary-foreground" : "border-border-strong",
                              )}
                            >
                              {selected && <Check className="h-3 w-3" />}
                            </span>
                            <span className="truncate font-mono">{s.name}</span>
                            {isBookSkill ? (
                              <Badge variant="primary" className="shrink-0">拆书</Badge>
                            ) : (
                              <span className="shrink-0 text-muted">
                                {skillSourceLabel(s.chunk_index, s.round_num)}
                              </span>
                            )}
                          </button>
                          {selected && (
                            <span className="flex shrink-0 items-center gap-1">
                              <span className="text-muted">权重</span>
                              <Input
                                type="number"
                                min={0}
                                step={0.5}
                                className="h-7 w-16 px-2 text-xs"
                                value={fusionSelected[s.id]}
                                onChange={(e) => setFusionWeight(s.id, e.target.value)}
                                aria-label={`Skill ${s.name} 的融合权重`}
                              />
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <Input
              placeholder="融合方案名称"
              value={fusionName}
              onChange={(e) => setFusionName(e.target.value)}
              aria-label="融合方案名称"
            />
            <Input
              placeholder="描述（可选）"
              value={fusionDesc}
              onChange={(e) => setFusionDesc(e.target.value)}
              aria-label="融合方案描述"
            />
          </div>
          <label className="flex items-center justify-between gap-2 rounded-lg border border-border px-3 py-2 text-xs">
            <span className="flex items-center gap-1.5 text-muted">
              <Trash2 className="h-3.5 w-3.5" />
              融合成功后删除原 Skill
            </span>
            <Switch checked={deleteOriginals} onCheckedChange={setDeleteOriginals} />
          </label>
          <div className="flex items-center gap-2">
            <Button variant="primary" size="sm" onClick={() => void handleFuse()} disabled={fusing}>
              {fusing ? <Loader2 className="h-4 w-4 animate-spin" /> : <GitMerge className="h-4 w-4" />}
              {fusing ? "提炼融合中..." : `创建融合方案${fusionCount > 0 ? `（已选 ${fusionCount}）` : ""}`}
            </Button>
            <Button variant="outline" size="sm" onClick={handleNineInOne} title="跨书选择所有 Skill（含拆书导入），多书混合融合">
              全选全部（跨书）
            </Button>
          </div>
          {fusing && (
            <div className="flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-xs text-muted">
              <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-primary" />
              <span className="min-w-0 truncate">{fusionStage || "融合中..."}</span>
              {fusionBatch && (
                <span className="shrink-0 font-mono">
                  {fusionBatch.batch}/{fusionBatch.total}
                </span>
              )}
            </div>
          )}
        </>
      )}
      {fusions.length > 0 && (
        <div className="border-t border-border pt-3">
          <div className="mb-1.5 text-xs font-medium text-muted">已有融合方案</div>
          <div className="space-y-1.5">
            {fusions.map((f) => (
              <div
                key={f.id}
                className="flex items-center justify-between gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-xs"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="font-medium">{f.name}</span>
                    {f.status === "done" ? (
                      <Badge variant="success">已完成</Badge>
                    ) : (
                      <Badge variant="warning">融合中</Badge>
                    )}
                  </div>
                  {f.description && <div className="truncate text-muted">{f.description}</div>}
                  {f.skill_file && <div className="truncate font-mono text-muted">{f.skill_file}</div>}
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <Badge variant="primary">{f.skill_ids.length} 合一</Badge>
                  <Button variant="ghost" size="sm" onClick={() => void handleViewFusion(f)} disabled={f.status !== "done"}>
                    查看
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-danger hover:bg-danger-muted"
                    onClick={() => requestDeleteFusion(f)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );

  // 效果对比
  const comparePanel = (
    <Card className="space-y-3 p-4">
      <div className="flex items-center gap-2">
        <div className="rounded-lg border border-border bg-primary-muted p-1.5 text-primary">
          <Beaker className="h-4 w-4" />
        </div>
        <div>
          <h3 className="text-sm font-semibold">效果对比</h3>
          <p className="text-xs text-muted">同一 Prompt：无章纲直出 vs 加载蒸馏 Skill 直出</p>
        </div>
      </div>
      <Textarea
        placeholder="输入写作 Prompt，例如：写一段主角在雨夜赶路的小说正文..."
        value={comparePrompt}
        onChange={(e) => setComparePrompt(e.target.value)}
        rows={3}
        aria-label="对比写作 Prompt"
      />
      <div className="flex items-center gap-2">
        <Select
          value={compareSkillId}
          onChange={(e) => setCompareSkillId(e.target.value)}
          className="flex-1"
          aria-label="选择蒸馏 Skill"
        >
          <option value="">不使用 Skill（仅生成基线）</option>
          {allSkills.map((s) => (
            <option key={s.id} value={s.id}>
              《{s.work_title}》{skillSourceLabel(s.chunk_index, s.round_num)} — {s.name}
            </option>
          ))}
        </Select>
        <Button variant="primary" size="sm" onClick={() => void handleCompare()} disabled={comparing}>
          {comparing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Beaker className="h-4 w-4" />}
          开始对比
        </Button>
      </div>
      {comparing && (
        <p className="text-xs text-muted">正在生成对比结果，LLM 调用可能需要几分钟，请耐心等待...</p>
      )}
      {compareResult && (
        <div className="grid gap-3 md:grid-cols-2">
          <div>
            <div className="mb-1 text-xs font-medium text-muted">无章纲直出（基线）</div>
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-background p-3 text-xs">
              {compareResult.baseline}
            </pre>
          </div>
          <div>
            <div className="mb-1 flex items-center gap-1 text-xs font-medium text-primary">
              <Sparkles className="h-3.5 w-3.5" />
              加载蒸馏 Skill 直出
            </div>
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg border border-primary/20 bg-primary-muted/40 p-3 text-xs">
              {compareResult.with_skill ?? "（未选择 Skill，仅生成基线）"}
            </pre>
          </div>
        </div>
      )}
    </Card>
  );

  let body: React.ReactNode;
  if (loading) {
    body = (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-muted" />
        <span className="text-sm text-muted">正在加载蒸馏数据...</span>
      </div>
    );
  } else if (error) {
    body = (
      <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-surface px-6 py-16 text-center">
        <FlaskConical className="mb-3 h-10 w-10 text-muted" />
        <h3 className="text-base font-semibold">蒸馏引擎连接失败</h3>
        <p className="mt-1 max-w-md text-sm text-muted">{error}</p>
        <Button variant="outline" size="sm" className="mt-4" onClick={() => void load(true)}>
          <RefreshCw className="h-4 w-4" />
          重试
        </Button>
      </div>
    );
  } else {
    body = (
      <>
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="lg:col-span-1">{worksPanel}</div>
          <div className="lg:col-span-2">{detailPanel}</div>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          {fusionPanel}
          {comparePanel}
        </div>
      </>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-6 p-6">
        {header}
        {statCards}
        {body}
      </div>

      {/* 导入作品对话框 */}
      <Dialog open={importOpen} onOpenChange={setImportOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>导入作品</DialogTitle>
          </DialogHeader>
          <div className="mt-4 space-y-3">
            {/* 模式切换 */}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setImportMode("paste")}
                className={cn("rounded-lg px-3 py-1.5 text-sm transition-colors", importMode === "paste" ? "bg-primary text-primary-foreground" : "bg-secondary text-muted hover:text-foreground")}
              >
                粘贴文本
              </button>
              <button
                type="button"
                onClick={() => setImportMode("upload")}
                className={cn("rounded-lg px-3 py-1.5 text-sm transition-colors", importMode === "upload" ? "bg-primary text-primary-foreground" : "bg-secondary text-muted hover:text-foreground")}
              >
                上传文件（PDF/EPUB/DOCX/TXT）
              </button>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="import-title">作品标题{importMode === "upload" ? "（可选，默认取文件名）" : ""}</Label>
              <Input
                id="import-title"
                placeholder="例如：《斗破苍穹》精选章节"
                value={importTitle}
                onChange={(e) => setImportTitle(e.target.value)}
              />
            </div>

            {importMode === "paste" ? (
              <div className="space-y-1.5">
                <Label htmlFor="import-content">作品内容（粘贴全文，自动按 ≤10 万字拆分片段）</Label>
                <Textarea
                  id="import-content"
                  className="min-h-[240px] font-mono text-xs"
                  placeholder="在此粘贴作品全文..."
                  value={importContent}
                  onChange={(e) => setImportContent(e.target.value)}
                />
                <div className="text-right text-xs text-muted tabular-nums">{formatChars(importContent.length)}</div>
              </div>
            ) : (
              <div className="space-y-1.5">
                <Label>选择文件</Label>
                <label className="flex cursor-pointer items-center justify-center rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm text-muted hover:border-primary hover:text-primary transition-colors">
                  <div>
                    <Upload className="mx-auto mb-2 h-6 w-6" />
                    {importFile ? importFile.name : "点击选择 PDF / EPUB / DOCX / TXT 文件"}
                    <input
                      type="file"
                      className="hidden"
                      accept=".pdf,.epub,.docx,.txt,.md"
                      onChange={(e) => setImportFile(e.target.files?.[0] ?? null)}
                    />
                  </div>
                </label>
                <p className="text-xs text-muted">上传后自动提取文本并按章节拆分片段</p>
              </div>
            )}

            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => setImportOpen(false)} disabled={importing}>
                取消
              </Button>
              <Button variant="primary" size="sm" onClick={() => void handleImport()} disabled={importing}>
                {importing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                导入并拆分
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Skill 编辑对话框 */}
      <Dialog open={editingSkill != null} onOpenChange={(open) => !open && setEditingSkill(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>编辑 Skill</DialogTitle>
          </DialogHeader>
          <div className="mt-4 space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="skill-name">名称（仅字母、数字、下划线、横线）</Label>
              <Input
                id="skill-name"
                className="font-mono"
                value={editForm.name}
                onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="skill-desc">描述</Label>
              <Input
                id="skill-desc"
                value={editForm.description}
                onChange={(e) => setEditForm((f) => ({ ...f, description: e.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="skill-content">内容</Label>
              <Textarea
                id="skill-content"
                className="min-h-[240px] font-mono text-xs"
                value={editForm.content}
                onChange={(e) => setEditForm((f) => ({ ...f, content: e.target.value }))}
              />
            </div>
            {editError && <p className="text-xs text-danger">{editError}</p>}
            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => setEditingSkill(null)} disabled={savingSkill}>
                取消
              </Button>
              <Button variant="primary" size="sm" onClick={() => void handleSaveSkill()} disabled={savingSkill}>
                {savingSkill && <Loader2 className="h-4 w-4 animate-spin" />}
                保存
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* 通用删除确认对话框 */}
      <Dialog
        open={confirmState != null}
        onOpenChange={(open) => {
          if (!open && !confirmBusy) setConfirmState(null);
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{confirmState?.title}</DialogTitle>
          </DialogHeader>
          <p className="mt-3 text-sm text-muted">{confirmState?.description}</p>
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={() => setConfirmState(null)} disabled={confirmBusy}>
              取消
            </Button>
            <Button variant="danger" size="sm" onClick={() => void runConfirm()} disabled={confirmBusy}>
              {confirmBusy && <Loader2 className="h-4 w-4 animate-spin" />}
              {confirmState?.actionLabel}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* 蒸馏维度选择对话框 */}
      <Dialog open={dimsDialogOpen} onOpenChange={setDimsDialogOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>蒸馏维度选择</DialogTitle>
          </DialogHeader>
          <div className="mt-3 space-y-3">
            <p className="text-sm text-muted">
              勾选要从作品中提取的写作维度。维度越多越全面，耗时与花费越高。已选{" "}
              {distillDims.length}/{TOTAL_ROUNDS} 项。
            </p>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={() => setDistillDims([...ALL_DIM_IDS])}>
                全选
              </Button>
              <Button variant="outline" size="sm" onClick={() => setDistillDims([])}>
                清空
              </Button>
            </div>
            <div className="max-h-[50vh] space-y-1.5 overflow-y-auto rounded-lg border border-border p-3">
              {DIMENSIONS.map((d) => {
                const checked = distillDims.includes(d.id);
                return (
                  <label
                    key={d.id}
                    className={cn(
                      "flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2 transition-colors",
                      checked ? "border-primary bg-primary-muted" : "border-border bg-surface hover:bg-surface-hover",
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() =>
                        setDistillDims((prev) =>
                          prev.includes(d.id) ? prev.filter((x) => x !== d.id) : [...prev, d.id],
                        )
                      }
                      className="mt-0.5 h-4 w-4 accent-primary"
                    />
                    <span className="min-w-0">
                      <span className="flex items-center gap-1.5 text-sm font-medium">
                        {d.name}
                        <span className="text-xs text-muted">（第 {d.id} 项）</span>
                      </span>
                      <span className="block text-xs text-muted">{d.points}</span>
                    </span>
                  </label>
                );
              })}
            </div>
            <div className="flex justify-end">
              <Button
                variant="primary"
                size="sm"
                onClick={() => setDimsDialogOpen(false)}
                disabled={distillDims.length === 0}
              >
                完成
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* 融合产物查看对话框 */}
      <Dialog open={viewFusion !== null} onOpenChange={(open) => !open && setViewFusion(null)}>
        <DialogContent className="max-h-[85vh] max-w-3xl overflow-hidden">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <span className="truncate">{viewFusion?.name}</span>
              {viewFusion?.distilled && <Badge variant="primary">AI提炼</Badge>}
              {!viewFusion?.distilled && viewFusion && <Badge variant="warning">拼接回退</Badge>}
            </DialogTitle>
          </DialogHeader>
          <div className="max-h-[65vh] overflow-y-auto pr-1">
            {viewFusionLoading ? (
              <div className="flex items-center gap-2 py-4 text-xs text-muted">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                加载融合 Skill 内容...
              </div>
            ) : (
              <Markdown content={viewFusion?.content ?? ""} />
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* 蒸馏模型设置对话框 */}
      <Dialog open={modelSettingsOpen} onOpenChange={setModelSettingsOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>蒸馏模型设置</DialogTitle>
          </DialogHeader>
          <div className="mt-3 space-y-4">
            <p className="text-sm text-muted">
              选择整书 / 角色蒸馏使用的模型。默认跟随 config.yaml 中 auditor 的配置，
              也可临时指定其他供应商的模型。
            </p>

            {/* 模式选择 */}
            <div className="flex gap-2">
              {(
                [
                  { key: "default", label: "跟随全局" },
                  { key: "provider", label: "供应商模型" },
                  { key: "custom", label: "自定义" },
                ] as const
              ).map((m) => (
                <button
                  key={m.key}
                  type="button"
                  onClick={() => setModelConfig((c) => ({ ...c, mode: m.key }))}
                  className={cn(
                    "rounded-lg px-3 py-1.5 text-sm transition-colors",
                    modelConfig.mode === m.key
                      ? "bg-primary text-primary-foreground"
                      : "bg-secondary text-muted hover:text-foreground",
                  )}
                >
                  {m.label}
                </button>
              ))}
            </div>

            {/* 供应商模型模式 */}
            {modelConfig.mode === "provider" && (
              <div className="space-y-3">
                <div className="space-y-1.5">
                  <Label htmlFor="distill-provider">供应商（来自「模型管理」页）</Label>
                  <Select
                    id="distill-provider"
                    value={modelConfig.provider}
                    onChange={(e) => {
                      const pname = e.target.value;
                      const p = modelProviders.find((it) => it.name === pname);
                      setModelConfig((c) => ({
                        ...c,
                        provider: pname,
                        model: p?.models?.[0] ?? "",
                      }));
                    }}
                  >
                    <option value="">选择供应商...</option>
                    {modelProviders.map((p) => (
                      <option key={p.name} value={p.name}>
                        {p.name}
                        {p.is_default ? "（默认）" : ""}
                      </option>
                    ))}
                  </Select>
                  {modelProviders.length === 0 && (
                    <p className="text-xs text-muted">
                      暂无已保存的供应商，可到「模型管理」页添加，或改用「自定义」模式
                    </p>
                  )}
                </div>
                {modelConfig.provider && (
                  <div className="space-y-1.5">
                    <Label htmlFor="distill-model">模型</Label>
                    {(() => {
                      const p = modelProviders.find((it) => it.name === modelConfig.provider);
                      const models = p?.models ?? [];
                      return models.length > 0 ? (
                        <Select
                          id="distill-model"
                          value={modelConfig.model}
                          onChange={(e) => setModelConfig((c) => ({ ...c, model: e.target.value }))}
                        >
                          {models.map((m) => (
                            <option key={m} value={m}>
                              {m}
                            </option>
                          ))}
                        </Select>
                      ) : (
                        <Input
                          id="distill-model"
                          value={modelConfig.model}
                          onChange={(e) => setModelConfig((c) => ({ ...c, model: e.target.value }))}
                          placeholder="该供应商未登记模型，手动输入模型名"
                        />
                      );
                    })()}
                  </div>
                )}
              </div>
            )}

            {/* 自定义模式 */}
            {modelConfig.mode === "custom" && (
              <div className="space-y-3">
                <div className="space-y-1.5">
                  <Label htmlFor="distill-custom-url">接口地址（base_url）</Label>
                  <Input
                    id="distill-custom-url"
                    value={modelConfig.customBaseUrl}
                    onChange={(e) => setModelConfig((c) => ({ ...c, customBaseUrl: e.target.value }))}
                    placeholder="https://api.openai.com/v1"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="distill-custom-key">API Key（仅本次使用，不会保存）</Label>
                  <Input
                    id="distill-custom-key"
                    type="password"
                    value={modelConfig.customApiKey}
                    onChange={(e) => setModelConfig((c) => ({ ...c, customApiKey: e.target.value }))}
                    placeholder="sk-..."
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="distill-custom-model">模型名</Label>
                  <Input
                    id="distill-custom-model"
                    value={modelConfig.customModel}
                    onChange={(e) => setModelConfig((c) => ({ ...c, customModel: e.target.value }))}
                    placeholder="gpt-4o-mini"
                  />
                </div>
              </div>
            )}

            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  setModelConfig({
                    mode: "default",
                    provider: "",
                    model: "",
                    customBaseUrl: "",
                    customApiKey: "",
                    customModel: "",
                  })
                }
              >
                恢复默认
              </Button>
              <Button variant="primary" size="sm" onClick={() => setModelSettingsOpen(false)}>
                完成
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* 角色蒸馏对话框 */}
      <Dialog open={charDistillOpen} onOpenChange={setCharDistillOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>角色蒸馏 · 提取角色对话风格</DialogTitle>
          </DialogHeader>
          <div className="mt-3 space-y-3">
            <p className="text-sm text-muted">
              从作品《{selectedWork?.title}》中提取指定角色的说话风格，生成可注入的 Skill。
              适用于同人文创作，确保角色对话不 OOC。
            </p>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted">角色名</label>
              <Input
                value={charDistillName}
                onChange={(e) => setCharDistillName(e.target.value)}
                placeholder="输入要蒸馏的角色名（如：叶凡、林动）"
                disabled={charDistilling}
              />
            </div>
            {charDistillLog.length > 0 && (
              <div className="max-h-40 overflow-auto rounded-lg border border-border bg-background p-3 text-xs">
                {charDistillLog.map((line, i) => (
                  <div key={i} className={line.startsWith("✓") ? "text-success" : line.startsWith("✗") ? "text-danger" : ""}>
                    {line}
                  </div>
                ))}
              </div>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => setCharDistillOpen(false)} disabled={charDistilling}>
                取消
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={() => void handleCharDistill()}
                disabled={charDistilling || !charDistillName.trim()}
              >
                {charDistilling && <Loader2 className="h-4 w-4 animate-spin" />}
                开始蒸馏
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* 盲测评估对话框 */}
      <Dialog open={blindEvalOpen} onOpenChange={setBlindEvalOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>盲测评估 · 验证蒸馏效果</DialogTitle>
          </DialogHeader>
          <div className="mt-3 space-y-3">
            <p className="text-sm text-muted">
              用同一 Prompt 分别生成两段文字（有 Skill / 无 Skill），随机打乱后让 LLM 盲评哪段更接近原作风格。
            </p>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted">写作 Prompt</label>
              <Textarea
                value={blindEvalPrompt}
                onChange={(e) => setBlindEvalPrompt(e.target.value)}
                placeholder="输入测试用的写作 Prompt（如：写一段修仙者突破境界失败的场景，300字）"
                rows={3}
                disabled={blindEvaluating}
              />
            </div>
            {blindEvalResult && (
              <div className="space-y-3 rounded-lg border border-border bg-background p-4">
                {/* 评判结果 */}
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">评判结果：</span>
                    {blindEvalResult.judgment?.winner_label === "with_style" ? (
                      <Badge variant="primary">Skill 版胜出</Badge>
                    ) : blindEvalResult.judgment?.winner_label === "baseline" ? (
                      <Badge variant="default">无 Skill 版胜出</Badge>
                    ) : (
                      <Badge variant="default">平局</Badge>
                    )}
                    {blindEvalResult.judgment?.confidence != null && (
                      <span className="text-xs text-muted">
                        置信度 {Math.round(blindEvalResult.judgment.confidence * 100)}%
                      </span>
                    )}
                  </div>
                  {blindEvalResult.judgment?.reason && (
                    <p className="text-xs text-muted">{blindEvalResult.judgment.reason}</p>
                  )}
                </div>
                {/* 评分 */}
                {blindEvalResult.judgment?.score_a != null && (
                  <div className="flex gap-4 text-xs">
                    <span>片段A（{blindEvalResult.judgment.text_a_is === "with_style" ? "有Skill" : "无Skill"}）：{blindEvalResult.judgment.score_a}/10</span>
                    <span>片段B（{blindEvalResult.judgment.text_b_is === "with_style" ? "有Skill" : "无Skill"}）：{blindEvalResult.judgment.score_b}/10</span>
                  </div>
                )}
                {/* 两段文字对比 */}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <div className="mb-1 text-xs font-medium text-muted">
                      片段A（{blindEvalResult.judgment?.text_a_is === "with_style" ? "有Skill" : "无Skill"}）
                    </div>
                    <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-surface p-2 text-xs">
                      {blindEvalResult.judgment?.text_a_is === "with_style" ? blindEvalResult.with_style : blindEvalResult.baseline}
                    </pre>
                  </div>
                  <div>
                    <div className="mb-1 text-xs font-medium text-muted">
                      片段B（{blindEvalResult.judgment?.text_b_is === "with_style" ? "有Skill" : "无Skill"}）
                    </div>
                    <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-surface p-2 text-xs">
                      {blindEvalResult.judgment?.text_b_is === "with_style" ? blindEvalResult.with_style : blindEvalResult.baseline}
                    </pre>
                  </div>
                </div>
              </div>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => setBlindEvalOpen(false)} disabled={blindEvaluating}>
                关闭
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={() => void handleBlindEval()}
                disabled={blindEvaluating || !blindEvalPrompt.trim()}
              >
                {blindEvaluating && <Loader2 className="h-4 w-4 animate-spin" />}
                开始盲测
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
