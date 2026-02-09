import subprocess
import threading
import os
import time
import socket
import psutil
import multiprocessing
import sys
import platform
import docker
from PyQt6.QtCore import QObject, pyqtSignal


class VMManager(QObject):
    log_received = pyqtSignal(str, str)
    status_changed = pyqtSignal(str)
    boot_finished = pyqtSignal()

    def __init__(self, base_path=None):
        super().__init__()
        if base_path:
            self.base_path = os.path.abspath(base_path)
        else:
            if getattr(sys, 'frozen', False):
                self.base_path = os.path.dirname(sys.executable)
            else:
                self.base_path = os.path.dirname(os.path.abspath(__file__))
                if self.base_path.endswith('core'):
                    self.base_path = os.path.dirname(self.base_path)

        self.qemu_dir = os.path.join(self.base_path, "v-core")
        self.qemu_path = os.path.join(self.qemu_dir, "qemu-system-x86_64.exe")
        self.shared_dir = os.path.join(self.base_path, "shared")

        self.vm_process = None
        self.host_port = 23760
        self.guest_port = 2376
        self.serial_port = 12345
        self.is_running = False
        self.docker_client = None
        self.is_windows = platform.system() == "Windows"
        self.whpx_available = None  # 缓存 WHPX 检测结果

    def check_whpx_available(self):
        """检测 Windows WHPX 硬件加速是否可用"""
        if self.whpx_available is not None:
            return self.whpx_available

        if not self.is_windows:
            self.whpx_available = False
            return False

        try:
            # 尝试运行 QEMU 检测 WHPX
            result = subprocess.run(
                [self.qemu_path, "-accel", "help"],
                capture_output=True, text=True, timeout=5,
                cwd=self.qemu_dir, creationflags=subprocess.CREATE_NO_WINDOW
            )
            self.whpx_available = "whpx" in result.stdout.lower()
            if self.whpx_available:
                self.log_received.emit("检测到 WHPX 硬件加速支持", "info")
            else:
                self.log_received.emit("未检测到 WHPX，将使用软件模拟（较慢）", "warn")
        except Exception as e:
            self.log_received.emit(f"WHPX 检测失败: {e}", "debug")
            self.whpx_available = False

        return self.whpx_available

    def get_auto_resources(self):
        cores = multiprocessing.cpu_count()
        vm_cores = max(2, cores // 2)
        total_mem = psutil.virtual_memory().total // (1024**2)
        # 提高内存分配：最小 4GB，或者系统总内存的 50%
        # Docker 环境 + 镜像解压非常消耗内存，2GB 容易导致 OOM 卡死
        vm_mem = max(4096, total_mem // 2)

        # 如果系统总内存确实很小（比如小于 6GB），则保守分配避免宿主机卡死
        if total_mem < 6144:
            vm_mem = max(2048, int(total_mem * 0.6))

        self.log_received.emit(f"资源分配: CPU={vm_cores}核, RAM={vm_mem}MB", "debug")
        return vm_cores, vm_mem

    def normalize_path_for_qemu(self, path):
        """将路径转换为 QEMU 兼容格式（使用正斜杠）"""
        abs_path = os.path.abspath(path)
        # QEMU 在 Windows 上也使用正斜杠
        return abs_path.replace("\\", "/")

    def start_vm(self, iso_path=None, custom_shared_dir=None):
        if self.is_running:
            return True

        # 如果没传路径，尝试自动在 v-core 目录下找一个
        if not iso_path:
            iso_dir = os.path.join(self.base_path, "v-core")
            if os.path.exists(iso_dir):
                isos = [f for f in os.listdir(iso_dir) if f.endswith(".iso")]
                if isos:
                    iso_path = os.path.join(iso_dir, isos[0])

        if not iso_path or not os.path.exists(iso_path):
            self.log_received.emit(f"错误: 未找到镜像文件 (路径: {iso_path})", "error")
            return False

        if not os.path.exists(self.qemu_path):
            self.log_received.emit(f"错误: 未找到 QEMU 程序: {self.qemu_path}", "error")
            return False

        # 处理共享目录路径 - 确保是绝对路径
        if custom_shared_dir:
            if os.path.isabs(custom_shared_dir):
                target_shared = custom_shared_dir
            else:
                target_shared = os.path.join(self.base_path, custom_shared_dir)
        else:
            target_shared = self.shared_dir

        target_shared = os.path.abspath(target_shared)

        if not os.path.exists(target_shared):
            os.makedirs(target_shared)
            self.log_received.emit(f"创建共享目录: {target_shared}", "info")

        # 清理旧证书以确保是本次启动生成的
        for f in ['ca.pem', 'cert.pem', 'key.pem']:
            p = os.path.join(target_shared, f)
            if os.path.exists(p):
                os.remove(p)

        cores, mem = self.get_auto_resources()

        # 转换路径为 QEMU 兼容格式
        iso_path_qemu = self.normalize_path_for_qemu(iso_path)
        shared_path_qemu = self.normalize_path_for_qemu(target_shared)
        qemu_dir_qemu = self.normalize_path_for_qemu(self.qemu_dir)

        # 构建 QEMU 启动命令
        cmd = [self.qemu_path, "-L", qemu_dir_qemu, "-m", str(mem)]

        # 检测并启用硬件加速
        if self.check_whpx_available():
            cmd.extend(["-accel", "whpx", "-cpu", "max"])
            self.log_received.emit("启用 WHPX 硬件加速", "info")
        else:
            cmd.extend(["-cpu", "qemu64"])

        # 添加其他参数
        cmd.extend([
            "-smp", f"cores={cores},threads=1",
            "-cdrom", iso_path_qemu,
            "-boot", "d",
            "-netdev", f"user,id=n1,hostfwd=tcp:127.0.0.1:{self.host_port}-:{self.guest_port}",
            "-device", "virtio-net-pci,netdev=n1",
            "-drive", f"file=fat:rw:{shared_path_qemu},format=raw,if=virtio",
            "-serial", f"tcp:127.0.0.1:{self.serial_port},server,nowait",
            "-device", "virtio-rng-pci",
            "-vga", "std",
            "-no-reboot"
        ])

        self.log_received.emit(f"ISO 路径: {iso_path}", "debug")
        self.log_received.emit(f"共享目录: {target_shared}", "debug")
        self.log_received.emit(f"启动指令: {' '.join(cmd)}", "debug")

        try:
            # Windows 平台使用新控制台窗口
            popen_kwargs = {
                "text": True,
                "cwd": self.base_path
            }
            if self.is_windows:
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE

            self.vm_process = subprocess.Popen(cmd, **popen_kwargs)
            self.is_running = True
            self.status_changed.emit("启动中...")
            threading.Thread(target=self._log_reader, daemon=True).start()
            threading.Thread(target=self._wait_for_docker, args=(target_shared,), daemon=True).start()
            threading.Thread(target=self._monitor_process, daemon=True).start()
            return True
        except FileNotFoundError:
            self.log_received.emit(f"错误: 找不到 QEMU 可执行文件", "error")
            return False
        except PermissionError:
            self.log_received.emit(f"错误: 没有权限执行 QEMU", "error")
            return False
        except Exception as e:
            self.log_received.emit(f"虚拟机启动失败: {type(e).__name__}: {e}", "error")
            return False

    def _wait_for_docker(self, cert_dir):
        """轮询证书和 Docker 端口，判定启动成功"""
        self.log_received.emit("等待系统初始化并生成安全证书...", "info")
        ca = os.path.join(cert_dir, 'ca.pem')
        cert = os.path.join(cert_dir, 'cert.pem')
        key = os.path.join(cert_dir, 'key.pem')

        timeout = 300
        start = time.time()
        poll_interval = 0.5  # 初始轮询间隔（秒）
        max_poll_interval = 2.0  # 最大轮询间隔

        # 第一阶段：等待证书生成
        certs_found = False
        while time.time() - start < timeout and self.is_running:
            if os.path.exists(ca) and os.path.exists(cert) and os.path.exists(key):
                if not certs_found:
                    elapsed = time.time() - start
                    self.log_received.emit(f"证书文件已检测到 ({elapsed:.1f}s)，等待 Docker 端口开放...", "info")
                    certs_found = True
                    poll_interval = 0.3  # 证书找到后加快轮询

                # 第二阶段：检测端口连通性
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(1)
                    result = s.connect_ex(('127.0.0.1', self.host_port))
                    s.close()

                    if result == 0:
                        # 端口通了，尝试 Docker 握手
                        try:
                            tls_config = docker.tls.TLSConfig(client_cert=(cert, key), ca_cert=ca, verify=True)
                            client = docker.DockerClient(base_url=f"tcp://127.0.0.1:{self.host_port}", tls=tls_config, timeout=5)
                            if client.ping():
                                self.docker_client = client
                                elapsed = time.time() - start
                                self.log_received.emit(f"虚拟机 Docker 服务已就绪！(总耗时 {elapsed:.1f}s)", "success")
                                self.boot_finished.emit()
                                self.status_changed.emit("运行中")
                                return
                        except Exception as e:
                            self.log_received.emit(f"TLS握手重试中: {e}", "debug")
                except Exception:
                    pass

            time.sleep(poll_interval)
            # 逐渐增加轮询间隔，避免过多 CPU 消耗
            poll_interval = min(poll_interval * 1.2, max_poll_interval)

        if self.is_running:
            self.log_received.emit("启动超时，请检查控制台日志", "error")
            self.status_changed.emit("启动超时")

    def _log_reader(self):
        s = None
        # 重试连接串口，使用递增间隔
        retry_interval = 0.5
        max_retries = 20
        for attempt in range(max_retries):
            if not self.is_running:
                return
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2)
                s.connect(('127.0.0.1', self.serial_port))
                self.log_received.emit("串口连接成功", "info")
                break
            except Exception:
                if s:
                    s.close()
                    s = None
                if attempt < max_retries - 1:
                    time.sleep(retry_interval)
                    retry_interval = min(retry_interval * 1.3, 2.0)
        else:
            self.log_received.emit("串口连接失败，日志功能不可用", "warn")
            return

        try:
            s.settimeout(None)  # 切换为阻塞模式
            buffer = ""
            while self.is_running:
                chunk = s.recv(4096).decode('utf-8', errors='ignore')
                if not chunk:
                    break
                buffer += chunk
                if '\n' in buffer:
                    lines = buffer.split('\n')
                    for line in lines[:-1]:
                        if line.strip():
                            self.log_received.emit(line.strip(), "vm")
                    buffer = lines[-1]
        except Exception as e:
            if self.is_running:
                self.log_received.emit(f"串口读取断开: {e}", "debug")
        finally:
            if s:
                s.close()

    def _monitor_process(self):
        """监控QEMU进程，只有进程真正退出才更新状态"""
        if self.vm_process:
            self.vm_process.wait()
            self.is_running = False
            self.status_changed.emit("已停止")

    def stop_vm(self):
        """停止虚拟机"""
        self.is_running = False
        if self.docker_client:
            try:
                self.docker_client.close()
            except Exception:
                pass
            self.docker_client = None

        if self.vm_process and self.vm_process.poll() is None:
            self.log_received.emit("正在停止虚拟机...", "info")
            self.vm_process.terminate()
            try:
                self.vm_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.vm_process.kill()
                self.log_received.emit("强制终止虚拟机", "warn")
        self.status_changed.emit("已停止")
