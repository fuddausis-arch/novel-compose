import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  Loader2,
  MessagesSquare,
  Pause,
  Play,
  Plus,
  Send,
  Settings2,
  Sparkles,
  Square,
  Users,
  X,
  Zap,
} from "lucide-react";
import { AppLayout } from "@/components/layout/AppLayout";
import { useCurrentProject } from "@/hooks/useCurrentProject";
import { DFEmptyState } from "../components/dashboard/DFEmptyState";
import { DFSection } from "../components/dashboard/DFSection";
import { DFSeatCard } from "../components/roundtable/DFSeatCard";
import { DFDangerButton, DFIconButton, DFPrimaryButton, DFSecondaryButton } from "../components/admin/df-ui";
import {
  blankSeat,
  cloneSeats,
  getSeatColor,
  MAX_ROUNDS,
  MAX_SEATS,
  MIN_SEATS,
  presetSeat,
  ROUNDTABLE_TEMPLATES,
  SEAT_PRESETS,
  type RoundtableSeat,
  type RoundtableStrategy,
  type RoundtableTemplate,
  type SeatPresetKey,
} from "../components/roundtable/roundtablePresets";
import {
  openRoundtableStream,
  roundtableApi,
  type CreateRoundtablePayload,
  type RoundtableEvent,
  type RoundtableSeatInfo,
  type RoundtableStatus,
  type RoundtableStrategy as ApiStrategy,
  type RoundtableSeatInput,
} from "../api/roundtableApi";

/** 讨论消息流中的一条消息 */
interface ChatMessage {
  id: string;
  seat_id: string;
  speaker_name: string;
  content: string;
  round: number;
  kind: "statement" | "moderator_note" | "summary" | "conclusion" | "user_inject" | "round_divider";
  timestamp: string;
  /** 当前正在流式累积（rt_turn_start 后到 rt_turn_end 前） */
  isStreaming?: boolean;
  /** 被中断（终止讨论时未说完） */
  interrupted?: boolean;
}

/** 会议结论卡片数据 */
interface ConclusionCard {
  content: string;
  structured: Record<string, unknown> | null;
}

let _idSeq = 0;
function genId(prefix = "m"): string {
  _idSeq += 1;
  return `${prefix}-${Date.now().toString(36)}-${_idSeq}`;
}

/** 提示条：info=成功信息（绿）/warn=校验警告（琥珀）/error=错误（红） */
interface Notice {
  tone: "info" | "warn" | "error";
  title: string;
  text: string;
}

/**
 * 圆桌讨论页（项目内路由 /projects/:projectId/roundtable）。
 *
 * 已接入后端 /api/roundtable 全套 API + SSE 流：
 * - 创建会话 → 连接 SSE → 触发 start → 接收 rt_token 流式发言
 * - 暂停 / 恢复 / 终止 / 插话 / 新会议
 * - 流式逐 token 显示，发言者配色与配置区一致
 */
