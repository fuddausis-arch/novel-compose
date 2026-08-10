import { Switch } from "@/components/ui/switch";

interface SettingToggleRowProps {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}

/** 通用设置开关行：左侧标签+描述，右侧 Switch */
export function SettingToggleRow({ label, description, checked, onChange }: SettingToggleRowProps) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="min-w-0">
        <div className="text-sm font-medium">{label}</div>
        {description && <div className="text-xs text-muted">{description}</div>}
      </div>
      <Switch checked={checked} onCheckedChange={onChange} />
    </div>
  );
}
