export const cleanGeneratedText = (text: string) => {
  if (!text) return "";
  let s = text;
  // 去掉 markdown 章节标题行
  s = s.replace(/^#+\s*第[\d一二三四五六七八九十百千万]+章[：:\s]*.*$/m, "");
  // 去掉 --- 分隔线
  s = s.replace(/^\s*---+\s*$/gm, "");
  // 去掉 markdown 加粗/斜体但保留文字
  s = s.replace(/\*\*(.+?)\*\*/g, "$1");
  s = s.replace(/(^|[^*])\*([^*]+)\*(?![*])/g, "$1$2");
  // 合并连续空行
  s = s.replace(/\n{3,}/g, "\n\n");
  return s.trim();
};
