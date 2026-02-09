#!/bin/bash
# Nekro-Agent Alpine Linux 适配版安装脚本
# 用于 V-OS 虚拟机环境

set -e

# 1. 参数处理
WITH_NAPCAT=$1  # 由 Python 传递 "true" 或空
BASE_URLS=(
    "https://ep.nekro.ai/e/KroMiose/nekro-agent/main/docker"
    "https://raw.githubusercontent.com/KroMiose/nekro-agent/main/docker"
)
DOCKER_IMAGE_MIRRORS=(
    "https://docker.m.daocloud.io"
    "https://docker.1ms.run"
)

# 2. 确保环境依赖 (Alpine)
echo "[1/6] 检查系统组件..."
apk add --no-cache curl jq bash openssl util-linux > /dev/null

# 3. 设置持久化数据目录
# 必须放在共享目录下，否则重启虚拟机数据丢失
NEKRO_DATA_DIR="/mnt/host_share/nekro_data"
mkdir -p "$NEKRO_DATA_DIR"
cd "$NEKRO_DATA_DIR"

# 4. 获取远程文件函数
get_remote_file() {
    local filename=$1
    local output=$2
    for base_url in "${BASE_URLS[@]}"; do
        if curl -fsSL -m 15 -o "$output" "${base_url}/${filename}"; then
            return 0
        fi
    done
    return 1
}

generate_random_string() {
    tr -dc 'a-zA-Z0-9' < /dev/urandom | fold -w "$1" | head -n 1
}

# 5. 配置环境
echo "[2/6] 正在配置环境变量..."
if [ ! -f .env ]; then
    get_remote_file .env.example .env.example
    cp .env.example .env
fi

# 注入数据目录
sed -i "s|^NEKRO_DATA_DIR=.*|NEKRO_DATA_DIR=${NEKRO_DATA_DIR}|" .env

# 生成随机密钥（如果为空）
if ! grep -q "ONEBOT_ACCESS_TOKEN=.." .env; then
    TOKEN=$(generate_random_string 32)
    sed -i "s|^ONEBOT_ACCESS_TOKEN=.*|ONEBOT_ACCESS_TOKEN=${TOKEN}|" .env
fi
if ! grep -q "NEKRO_ADMIN_PASSWORD=.." .env; then
    PASS=$(generate_random_string 16)
    sed -i "s|^NEKRO_ADMIN_PASSWORD=.*|NEKRO_ADMIN_PASSWORD=${PASS}|" .env
fi
if ! grep -q "QDRANT_API_KEY=.." .env; then
    KEY=$(generate_random_string 32)
    sed -i "s|^QDRANT_API_KEY=.*|QDRANT_API_KEY=${KEY}|" .env
fi

# 6. 获取 Docker Compose 配置
echo "[3/6] 正在拉取 Docker 编排文件..."
if [ "$WITH_NAPCAT" = "true" ]; then
    compose_file="docker-compose-x-napcat.yml"
else
    compose_file="docker-compose.yml"
fi
get_remote_file "$compose_file" docker-compose.yml

# 7. 配置 Docker 镜像加速 (如果尚未配置)
if [ ! -f /etc/docker/daemon.json ] || ! grep -q "registry-mirrors" /etc/docker/daemon.json; then
    echo "[4/6] 优化 Docker 镜像源..."
    mkdir -p /etc/docker
    # 简单的 JSON 拼接逻辑
    echo '{"registry-mirrors": ["'${DOCKER_IMAGE_MIRRORS[0]}'", "'${DOCKER_IMAGE_MIRRORS[1]}'"], "storage-driver": "overlay2"}' > /etc/docker/daemon.json
    rc-service docker restart
fi

# 8. 执行部署
echo "[5/6] 正在拉取容器镜像 (这可能需要较长时间)..."
docker compose pull

echo "[6/6] 启动 Nekro-Agent 服务..."
docker compose up -d

# 额外拉取沙盒镜像
docker pull kromiose/nekro-agent-sandbox

echo "=== DEPLOY_SUCCESS ==="
# 打印关键配置供 UI 捕获
echo "ADMIN_PASS: $(grep 'NEKRO_ADMIN_PASSWORD=' .env | cut -d'=' -f2)"
echo "ACCESS_TOKEN: $(grep 'ONEBOT_ACCESS_TOKEN=' .env | cut -d'=' -f2)"
