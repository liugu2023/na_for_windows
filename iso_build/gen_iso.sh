#!/bin/bash
set -e

# 配置
ARCH="x86_64"
ROOTFS="/work/rootfs"
ISO_DIR="/work/iso"
DATA_DIR="$ISO_DIR/nekro_data" # 放在 ISO 根目录，不进 initramfs
REPO_URL="https://mirrors.aliyun.com/alpine/latest-stable/main"
REPO_COMMUNITY_URL="https://mirrors.aliyun.com/alpine/latest-stable/community"

# 基础镜像
DOCKER_IMAGES=(
    "postgres:14"
    "qdrant/qdrant"
    "kromiose/nekro-agent:latest"
    "kromiose/nekro-agent-sandbox:latest"
)

if [ "$BUILD_MODE" = "napcat" ]; then
    echo "=== 正在构建 [Napcat 版] ==="
    OUT_ISO="/out/alpine-docker-napcat.iso"
    DOCKER_IMAGES+=("mlikiowa/napcat-docker:latest")
    USE_NAPCAT="true"
else
    echo "=== 正在构建 [精简版] ==="
    OUT_ISO="/out/alpine-docker-lite.iso"
    USE_NAPCAT="false"
fi

echo "=== 1. 初始化构建环境 ==="
rm -rf "$ROOTFS" "$ISO_DIR"
mkdir -p "$ROOTFS" "$ISO_DIR/boot/isolinux" "$DATA_DIR/images" "$DATA_DIR/compose"

# 复制 apk 密钥
mkdir -p "$ROOTFS/etc/apk"
cp -r /etc/apk/keys "$ROOTFS/etc/apk/" || true

echo "=== 2. 拉取并保存 Docker 镜像到 ISO (外部存储) ==="
for img in "${DOCKER_IMAGES[@]}"; do
    echo "拉取镜像: $img"
    docker pull "$img"
done

echo "导出镜像到 ISO 数据区..."
docker save "${DOCKER_IMAGES[@]}" -o "$DATA_DIR/images/nekro-images.tar"

echo "=== 3. 复制配置到 ISO 数据区 ==="
cp /compose/docker-compose.yml "$DATA_DIR/compose/"
cp /compose/docker-compose-napcat.yml "$DATA_DIR/compose/"
cp /compose/env.template "$DATA_DIR/compose/"
echo "$USE_NAPCAT" > "$ROOTFS/etc/nekro_default_napcat"

echo "=== 4. 构建精简版 Alpine RootFS (仅基础系统) ==="
apk --root "$ROOTFS" --initdb --update-cache --no-cache \
    --repository "$REPO_URL" \
    --repository "$REPO_COMMUNITY_URL" \
    add \
    alpine-base \
    linux-virt \
    openrc \
    docker \
    docker-cli-compose \
    util-linux \
    haveged \
    openssl \
    e2fsprogs \
    mkinitfs \
    eudev \
    bash

echo "=== 5. 配置系统服务 ==="
for service in bootmisc hostname syslog networking haveged udev; do
    [ -f "$ROOTFS/etc/init.d/$service" ] && ln -s "/etc/init.d/$service" "$ROOTFS/etc/runlevels/boot/$service" || true
done
ln -s "/etc/init.d/udev-trigger" "$ROOTFS/etc/runlevels/sysinit/udev-trigger" || true
ln -s "/etc/init.d/cgroups" "$ROOTFS/etc/runlevels/sysinit/cgroups" || true
ln -s "/etc/init.d/local" "$ROOTFS/etc/runlevels/default/local" || true

sed -i 's/^root:!:/root::/' "$ROOTFS/etc/shadow"
# 配置登录终端 (直接追加到 inittab，避免 sed 模式匹配问题)
cat >> "$ROOTFS/etc/inittab" <<'INITTAB'

# Serial console (用于 QEMU 串口输出)
ttyS0::respawn:/sbin/getty -L 115200 ttyS0 vt100

