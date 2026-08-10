import { cn } from "@/lib/utils";

export type AssetNavType =
  | "characters"
  | "world"
  | "foreshadows"
  | "factions"
  | "monsters"
  | "instances"
  | "redLines"
  | "gags"
  | "importFolder";

export const ASSET_TYPES: { key: AssetNavType; label: string; icon: string }[] = [
  { key: "characters", label: "角色", icon: "👤" },
  { key: "world", label: "世界设定", icon: "🌍" },
  { key: "foreshadows", label: "伏笔", icon: "🪝" },
  { key: "factions", label: "势力", icon: "🏰" },
  { key: "monsters", label: "怪物", icon: "👹" },
  { key: "instances", label: "副本", icon: "🗺️" },
  { key: "redLines", label: "红线", icon: "🚫" },
  { key: "gags", label: "梗管理", icon: "🎭" },
  { key: "importFolder", label: "导入文件夹", icon: "📁" },
];

export interface AssetTypeNavProps {
  value: AssetNavType;
  onChange: (value: AssetNavType) => void;
}

export function AssetTypeNav({ value, onChange }: AssetTypeNavProps) {
  return (
    <nav className="flex w-44 shrink-0 flex-col gap-1 border-r border-border bg-surface p-3">
      {ASSET_TYPES.map((type) => (
        <button
          key={type.key}
          onClick={() => onChange(type.key)}
          className={cn(
            "flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm font-medium transition-colors",
            value === type.key
              ? "bg-primary text-primary-foreground"
              : "text-foreground hover:bg-foreground/5"
          )}
        >
          <span>{type.icon}</span>
          <span>{type.label}</span>
        </button>
      ))}
    </nav>
  );
}
