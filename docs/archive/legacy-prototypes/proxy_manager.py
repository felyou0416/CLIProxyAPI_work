import tkinter as tk
from tkinter import ttk, messagebox
import winreg
import os
import socket
import threading
import time
import urllib.request

CHECK_PORTS = [7890, 7891, 7897, 10090, 1080, 8080]


class ProxyManager:
    def __init__(self, root):
        self.root = root
        self.root.title("代理管理器")
        self.root.geometry("550x500")
        self.root.resizable(False, False)

        self.monitor_running = False
        self.monitor_thread = None
        self.is_proxy_enabled = False

        self.create_widgets()
        self.detect_config()

    def create_widgets(self):
        style = ttk.Style()
        style.configure("Title.TLabel", font=("Microsoft YaHei", 14, "bold"))
        style.configure("Status.TLabel", font=("Microsoft YaHei", 10))
        style.configure("Success.TLabel", foreground="#006600")
        style.configure("Error.TLabel", foreground="#CC0000")
        style.configure("Info.TLabel", foreground="#0066CC")
        style.configure("Stop.TButton", foreground="red")
        style.configure("Start.TButton", foreground="green")

        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_label = ttk.Label(main_frame, text="代理管理器", style="Title.TLabel")
        title_label.pack(pady=(0, 15))

        self.status_frame = ttk.LabelFrame(main_frame, text="当前状态")
        self.status_frame.pack(fill=tk.X, pady=(0, 10))

        self.system_proxy_label = ttk.Label(self.status_frame, text="系统代理: 检测中...", style="Status.TLabel")
        self.system_proxy_label.pack(anchor=tk.W, padx=10, pady=5)

        self.env_vars_label = ttk.Label(self.status_frame, text="环境变量: 检测中...", style="Status.TLabel")
        self.env_vars_label.pack(anchor=tk.W, padx=10, pady=5)

        self.available_ports_label = ttk.Label(self.status_frame, text="可用端口: 检测中...", style="Status.TLabel")
        self.available_ports_label.pack(anchor=tk.W, padx=10, pady=5)

        self.current_port_label = ttk.Label(self.status_frame, text="当前使用端口: 无", style="Status.TLabel")
        self.current_port_label.pack(anchor=tk.W, padx=10, pady=5)

        self.test_result_label = ttk.Label(self.status_frame, text="连接测试: 未测试", style="Status.TLabel")
        self.test_result_label.pack(anchor=tk.W, padx=10, pady=5)

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=10)

        self.detect_btn = ttk.Button(button_frame, text="一键检测配置", command=self.detect_and_configure)
        self.detect_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        self.toggle_btn = ttk.Button(button_frame, text="全部取消停止", command=self.toggle_proxy)
        self.toggle_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        self.restore_btn = ttk.Button(button_frame, text="恢复默认状态", command=self.restore_default)
        self.restore_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))

        monitor_frame = ttk.LabelFrame(main_frame, text="自动监听")
        monitor_frame.pack(fill=tk.X, pady=10)

        self.monitor_var = tk.BooleanVar()
        self.monitor_check = ttk.Checkbutton(monitor_frame, text="开启自动监听（每10秒检测一次）",
                                             variable=self.monitor_var, command=self.toggle_monitor)
        self.monitor_check.pack(anchor=tk.W, padx=10, pady=5)

        self.log_text = tk.Text(main_frame, height=6, font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=5)
        self.log_text.insert(tk.END, "代理管理器已启动\n")

    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)

    def get_system_proxy(self):
        try:
            reg = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r'Software\Microsoft\Windows\CurrentVersion\Internet Settings')
            enable, _ = winreg.QueryValueEx(reg, 'ProxyEnable')
            server, _ = winreg.QueryValueEx(reg, 'ProxyServer')
            winreg.CloseKey(reg)
            return bool(enable), server
        except Exception as e:
            return False, f"读取失败: {e}"

    def set_system_proxy(self, enable, server=''):
        try:
            reg = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r'Software\Microsoft\Windows\CurrentVersion\Internet Settings',
                                 0, winreg.KEY_WRITE)
            winreg.SetValueEx(reg, 'ProxyEnable', 0, winreg.REG_DWORD, 1 if enable else 0)
            if server:
                winreg.SetValueEx(reg, 'ProxyServer', 0, winreg.REG_SZ, server)
            winreg.CloseKey(reg)
            return True
        except Exception as e:
            self.log(f"设置系统代理失败: {e}")
            return False

    def get_env_vars(self):
        vars_dict = {}
        for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']:
            vars_dict[key] = os.environ.get(key, '')
        return vars_dict

    def set_env_vars(self, proxy_url):
        import subprocess
        variables = ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']
        for var in variables:
            subprocess.run(['setx', var, proxy_url], capture_output=True)
            os.environ[var] = proxy_url

    def clear_env_vars(self):
        import subprocess
        variables = ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']
        for var in variables:
            subprocess.run(['setx', var, ''], capture_output=True)
            if var in os.environ:
                del os.environ[var]

    def check_port(self, port):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        result = s.connect_ex(('127.0.0.1', port))
        s.close()
        return result == 0

    def get_available_ports(self):
        available = []
        for port in CHECK_PORTS:
            if self.check_port(port):
                available.append(port)
        return available

    def test_connection_through_proxy(self, port):
        proxy_url = f'http://127.0.0.1:{port}'
        proxy_handler = urllib.request.ProxyHandler({'http': proxy_url, 'https': proxy_url})
        opener = urllib.request.build_opener(proxy_handler)
        try:
            req = urllib.request.Request('https://www.google.com', method='HEAD')
            resp = opener.open(req, timeout=10)
            return True, f"端口 {port} 测试成功"
        except Exception as e:
            return False, f"端口 {port} 测试失败: {str(e)[:30]}"

    def test_connection_direct(self):
        try:
            req = urllib.request.Request('https://www.google.com', method='HEAD')
            resp = urllib.request.urlopen(req, timeout=10)
            return True, f"成功 (HTTP {resp.status})"
        except Exception as e:
            return False, str(e)[:50]

    def detect_config(self):
        enable, server = self.get_system_proxy()
        self.is_proxy_enabled = enable

        if enable:
            self.system_proxy_label.config(text=f"系统代理: ✓ 已启用 ({server})", style="Success.TLabel")
            self.toggle_btn.config(text="全部取消停止")
            if ':' in server:
                port = server.split(':')[1]
                self.current_port_label.config(text=f"当前使用端口: {port}", style="Success.TLabel")
            else:
                self.current_port_label.config(text=f"当前使用端口: {server}", style="Success.TLabel")
        else:
            self.system_proxy_label.config(text="系统代理: ✗ 未启用", style="Error.TLabel")
            self.toggle_btn.config(text="启动代理")
            self.current_port_label.config(text="当前使用端口: 无", style="Error.TLabel")

        env_vars = self.get_env_vars()
        env_str = []
        for k, v in env_vars.items():
            if v:
                env_str.append(f"{k}={v}")
        if env_str:
            self.env_vars_label.config(text=f"环境变量: ✓ {', '.join(env_str)}", style="Success.TLabel")
        else:
            self.env_vars_label.config(text="环境变量: ✗ 未设置", style="Error.TLabel")

        available_ports = self.get_available_ports()
        if available_ports:
            ports_str = ", ".join([f"{p}✓" for p in available_ports])
            self.available_ports_label.config(text=f"可用端口: {ports_str}", style="Success.TLabel")
        else:
            self.available_ports_label.config(text="可用端口: 无", style="Error.TLabel")

        success, msg = self.test_connection_direct()
        if success:
            self.test_result_label.config(text=f"连接测试: ✓ {msg}", style="Success.TLabel")
        else:
            self.test_result_label.config(text=f"连接测试: ✗ {msg}", style="Error.TLabel")

        self.log("配置检测完成")

    def detect_and_configure(self):
        self.log("开始检测可用端口...")
        available_ports = self.get_available_ports()

        if not available_ports:
            messagebox.showwarning("警告", "未检测到任何可用的代理端口！\n请确保代理软件已启动。")
            self.detect_config()
            return

        self.log(f"检测到可用端口: {available_ports}")

        best_port = None
        for port in available_ports:
            self.log(f"测试端口 {port}...")
            success, msg = self.test_connection_through_proxy(port)
            if success:
                best_port = port
                self.log(f"端口 {port} 测试通过！")
                break
            else:
                self.log(msg)

        if best_port:
            proxy_url = f'http://127.0.0.1:{best_port}'
            self.set_system_proxy(True, f'127.0.0.1:{best_port}')
            self.set_env_vars(proxy_url)
            self.log(f"已配置代理到端口 {best_port}")
            self.detect_config()
            messagebox.showinfo("完成", f"已自动检测并配置代理到可用端口 {best_port}！")
        else:
            self.log("所有端口测试失败")
            self.detect_config()
            messagebox.showwarning("警告", "所有可用端口测试失败，无法自动配置代理。")

    def toggle_proxy(self):
        if self.is_proxy_enabled:
            if messagebox.askyesno("确认", "确定要停止代理吗？"):
                self.set_system_proxy(False)
                self.clear_env_vars()
                self.is_proxy_enabled = False
                self.toggle_btn.config(text="启动代理")
                self.log("代理已停止")
                self.detect_config()
                messagebox.showinfo("完成", "代理已停止，系统恢复正常状态。")
        else:
            available_ports = self.get_available_ports()
            if not available_ports:
                messagebox.showwarning("警告", "未检测到可用端口，请先启动代理软件！")
                return

            best_port = None
            for port in available_ports:
                success, _ = self.test_connection_through_proxy(port)
                if success:
                    best_port = port
                    break

            if best_port:
                proxy_url = f'http://127.0.0.1:{best_port}'
                self.set_system_proxy(True, f'127.0.0.1:{best_port}')
                self.set_env_vars(proxy_url)
                self.is_proxy_enabled = True
                self.toggle_btn.config(text="全部取消停止")
                self.log(f"代理已启动，使用端口 {best_port}")
                self.detect_config()
                messagebox.showinfo("完成", f"代理已启动，使用端口 {best_port}。")
            else:
                messagebox.showwarning("警告", "没有可用的代理端口，无法启动代理。")

    def restore_default(self):
        if messagebox.askyesno("确认", "确定要恢复默认状态吗？\n这将关闭系统代理并清除所有代理环境变量。"):
            self.set_system_proxy(False)
            self.clear_env_vars()
            self.is_proxy_enabled = False
            self.toggle_btn.config(text="启动代理")
            self.log("已恢复默认状态（关闭代理）")
            self.detect_config()
            messagebox.showinfo("完成", "已恢复默认状态，系统不再使用代理。")

    def toggle_monitor(self):
        if self.monitor_var.get():
            self.monitor_running = True
            self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
            self.monitor_thread.start()
            self.log("自动监听已开启")
        else:
            self.monitor_running = False
            self.log("自动监听已关闭")

    def monitor_loop(self):
        while self.monitor_running:
            self.root.after(0, self.detect_config)
            time.sleep(10)


if __name__ == "__main__":
    root = tk.Tk()
    app = ProxyManager(root)
    root.mainloop()
