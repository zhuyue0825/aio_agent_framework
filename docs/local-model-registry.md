# 本地模型扫描与注册

应用现在用稳定的 `model_id` 区分具体模型，而不是只保存 `local` 或 `remote`：

- `local:minimind-64m`：MiniMind 64M（768 x 8）
- `local:minimind-94m`：MiniMind 94M（768 x 12）
- `remote:deepseek`：管理员配置的 DeepSeek

每个会话保存自己的 `model_id`，创建任务时还会把它复制到运行记录中。因此，修改其他会话或刷新模型扫描结果不会改变已经创建的任务。

## 换电脑后会发现哪些模型

`agent-service` 只扫描 `MODEL_SCAN_ROOTS` 指定的只读目录，Docker Compose 默认挂载：

- `MINIMIND_WEIGHTS_HOST_PATH` → `/models/minimind`
- `HF_MODELS_HOST_PATH` → `/models/huggingface`

扫描器能识别：

- 标准 Hugging Face 目录（包含 `config.json` 和完整 Safetensors/PyTorch 权重）
- Hugging Face 尚未下载完整的分片或 `.incomplete` 文件
- GGUF 文件
- `backend/model-registry.default.json` 中登记的自定义权重（当前是两套 MiniMind `.pth`）

扫描到文件不等于能直接推理。下载完整但尚未启动推理服务的模型会显示在界面里，但会被禁用并说明原因。任意模型只要由 vLLM、MLX、llama.cpp、Ollama 的 OpenAI 兼容层或其他服务暴露 `/v1/models` 与 `/v1/chat/completions`，再把地址加入 `MODEL_RUNTIME_ENDPOINTS`，就会成为可选择模型。

例如宿主机启动了 Qwen 的 OpenAI 兼容服务：

```dotenv
HF_MODELS_HOST_PATH=/Users/your-name/Models
MODEL_RUNTIME_ENDPOINTS=http://host.docker.internal:8001/v1
MODEL_LOCAL_ALLOWED_HOSTS=minimind,minimind-94m,host.docker.internal,localhost,127.0.0.1
```

多个推理服务地址用英文逗号分隔。服务返回的每个模型都会生成稳定的本地模型 ID。

无法承诺“磁盘上的任何文件都自动可运行”：自定义 `.pth` 无法仅从文件名推断网络结构，量化格式也需要对应引擎。此类模型需要在受信任的注册表清单里描述，或先由兼容推理服务加载。

## 启动两套 MiniMind

64M 使用默认 `minimind` 服务。94M 是可选服务，避免平时同时占用两份内存：

```bash
docker compose --profile extra-models up -d minimind-94m agent-service business-service frontend
```

94M 文件默认应位于：

```text
${MINIMIND_WEIGHTS_HOST_PATH}/autodl-93m/full_sft_12l_768.pth
```

若只启动默认 Compose，94M 仍会被扫描到，但界面会显示“模型已安装，但推理服务未启动”。
