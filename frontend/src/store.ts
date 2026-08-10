import { create } from "zustand";
import type { AppState } from "./store/types";
import { projectSlice } from "./store/slices/project";
import { bibleSlice } from "./store/slices/bible";
import { chapterSlice } from "./store/slices/chapter";
import { pipelineSlice } from "./store/slices/pipeline";
import { interactiveSlice } from "./store/slices/interactive";
import { opsSlice } from "./store/slices/ops";

/**
 * 全局 store（zustand slice 模式）。
 *
 * 按 6 个功能域拆分到 store/slices/ 下，再用共享的 set/get 组合成单一 store：
 *  - project    项目列表 / 当前项目
 *  - bible      圣经资产（角色/伏笔/大纲/世界观/势力/关系/怪物/副本/红线/梗等）
 *  - chapter    章节 / 摘要 / 题材上下文
 *  - pipeline   流水线状态 + 章节生成 SSE 流
 *  - interactive 交互式创作（消息 / 模式 / 抽卡 / 润色 / 重写）
 *  - ops        批量生成 + loading 标记
 *
 * 对外接口（useAppStore 的字段与 actions）与重构前完全一致，
 * 所有消费者仍从 "@/store" 导入，无需改动。
 */
export const useAppStore = create<AppState>((set, get) => ({
  ...projectSlice(set, get),
  ...bibleSlice(set, get),
  ...chapterSlice(set, get),
  ...pipelineSlice(set, get),
  ...interactiveSlice(set, get),
  ...opsSlice(set, get),
}) as AppState);
