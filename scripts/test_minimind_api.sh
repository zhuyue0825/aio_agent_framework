#!/usr/bin/env bash
set -euo pipefail

curl -s http://127.0.0.1:8998/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"minimind","messages":[{"role":"user","content":"你好，用一句话介绍你自己。"}],"stream":false,"max_tokens":64}'