export default function DFRoundtablePage() {
  useCurrentProject();

  // ── 配置状态 ──────────────────────────────────────────
  const [topic, setTopic] = useState(ROUNDTABLE_TEMPLATES[0].topic);
  const [maxRounds, setMaxRounds] = useState(3);
  const [strategy, setStrategy] = useState<RoundtableStrategy>(ROUNDTABLE_TEMPLATES[0].strategy);
  const [seats, setSeats] = useState<RoundtableSeat[]>(() => cloneSeats(ROUNDTABLE_TEMPLATES[0].seats));

  // ── 运行时状态 ────────────────────────────────────────
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionStatus, setSessionStatus] = useState<RoundtableStatus | "idle">("idle");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [runtimeSeats, setRuntimeSeats] = useState<RoundtableSeatInfo[]>([]);
  const [conclusion, setConclusion] = useState<ConclusionCard | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busy, setBusy] = useState(false); // 创建/启动中
  const [injectText, setInjectText] = useState("");

  const esRef = useRef<EventSource | null>(null);
  const streamEndRef = useRef<HTMLDivElement | null>(null);

  // 配置是否可编辑：仅在 idle（未开始）时可改
  const configEditable = sessionStatus === "idle";
  // 讨论是否进行中（可暂停/恢复/插话）
  const isLive = sessionStatus === "discussing" || sessionStatus === "paused";
  // 席位 seat_id -> 配色下标（运行时席位可能动态增减）
  const seatColorIndex = useMemo(() => {
    const map: Record<string, number> = {};
    runtimeSeats.forEach((s, i) => {
      map[s.seat_id] = i;
    });
    return map;
  }, [runtimeSeats]);

  // ── 配置操作（保留原有逻辑）────────────────────────────
  const applyTemplate = (tpl: RoundtableTemplate) => {
    if (!configEditable) return;
    setTopic(tpl.topic);
    setStrategy(tpl.strategy);
    setSeats(cloneSeats(tpl.seats));
  };
  const updateSeat = (index: number, field: keyof RoundtableSeat, value: string | number | boolean) => {
    setSeats((prev) => prev.map((s, i) => (i === index ? { ...s, [field]: value } : s)));
  };
  const addSeat = () => {
    setSeats((prev) => (prev.length >= MAX_SEATS ? prev : [...prev, blankSeat()]));
  };
  const addPresetSeat = (key: SeatPresetKey) => {
    setSeats((prev) => (prev.length >= MAX_SEATS ? prev : [...prev, presetSeat(key)]));
  };
  const removeSeat = (index: number) => {
    setSeats((prev) => (prev.length <= MIN_SEATS ? prev : prev.filter((_, i) => i !== index)));
  };

  // ── SSE 事件处理 ─────────────────────────────────────
  const handleEvent = useCallback((event: RoundtableEvent) => {
    switch (event.type) {
      case "rt_started":
        setSessionStatus("discussing");
        setRuntimeSeats(event.seats);
        setNotice({ tone: "info", title: "讨论已开始", text: `共 ${event.seats.length} 个席位，将进行 ${event.max_rounds} 轮讨论（${event.strategy === "moderator_decides" ? "智能主持" : "固定轮询"}）。` });
        break;

      case "rt_turn_start": {
        // 新建一条流式消息，等待 rt_token 累积
        const colorName = event.seat_id;
        const msg: ChatMessage = {
          id: genId("turn"),
          seat_id: event.seat_id,
          speaker_name: event.is_moderator_thinking ? `${event.speaker_name}（思考）` : event.speaker_name,
          content: "",
          round: event.round,
          kind: event.is_moderator_thinking ? "moderator_note" : "statement",
          timestamp: new Date().toISOString(),
          isStreaming: true,
        };
        // 占位，避免 seatColorIndex 未命中时无色
        void colorName;
        setMessages((prev) => [...prev, msg]);
        break;
      }

      case "rt_token":
        // 追加到当前 seat 的流式消息
        setMessages((prev) =>
          prev.map((m) =>
            m.isStreaming && m.seat_id === event.seat_id
              ? { ...m, content: m.content + event.content }
              : m,
          ),
        );
        break;

      case "rt_turn_end":
        // 定型：用 full_content 覆盖（确保完整），取消 isStreaming
        setMessages((prev) =>
          prev.map((m) => {
            if (m.seat_id === event.seat_id && m.isStreaming) {
              return {
                ...m,
                content: event.full_content || m.content,
                isStreaming: false,
                interrupted: event.interrupted === true,
                speaker_name: event.speaker_name,
              };
            }
            return m;
          }),
        );
        break;

      case "rt_round_end":
        setMessages((prev) => [
          ...prev,
          {
            id: genId("round"),
            seat_id: "",
            speaker_name: "",
            content: `第 ${event.round} 轮结束`,
            round: event.round,
            kind: "round_divider",
            timestamp: new Date().toISOString(),
          },
        ]);
        break;

      case "roundtable_summary":
        setMessages((prev) => [
          ...prev,
          {
            id: genId("sum"),
            seat_id: "",
            speaker_name: event.source,
            content: event.content,
            round: event.round,
            kind: "summary",
            timestamp: new Date().toISOString(),
          },
        ]);
        break;

      case "roundtable_conclusion":
        setConclusion({ content: event.content, structured: event.structured ?? null });
        setMessages((prev) => [
          ...prev,
          {
            id: genId("conc"),
            seat_id: "",
            speaker_name: event.source,
            content: event.content,
            round: event.total_rounds,
            kind: "conclusion",
            timestamp: new Date().toISOString(),
          },
        ]);
        break;

      case "rt_paused":
        setSessionStatus("paused");
        setNotice({ tone: "info", title: "已暂停", text: "讨论已暂停，可随时恢复继续。" });
        break;

      case "rt_resumed":
        setSessionStatus("discussing");
        setNotice(null);
        break;

      case "rt_seat_added":
        setRuntimeSeats((prev) => [...prev, event.seat]);
        break;

      case "rt_seat_removed":
        setRuntimeSeats((prev) => prev.filter((s) => s.seat_id !== event.seat_id));
        break;

      case "rt_ended":
        setSessionStatus("ended");
        setNotice({
          tone: "info",
          title: "讨论已结束",
          text: `共完成 ${event.total_rounds} 轮，${event.transcript_count} 条发言。`,
        });
        break;

      case "rt_deleted":
        setSessionStatus("idle");
        setSessionId(null);
        setMessages([]);
        setRuntimeSeats([]);
        setConclusion(null);
        break;

      // speaker_selected / moderator_decision / ping 暂不单独渲染
      default:
        break;
    }
  }, []);

  // ── 启动讨论：创建会话 → 连 SSE → start ──────────────
  const startDiscussion = async () => {
    setNotice(null);
    if (!topic.trim()) {
      setNotice({ tone: "warn", title: "请先完善讨论配置", text: "讨论主题不能为空，请先填写主题或选择一个快速模板。" });
      return;
    }
    if (seats.some((s) => !s.role_name.trim())) {
      setNotice({ tone: "warn", title: "请先完善讨论配置", text: "存在未命名的席位，请为每个席位填写角色名称。" });
      return;
    }
    if (seats.length < MIN_SEATS) {
      setNotice({ tone: "warn", title: "请先完善讨论配置", text: `至少需要 ${MIN_SEATS} 个席位。` });
      return;
    }

    setBusy(true);
    try {
      const seatInputs: RoundtableSeatInput[] = seats.map((s) => ({
        role_name: s.role_name.trim(),
        system_prompt: s.system_prompt,
        temperature: s.temperature,
        is_moderator: s.is_moderator,
      }));
      const payload: CreateRoundtablePayload = {
        topic: topic.trim(),
        seats: seatInputs,
        max_rounds: maxRounds,
        strategy: strategy as ApiStrategy,
      };
      const resp = await roundtableApi.create(payload);
      const sid = resp.session.session_id;
      setSessionId(sid);
      setSessionStatus("waiting");
      setMessages([]);
      setConclusion(null);
      setRuntimeSeats([]);

      // 1. 先建立 SSE 连接（必须在 start 之前，避免丢 rt_started）
      esRef.current = openRoundtableStream(sid, handleEvent, (err) => {
        // 连接错误：若会话仍在进行，提示但不断开（EventSource 会自动重连）
        console.warn("Roundtable SSE error", err);
      });

      // 2. 再触发 start
      try {
        await roundtableApi.start(sid);
      } catch (e) {
        // start 失败：关闭 SSE，回退状态
        esRef.current?.close();
        esRef.current = null;
        setSessionStatus("idle");
        setSessionId(null);
        throw e;
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setNotice({ tone: "error", title: "启动失败", text: msg });
      setSessionStatus("idle");
      setSessionId(null);
    } finally {
      setBusy(false);
    }
  };

  // ── 控制操作 ──────────────────────────────────────────
  const pauseDiscussion = async () => {
    if (!sessionId) return;
    try {
      await roundtableApi.pause(sessionId);
    } catch (e: unknown) {
      setNotice({ tone: "error", title: "暂停失败", text: e instanceof Error ? e.message : String(e) });
    }
  };
  const resumeDiscussion = async () => {
    if (!sessionId) return;
    try {
      await roundtableApi.resume(sessionId);
    } catch (e: unknown) {
      setNotice({ tone: "error", title: "恢复失败", text: e instanceof Error ? e.message : String(e) });
    }
  };
  const stopDiscussion = async () => {
    if (!sessionId) return;
    try {
      await roundtableApi.stop(sessionId);
      // 后端会 emit rt_ended，SSE 自动关闭；状态由 handleEvent 更新
    } catch (e: unknown) {
      setNotice({ tone: "error", title: "终止失败", text: e instanceof Error ? e.message : String(e) });
    }
  };
  const newSession = () => {
    esRef.current?.close();
    esRef.current = null;
    setSessionId(null);
    setSessionStatus("idle");
    setMessages([]);
    setRuntimeSeats([]);
    setConclusion(null);
    setNotice(null);
  };

  // ── 插话 ──────────────────────────────────────────────
  const sendInterjection = async () => {
    const content = injectText.trim();
    if (!content || !sessionId || !isLive) return;
    setInjectText("");
    // 乐观：本地立即插入一条用户消息（后端 rt_turn_end 也会回显，但插话体验需要即时反馈）
    setMessages((prev) => [
      ...prev,
      {
        id: genId("inj"),
        seat_id: "user",
        speaker_name: "你",
        content,
        round: 0,
        kind: "user_inject",
        timestamp: new Date().toISOString(),
      },
    ]);
    try {
      await roundtableApi.inject(sessionId, content);
    } catch (e: unknown) {
      setNotice({ tone: "error", title: "插话失败", text: e instanceof Error ? e.message : String(e) });
    }
  };

  // ── 自动滚动到底部（新消息/流式更新时）────────────────
  useEffect(() => {
    streamEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  // ── 卸载时清理 SSE 连接 ────────────────────────────────
  useEffect(() => {
    return () => {
      esRef.current?.close();
      esRef.current = null;
    };
  }, []);

  // 席位配色：运行时用 seat_id 索引，配置态用下标
  const colorForSeat = (seatId: string, fallbackIndex: number) => {
    const idx = seatColorIndex[seatId];
    return getSeatColor(idx ?? fallbackIndex);
  };

  // ── 渲染 ──────────────────────────────────────────────
  return (
    <AppLayout>
      <div className="h-full overflow-y-auto p-6">
        <div className="mx-auto max-w-7xl space-y-4">
          {/* 页头 */}
          <header className="flex items-center gap-3">
            <span className="rounded-lg bg-green-500/20 p-2 text-green-400" aria-hidden="true">
              <Users size={20} />
            </span>
            <div className="flex-1">
              <h1 className="text-lg font-semibold text-foreground">圆桌讨论</h1>
              <p className="text-xs text-muted">
                作者、编辑、读者等多角色席位围绕创作议题交锋，碰撞剧情火花
              </p>
            </div>
            {sessionId && (
              <span className="max-w-[30vw] truncate rounded bg-secondary px-2 py-1 text-xs text-muted font-mono" title={sessionId}>
                {sessionId}
              </span>
            )}
          </header>

          {/* 提示条 */}
          {notice && (
            <div
              className={`flex items-start gap-3 rounded-xl border px-4 py-3 ${
                notice.tone === "info"
                  ? "border-green-500/30 bg-green-500/10"
                  : notice.tone === "warn"
                    ? "border-amber-500/30 bg-amber-500/10"
                    : "border-red-500/30 bg-red-500/10"
              }`}
              role="status"
              aria-live="polite"
            >
              {notice.tone === "info" ? (
                <Sparkles size={16} className="mt-0.5 shrink-0 text-green-400" aria-hidden="true" />
              ) : notice.tone === "warn" ? (
                <AlertTriangle size={16} className="mt-0.5 shrink-0 text-amber-400" aria-hidden="true" />
              ) : (
                <AlertTriangle size={16} className="mt-0.5 shrink-0 text-red-400" aria-hidden="true" />
              )}
              <div className="min-w-0 flex-1">
                <p
                  className={`text-sm font-medium ${
                    notice.tone === "info"
                      ? "text-green-300"
                      : notice.tone === "warn"
                        ? "text-amber-300"
                        : "text-red-300"
                  }`}
                >
                  {notice.title}
                </p>
                <p
                  className={`mt-0.5 text-xs ${
                    notice.tone === "info"
                      ? "text-green-200/70"
                      : notice.tone === "warn"
                        ? "text-amber-200/70"
                        : "text-red-200/70"
                  }`}
                >
                  {notice.text}
                </p>
              </div>
              <DFIconButton
                type="button"
                onClick={() => setNotice(null)}
                aria-label="关闭提示"
                className="-my-1 -mr-2 flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg text-muted transition-colors hover:bg-secondary hover:text-muted"
              >
                <X size={14} aria-hidden="true" />
              </DFIconButton>
            </div>
          )}

          {/* 结论卡片（会议结束时展示） */}
          {conclusion && (
            <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4">
              <div className="mb-1.5 flex items-center gap-2">
                <CheckCircle2 size={16} className="text-emerald-400" aria-hidden="true" />
                <span className="text-sm font-semibold text-emerald-300">会议结论</span>
              </div>
              <p className="whitespace-pre-wrap text-sm text-foreground/90">{conclusion.content}</p>
              {conclusion.structured && (
                <details className="mt-2">
                  <summary className="cursor-pointer text-xs text-muted hover:text-foreground">
                    查看结构化结论（共识 / 分歧 / 行动项）
                  </summary>
                  <pre className="mt-1 overflow-x-auto rounded bg-black/20 p-2 text-xs text-muted">
                    {JSON.stringify(conclusion.structured, null, 2)}
                  </pre>
                </details>
              )}
            </div>
          )}

          {/* 讨论配置：会话进行中禁用编辑 */}
          <DFSection title="讨论配置" icon={Settings2}>
            {/* 快速模板 */}
            <fieldset className="mb-4" disabled={!configEditable}>
              <legend className="mb-2 text-xs text-muted">快速模板</legend>
              <div className="flex flex-wrap gap-2">
                {ROUNDTABLE_TEMPLATES.map((tpl) => (
                  <DFSecondaryButton
                    key={tpl.name}
                    type="button"
                    accent="green"
                    onClick={() => applyTemplate(tpl)}
                    disabled={!configEditable}
                    aria-label={`应用模板：${tpl.name}`}
                    className="inline-flex min-h-[36px] items-center justify-start gap-1.5 rounded-lg border border-border-strong bg-surface px-3 text-xs font-normal text-foreground transition-colors hover:border-green-500/40 hover:bg-surface hover:text-green-300 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {tpl.strategy === "moderator_decides" ? (
                      <Brain size={12} className="text-amber-400" aria-hidden="true" />
                    ) : (
                      <Zap size={12} className="text-green-400" aria-hidden="true" />
                    )}
                    {tpl.name}
                  </DFSecondaryButton>
                ))}
              </div>
            </fieldset>

            {/* 讨论主题 */}
            <div className="mb-4">
              <label htmlFor="df-rt-topic" className="mb-1.5 block text-xs text-muted">
                讨论主题 *
              </label>
              <input
                id="df-rt-topic"
                type="text"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                disabled={!configEditable}
                placeholder="例如：第 12 章高潮战的胜负安排"
                aria-required="true"
                className="min-h-[44px] w-full rounded-lg border border-border-strong bg-surface px-3 text-sm text-foreground placeholder:text-muted focus:border-green-500/50 focus:outline-none disabled:opacity-50"
              />
            </div>

            {/* 调度策略 + 讨论轮次 */}
            <div className="flex flex-wrap gap-4">
              <div className="min-w-64 flex-1">
                <span id="df-rt-strategy-label" className="mb-1.5 block text-xs text-muted">
                  调度策略
                </span>
                <div className="flex gap-2" role="radiogroup" aria-labelledby="df-rt-strategy-label">
                  <DFPrimaryButton
                    type="button"
                    role="radio"
                    accent="green"
                    aria-checked={strategy === "round_robin"}
                    onClick={() => configEditable && setStrategy("round_robin")}
                    disabled={!configEditable}
                    className={`flex min-h-[44px] flex-1 items-center justify-center gap-1 rounded-lg border px-3 text-xs font-normal transition-colors ${
                      strategy === "round_robin"
                        ? "border-green-500/50 bg-green-500/10 text-green-300 hover:bg-green-500/10"
                        : "border-border-strong bg-surface text-muted hover:bg-surface"
                    } disabled:cursor-not-allowed disabled:opacity-50`}
                  >
                    <Zap size={12} className="text-green-400" aria-hidden="true" />
                    固定轮询
                  </DFPrimaryButton>
                  <DFPrimaryButton
                    type="button"
                    role="radio"
                    accent="amber"
                    aria-checked={strategy === "moderator_decides"}
                    onClick={() => configEditable && setStrategy("moderator_decides")}
                    disabled={!configEditable}
                    className={`flex min-h-[44px] flex-1 items-center justify-center gap-1 rounded-lg border px-3 text-xs font-normal transition-colors ${
                      strategy === "moderator_decides"
                        ? "border-amber-400/50 bg-amber-400/10 text-amber-400 hover:bg-amber-400/10"
                        : "border-border-strong bg-surface text-muted hover:bg-surface"
                    } disabled:cursor-not-allowed disabled:opacity-50`}
                  >
                    <Brain size={12} className="text-amber-400" aria-hidden="true" />
                    智能主持
                  </DFPrimaryButton>
                </div>
              </div>
              <div>
                <label htmlFor="df-rt-rounds" className="mb-1.5 block text-xs text-muted">
                  讨论轮次
                </label>
                <input
                  id="df-rt-rounds"
                  type="number"
                  value={maxRounds}
                  onChange={(e) => setMaxRounds(Math.max(1, Math.min(MAX_ROUNDS, Number(e.target.value))))}
                  disabled={!configEditable}
                  min={1}
                  max={MAX_ROUNDS}
                  className="min-h-[44px] w-20 rounded-lg border border-border-strong bg-surface px-3 text-sm text-foreground focus:border-green-500/50 focus:outline-none disabled:opacity-50"
                />
              </div>
            </div>
          </DFSection>

          {/* 席位卡片网格（会话进行中禁用编辑，仅展示） */}
          <DFSection
            title={`席位配置（${seats.length}/${MAX_SEATS}）`}
            icon={Users}
            extra={
              configEditable && seats.length < MAX_SEATS ? (
                <DFIconButton
                  type="button"
                  accent="green"
                  onClick={addSeat}
                  aria-label="添加空白席位"
                  className="inline-flex min-h-[32px] items-center justify-start gap-1 rounded-lg bg-transparent px-2 text-xs text-green-400 transition-colors hover:bg-green-500/10"
                >
                  <Plus size={12} aria-hidden="true" />
                  添加席位
                </DFIconButton>
              ) : undefined
            }
          >
            {configEditable && (
              <div className="mb-3 flex flex-wrap items-center gap-1.5">
                <span className="text-xs text-muted">席位预设：</span>
                {SEAT_PRESETS.map((p) => (
                  <DFIconButton
                    key={p.key}
                    type="button"
                    accent="green"
                    onClick={() => addPresetSeat(p.key)}
                    disabled={seats.length >= MAX_SEATS}
                    aria-label={`添加预设席位：${p.role_name}`}
                    className="inline-flex min-h-[32px] items-center justify-start gap-1 rounded-lg border border-border-strong bg-surface px-2 text-xs text-foreground transition-colors hover:border-green-500/40 hover:bg-surface hover:text-green-300 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <Plus size={10} aria-hidden="true" />
                    {p.role_name}
                  </DFIconButton>
                ))}
              </div>
            )}
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {seats.map((seat, i) => (
                <DFSeatCard
                  key={i}
                  seat={seat}
                  index={i}
                  canRemove={configEditable && seats.length > MIN_SEATS}
                  onChange={updateSeat}
                  onRemove={removeSeat}
                />
              ))}
            </div>
          </DFSection>

          {/* 讨论区：消息流 */}
          <DFSection
            title="讨论区"
            icon={MessagesSquare}
            extra={
              <span className="rounded bg-secondary px-2 py-0.5 text-xs text-muted">
                {strategy === "moderator_decides" ? "智能主持" : "固定轮询"} · {maxRounds} 轮
                {sessionStatus !== "idle" && ` · ${statusLabel(sessionStatus)}`}
              </span>
            }
          >
            {messages.length === 0 ? (
              <DFEmptyState
                title="尚无讨论消息"
                description={`主题「${topic.trim() || "未设置"}」共 ${seats.length} 个席位。配置完成后点击底部「开始讨论」。`}
              />
            ) : (
              <div className="max-h-[480px] space-y-3 overflow-y-auto pr-1">
                {messages.map((m) => (
                  <MessageBubble key={m.id} message={m} colorForSeat={colorForSeat} />
                ))}
                <div ref={streamEndRef} />
              </div>
            )}
          </DFSection>

          {/* 底部控制栏：插话 + 开始/暂停/恢复/终止/新会议 */}
          <div className="space-y-3 rounded-xl border border-border bg-surface p-4">
            {/* 插话输入（仅讨论进行中可用） */}
            <div className="flex gap-2">
              <label htmlFor="df-rt-inject" className="sr-only">
                插话输入
              </label>
              <input
                id="df-rt-inject"
                type="text"
                value={injectText}
                onChange={(e) => setInjectText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") sendInterjection();
                }}
                disabled={!isLive}
                placeholder={isLive ? "插话…（输入 @角色名 可点名发言）" : "开始讨论后可在此插话"}
                aria-label="插话输入，输入 @角色名 可点名发言"
                className="min-h-[44px] min-w-0 flex-1 rounded-lg border border-border-strong bg-surface px-3 text-sm text-foreground placeholder:text-muted focus:border-green-500/50 focus:outline-none disabled:opacity-50"
              />
              <DFIconButton
                type="button"
                accent="green"
                onClick={sendInterjection}
                disabled={!isLive || !injectText.trim()}
                aria-label="发送插话"
                className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg bg-green-500/20 text-green-400 transition-colors hover:bg-green-500/30 disabled:cursor-not-allowed disabled:opacity-30"
              >
                <Send size={14} aria-hidden="true" />
              </DFIconButton>
            </div>

            {/* 主控制按钮组 */}
            <div className="flex flex-wrap items-center gap-3">
              {sessionStatus === "idle" && (
                <DFPrimaryButton
                  type="button"
                  accent="green"
                  onClick={startDiscussion}
                  disabled={busy}
                  aria-label="开始讨论"
                  className="inline-flex min-h-[44px] items-center justify-start gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-green-500 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {busy ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <Play size={16} aria-hidden="true" />}
                  {busy ? "正在启动…" : "开始讨论"}
                </DFPrimaryButton>
              )}

              {sessionStatus === "discussing" && (
                <>
                  <DFPrimaryButton
                    type="button"
                    accent="amber"
                    onClick={pauseDiscussion}
                    aria-label="暂停讨论"
                    className="inline-flex min-h-[44px] items-center justify-start gap-2 rounded-lg bg-amber-500/20 px-4 py-2 text-sm font-medium text-amber-400 transition-colors hover:bg-amber-500/30"
                  >
                    <Pause size={16} aria-hidden="true" />
                    暂停
                  </DFPrimaryButton>
                  <DFDangerButton
                    type="button"
                    accent="red"
                    onClick={stopDiscussion}
                    aria-label="终止讨论"
                    className="inline-flex min-h-[44px] items-center justify-start gap-2 rounded-lg bg-red-500/20 px-4 py-2 text-sm font-medium text-red-400 transition-colors hover:bg-red-500/30"
                  >
                    <Square size={16} aria-hidden="true" />
                    终止讨论
                  </DFDangerButton>
                </>
              )}

              {sessionStatus === "paused" && (
                <>
                  <DFPrimaryButton
                    type="button"
                    accent="green"
                    onClick={resumeDiscussion}
                    aria-label="恢复讨论"
                    className="inline-flex min-h-[44px] items-center justify-start gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-green-500"
                  >
                    <Play size={16} aria-hidden="true" />
                    恢复
                  </DFPrimaryButton>
                  <DFDangerButton
                    type="button"
                    accent="red"
                    onClick={stopDiscussion}
                    aria-label="终止讨论"
                    className="inline-flex min-h-[44px] items-center justify-start gap-2 rounded-lg bg-red-500/20 px-4 py-2 text-sm font-medium text-red-400 transition-colors hover:bg-red-500/30"
                  >
                    <Square size={16} aria-hidden="true" />
                    终止讨论
                  </DFDangerButton>
                </>
              )}

              {sessionStatus === "ended" && (
                <DFPrimaryButton
                  type="button"
                  accent="green"
                  onClick={newSession}
                  aria-label="开始新会议"
                  className="inline-flex min-h-[44px] items-center justify-start gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-green-500"
                >
                  <Plus size={16} aria-hidden="true" />
                  新会议
                </DFPrimaryButton>
              )}

              <span className="text-xs text-muted">
                {sessionStatus === "idle" &&
                  `圆桌引擎接入后，席位将按「${strategy === "moderator_decides" ? "智能主持" : "固定轮询"}」策略讨论 ${maxRounds} 轮`}
                {sessionStatus === "waiting" && "正在启动讨论…"}
                {sessionStatus === "discussing" && "讨论进行中，可随时插话或暂停"}
                {sessionStatus === "paused" && "已暂停，点击恢复继续"}
                {sessionStatus === "ended" && "讨论已结束，可开始新会议"}
              </span>
            </div>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}

