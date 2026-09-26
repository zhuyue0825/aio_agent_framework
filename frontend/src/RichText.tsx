import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Evidence } from "./api";

type RichTextProps = {
  children: string;
  className?: string;
  sources?: Evidence[];
  onSource?: (source: Evidence) => void;
};

export default function RichText({ children, className = "", sources = [], onSource }: RichTextProps) {
  const classes = ["content", "rich-text", className].filter(Boolean).join(" ");

  return (
    <div className={classes}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          a({ children: label, node: _node, ...props }) {
            const source = sources.find(s=>props.href === `#source-${s.evidence_id}`);
            if(source && onSource) return <button className="inline-citation" onClick={()=>onSource(source)}>{label}</button>;
            return (
              <a {...props} target="_blank" rel="noopener noreferrer">
                {label}
              </a>
            );
          },
          img({ alt, node: _node }) {
            return <span className="rich-text-image-placeholder">[图片：{alt || "外部图片"}]</span>;
          },
        }}
      >
        {children.replace(/\[(E\d+)\](?!\()/g,(match,id)=>sources.some(s=>s.evidence_id===id)?`[${id}](#source-${id})`:match)}
      </ReactMarkdown>
    </div>
  );
}
