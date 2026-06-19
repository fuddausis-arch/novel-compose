import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import { Plus } from "lucide-react";
import { api } from "@/api";

interface Props {
  onCreate: (title: string, genre: string, summary: string, templateKey: string) => void;
}

export function CreateProjectDialog({ onCreate }: Props) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [genre, setGenre] = useState("");
  const [summary, setSummary] = useState("");
  const [templateKey, setTemplateKey] = useState("");
  const [templates, setTemplates] = useState<{ key: string; title: string }[]>([]);

  useEffect(() => {
    if (!open) return;
    api.listGenreTemplates().then(setTemplates).catch(() => setTemplates([]));
  }, [open]);

  const handleSubmit = () => {
    if (!title.trim()) return;
    onCreate(title.trim(), genre.trim(), summary.trim(), templateKey);
    setTitle("");
    setGenre("");
    setSummary("");
    setTemplateKey("");
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="primary"><Plus className="h-4 w-4 mr-1" /> 新建</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>新建项目</DialogTitle></DialogHeader>
        <div className="space-y-3 mt-2">
          <Input placeholder="项目标题" value={title} onChange={(e) => setTitle(e.target.value)} />
          <Input placeholder="类型，如：玄幻 / 科幻" value={genre} onChange={(e) => setGenre(e.target.value)} />
          <Textarea placeholder="一句话简介" value={summary} onChange={(e) => setSummary(e.target.value)} />
          <Select value={templateKey} onChange={(e) => setTemplateKey(e.target.value)}>
            <option value="">不选择模板</option>
            {templates.map((t) => (
              <option key={t.key} value={t.key}>{t.title}</option>
            ))}
          </Select>
          <Button className="w-full" onClick={handleSubmit}>创建</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
