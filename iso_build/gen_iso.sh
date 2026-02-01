#!/bin/bash
set -e

# 配置
ARCH="x86_64"
OUT_ISO="/out/alpine-docker.iso"
ROOTFS="/work/rootfs"
ISO_DIR="/work/iso"
REPO_URL="https://mirrors.aliyun.com/alpine/latest-stable/main"
REPO_COMMUNITY_URL="https://mirrors.aliyun.com/alpine/latest-stable/community"

echo "=== 1. 初始化构建环境 ==="
mkdir -p "$ROOTFS" "$ISO_DIR/boot/isolinux"

# 复制 apk 密钥
mkdir -p "$ROOTFS/etc/apk"
cp -r /etc/apk/keys "$ROOTFS/etc/apk/" || true

echo "=== 2. 构建 Alpine RootFS ==="
# 安装基础系统、内核、OpenRC、Docker 和工具
apk --root "$ROOTFS" --initdb --update-cache --no-cache \
    --repository "$REPO_URL" \
    --repository "$REPO_COMMUNITY_URL" \
    add \
    alpine-base \
    linux-virt \
    openrc \
    docker \
    util-linux \
    haveged \
    openssl \
    e2fsprogs \
    mkinitfs \
    eudev \
    bash

echo "=== 3. 配置系统服务 ==="
# 启用必要服务
for service in bootmisc hostname syslog networking haveged udev; do
    if [ -f "$ROOTFS/etc/init.d/$service" ]; then
        mkdir -p "$ROOTFS/etc/runlevels/boot"
        ln -s "/etc/init.d/$service" "$ROOTFS/etc/runlevels/boot/$service" || true
    fi
done

# 启用 udev-trigger
if [ -f "$ROOTFS/etc/init.d/udev-trigger" ]; then
     mkdir -p "$ROOTFS/etc/runlevels/sysinit"
     ln -s "/etc/init.d/udev-trigger" "$ROOTFS/etc/runlevels/sysinit/udev-trigger" || true
fi

# 关键修正：启用 cgroups (Docker 必须)
if [ -f "$ROOTFS/etc/init.d/cgroups" ]; then
     mkdir -p "$ROOTFS/etc/runlevels/sysinit"
     ln -s "/etc/init.d/cgroups" "$ROOTFS/etc/runlevels/sysinit/cgroups" || true
fi

# 启用 local 服务 (用于运行我们的 setup 脚本)
mkdir -p "$ROOTFS/etc/runlevels/default"
ln -s "/etc/init.d/local" "$ROOTFS/etc/runlevels/default/local" || true

# 允许串口 root 登录
sed -i 's/^root:!:/root::/' "$ROOTFS/etc/shadow"
sed -i 's/#ttyS0::respawn:\/sbin\/getty -L ttyS0 115200 vt100/ttyS0::respawn:\/sbin\/getty -L -n -l \/bin\/sh ttyS0 115200 vt100/' "$ROOTFS/etc/inittab"

# 配置网络
cat > "$ROOTFS/etc/network/interfaces" <<EOF
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet dhcp
EOF

# 配置 Docker daemon
mkdir -p "$ROOTFS/etc/docker"
cat > "$ROOTFS/etc/docker/daemon.json" <<EOF
{
    "hosts": ["unix:///var/run/docker.sock", "tcp://0.0.0.0:2376"],
    "tlsverify": true,
    "tlscacert": "/etc/docker/certs/ca.pem",
    "tlscert": "/etc/docker/certs/server-cert.pem",
    "tlskey": "/etc/docker/certs/server-key.pem",
    "storage-driver": "overlay2"
}
EOF

echo "=== 4. 创建自动初始化脚本 ==="
mkdir -p "$ROOTFS/etc/local.d"
cat > "$ROOTFS/etc/local.d/setup.start" <<'EOF'
#!/bin/sh

echo "V-OS: 正在初始化..." > /dev/console

# 1. 挂载宿主机共享目录
mkdir -p /mnt/host_share
# 尝试挂载虚拟磁盘 (QEMU fat:rw 或 image)
# 通常根据启动顺序为 /dev/vda1 或 /dev/vdb1
for drive in /dev/vda1 /dev/vdb1 /dev/sdb1; do
    if mount -t vfat $drive /mnt/host_share; then
        echo "已挂载共享目录于 $drive" > /dev/console
        break
    fi
done

# 2. 证书管理
CERT_DIR="/etc/docker/certs"
mkdir -p "$CERT_DIR"
SHARED_CA="/mnt/host_share/ca.pem"

