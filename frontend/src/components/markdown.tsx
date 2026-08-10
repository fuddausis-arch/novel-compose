import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { useState, type ReactNode } from "react";

// 代码块带复制按钮
function CodeBlock({ children, className }: { children: ReactNode; className?: string }) {
  const [copied, setCopied] = useState(false);
  const lang = className?.replace("language-", "") || "text";
  return (
    <div className="group relative my-3 rounded-lg overflow-hidden border border-border bg-zinc-950">
      <div className="flex items-center justify-between px-3 py-1.5 bg-zinc-800/80 text-xs text-zinc-400">
        <span>{lang}</span>
        <button
          onClick={() => {
            navigator.clipboard.writeText(typeof children === "string" ? children : "");
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }}
          className="opacity-0 group-hover:opacity-100 transition-opacity hover:text-zinc-200"
        >
          {copied ? "✓ 已复制" : "复制"}
        </button>
      </div>
      <pre className="p-3 overflow-x-auto text-sm">
        <code className={className}>{children}</code>
      </pre>
    </div>
  );
}

export function Markdown({ content }: { content: string }) {
  return (
    <div className="prose prose-sm dark:prose-invert max-w-none break-words
      prose-headings:my-2 prose-headings:first:mt-0 prose-p:my-1.5 prose-li:my-0.5
      prose-table:my-3 prose-th:px-2 prose-th:py-1 prose-td:px-2 prose-td:py-1
      prose-th:bg-muted/50 prose-pre:bg-transparent prose-pre:p-0
      prose-code:before:content-none prose-code:after:content-none
      prose-code:bg-muted/60 prose-code:px-1 prose-code:py-0.5 prose-code:rounded
      prose-blockquote:border-l-primary/40 prose-blockquote:not-italic">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          pre: ({ children }) => <>{children}</>,
          code: ({ node, className, children, ...props }: any) => {
            const isInline = !className;
            if (isInline) return <code className="rounded bg-muted/60 px-1 py-0.5 text-[0.875em]" {...props}>{children}</code>;
            return <CodeBlock className={className}>{children}</CodeBlock>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
