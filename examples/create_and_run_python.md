# Example Task

```bash
cd /private/tmp/aio_agent_framework

export MODEL_API_BASE="https://your-model-host/v1"
export MODEL_API_KEY="your-key"
export MODEL_NAME="your-model-name"
export AIO_SANDBOX_URL="http://127.0.0.1:8080"

python3 cli.py "在沙箱里创建 /home/gem/hello.py，内容是打印 hello agent framework，然后运行它，并告诉我输出"
```