if [ -f "$SHARED_CA" ]; then
    echo "检测到现有证书，正在使用..." > /dev/console
    cp /mnt/host_share/*.pem "$CERT_DIR/"
else
    echo "正在生成新证书..." > /dev/console
    cd "$CERT_DIR"

    # 生成 CA
    openssl genrsa -out ca-key.pem 2048
    openssl req -new -x509 -days 3650 -key ca-key.pem -sha256 -out ca.pem -subj "/CN=V-OS-CA"

    # 生成服务器证书
    openssl genrsa -out server-key.pem 2048
    openssl req -new -key server-key.pem -out server.csr -subj "/CN=localhost"
    echo "subjectAltName = DNS:localhost,IP:127.0.0.1,IP:10.0.2.15" > extfile.cnf
    openssl x509 -req -days 3650 -sha256 -in server.csr -CA ca.pem -CAkey ca-key.pem -CAcreateserial -out server-cert.pem -extfile extfile.cnf

    # 生成客户端证书
    openssl genrsa -out key.pem 2048
    openssl req -new -key key.pem -out client.csr -subj "/CN=client"
    echo "extendedKeyUsage = clientAuth" > extfile-client.cnf
    openssl x509 -req -days 3650 -sha256 -in client.csr -CA ca.pem -CAkey ca-key.pem -CAcreateserial -out cert.pem -extfile extfile-client.cnf

    # 将证书复制回宿主机
    cp ca.pem server-cert.pem server-key.pem cert.pem key.pem /mnt/host_share/ 2>/dev/null

    # 清理临时文件
    rm *.csr *.cnf
fi

chmod 600 "$CERT_DIR"/*-key.pem

# 3. 启动 Docker
# 因为我们没有在 boot runlevel 启用它，现在证书准备好后显式启动
echo "正在启动 Docker 服务..." > /dev/console
rc-service docker start

# 4. 发送就绪信号
echo "V-OS READY" > /dev/ttyS0
echo "V-OS 就绪" > /dev/console
EOF

chmod +x "$ROOTFS/etc/local.d/setup.start"

echo "=== 5. 配置 Init ==="
# 创建自定义 /init 脚本用于 initramfs 启动
cat > "$ROOTFS/init" <<'EOF'
#!/bin/sh
export PATH=/sbin:/usr/sbin:/bin:/usr/bin

# 挂载基础文件系统
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs none /dev
mkdir -p /dev/pts
mount -t devpts devpts /dev/pts
mount -t tmpfs -o nosuid,nodev,noexec shm /dev/shm

# 填充 /dev
if [ -x /sbin/mdev ]; then
    mdev -s
fi

# 移交给 OpenRC init
exec /sbin/init
EOF
chmod +x "$ROOTFS/init"

echo "=== 6. 打包 Initramfs ==="
# 我们将整个 rootfs 打包进 initramfs，以实现简单且稳健的 RAM 运行模式
echo "正在打包 rootfs (可能需要一点时间)..."
cd "$ROOTFS"
find . | cpio -o -H newc | gzip -9 > "$ISO_DIR/boot/initramfs"

echo "=== 7. 创建 ISO ==="
# 配置 ISOLINUX
cat > "$ISO_DIR/boot/isolinux/isolinux.cfg" <<EOF
SERIAL 0 115200
# 移除菜单界面，直接启动 (1 = 0.1秒)
PROMPT 0
TIMEOUT 1
DEFAULT alpine

LABEL alpine
    LINUX /boot/vmlinuz
    INITRD /boot/initramfs
    APPEND root=/dev/ram0 console=ttyS0,115200 noapic nolapic quiet
EOF

# 复制 syslinux 模块
cp /usr/share/syslinux/isolinux.bin "$ISO_DIR/boot/isolinux/"
cp /usr/share/syslinux/ldlinux.c32 "$ISO_DIR/boot/isolinux/"
cp /usr/share/syslinux/menu.c32 "$ISO_DIR/boot/isolinux/"
cp /usr/share/syslinux/libutil.c32 "$ISO_DIR/boot/isolinux/"
cp /usr/share/syslinux/libcom32.c32 "$ISO_DIR/boot/isolinux/"

# 复制内核
cp "$ROOTFS/boot/vmlinuz-virt" "$ISO_DIR/boot/vmlinuz"

# 生成 ISO
xorriso -as mkisofs -r -V "ALPINE_DOCKER" \
    -b boot/isolinux/isolinux.bin -c boot/isolinux/boot.cat \
    -no-emul-boot -boot-load-size 4 -boot-info-table \
    -o "${OUT_ISO}" "$ISO_DIR"

echo "构建完成: ${OUT_ISO}"
