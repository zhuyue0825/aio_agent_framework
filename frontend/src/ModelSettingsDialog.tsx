import { Cloud, Cpu, Eye, EyeOff, KeyRound, LoaderCircle, PlugZap, X } from "lucide-react";
import { useEffect, useState } from "react";
import {
  api,
  type ModelProvider,
  type ModelSettings,
  type ModelSettingsUpdate,
} from "./api";

type ModelSettingsDialogProps = {
  open: boolean;
  onClose: () => void;
  onSaved: (settings: ModelSettings) => Promise<void> | void;
};

export default function ModelSettingsDialog({ open, onClose, onSaved }: ModelSettingsDialogProps) {
  const [settings, setSettings] = useState<ModelSettings | null>(null);
  const [provider, setProvider] = useState<ModelProvider>("remote");
  const [remoteApiBase, setRemoteApiBase] = useState("https://api.deepseek.com");
  const [remoteModelName, setRemoteModelName] = useState("deepseek-v4-flash");
  const [remoteApiKey, setRemoteApiKey] = useState("");
  const [localApiBase, setLocalApiBase] = useState("http://host.docker.internal:8010/v1");
  const [localModelName, setLocalModelName] = useState("local-deepseek-r1-distill-qwen-1.5b");
  const [showKey, setShowKey] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setMessage(null);
    setError(null);
    setRemoteApiKey("");
    void api
      .modelSettings()
      .then((data) => {
        setSettings(data);
        setProvider(data.active_provider);
        setRemoteApiBase(data.remote.api_base);
        setRemoteModelName(data.remote.model_name);
        setLocalApiBase(data.local.api_base);
        setLocalModelName(data.local.model_name);
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, [open]);

  if (!open) return null;

  const remoteKeyReady = Boolean(remoteApiKey.trim()) || Boolean(settings?.remote.api_key_configured);
  const valid =
    Boolean(remoteApiBase.trim()) &&
    Boolean(remoteModelName.trim()) &&
    Boolean(localApiBase.trim()) &&
    Boolean(localModelName.trim()) &&
    (provider === "local" || remoteKeyReady);

  function payload(): ModelSettingsUpdate {
    return {
      active_provider: provider,
      remote_api_base: remoteApiBase.trim(),
      remote_model_name: remoteModelName.trim(),
      ...(remoteApiKey.trim() ? { remote_api_key: remoteApiKey.trim() } : {}),
      local_api_base: localApiBase.trim(),
      local_model_name: localModelName.trim(),
    };
  }

  async function save(testAfterSave: boolean) {
    if (!valid || saving) return;
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const saved = await api.updateModelSettings(payload());
      setSettings(saved);
      setRemoteApiKey("");
      await onSaved(saved);
      if (testAfterSave) {
        const result = await api.testModelSettings();
        setMessage(
          `${result.provider === "local" ? "本地模型" : "远程 API"}连接成功：${result.model_name}${result.response ? ` · ${result.response}` : ""}`,
        );
      } else {
        onClose();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="dialog-backdrop model-settings-backdrop" role="presentation">
      <section className="model-settings-dialog" role="dialog" aria-modal="true" aria-labelledby="model-settings-title">
        <header className="dialog-header">
          <div>
            <h2 id="model-settings-title">模型设置</h2>
            <p>切换本地模型或远程 OpenAI 兼容 API，下一次对话立即生效。</p>
          </div>
          <button className="icon-button" title="关闭" disabled={saving} onClick={onClose}>
            <X size={17} />
          </button>
        </header>

        {loading ? (
          <div className="model-settings-loading">
            <LoaderCircle className="spin" size={22} />
            正在读取后端配置
          </div>
        ) : (
          <div className="model-settings-body">
            <div className="provider-switch" aria-label="模型来源">
              <button className={provider === "remote" ? "active" : ""} onClick={() => setProvider("remote")}>
                <Cloud size={19} />
                <span>
                  <strong>远程 API</strong>
                  <small>DeepSeek 或其他兼容接口</small>
                </span>
              </button>
              <button className={provider === "local" ? "active" : ""} onClick={() => setProvider("local")}>
                <Cpu size={19} />
                <span>
                  <strong>本地模型</strong>
                  <small>连接电脑上的模型服务</small>
                </span>
              </button>
            </div>

            {provider === "remote" ? (
              <div className="model-form-section">
                <label>
                  <span>API 地址</span>
                  <input value={remoteApiBase} onChange={(event) => setRemoteApiBase(event.target.value)} />
                </label>
                <label>
                  <span>模型名称</span>
                  <input value={remoteModelName} onChange={(event) => setRemoteModelName(event.target.value)} />
                </label>
                <label>
                  <span>API Key</span>
                  <div className="secret-input">
                    <KeyRound size={15} />
                    <input
                      type={showKey ? "text" : "password"}
                      value={remoteApiKey}
                      autoComplete="new-password"
                      placeholder={settings?.remote.api_key_configured ? "已保存；留空表示不修改" : "粘贴 API Key"}
                      onChange={(event) => setRemoteApiKey(event.target.value)}
                    />
                    <button className="icon-button" title={showKey ? "隐藏 Key" : "显示 Key"} onClick={() => setShowKey(!showKey)}>
                      {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </label>
                <div className="settings-note">
                  Key 仅保存在后端本机文件中，权限为 600；前端不会保存或再次读取它。
                </div>
              </div>
            ) : (
              <div className="model-form-section">
                <label>
                  <span>本地 API 地址</span>
                  <input value={localApiBase} onChange={(event) => setLocalApiBase(event.target.value)} />
                </label>
                <label>
                  <span>本地模型名称</span>
                  <input value={localModelName} onChange={(event) => setLocalModelName(event.target.value)} />
                </label>
                <div className="settings-note">
                  本地服务需要提供兼容的 <code>/chat/completions</code> 接口。Docker 内默认通过 host.docker.internal 访问宿主机。
                </div>
              </div>
            )}

            {provider === "remote" && !remoteKeyReady ? (
              <div className="settings-warning">远程 API 模式需要先输入 API Key。</div>
            ) : null}
            {message ? <div className="settings-success">{message}</div> : null}
            {error ? <div className="settings-error">{error}</div> : null}
          </div>
        )}

        <footer className="model-settings-footer">
          <button disabled={saving} onClick={onClose}>取消</button>
          <button disabled={loading || saving || !valid} onClick={() => void save(true)}>
            <PlugZap size={15} />
            {saving ? "正在连接" : "保存并测试"}
          </button>
          <button className="primary" disabled={loading || saving || !valid} onClick={() => void save(false)}>
            {saving ? "正在保存" : "保存并应用"}
          </button>
        </footer>
      </section>
    </div>
  );
}