// ── 子组件：单条消息气泡 ──────────────────────────────────

function MessageBubble({
  message,
  colorForSeat,
}: {
  message: ChatMessage;
  colorForSeat: (seatId: string, fallbackIndex: number) => ReturnType<typeof getSeatColor>;
}) {
  // 轮次分隔线
  if (message.kind === "round_divider") {
    return (
      <div className="flex items-center gap-2 py-1 text-xs text-muted">
        <span className="h-px flex-1 bg-border-strong" />
        <span>{message.content}</span>
        <span className="h-px flex-1 bg-border-strong" />
      </div>
    );
  }

  // 摘要 / 结论：横向卡片
  if (message.kind === "summary" || message.kind === "conclusion") {
    const isConclusion = message.kind === "conclusion";
    return (
      <div
        className={`rounded-xl border p-3 ${
          isConclusion
            ? "border-emerald-500/30 bg-emerald-500/5"
            : "border-indigo-500/30 bg-indigo-500/5"
        }`}
      >
        <div className="mb-1 flex items-center gap-1.5">
          <Sparkles
            size={12}
            className={isConclusion ? "text-emerald-400" : "text-indigo-400"}
            aria-hidden="true"
          />
          <span className={`text-xs font-medium ${isConclusion ? "text-emerald-300" : "text-indigo-300"}`}>
            {isConclusion ? "会议结论" : `第 ${message.round} 轮摘要`}
          </span>
          <span className="text-xs text-muted">· {message.speaker_name}</span>
        </div>
        <p className="whitespace-pre-wrap text-sm text-foreground/90">{message.content}</p>
      </div>
    );
  }

  // 普通发言 / 主持人备注 / 用户插话
  const isUser = message.kind === "user_inject";
  const color = colorForSeat(message.seat_id, 0);
  return (
    <div className={`flex gap-2.5 ${isUser ? "flex-row-reverse" : ""}`}>
      <div
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-medium ${color.bg} ${color.text}`}
        aria-hidden="true"
      >
        {isUser ? "你" : message.speaker_name.slice(0, 1) || "?"}
      </div>
      <div className={`min-w-0 max-w-[80%] ${isUser ? "text-right" : ""}`}>
        <div className={`mb-0.5 flex items-center gap-1.5 text-xs text-muted ${isUser ? "justify-end" : ""}`}>
          <span className={`font-medium ${color.text}`}>{message.speaker_name}</span>
          {message.round > 0 && <span>· 第 {message.round} 轮</span>}
          {message.interrupted && (
            <span className="text-amber-400" title="发言被中断">
              （中断）
            </span>
          )}
        </div>
        <div
          className={`inline-block whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm ${
            isUser
              ? "bg-green-600/20 text-green-100"
              : message.kind === "moderator_note"
                ? "border border-amber-400/30 bg-amber-400/5 text-foreground/90"
                : "border border-border-strong bg-surface text-foreground/90"
          }`}
        >
          {message.content}
          {message.isStreaming && (
            <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-green-400 align-middle" aria-hidden="true" />
          )}
        </div>
      </div>
    </div>
  );
}

function statusLabel(status: RoundtableStatus | "idle"): string {
  switch (status) {
    case "idle":
      return "未开始";
    case "waiting":
      return "启动中";
    case "discussing":
      return "讨论中";
    case "paused":
      return "已暂停";
    case "ended":
      return "已结束";
    default:
      return "";
  }
}
