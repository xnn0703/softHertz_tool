import tkinter as tk
from tkinter import ttk, messagebox
from ui.ui_base import UIBase

class KauDC004AUI(UIBase):
    """KauDC004A设备的UI实现"""
    
    def __init__(self, master, device):
        super().__init__(master, device)
        self.master.title("softHertz串口调试工具")
        # 定义布局配置（考虑设备类型下拉框占用的列）
        self.layout_config = {
            'status_table': {'row': 1, 'column': 0, 'column_span': 7, 'padx': 10, 'pady': 10},
            'txlo_btn': {'row': 2, 'column': 0, 'padx': 10, 'pady': 10},
            'txlo_cb': {'row': 2, 'column': 1, 'padx': 10, 'pady': 10},
            'rxlo_btn': {'row': 3, 'column': 0, 'padx': 10, 'pady': 10},
            'rxlo_cb': {'row': 3, 'column': 1, 'padx': 10, 'pady': 10},
            'cmd_cb': {'row': 4, 'column': 0, 'column_span': 1, 'padx': 10, 'pady': 10},
            'param_entry': {'row': 4, 'column': 1, 'padx': 10, 'pady': 10},
            'send_btn': {'row': 4, 'column': 2, 'padx': 10, 'pady': 10},
            'text': {'row': 5, 'column': 0, 'column_span': 7, 'padx': 10, 'pady': 10},
            'device_query_btn': {'row': 6, 'column': 1, 'padx': 10, 'pady': 10},
            'clear_btn': {'row': 6, 'column': 2, 'padx': 10, 'pady': 10}
        }
        # 重新创建设备特定的UI组件
        self.create_specific_widgets()
        # 定时更新设备状态
        self.update_device_status_timer()
    
    def create_widgets(self):
        """重写创建基本UI组件，调用父类方法创建包含设备选择的基本组件"""
        # 调用父类方法创建设备选择和基本串口设置组件
        super().create_widgets()
    
    def create_specific_widgets(self):
        """创建设备特定的UI组件"""
        # 状态表格
        self.status_table = ttk.Treeview(self.master, columns=("Parameter", "Value"), show="headings", height=8)
        self.status_table.grid(row=self.layout_config['status_table']['row'], 
                              column=self.layout_config['status_table']['column'],
                              columnspan=self.layout_config['status_table']['column_span'], 
                              padx=self.layout_config['status_table']['padx'],
                              pady=self.layout_config['status_table']['pady'])
        self.status_table.heading("Parameter", text="参数")
        self.status_table.heading("Value", text="值")
        for param in ["版本", "温度", "TxLO", "RxLO", "Tx衰减", "Rx衰减", "锁定状态"]:
            self.status_table.insert("", "end", values=(param, "N/A"))
        
        # 接收本振下拉框（RxLO）
        self.rxlo_cb = ttk.Combobox(self.master, 
                                   values=self.device.get_supported_rxlo_values(), 
                                   width=25)
        self.rxlo_cb.grid(row=self.layout_config['rxlo_cb']['row'], 
                         column=self.layout_config['rxlo_cb']['column'],
                         padx=self.layout_config['rxlo_cb']['padx'], 
                         pady=self.layout_config['rxlo_cb']['pady'])
        self.rxlo_cb.set(self.device.get_supported_rxlo_values()[0])
        
        # 发射本振下拉框（TxLO）
        self.txlo_cb = ttk.Combobox(self.master, 
                                   values=self.device.get_supported_txlo_values(), 
                                   width=25)
        self.txlo_cb.grid(row=self.layout_config['txlo_cb']['row'], 
                         column=self.layout_config['txlo_cb']['column'],
                         padx=self.layout_config['txlo_cb']['padx'], 
                         pady=self.layout_config['txlo_cb']['pady'])
        self.txlo_cb.set(self.device.get_supported_txlo_values()[0])
        
        # 分开设置发射和接收本振按钮
        self.txlo_btn = ttk.Button(self.master, text="设置发射本振", command=self.set_txlo)
        self.txlo_btn.grid(row=self.layout_config['txlo_btn']['row'], 
                          column=self.layout_config['txlo_btn']['column'],
                          padx=self.layout_config['txlo_btn']['padx'], 
                          pady=self.layout_config['txlo_btn']['pady'])
        
        self.rxlo_btn = ttk.Button(self.master, text="设置接收本振", command=self.set_rxlo)
        self.rxlo_btn.grid(row=self.layout_config['rxlo_btn']['row'], 
                          column=self.layout_config['rxlo_btn']['column'],
                          padx=self.layout_config['rxlo_btn']['padx'], 
                          pady=self.layout_config['rxlo_btn']['pady'])
        
        # 命令选择
        cmd_values = [cmd for cmd in self.device.get_supported_commands() 
                      if cmd not in ["设置发射本振", "设置接收本振"]]
        self.cmd_cb = ttk.Combobox(self.master, values=cmd_values, width=25)
        self.cmd_cb.grid(row=self.layout_config['cmd_cb']['row'], 
                        column=self.layout_config['cmd_cb']['column'],
                        columnspan=self.layout_config['cmd_cb']['column_span'], 
                        padx=self.layout_config['cmd_cb']['padx'],
                        pady=self.layout_config['cmd_cb']['pady'])
        self.cmd_cb.set("本振查询")
        self.cmd_cb.bind("<<ComboboxSelected>>", self.update_input_type)
        
        self.param_entry = ttk.Entry(self.master, width=10)
        self.param_entry.grid(row=self.layout_config['param_entry']['row'], 
                             column=self.layout_config['param_entry']['column'],
                             padx=self.layout_config['param_entry']['padx'], 
                             pady=self.layout_config['param_entry']['pady'])
        self.param_entry.grid_forget()
        
        self.send_btn = ttk.Button(self.master, text="发送指令", command=self.send_command)
        self.send_btn.grid(row=self.layout_config['send_btn']['row'], 
                          column=self.layout_config['send_btn']['column'],
                          padx=self.layout_config['send_btn']['padx'], 
                          pady=self.layout_config['send_btn']['pady'])
        
        self.text = tk.scrolledtext.ScrolledText(self.master, width=80, height=10)
        self.text.grid(row=self.layout_config['text']['row'], 
                      column=self.layout_config['text']['column'],
                      columnspan=self.layout_config['text']['column_span'], 
                      padx=self.layout_config['text']['padx'],
                      pady=self.layout_config['text']['pady'])
        
        # 设备查询按钮
        self.device_query_btn = ttk.Button(self.master, text="设备查询", command=self.query_device)
        self.device_query_btn.grid(row=self.layout_config['device_query_btn']['row'], 
                                  column=self.layout_config['device_query_btn']['column'],
                                  padx=self.layout_config['device_query_btn']['padx'], 
                                  pady=self.layout_config['device_query_btn']['pady'])
        
        # 清除数据按钮
        self.clear_btn = ttk.Button(self.master, text="清除数据", command=self.clear_data)
        self.clear_btn.grid(row=self.layout_config['clear_btn']['row'], 
                          column=self.layout_config['clear_btn']['column'],
                          padx=self.layout_config['clear_btn']['padx'], 
                          pady=self.layout_config['clear_btn']['pady'])
    
    def update_input_type(self, event):
        """根据选择的命令更新输入类型"""
        cmd = self.cmd_cb.get()
        self.param_entry.grid_forget()
        if cmd in ("发射衰减设置", "接收衰减设置"):
            self.param_entry.grid(row=self.layout_config['param_entry']['row'], 
                                 column=self.layout_config['param_entry']['column'],
                                 padx=self.layout_config['param_entry']['padx'], 
                                 pady=self.layout_config['param_entry']['pady'])
    
    def set_txlo(self):
        """设置发射本振"""
        if not self.device.is_connected():
            messagebox.showwarning("未连接", "请先打开串口")
            return        
        success, msg = self.device.send_command("设置发射本振", self.txlo_cb.get())
        if success:
            self.log_message(msg)
        else:
            messagebox.showerror("发送错误", msg)
    
    def set_rxlo(self):
        """设置接收本振"""
        if not self.device.is_connected():
            messagebox.showwarning("未连接", "请先打开串口")
            return        
        success, msg = self.device.send_command("设置接收本振", self.rxlo_cb.get())
        if success:
            self.log_message(msg)
        else:
            messagebox.showerror("发送错误", msg)
    
    def send_command(self):
        """发送命令"""
        if not self.device.is_connected():
            messagebox.showwarning("未连接", "请先打开串口")
            return
        
        cmd = self.cmd_cb.get()
        param = None
        if cmd in ("发射衰减设置", "接收衰减设置"):
            param = self.param_entry.get().strip()
            if not param:
                messagebox.showwarning("参数为空", "请输入参数值")
                return
        
        success, msg = self.device.send_command(cmd, param)
        if success:
            self.log_message(msg)
        else:
            messagebox.showerror("发送错误", msg)
    
    def query_device(self):
        """查询设备信息"""
        if not self.device.is_connected():
            messagebox.showwarning("未连接", "请先打开串口")
            return
        
        self.device.query_device_info()
        self.log_message("开始查询设备信息...")
    
    def clear_data(self):
        """清除数据"""
        # 清除文本显示
        self.text.delete('1.0', tk.END)
        # 重置状态表格
        for iid in self.status_table.get_children():
            param = self.status_table.item(iid, 'values')[0]
            self.status_table.item(iid, values=(param, "N/A"))
        
        # 记录日志
        self.log_message("已清除所有数据和缓存")
    
    def update_device_status_timer(self):
        """定时更新设备状态"""
        if self.device.is_connected():
            device_info = self.device.device_info
            # 更新状态表格
            self.status_table.item(self.status_table.get_children()[0], 
                                  values=("版本", f"{device_info['version']}"))
            self.status_table.item(self.status_table.get_children()[1], 
                                  values=("温度", f"{device_info['temperature']}°C"))
            self.status_table.item(self.status_table.get_children()[2], 
                                  values=("TxLO", f"{device_info['txlo']} MHz"))
            self.status_table.item(self.status_table.get_children()[3], 
                                  values=("RxLO", f"{device_info['rxlo']} MHz"))
            self.status_table.item(self.status_table.get_children()[4], 
                                  values=("Tx衰减", f"{device_info['tx_attenuation']:.1f} dB"))
            self.status_table.item(self.status_table.get_children()[5], 
                                  values=("Rx衰减", f"{device_info['rx_attenuation']:.1f} dB"))
            self.status_table.item(self.status_table.get_children()[6], 
                                  values=("锁定状态", device_info['lock_status']))
        
        # 继续定时更新
        self.master.after(500, self.update_device_status_timer)
    
    def log_message(self, msg):
        """在日志区域显示消息"""
        self.text.insert(tk.END, msg + "\n")
        self.text.see(tk.END)