FROM alpine/git:2.49.1 AS source

ARG MINIMIND_REPOSITORY=https://github.com/jingyaogong/minimind.git
ARG MINIMIND_REVISION=512eed0b6556e741d80864f054d45d271459772a

RUN git init /src \
    && git -C /src remote add origin "${MINIMIND_REPOSITORY}" \
    && git -C /src fetch --depth 1 origin "${MINIMIND_REVISION}" \
    && git -C /src checkout --detach FETCH_HEAD \
    && test "$(git -C /src rev-parse HEAD)" = "${MINIMIND_REVISION}" \
    && rm -rf /src/.git

FROM python:3.12-slim-bookworm

ENV HF_HOME=/tmp/minimind/huggingface \
    HOME=/tmp/minimind \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt /tmp/minimind-requirements.txt
RUN python -m pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        torch==2.12.1+cpu \
    && python -m pip install --no-cache-dir -r /tmp/minimind-requirements.txt \
    && rm /tmp/minimind-requirements.txt \
    && groupadd --system --gid 10002 minimind \
    && useradd --system --uid 10002 --gid 10002 --home-dir /tmp/minimind --no-create-home minimind

COPY --from=source --chown=10002:10002 /src /opt/minimind

WORKDIR /opt/minimind/scripts
USER 10002:10002
EXPOSE 8998

CMD ["python", "serve_openai_api.py", "--weight", "full_sft", "--device", "cpu"]
