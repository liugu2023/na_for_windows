import webview
import docker
import subprocess
import threading
import os
import time
import socket
import psutil
import multiprocessing
import sys
import atexit
import shutil

# --- 虚拟机管理逻辑 ---
class VMManager:
    def __init__(self):
        # 根据运行环境（打包或脚本）确定路径
        if getattr(sys, 'frozen', False):
            self.base_path = os.path.dirname(sys.executable)
        else:
            self.base_path = os.path.dirname(os.path.abspath(__file__))

        # 文件路径配置
        self.qemu_dir = os.path.join(self.base_path, "v-core")
        self.qemu_path = os.path.join(self.qemu_dir, "qemu-system-x86_64.exe")
        self.iso_path = os.path.join(self.qemu_dir, "alpine-docker.iso")
        self.shared_dir = os.path.join(self.base_path, "shared")

        # 确保共享目录存在
        if not os.path.exists(self.shared_dir):
            os.makedirs(self.shared_dir)

        self.vm_process = None
        self.boot_event = threading.Event() # 用于标记虚拟机启动完成
        self.host_port = 23760
        self.guest_port = 2376
        self.serial_port = 12345

        # 退出时清理
        atexit.register(self.stop_vm)

    def get_auto_resources(self):
        """自动计算最优 CPU 和内存资源"""
        cores = multiprocessing.cpu_count()
        vm_cores = max(2, cores // 2)

        total_mem = psutil.virtual_memory().total // (1024**2)
        vm_mem = max(2048, total_mem // 4) # 至少分配 2GB 以保证 Docker 流畅运行
        return vm_cores, vm_mem

    def _clean_certs(self):
        """清理旧证书以强制重新生成或避免不匹配"""
        for f in ['ca.pem', 'cert.pem', 'key.pem', 'server-cert.pem', 'server-key.pem']:
            path = os.path.join(self.shared_dir, f)
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception as e:
                    print(f"警告: 清理文件 {f} 失败: {e}")

    def start_vm(self):
        """启动 QEMU 虚拟机"""
        if not os.path.exists(self.qemu_path):
            print(f"错误: 未找到 QEMU 程序: {self.qemu_path}")
            return False

        if not os.path.exists(self.iso_path):
            print(f"错误: 未找到 ISO 镜像: {self.iso_path}")
            return False

        # 清理旧状态
        self._clean_certs()

        cores, mem = self.get_auto_resources()

        # Windows 路径处理（QEMU 使用正斜杠更安全）
        # 修复：使用相对路径 "shared" 避免 QEMU 在 Windows 下处理盘符(如 D:)出错
        safe_shared_dir = "shared"

        # QEMU 启动参数 - 针对 Alpine 优化
        cmd = [
            self.qemu_path,
            "-L", self.qemu_dir,
            "-m", str(mem),
            "-smp", f"cores={cores}",
            # "-cpu max" 在 Windows 纯模拟模式下会导致 IO-APIC 错误，改为通用的 qemu64
            "-cpu", "qemu64",
            "-cdrom", self.iso_path,
            "-boot", "d",
            # 网络: 用户模式网络 + 端口转发
            "-netdev", f"user,id=n1,hostfwd=tcp:127.0.0.1:{self.host_port}-:{self.guest_port}",
            "-device", "virtio-net-pci,netdev=n1",
            # 共享文件夹 (暴露为虚拟磁盘 /dev/vda1 或 /dev/sdb1)
            "-drive", f"file=fat:rw:{safe_shared_dir},format=raw,if=virtio",
            # 串口重定向到 TCP，避免 Windows 管道阻塞
            "-serial", f"tcp:127.0.0.1:{self.serial_port},server,nowait",
            # 添加随机数生成器，加速密钥生成，防止卡在证书生成步骤
            "-device", "virtio-rng-pci",
            "-vga", "std",
            "-no-reboot"
        ]

        print(f"正在启动虚拟机...")

        try:
            # 移除 stderr/stdout 管道，改用 TCP 读取日志，彻底解决无响应问题
            self.vm_process = subprocess.Popen(
                cmd,
                creationflags=subprocess.CREATE_NEW_CONSOLE, # 保留独立窗口
                text=True, cwd=self.base_path
            )

            # 启动日志读取线程
            threading.Thread(target=self._log_reader, daemon=True).start()

            return True
        except Exception as e:
            print(f"虚拟机启动失败: {e}")
            return False

    def _log_reader(self):
        """通过 TCP Socket 读取虚拟机串口输出，防止 Windows 管道死锁"""
        time.sleep(1) # 等待 QEMU 启动监听

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        connected = False

        # 尝试连接
        for _ in range(20):
            try:
                s.connect(('127.0.0.1', self.serial_port))
                connected = True
                break
            except:
                time.sleep(0.5)

        if not connected:
            print("警告: 无法连接到虚拟机串口日志")
            return

        try:
            buffer = ""
            while True:
                if self.vm_process and self.vm_process.poll() is not None:
                    break

                try:
                    chunk = s.recv(1024).decode('utf-8', errors='ignore')
                    if not chunk: break

                    # 关键修复：不再依赖串口日志中的 "login:" 或 "v-os ready" 判定
                    # 只有当共享目录出现证书且 Docker 能连接时，才视为真正启动成功
                    # 这里的日志读取仅用于监控内核崩溃或调试输出
                    check_content = (buffer + chunk).lower()

                    # 增加崩溃检测
                    if "Kernel panic" in chunk or "Kernel panic" in buffer + chunk:
                        print("错误: 检测到虚拟机内核崩溃 (Kernel panic)!")
                        # 可以在这里选择自动重启或停止，目前先打印错误

                    buffer += chunk

                    if '\n' in buffer:
                        lines = buffer.split('\n')
                        for line in lines[:-1]:
                            # 实时打印虚拟机日志
                            print(f"[VM]: {line.strip()}")
                        buffer = lines[-1]
                except socket.error:
                    break
        except Exception as e:
            print(f"日志读取异常: {e}")
        finally:
            s.close()

    def stop_vm(self):
        """终止虚拟机"""
        if self.vm_process and self.vm_process.poll() is None:
            print("正在停止虚拟机...")
            self.vm_process.terminate()
            try:
                self.vm_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.vm_process.kill()

# --- 前端 UI 的后端 API ---
class ProAPI:
    def __init__(self, vm_manager):
        self.vm = vm_manager
        self.docker_client = None
        self.is_connected = False
        threading.Thread(target=self._auto_connect, daemon=True).start()

    def _auto_connect(self):
        print("正在等待虚拟机启动 (等待证书生成)...")

        # 证书路径
        ca_path = os.path.join(self.vm.shared_dir, 'ca.pem')
        cert_path = os.path.join(self.vm.shared_dir, 'cert.pem')
        key_path = os.path.join(self.vm.shared_dir, 'key.pem')

        # 总超时时间 300 秒 (给足时间)
        timeout = 300
        start_time = time.time()

        while time.time() - start_time < timeout:
            # 1. 检查虚拟机进程是否意外退出
            if self.vm.vm_process and self.vm.vm_process.poll() is not None:
                print("错误: 虚拟机进程已退出，停止连接尝试")
                return

            # 2. 核心逻辑：只认证书文件
            # 这是唯一可靠的标志，证明虚拟机内部脚本已成功运行到最后
            if os.path.exists(ca_path) and os.path.exists(cert_path) and os.path.exists(key_path):
                print(">>> 检测到证书文件生成，虚拟机服务即将就绪")

                # 证书生成后，Docker 守护进程启动可能还需要几秒
                # 尝试连接，如果失败则继续循环重试
                if self._connect_docker(ca_path, cert_path, key_path):
                    self.vm.boot_event.set() # 标记为启动完成
                    return

            time.sleep(2)

        print("错误: 启动超时，未检测到证书生成。")

    def _connect_docker(self, ca, cert, key):
        # 这里的 print 稍微降噪一下，避免刷屏
        # print("正在尝试连接 Docker...")
        try:
            tls_config = docker.tls.TLSConfig(
                client_cert=(cert, key),
                ca_cert=ca,
                verify=True
            )
            # 使用 Docker SDK 连接
            client = docker.DockerClient(
                base_url=f"tcp://127.0.0.1:{self.vm.host_port}",
                tls=tls_config,
                timeout=5 # 短超时，快速失败重试
            )

            if client.ping():
                print(">>> Docker 连接成功！")
                self.docker_client = client
                self.is_connected = True
                return True
        except Exception as e:
            # 连接失败是正常的（服务还没起来），不打印错误堆栈以免吓到用户
            pass
        return False

    def get_sys_info(self):
        cpu, mem = self.vm.get_auto_resources()
        status = "已连接" if self.is_connected else "正在连接..."
        if not self.vm.vm_process: status = "已停止"
        return {
            "cpu": f"{cpu} 核",
            "mem": f"{mem} MB",
            "docker": status
        }

    def get_containers(self):
        if not self.is_connected or not self.docker_client:
            return []
        try:
            containers = self.docker_client.containers.list(all=True)
            return [{"name": c.name, "status": c.status, "image": c.image.tags[0] if c.image.tags else c.image.short_id} for c in containers]
        except Exception as e:
            print(f"获取容器列表错误: {e}")
            return []

    def open_shared_folder(self):
        if os.name == 'nt': # Windows
            os.startfile(self.vm.shared_dir)
        else:
            subprocess.Popen(['xdg-open', self.vm.shared_dir])

# --- UI 界面内容 ---
html_content = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body { background: #0d1117; color: #c9d1d9; font-family: "Microsoft YaHei", sans-serif; padding: 20px; user-select: none; }
        .header { border-bottom: 1px solid #30363d; padding-bottom: 10px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 15px; margin-bottom: 15px; }
        .btn { background: #238636; color: white; border: none; padding: 8px 15px; border-radius: 6px; cursor: pointer; transition: 0.2s; font-family: "Microsoft YaHei"; }
        .btn:hover { background: #2ea043; }
        .status-on { color: #3fb950; font-weight: bold; }
        .status-off { color: #f85149; }
        h2, h3 { margin-top: 0; }
        .container-item { padding: 8px; border-bottom: 1px solid #21262d; display: flex; justify-content: space-between; }
        .container-item:last-child { border-bottom: none; }
    </style>
</head>
<body>
    <div class="header">
        <h2>V-OS 控制台 (Alpine 版)</h2>
        <div id="quick-stats" style="font-size: 0.9em; color: #8b949e;">CPU: - | MEM: -</div>
    </div>

    <div class="card">
        <h3>系统状态</h3>
        <p>Docker 引擎: <span id="docker-status" class="status-off">正在连接...</span></p>
        <button class="btn" onclick="pywebview.api.open_shared_folder()">打开宿主机共享目录</button>
        <p style="font-size: 12px; color: #8b949e; margin-top: 8px;">
            提示: 放入 <b>shared</b> 文件夹的文件可在容器内 <b>/mnt/host_share</b> 路径访问
        </p>
    </div>

    <div class="card">
        <h3>容器列表</h3>
        <div id="clist">
            <div style="color: #8b949e; font-style: italic;">等待连接...</div>
        </div>
    </div>

    <script>
        function update() {
            pywebview.api.get_sys_info().then(d => {
                document.getElementById('quick-stats').innerText = "CPU: " + d.cpu + " | 内存: " + d.mem;
                const statusEl = document.getElementById('docker-status');
                statusEl.innerText = d.docker;
                statusEl.className = d.docker === "已连接" ? "status-on" : "status-off";
            });

            pywebview.api.get_containers().then(list => {
                const listEl = document.getElementById('clist');
                if (list.length > 0) {
                    listEl.innerHTML = list.map(c =>
                        `<div class="container-item">
                            <span><b>${c.name}</b> <span style="font-size:0.8em; color:#8b949e">(${c.image})</span></span>
                            <span style="color: ${c.status === 'running' ? '#3fb950' : '#8b949e'}">${c.status}</span>
                         </div>`
                    ).join('');
                } else {
                     pywebview.api.get_sys_info().then(d => {
                        if (d.docker === "已连接") {
                            listEl.innerHTML = '<div style="color: #8b949e; font-style: italic;">暂无运行中的容器</div>';
                        }
                     });
                }
            });
        }

        // 每2秒更新一次
        setInterval(update, 2000);
        // 初始化调用
        update();
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    # Windows 打包支持
    multiprocessing.freeze_support()

    vm = VMManager()

    if vm.start_vm():
        api = ProAPI(vm)

        # 创建窗口
        window = webview.create_window(
            'V-OS 控制台',
            html=html_content,
            js_api=api,
            width=900,
            height=600,
            resizable=True
        )

        # 启动 GUI (阻塞模式)
        webview.start(debug=True)
    else:
        print("初始化虚拟机环境失败。")
        input("按回车键退出...")