# Virtual consoles
tty1::respawn:/sbin/getty 38400 tty1
tty2::respawn:/sbin/getty 38400 tty2
INITTAB

# 配置网络
cat > "$ROOTFS/etc/network/interfaces" <<EOF
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet dhcp
EOF

echo "=== 6. 创建自动初始化脚本 (支持从 CDROM 读取数据) ==="
mkdir -p "$ROOTFS/etc/local.d"
cat > "$ROOTFS/etc/local.d/setup.start" <<'EOF'
#!/bin/sh

SHARED_DIR="/mnt/host_share"
DATA_DIR="$SHARED_DIR/nekro_data"
CDROM_DIR="/mnt/cdrom"
CERT_DIR="/etc/docker/certs"

log() {
    echo "V-OS: $1" > /dev/console
    echo "$1" > /dev/ttyS0
}

# Run initialization in background so boot continues
(
    log "系统启动中 (后台初始化)..."

    # 1. 挂载 9pfs 或共享目录
    mkdir -p "$SHARED_DIR"
    mount -t 9p -o trans=virtio,version=9p2000.L hostshare "$SHARED_DIR" 2>/dev/null || \
    mount -t vfat /dev/vda1 "$SHARED_DIR" 2>/dev/null || true

    # 2. 挂载光驱以获取预包装数据
    mkdir -p "$CDROM_DIR"
    mount -t iso9660 /dev/cdrom "$CDROM_DIR" 2>/dev/null || \
    mount -t iso9660 /dev/sr0 "$CDROM_DIR" 2>/dev/null || true

    # 3. 证书与环境准备
    mkdir -p "$CERT_DIR"

    # [关键修复] 强制覆盖 Docker 配置，确保监听 TCP 2376
    cat > /etc/conf.d/docker <<DOCKER_CONF
DOCKER_OPTS="--tlsverify --tlscacert=/etc/docker/certs/ca.pem --tlscert=/etc/docker/certs/server-cert.pem --tlskey=/etc/docker/certs/server-key.pem -H fd:// -H tcp://0.0.0.0:2376"
DOCKER_CONF

    if [ ! -f "$SHARED_DIR/ca.pem" ]; then
        cd "$CERT_DIR"
        openssl genrsa -out ca-key.pem 2048 2>/dev/null
        openssl req -new -x509 -days 3650 -key ca-key.pem -sha256 -out ca.pem -subj "/CN=V-OS-CA" 2>/dev/null
        openssl genrsa -out server-key.pem 2048 2>/dev/null
        openssl req -new -key server-key.pem -out server.csr -subj "/CN=localhost" 2>/dev/null
        echo "subjectAltName = DNS:localhost,IP:127.0.0.1,IP:10.0.2.15" > extfile.cnf
        openssl x509 -req -days 3650 -sha256 -in server.csr -CA ca.pem -CAkey ca-key.pem -CAcreateserial -out server-cert.pem -extfile extfile.cnf 2>/dev/null
        openssl genrsa -out key.pem 2048 2>/dev/null
        openssl req -new -key key.pem -out client.csr -subj "/CN=client" 2>/dev/null
        echo "extendedKeyUsage = clientAuth" > extfile-client.cnf
        openssl x509 -req -days 3650 -sha256 -in client.csr -CA ca.pem -CAkey ca-key.pem -CAcreateserial -out cert.pem -extfile extfile-client.cnf 2>/dev/null
        cp *.pem "$SHARED_DIR/" 2>/dev/null || true
    fi

    # 4. 启动 Docker (强制重启以加载新配置) 并从 CDROM 加载镜像
    rc-service docker restart
    for i in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 1; done
    if ! docker info >/dev/null 2>&1; then
        log "错误: Docker 服务启动失败，请检查 /etc/conf.d/docker"
    fi

    VERSION_TAG=$(cat /etc/nekro_default_napcat)
    if [ -z "$(docker images -q kromiose/nekro-agent:latest 2>/dev/null)" ]; then
        log "正在从光盘恢复系统环境 (约 1 分钟)..."
        if [ -f "$CDROM_DIR/nekro_data/images/nekro-images.tar" ]; then
            docker load -i "$CDROM_DIR/nekro_data/images/nekro-images.tar"
            log "系统环境恢复完成"
        fi
    fi

    # 5. 启动服务
    mkdir -p "$DATA_DIR"
    [ ! -f "$DATA_DIR/.env" ] && cp "$CDROM_DIR/nekro_data/compose/env.template" "$DATA_DIR/.env"

    COMPOSE_SRC="$CDROM_DIR/nekro_data/compose/docker-compose.yml"
    [ "$VERSION_TAG" = "true" ] && COMPOSE_SRC="$CDROM_DIR/nekro_data/compose/docker-compose-napcat.yml"

    log "正在启动 Nekro 服务..."
    docker compose -f "$COMPOSE_SRC" --env-file "$DATA_DIR/.env" up -d

    log "V-OS READY"
    echo "V-OS READY" > /dev/ttyS0
) &

