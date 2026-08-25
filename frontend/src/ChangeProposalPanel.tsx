import { Check, FileDiff, X } from "lucide-react";
import type { AgentRun } from "./api";

type Props = {
  run: AgentRun | null;
  busy: boolean;
  onApply: () => void;
  onReject: () => void;
};

export default function ChangeProposalPanel({ run, busy, onApply, onReject }: Props) {
  if (
    !run ||
    !["PROPOSED", "APPLYING", "APPLY_FAILED"].includes(run.change_status) ||
    !run.proposed_changes.length
  )
    return null;
  const applying = run.change_status === "APPLYING";
  return (
    <div className="proposal-backdrop" role="dialog" aria-modal="true" aria-label="确认 Agent 修改">
      <section className="proposal-panel">
        <header>
          <div>
            <FileDiff size={19} />
            <strong>确认 Agent 修改</strong>
          </div>
          <span>{run.proposed_changes.length} 个文件</span>
        </header>
        <p>这些修改尚未写入项目。确认时会再次校验原文件，文件已变化则拒绝覆盖。</p>
        {run.change_status === "APPLY_FAILED" && (
          <p role="alert">{run.change_error_message || "上一次写入失败，可以重新确认。"}</p>
        )}
        <div className="proposal-diffs">
          {run.proposed_changes.map((change) => (
            <article key={change.path}>
              <h3>{change.path}</h3>
              <pre>{change.diff || "（新文件或内容无变化）"}</pre>
            </article>
          ))}
        </div>
        <footer>
          <button disabled={busy || applying} className="proposal-reject" onClick={onReject}>
            <X size={16} />
            拒绝
          </button>
          <button disabled={busy || applying} className="primary" onClick={onApply}>
            <Check size={16} />
            {applying ? "正在写入" : run.change_status === "APPLY_FAILED" ? "重新写入" : "确认写入"}
          </button>
        </footer>
      </section>
    </div>
  );
}
