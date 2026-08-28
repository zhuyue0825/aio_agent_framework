import {
  CheckCircle2,
  ExternalLink,
  Eye,
  EyeOff,
  KeyRound,
  LoaderCircle,
  LockKeyhole,
  LogOut,
  Mail,
  Plus,
  RefreshCw,
  Server,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api, type McpCatalogItem, type McpServer } from "./api";

type McpServersPageProps = {
  username: string;
  onLogout: () => void;
};

export default function McpServersPage({ username, onLogout }: McpServersPageProps) {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [catalog, setCatalog] = useState<McpCatalogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [authorizationCode, setAuthorizationCode] = useState("");
  const [showCode, setShowCode] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const qqMail = servers.find((server) => server.kind === "qq_mail") ?? null;
  const qqCatalog = catalog.find((item) => item.kind === "qq_mail") ?? null;

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const response = await api.listMcpServers();
      setServers(response.servers);
      setCatalog(response.catalog);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  function replaceServer(server: McpServer) {
    setServers((current) => [server, ...current.filter((item) => item.id !== server.id)]);
  }

  async function connect() {
    if (!email.trim() || authorizationCode.trim().length < 8 || busy) return;
    setBusy("connect");
    setError(null);
    setMessage(null);
    try {
      const response = await api.connectQqMail(email.trim(), authorizationCode.trim());
      replaceServer(response.server);
      setAuthorizationCode("");
      setDialogOpen(false);
      setMessage(`QQ 邮箱 MCP Server 已连接，Agent 现在可以使用 ${response.server.tools.length} 个只读邮件工具。`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function test(server: McpServer) {
    setBusy(`test:${server.id}`);
    setError(null);
    setMessage(null);
    try {
      const response = await api.testMcpServer(server.id);
      replaceServer(response.server);
      setMessage("连接测试成功。");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      await refresh();
    } finally {
      setBusy(null);
    }
  }

  async function toggle(server: McpServer) {
    setBusy(`toggle:${server.id}`);
    setError(null);
    try {
      const response = await api.setMcpServerEnabled(server.id, !server.enabled);
      replaceServer(response.server);
      setMessage(response.server.enabled ? "QQ 邮箱工具已为 Agent 启用。" : "QQ 邮箱工具已停用，连接信息仍安全保留。");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function disconnect(server: McpServer) {
    if (!window.confirm("确定断开 QQ 邮箱吗？保存的授权码也会被删除。")) return;
    setBusy(`delete:${server.id}`);
    setError(null);
    try {
      await api.deleteMcpServer(server.id);
      setServers((current) => current.filter((item) => item.id !== server.id));
      setMessage("QQ 邮箱已断开，保存的授权码已删除。");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  function openConnectDialog() {
    setEmail("");
    setAuthorizationCode("");
    setShowCode(false);
    setError(null);
    setMessage(null);
    setDialogOpen(true);
  }

  return (
    <main className="mcp-page">
      <header className="mcp-page-header">
        <div>
          <span className="eyebrow">Agent capabilities</span>
          <h1>MCP Servers</h1>
          <p>连接外部服务，让 Agent 在明确的工具权限内读取和处理你的数据。</p>
        </div>
        <div className="mcp-header-actions">
          <div className="mcp-user-chip">
            <ShieldCheck size={15} />
            <span>{username} 的私有连接</span>
          </div>
          <button className="icon-button" title="退出登录" onClick={onLogout}>
            <LogOut size={17} />
          </button>
        </div>
      </header>

      <section className="mcp-content">
        <div className="mcp-section-title">
          <div>
            <h2>连接器</h2>
            <p>授权码保存后不再向前端或模型回显；调用工具时，模型只会看到完成请求所需的邮件内容。</p>
          </div>
          <button className="icon-button" title="刷新 MCP Servers" disabled={loading} onClick={() => void refresh()}>
            <RefreshCw className={loading ? "spin" : ""} size={17} />
          </button>
        </div>

        {error ? <div className="settings-error mcp-feedback">{error}</div> : null}
        {message ? <div className="settings-success mcp-feedback">{message}</div> : null}

        <div className="connector-grid">
          <article className={`connector-card ${qqMail?.enabled ? "connected" : ""}`}>
            <div className="connector-main-row">
              <div className="qq-mail-icon" aria-hidden="true">
                <Mail size={28} strokeWidth={2.2} />
              </div>
              <div className="connector-copy">
                <div className="connector-title-row">
                  <h3>QQ 邮箱</h3>
                  <span className="connector-type">内置 MCP</span>
                  {qqMail ? (
                    <span className={`connector-status ${qqMail.status}`}>
                      <span />
                      {qqMail.status === "connected" ? (qqMail.enabled ? "已启用" : "已停用") : "连接异常"}
                    </span>
                  ) : null}
                </div>
                <p>{qqCatalog?.description ?? "读取和搜索 QQ 邮箱中的邮件。"}</p>
                {qqMail ? <strong className="connector-account">{qqMail.account}</strong> : null}
              </div>
              {qqMail ? (
                <label className="mcp-switch">
                  <input
                    type="checkbox"
                    checked={qqMail.enabled}
                    disabled={Boolean(busy)}
                    onChange={() => void toggle(qqMail)}
                  />
                  <span aria-hidden="true" />
                  <em>{qqMail.enabled ? "启用" : "停用"}</em>
                </label>
              ) : (
                <button className="connector-add" aria-label="连接 QQ 邮箱" title="连接 QQ 邮箱" onClick={openConnectDialog}>
                  <Plus size={20} />
                  <span>连接</span>
                </button>
              )}
            </div>

            <div className="connector-tools">
              <span className="connector-tools-label">可用工具</span>
              {(qqMail?.tools ?? qqCatalog?.tools ?? []).map((tool) => (
                <span className="tool-pill" key={tool.name} title={tool.description}>
                  <LockKeyhole size={12} />
                  {tool.name.replace("qq_mail_", "")}
                </span>
              ))}
            </div>

            {qqMail ? (
              <div className="connector-footer">
                <span>
                  {qqMail.last_checked_at
                    ? `上次检查 ${new Date(qqMail.last_checked_at).toLocaleString()}`
                    : "尚未检查"}
                </span>
                <div>
                  <button disabled={Boolean(busy)} onClick={() => void test(qqMail)}>
                    {busy === `test:${qqMail.id}` ? <LoaderCircle className="spin" size={14} /> : <CheckCircle2 size={14} />}
                    测试连接
                  </button>
                  <button disabled={Boolean(busy)} onClick={openConnectDialog}>重新配置</button>
                  <button className="danger-button" disabled={Boolean(busy)} onClick={() => void disconnect(qqMail)}>
                    <Trash2 size={14} />
                    断开
                  </button>
                </div>
              </div>
            ) : null}
          </article>

          <article className="connector-card connector-coming-soon">
            <div className="connector-main-row">
              <div className="generic-server-icon"><Server size={25} /></div>
              <div className="connector-copy">
                <div className="connector-title-row">
                  <h3>自定义 MCP Server</h3>
                  <span className="connector-type">Streamable HTTP</span>
                </div>
                <p>后续可连接经过白名单校验的远程 MCP Server。</p>
              </div>
              <span className="soon-badge">下一步</span>
            </div>
          </article>
        </div>

        <aside className="mcp-security-note">
          <ShieldCheck size={18} />
          <div>
            <strong>当前版本采用只读权限</strong>
            <p>
              QQ 邮箱只提供目录查看、列出、搜索和读取工具；发送、删除、移动邮件要等逐次确认能力完成后再开放。
              使用 DeepSeek 等远程模型时，为回答问题所需的邮件内容会发送给对应模型服务；希望内容留在本机时请选择本地模型。
            </p>
          </div>
        </aside>
      </section>

      {dialogOpen ? (
        <div className="dialog-backdrop" role="presentation">
          <section className="model-settings-dialog qq-mail-dialog" role="dialog" aria-modal="true" aria-labelledby="qq-mail-title">
            <header className="dialog-header">
              <div>
                <h2 id="qq-mail-title">连接 QQ 邮箱</h2>
                <p>请使用 QQ 邮箱授权码，不要输入 QQ 登录密码。</p>
              </div>
              <button className="icon-button" title="关闭" disabled={busy === "connect"} onClick={() => setDialogOpen(false)}>
                <X size={17} />
              </button>
            </header>
            <div className="model-settings-body">
              <div className="qq-connect-intro">
                <div className="qq-mail-icon"><Mail size={24} /></div>
                <div>
                  <strong>QQ 邮箱 MCP Server</strong>
                  <span>使用加密 IMAP 连接 imap.qq.com:993</span>
                </div>
              </div>
              <div className="model-form-section">
                <label>
                  <span>QQ 邮箱地址</span>
                  <input
                    type="email"
                    value={email}
                    autoComplete="email"
                    placeholder="123456789@qq.com"
                    onChange={(event) => setEmail(event.target.value)}
                  />
                </label>
                <label>
                  <span>邮箱授权码</span>
                  <div className="secret-input">
                    <KeyRound size={15} />
                    <input
                      type={showCode ? "text" : "password"}
                      value={authorizationCode}
                      autoComplete="new-password"
                      placeholder="粘贴在 QQ 邮箱设置中生成的授权码"
                      onChange={(event) => setAuthorizationCode(event.target.value)}
                    />
                    <button className="icon-button" title={showCode ? "隐藏授权码" : "显示授权码"} onClick={() => setShowCode(!showCode)}>
                      {showCode ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </label>
                <div className="settings-note connector-secret-note">
                  <LockKeyhole size={14} />
                  授权码经 AES-GCM 加密保存，接口只返回“已配置”状态，永不回显原文。
                </div>
              </div>
              <a className="qq-help-link" href="https://mail.qq.com/" target="_blank" rel="noreferrer">
                登录 QQ 邮箱，在设置中开启 IMAP/SMTP 并生成授权码
                <ExternalLink size={14} />
              </a>
              {error ? <div className="settings-error">{error}</div> : null}
            </div>
            <footer className="model-settings-footer">
              <button disabled={busy === "connect"} onClick={() => setDialogOpen(false)}>取消</button>
              <button
                className="primary"
                disabled={busy === "connect" || !email.trim() || authorizationCode.trim().length < 8}
                onClick={() => void connect()}
              >
                {busy === "connect" ? <LoaderCircle className="spin" size={15} /> : <CheckCircle2 size={15} />}
                {busy === "connect" ? "正在测试连接" : "测试并连接"}
              </button>
            </footer>
          </section>
        </div>
      ) : null}
    </main>
  );
}
