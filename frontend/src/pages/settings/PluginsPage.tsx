/** 全局设置 · 插件管理页：已安装 / 仓库 双 tab，支持安装与启停 + 资产导入导出 */
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Archive, Boxes, Loader2, PackagePlus, RefreshCw } from "lucide-react";
import { api } from "@/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState } from "@/components/ui/empty-state";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/useToast";

interface Plugin {
  name: string;
  version?: string;
  description?: string;
  enabled: boolean;
  source?: string;
}

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

/** 资产导入导出：skills / rules / preset_phrases 打包为 .naassets */
function AssetsTransferSection() {
  const { showSuccess, showError } = useToast();
  const [exportPath, setExportPath] = useState("assets.naassets");
  const [include, setInclude] = useState<string[]>(["skills", "rules", "preset_phrases"]);
  const [packagePath, setPackagePath] = useState("");
  const [strategy, setStrategy] = useState<"merge" | "overwrite">("merge");
  const [busy, setBusy] = useState<"export" | "inspect" | "import" | null>(null);
  const [inspectResult, setInspectResult] = useState<{ manifest?: any; files?: string[] } | null>(null);
  const [transferResult, setTransferResult] = useState<string | null>(null);

  const toggleInclude = (key: string) => {
    setInclude((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));
  };

  const handleExport = async () => {
    if (!exportPath.trim()) {
      showError("请输入导出路径");
      return;
    }
    setBusy("export");
    setTransferResult(null);
    try {
      const r = await api.exportPluginAssets(exportPath.trim(), include);
      const counts = Object.entries(r.counts || {})
        .filter(([, v]) => v > 0)
        .map(([k, v]) => `${k}: ${v}`)
        .join("，");
      setTransferResult(`已导出到 ${r.path}${counts ? `（${counts}）` : ""}`);
      showSuccess("资产包导出成功");
    } catch (e: any) {
      showError("导出失败：" + e.message);
    } finally {
      setBusy(null);
    }
  };

  const handleInspect = async () => {
    if (!packagePath.trim()) {
      showError("请输入资产包路径");
      return;
    }
    setBusy("inspect");
    try {
      const r = await api.inspectPluginAssets(packagePath.trim());
      setInspectResult(r);
      showSuccess("资产包检查完成");
    } catch (e: any) {
      setInspectResult(null);
      showError("检查失败：" + e.message);
    } finally {
      setBusy(null);
    }
  };

  const handleImport = async () => {
    if (!packagePath.trim()) {
      showError("请输入资产包路径");
      return;
    }
    setBusy("import");
    setTransferResult(null);
    try {
      const r = await api.importPluginAssets(packagePath.trim(), strategy);
      const imported = Object.entries(r.imported || {}).filter(([, v]) => v > 0);
      const skipped = Object.entries(r.skipped || {}).filter(([, v]) => v > 0);
      setTransferResult(
        `导入完成：${imported.length > 0 ? imported.map(([k, v]) => `${k} ${v} 项`).join("，") : "无新增"}` +
          (skipped.length > 0 ? `；跳过：${skipped.map(([k, v]) => `${k} ${v} 项`).join("，")}` : ""),
      );
      showSuccess("资产包导入成功");
    } catch (e: any) {
      showError("导入失败：" + e.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card className="p-4">
      <div className="flex items-center gap-2">
        <Archive className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-semibold text-foreground">资产导入导出</h3>
      </div>
      <p className="mt-1 text-xs text-muted">将 Skill / Rule / 预设短语打包为 .naassets 资产包，或从资产包导入（路径需为服务端可访问的本地路径）。</p>

      <div className="mt-3 space-y-4">
        {/* 导出 */}
        <div className="space-y-2 rounded-lg border border-border bg-surface/50 p-3">
          <div className="text-xs font-medium text-muted">导出</div>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              className="flex-1 min-w-[200px] font-mono text-xs"
              value={exportPath}
              onChange={(e) => setExportPath(e.target.value)}
              placeholder="输出路径，如 assets.naassets"
            />
            <div className="flex flex-wrap items-center gap-3 text-xs text-foreground">
              {["skills", "rules", "preset_phrases"].map((k) => (
                <label key={k} className="flex cursor-pointer items-center gap-1">
                  <input
                    type="checkbox"
                    checked={include.includes(k)}
                    onChange={() => toggleInclude(k)}
                    className="h-3.5 w-3.5 rounded border-border-strong"
                  />
                  {k}
                </label>
              ))}
            </div>
            <Button size="sm" variant="primary" onClick={() => void handleExport()} disabled={busy !== null}>
              {busy === "export" ? "导出中…" : "导出资产包"}
            </Button>
          </div>
        </div>

        {/* 检查 / 导入 */}
        <div className="space-y-2 rounded-lg border border-border bg-surface/50 p-3">
          <div className="text-xs font-medium text-muted">检查 / 导入</div>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              className="flex-1 min-w-[200px] font-mono text-xs"
              value={packagePath}
              onChange={(e) => setPackagePath(e.target.value)}
              placeholder="资产包路径，如 project_data/assets.naassets"
            />
            <select
              value={strategy}
              onChange={(e) => setStrategy(e.target.value as "merge" | "overwrite")}
              className="h-9 rounded-lg border border-border-strong bg-surface px-3 text-xs text-foreground"
            >
              <option value="merge">merge（同名跳过）</option>
              <option value="overwrite">overwrite（同名覆盖）</option>
            </select>
            <Button size="sm" variant="outline" onClick={() => void handleInspect()} disabled={busy !== null}>
              {busy === "inspect" ? "检查中…" : "检查资产包"}
            </Button>
            <Button size="sm" variant="primary" onClick={() => void handleImport()} disabled={busy !== null}>
              {busy === "import" ? "导入中…" : "导入资产包"}
            </Button>
          </div>

          {inspectResult && (
            <div className="rounded-lg bg-surface p-2 text-xs text-muted">
              <div>Manifest：{inspectResult.manifest ? JSON.stringify(inspectResult.manifest.counts || {}) : "—"}</div>
              {inspectResult.files && inspectResult.files.length > 0 && (
                <div className="mt-1 max-h-28 overflow-y-auto">
                  {inspectResult.files.map((f) => (
                    <div key={f} className="truncate font-mono">{f}</div>
                  ))}
                </div>
              )}
            </div>
          )}
          {transferResult && <div className="text-xs text-success">{transferResult}</div>}
        </div>
      </div>
    </Card>
  );
}

export default function PluginsPage() {
  const { showError, showSuccess } = useToast();
  const [installed, setInstalled] = useState<Plugin[]>([]);
  const [sources, setSources] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [installName, setInstallName] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (initial = false) => {
    if (initial) setLoading(true);
    else setRefreshing(true);
    setError(null);
    try {
      const data = await fetchJson<{ installed: Plugin[]; sources: string[] }>("/api/plugins");
      setInstalled(data.installed || []);
      setSources(data.sources || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
      setInstalled([]);
      setSources([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load(true);
  }, [load]);

  const handleToggle = async (plugin: Plugin, enabled: boolean) => {
    const snapshot = installed;
    setInstalled((prev) => prev.map((p) => (p.name === plugin.name ? { ...p, enabled } : p)));
    try {
      await fetchJson(`/api/plugins/${encodeURIComponent(plugin.name)}/${enabled ? "enable" : "disable"}`, {
        method: "PUT",
      });
    } catch (e) {
      setInstalled(snapshot);
      showError(e instanceof Error ? e.message : "切换状态失败");
    }
  };

  const handleInstall = async () => {
    if (!installName.trim()) {
      showError("请输入插件名称");
      return;
    }
    setBusy(true);
    try {
      await fetchJson("/api/plugins/install", {
        method: "POST",
        body: JSON.stringify({ name: installName.trim() }),
      });
      showSuccess("插件已安装");
      setInstalling(false);
      setInstallName("");
      await load();
    } catch (e) {
      showError(e instanceof Error ? e.message : "安装失败");
    } finally {
      setBusy(false);
    }
  };

  const enabledCount = installed.filter((p) => p.enabled).length;

  const header = (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-3">
        <div className="rounded-lg border border-border bg-primary-muted p-2 text-primary">
          <Boxes className="h-5 w-5" />
        </div>
        <div>
          <h2 className="text-lg font-semibold">插件管理</h2>
          <p className="text-sm text-muted">插件安装、启停与插件源管理</p>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={() => void load()} disabled={refreshing}>
          <RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} />
          刷新
        </Button>
        <Button variant="primary" size="sm" onClick={() => setInstalling(true)}>
          <PackagePlus className="h-4 w-4" />
          安装插件
        </Button>
      </div>
    </div>
  );

  const stats = (
    <div className="grid grid-cols-3 gap-4">
      <Card className="p-4">
        <div className="text-xs text-muted">已安装</div>
        <div className="mt-1 text-2xl font-bold tabular-nums">{installed.length}</div>
      </Card>
      <Card className="p-4">
        <div className="text-xs text-muted">已启用</div>
        <div className="mt-1 text-2xl font-bold tabular-nums text-success">{enabledCount}</div>
      </Card>
      <Card className="p-4">
        <div className="text-xs text-muted">插件源</div>
        <div className="mt-1 text-2xl font-bold tabular-nums text-muted">{sources.length}</div>
      </Card>
    </div>
  );

  let body: ReactNode;
  if (loading) {
    body = (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-muted" />
        <span className="text-sm text-muted">正在加载插件...</span>
      </div>
    );
  } else if (error) {
    body = <EmptyState icon={<Boxes className="h-10 w-10 text-muted" />} title="后端插件系统尚未接入" description={error} />;
  } else {
    body = (
      <Tabs defaultValue="installed">
        <TabsList aria-label="插件分类">
          <TabsTrigger value="installed" className="cursor-pointer">已安装</TabsTrigger>
          <TabsTrigger value="repo" className="cursor-pointer">仓库</TabsTrigger>
        </TabsList>
        <TabsContent value="installed">
          {installed.length === 0 ? (
            <EmptyState icon={<Boxes className="h-10 w-10 text-muted" />} title="暂无已安装插件" description="点击「安装插件」添加新插件" />
          ) : (
            <div className="space-y-2">
              {installed.map((p) => (
                <Card key={p.name} className={cn("p-4", !p.enabled && "opacity-60")}>
                  <div className="flex items-center gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-sm font-semibold">{p.name}</span>
                        {p.version && <Badge variant="default">v{p.version}</Badge>}
                        <Badge variant={p.enabled ? "success" : "default"}>
                          {p.enabled ? "启用" : "禁用"}
                        </Badge>
                      </div>
                      {p.description && <p className="mt-1 text-xs text-muted">{p.description}</p>}
                    </div>
                    <Switch
                      checked={p.enabled}
                      onCheckedChange={(v) => void handleToggle(p, v)}
                      aria-label={`${p.enabled ? "禁用" : "启用"}插件 ${p.name}`}
                    />
                  </div>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>
        <TabsContent value="repo">
          {sources.length === 0 ? (
            <EmptyState icon={<Boxes className="h-10 w-10 text-muted" />} title="暂无插件源" description="后端尚未配置任何插件仓库" />
          ) : (
            <div className="space-y-2">
              {sources.map((url) => (
                <Card key={url} className="p-3">
                  <span className="truncate font-mono text-xs text-muted" title={url}>
                    {url}
                  </span>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-6 p-6">
        {header}
        {stats}
        {body}
        <AssetsTransferSection />
      </div>

      {/* 安装弹窗 */}
      <Dialog open={installing} onOpenChange={(o) => !o && setInstalling(false)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>安装插件</DialogTitle>
          </DialogHeader>
          <label className="block">
            <span className="mb-1 block text-xs font-medium">插件名称</span>
            <Input
              value={installName}
              onChange={(e) => setInstallName(e.target.value)}
              placeholder="插件包名称"
              className="font-mono text-xs"
            />
          </label>
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setInstalling(false)} disabled={busy}>
              取消
            </Button>
            <Button variant="primary" size="sm" onClick={() => void handleInstall()} disabled={busy}>
              {busy ? "安装中..." : "安装"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
