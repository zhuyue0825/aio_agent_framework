import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type RichTextProps = {
  children: string;
  className?: string;
};

export default function RichText({ children, className = "" }: RichTextProps) {
  const classes = ["content", "rich-text", className].filter(Boolean).join(" ");

  return (
    <div className={classes}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          a({ children: label, node: _node, ...props }) {
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
        {children}
      </ReactMarkdown>
    </div>
  );
}