exit 0

EOF

chmod +x "$ROOTFS/etc/local.d/setup.start"

echo "=== 6.5. 配置 Init 引导脚本 ==="
cat > "$ROOTFS/init" <<'EOF'
#!/bin/sh
export PATH=/sbin:/usr/sbin:/bin:/usr/bin
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs none /dev
mkdir -p /dev/pts
mount -t devpts devpts /dev/pts
mount -t tmpfs -o nosuid,nodev,noexec shm /dev/shm
if [ -x /sbin/mdev ]; then mdev -s; fi
exec /sbin/init
EOF
chmod +x "$ROOTFS/init"

echo "=== 7. 打包轻量级 Initramfs ==="
cd "$ROOTFS"
# 确保 init 存在并有执行权限
if [ ! -f "init" ]; then
    echo "错误: 未找到 init 脚本!"
    exit 1
fi
chmod +x init

# 确保 /bin/sh 等基础工具存在
if [ ! -f "bin/sh" ]; then
    echo "警告: /bin/sh 不存在，系统可能无法启动"
fi

# 关键修复：先将内核复制到 ISO 目录，再清理 boot
echo "正在提取内核..."
if [ -f "boot/vmlinuz-virt" ]; then
    cp "boot/vmlinuz-virt" "$ISO_DIR/boot/vmlinuz"
else
    echo "错误: 未找到内核文件 boot/vmlinuz-virt"
    exit 1
fi

# 移除冗余文件以减小 initramfs 体积
rm -rf boot/* 2>/dev/null || true

# 使用最稳健的打包方式：不含 ./ 前缀
find * -print0 | cpio --null -ov -H newc | gzip -1 > "$ISO_DIR/boot/initramfs"
du -sh "$ISO_DIR/boot/initramfs"

echo "=== 8. 创建 ISO (包含外部数据区) ==="
cat > "$ISO_DIR/boot/isolinux/isolinux.cfg" <<EOF
SERIAL 0 115200
PROMPT 0
TIMEOUT 1
DEFAULT alpine

LABEL alpine
    LINUX /boot/vmlinuz
    APPEND initrd=/boot/initramfs console=ttyS0,115200 rdinit=/init noapic nolapic
EOF

cp /usr/share/syslinux/*.c32 "$ISO_DIR/boot/isolinux/"
cp /usr/share/syslinux/isolinux.bin "$ISO_DIR/boot/isolinux/"
# cp "$ROOTFS/boot/vmlinuz-virt" "$ISO_DIR/boot/vmlinuz" # 已提前复制，注释掉此行

xorriso -as mkisofs -r -V "NEKRO_VOS" \
    -b boot/isolinux/isolinux.bin -c boot/isolinux/boot.cat \
    -no-emul-boot -boot-load-size 4 -boot-info-table \
    -o "${OUT_ISO}" "$ISO_DIR"

echo "=== 构建完成: ${OUT_ISO} ==="
