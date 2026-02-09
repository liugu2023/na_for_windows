import subprocess
import threading
import os
import time
import socket
import psutil
import multiprocessing
import sys
import docker
from PyQt6.QtCore import QObject, pyqtSignal

class VMManager(QObject):
    log_received = pyqtSignal(str, str)
    status_changed = pyqtSignal(str)
    boot_finished = pyqtSignal()

    def __init__(self, base_path=None):
        super().__init__()
        if base_path:
            self.base_path = base_path
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
            self.log_received.emit(f"错误: 未找到镜像文件", "error")
            return False

        if not os.path.exists(self.qemu_path):
            self.log_received.emit(f"错误: 未找到 QEMU 程序: {self.qemu_path}", "error")
            return False

        target_shared = custom_shared_dir if custom_shared_dir else self.shared_dir
        if not os.path.exists(target_shared):
            os.makedirs(target_shared)

        # 清理旧证书以确保是本次启动生成的
        for f in ['ca.pem', 'cert.pem', 'key.pem']:
            p = os.path.join(target_shared, f)
            if os.path.exists(p): os.remove(p)

        cores, mem = self.get_auto_resources()

        cmd = [
            self.qemu_path, "-L", self.qemu_dir, "-m", str(mem),
            "-smp", f"cores={cores}", "-cpu", "qemu64", "-cdrom", iso_path,
            "-boot", "d", "-netdev", f"user,id=n1,hostfwd=tcp:127.0.0.1:{self.host_port}-:{self.guest_port}",
            "-device", "virtio-net-pci,netdev=n1",
            "-drive", f"file=fat:rw:{target_shared},format=raw,if=virtio",
            "-serial", f"tcp:127.0.0.1:{self.serial_port},server,nowait",
            "-device", "virtio-rng-pci", "-vga", "std", "-no-reboot"
        ]

        self.log_received.emit(f"启动指令: {' '.join(cmd)}", "debug")

        try:
            # 调试阶段：显示控制台窗口以便观察
            self.vm_process = subprocess.Popen(
                cmd, creationflags=subprocess.CREATE_NEW_CONSOLE,
                text=True, cwd=self.base_path
            )
            self.is_running = True
            self.status_changed.emit("启动中...")
            threading.Thread(target=self._log_reader, daemon=True).start()
            threading.Thread(target=self._wait_for_docker, args=(target_shared,), daemon=True).start()
            threading.Thread(target=self._monitor_process, daemon=True).start()
            return True
        except Exception as e:
            self.log_received.emit(f"虚拟机启动失败: {e}", "error")
            return False

    def _wait_for_docker(self, cert_dir):
        """轮询证书和 Docker 端口，判定启动成功"""
        self.log_received.emit("等待系统初始化并生成安全证书...", "info")
        ca = os.path.join(cert_dir, 'ca.pem')
        cert = os.path.join(cert_dir, 'cert.pem')
        key = os.path.join(cert_dir, 'key.pem')

        timeout = 300
        start = time.time()

        # 第一阶段：等待证书生成
        certs_found = False
        while time.time() - start < timeout and self.is_running:
            if os.path.exists(ca) and os.path.exists(cert) and os.path.exists(key):
                if not certs_found:
                    self.log_received.emit("证书文件已检测到，等待 Docker 端口开放...", "info")
                    certs_found = True

                # 第二阶段：检测端口连通性
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(2)
                    result = s.connect_ex(('127.0.0.1', self.host_port))
                    s.close()

                    if result == 0:
                        # 端口通了，尝试 Docker 握手
                        try:
                            tls_config = docker.tls.TLSConfig(client_cert=(cert, key), ca_cert=ca, verify=True)
                            client = docker.DockerClient(base_url=f"tcp://127.0.0.1:{self.host_port}", tls=tls_config, timeout=5)
                            if client.ping():
                                self.docker_client = client
                                self.log_received.emit("虚拟机 Docker 服务已就绪！", "success")
                                self.boot_finished.emit()
                                self.status_changed.emit("运行中")
                                return
                        except Exception as e:
                            self.log_received.emit(f"TLS握手失败: {e}", "warn")

                            # 诊断逻辑
                            try:
                                # Test 1: Socket Check
                                s_diag = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                                s_diag.settimeout(1)
                                if s_diag.connect_ex(('127.0.0.1', self.host_port)) == 0:
                                    # Test 2: HTTP vs HTTPS
                                    try:
                                        s_diag.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
                                        resp = s_diag.recv(1024)
                                        if b"Client sent an HTTP request to an HTTPS server" in resp:
                                            self.log_received.emit("诊断: 端口开放且检测到HTTPS服务(正常)", "debug")
                                        else:
                                            self.log_received.emit(f"诊断: 端口响应但不符合预期: {resp[:60]}", "warn")
                                    except Exception:
                                        self.log_received.emit("诊断: 端口开放但无法读取响应", "warn")
                                else:
                                    self.log_received.emit("诊断: 端口连接被拒绝", "error")
                                s_diag.close()
                            except Exception as se:
                                self.log_received.emit(f"诊断: Socket检查异常: {se}", "error")

                            # Test 3: Certificate Validation
                            try:
                                c_exists = os.path.exists(cert) and os.path.getsize(cert) > 0
                                k_exists = os.path.exists(key) and os.path.getsize(key) > 0
                                if not (c_exists and k_exists):
                                    self.log_received.emit(f"诊断: 证书文件异常 (Cert: {c_exists}, Key: {k_exists})", "error")
                            except Exception:
                                pass

                            # 可能是服务刚起，证书还没加载完，继续重试
                    else:
                        # 端口不通，说明 Docker 还没监听
                        pass
                except Exception as e:
                    pass

            time.sleep(2)

        if self.is_running:
            self.log_received.emit("启动超时，请检查控制台日志", "error")

    def _log_reader(self):
        s = None
        # 重试连接串口，最多等待30秒
        for attempt in range(15):
            if not self.is_running:
                return
            time.sleep(2)
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect(('127.0.0.1', self.serial_port))
                self.log_received.emit("串口连接成功", "info")
                break
            except Exception as e:
                if s:
                    s.close()
                    s = None
                if attempt < 14:
                    self.log_received.emit(f"串口连接重试中... ({attempt + 1}/15)", "debug")
        else:
            self.log_received.emit("串口连接失败，日志功能不可用", "warn")
            return

        try:
            buffer = ""
            while self.is_running:
                chunk = s.recv(1024).decode('utf-8', errors='ignore')
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
        self.is_running = False
        if self.vm_process and self.vm_process.poll() is None:
            self.vm_process.terminate()
