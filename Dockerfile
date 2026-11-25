# Strategy Tribunal — controller, CLI, MCP server and web interface in one image.
#
#   docker build -t strategy-tribunal .
#   docker run --rm -p 8771:8771 -v "$PWD/work:/work" strategy-tribunal            # web interface on http://127.0.0.1:8771
#   docker run --rm -i -v "$PWD/work:/work" strategy-tribunal council start --args "Should we …?"
#   docker run --rm -i -v "$PWD/work:/work" strategy-tribunal council submit <run_id> - --request-id req_0001 < reply.json
#
# /work holds council.config.json, .council/ (settings) and council_outcomes/ (runs); mount it to keep them.
# Models are not in the image: answer requests from any chat (copy-paste or MCP), or install OpenCode on the host.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 COUNCIL_ROOT=/work

WORKDIR /opt/strategy-tribunal
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY adapters ./adapters
RUN pip install --no-cache-dir .

WORKDIR /work
COPY council.config.json /opt/strategy-tribunal/council.config.json
# first start of an empty /work: seed the project config so the controller finds its root
RUN printf '#!/bin/sh\nset -e\n[ -f /work/council.config.json ] || cp /opt/strategy-tribunal/council.config.json /work/council.config.json\nexec "$@"\n' > /usr/local/bin/entry && chmod +x /usr/local/bin/entry

EXPOSE 8771
ENTRYPOINT ["entry"]
CMD ["council", "ui", "--host", "0.0.0.0", "--port", "8771", "--no-open"]
