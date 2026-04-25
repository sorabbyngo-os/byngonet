# Byngonet Node — Docker image
# Runs on T1 servers, T2 gateways, and T3 edge devices
# Build: docker build -t byngonet-node .
# Run:   docker run --network host --env-file .env byngonet-node

FROM python:3.12-slim

LABEL org.opencontainers.image.title="Byngonet Node"
LABEL org.opencontainers.image.description="Sorabbyngo AI-native mesh network node"
LABEL org.opencontainers.image.vendor="Sorabbyngo Company"
LABEL org.opencontainers.image.source="https://github.com/sorabbyngo-Labs/byngonet"

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    iproute2 \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/byngonet

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Key and identity storage
RUN mkdir -p /etc/sorabbyngo/byngonet/keys
VOLUME ["/etc/sorabbyngo/byngonet"]

# AISP mesh port
EXPOSE 7422/udp

# Environment defaults
ENV BYNGONET_PORT=7422
ENV BYNGONET_SECRET=change-me-in-production
ENV BYNGONET_TIER=T1_X86
ENV NATS_URL=nats://localhost:4222
ENV LOG_LEVEL=INFO

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.bind(('',0)); s.close(); print('ok')" || exit 1

CMD ["python3", "byngonet_node.py"]
