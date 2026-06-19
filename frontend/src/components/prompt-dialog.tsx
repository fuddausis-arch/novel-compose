import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface Props {
  title: string;
  placeholder?: string;
  defaultValue?: string;
  children: React.ReactNode;
  onConfirm: (value: string) => void;
}

export function PromptDialog({ title, placeholder, defaultValue = "", children, onConfirm }: Props) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(defaultValue);

  useEffect(() => {
    setValue(defaultValue);
  }, [defaultValue, open]);

  const handleSubmit = () => {
    onConfirm(value);
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>{title}</DialogTitle></DialogHeader>
        <div className="space-y-3 mt-2">
          <Input placeholder={placeholder} value={value} onChange={(e) => setValue(e.target.value)} />
          <Button className="w-full" onClick={handleSubmit}>确认</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
