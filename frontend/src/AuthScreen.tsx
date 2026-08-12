import { Bot, KeyRound, UserPlus } from "lucide-react";
import { useState } from "react";
import { api, type AuthResponse } from "./api";

type AuthScreenProps = {
  onAuthenticated: (session: AuthResponse) => Promise<void>;
};

export default function AuthScreen({ onAuthenticated }: AuthScreenProps) {
  const [registering, setRegistering] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!username.trim() || password.length < 8 || busy) return;
    setBusy(true);
    setError(null);
    try {
      const session = registering
        ? await api.register(username.trim(), password)
        : await api.login(username.trim(), password);
      await onAuthenticated(session);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-card">
        <div className="auth-brand-mark">
          <Bot size={28} />
        </div>
        <div className="auth-heading">
          <h1>AIO Agent</h1>
          <p>Spring Boot 业务服务 · FastAPI Agent 执行服务</p>
        </div>
        <div className="auth-tabs">
          <button className={!registering ? "active" : ""} onClick={() => setRegistering(false)}>
            <KeyRound size={15} /> 登录
          </button>
          <button className={registering ? "active" : ""} onClick={() => setRegistering(true)}>
            <UserPlus size={15} /> 注册
          </button>
        </div>
        <label className="auth-field">
          <span>用户名</span>
          <input
            autoComplete="username"
            value={username}
            placeholder="3-50 位字母、数字或 _.-"
            onChange={(event) => setUsername(event.target.value)}
          />
        </label>
        <label className="auth-field">
          <span>密码</span>
          <input
            type="password"
            autoComplete={registering ? "new-password" : "current-password"}
            value={password}
            placeholder="至少 8 位"
            onChange={(event) => setPassword(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && void submit()}
          />
        </label>
        {error ? <div className="auth-error">{error}</div> : null}
        <button
          className="primary auth-submit"
          disabled={busy || username.trim().length < 3 || password.length < 8}
          onClick={() => void submit()}
        >
          {busy ? "请稍候..." : registering ? "创建账号" : "登录"}
        </button>
        <p className="auth-note">本地首次启动可使用文档中的 bootstrap admin，也可以直接注册普通用户。</p>
      </section>
    </main>
  );
}
