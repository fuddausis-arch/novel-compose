import type { ReactNode } from "react";
import { BookMarked, MapPinned, Skull, User, Users } from "lucide-react";
import type { EntityCardType } from "./EntityCardDrawer";

/** 实体类型元信息：label + 图标 + 图标文字色（卡片抽屉用）+ Badge 配色（百科卡用） */
export const ENTITY_TYPE_META: Record<
  EntityCardType,
  { label: string; icon: ReactNode; color: string; badge: string }
> = {
  character: {
    label: "角色",
    icon: <User size={14} aria-hidden="true" />,
    color: "text-blue-500",
    badge: "bg-blue-100 text-blue-700 dark:bg-blue-950/50 dark:text-blue-400",
  },
  faction: {
    label: "势力",
    icon: <Users size={14} aria-hidden="true" />,
    color: "text-purple-500",
    badge: "bg-purple-100 text-purple-700 dark:bg-purple-950/50 dark:text-purple-400",
  },
  monster: {
    label: "怪物",
    icon: <Skull size={14} aria-hidden="true" />,
    color: "text-red-500",
    badge: "bg-red-100 text-red-700 dark:bg-red-950/50 dark:text-red-400",
  },
  foreshadow: {
    label: "伏笔",
    icon: <BookMarked size={14} aria-hidden="true" />,
    color: "text-amber-500",
    badge: "bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-400",
  },
  location: {
    label: "地点",
    icon: <MapPinned size={14} aria-hidden="true" />,
    color: "text-cyan-500",
    badge: "bg-cyan-100 text-cyan-700 dark:bg-cyan-950/50 dark:text-cyan-400",
  },
};

/** 伏笔状态标签：文案 + Badge 配色 */
export const FORESHADOW_STATUS_LABEL: Record<string, { text: string; cls: string }> = {
  planted: { text: "已埋设", cls: "bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-400" },
  pending: { text: "待埋设", cls: "bg-slate-100 text-slate-600 dark:bg-slate-800/50 dark:text-slate-400" },
  developing: { text: "推进中", cls: "bg-cyan-100 text-cyan-700 dark:bg-cyan-950/50 dark:text-cyan-400" },
  resolved: { text: "已回收", cls: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400" },
  abandoned: { text: "已废弃", cls: "bg-rose-100 text-rose-700 dark:bg-rose-950/50 dark:text-rose-400" },
};
