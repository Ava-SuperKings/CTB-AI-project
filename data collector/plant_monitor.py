import serial
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.widgets import CheckButtons, Button, TextBox
from collections import deque
import time
import numpy as np
import csv
import os
from datetime import datetime

# --- 1. 配置区域 ---
COM_PORT = 'COM11'  # ⚠️ 修改你的端口
BAUD_RATE = 9600   

PRESET_LABELS = ["Fire Stimulus", "Cut Leaf", "Touch", "Lights Off", "Artifact"]
NOISE_THRESHOLD = 0.002 

# --- 2. 全局变量初始化 ---
program_start_time = time.time()

# 录制相关变量
is_recording = False 
current_run_id = 0      # 实验次数计数器
csv_file = None         # 文件句柄
csv_writer = None       # 写入器
current_filename = "Ready to Record" # 当前文件名
last_save_time_str = "---" 

# --- 3. 数据容器 ---
MAX_POINTS = 300
data_buffer = deque([0.0] * MAX_POINTS, maxlen=MAX_POINTS)
active_markers = [] 

is_auto_scale = False
last_valid_voltage = 0.0
pending_event = [None] 

# --- 4. 连接 Arduino ---
try:
    ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
    print(f"✅ 成功连接到 {COM_PORT}")
    ser.reset_input_buffer()
    time.sleep(2)
except serial.SerialException:
    print(f"❌ 无法打开端口 {COM_PORT}")
    exit()

# --- 5. 绘图初始化 ---
fig, ax = plt.subplots(figsize=(12, 8))
plt.subplots_adjust(bottom=0.35) 

line_normal, = ax.plot(range(MAX_POINTS), data_buffer, color='#007acc', linewidth=1.5, zorder=1)
line_error, = ax.plot(range(MAX_POINTS), [np.nan]*MAX_POINTS, 'r.', markersize=5, zorder=2)
current_point, = ax.plot([], [], 'ro', zorder=3) 

# === 界面文字区域 ===
# 左上角：系统状态
text_left = ax.text(0.02, 0.98, '', transform=ax.transAxes, 
                    fontsize=11, verticalalignment='top', horizontalalignment='left', family='monospace',
                    bbox=dict(boxstyle='round', facecolor='white', alpha=0.9))

# 右上角：数据统计
text_right = ax.text(0.98, 0.98, '', transform=ax.transAxes, 
                     fontsize=11, verticalalignment='top', horizontalalignment='right', family='monospace',
                     bbox=dict(boxstyle='round', facecolor='white', alpha=0.9))

# 初始标题
ax.set_title(f'Plant Monitor - Ready', fontsize=12, fontweight='bold')
ax.set_ylabel('Voltage (V)')
ax.grid(True, linestyle='--', alpha=0.6)
ax.set_ylim(0, 5)

# --- 6. 交互控件 ---

# A. [录制控制按钮] (核心修改)
rax_rec = plt.axes([0.02, 0.05, 0.12, 0.08]) 
btn_record = Button(rax_rec, 'Start REC', color='#90caf9', hovercolor='#42a5f5')

def func_record_toggle(event):
    global is_recording, current_run_id, csv_file, csv_writer, current_filename
    
    # 切换状态
    is_recording = not is_recording
    
    if is_recording:
        # === 开始录制：创建新文件 ===
        current_run_id += 1
        # 文件名格式: Run_01_20251208_1430.csv
        timestamp = datetime.now().strftime("%H%M%S")
        current_filename = f"Run_{current_run_id:02d}_{timestamp}.csv"
        
        try:
            csv_file = open(current_filename, 'w', newline='', encoding='utf-8-sig')
            csv_writer = csv.writer(csv_file)
            # 写入表头
            csv_writer.writerow(["Timestamp", "Time_Sec", "Voltage", "Event_Note"])
            print(f"🔴 开始录制: {current_filename}")
            
            # 更新按钮样式
            btn_record.label.set_text(f"STOP (Run {current_run_id})")
            btn_record.color = '#ef9a9a' 
            btn_record.hovercolor = '#e57373'
            ax.set_title(f'Recording to: {current_filename}', fontsize=12, fontweight='bold', color='red')
            
        except Exception as e:
            print(f"❌ 创建文件失败: {e}")
            is_recording = False
            
    else:
        # === 停止录制：保存并关闭文件 ===
        if csv_file:
            csv_file.close()
            csv_file = None
            csv_writer = None
            print(f"💾 文件已保存: {current_filename}")
        
        # 更新按钮样式
        btn_record.label.set_text("Start New REC")
        btn_record.color = '#90caf9'
        btn_record.hovercolor = '#42a5f5'
        ax.set_title(f'Plant Monitor - Paused (Last: {current_filename})', fontsize=12, fontweight='bold', color='black')

btn_record.on_clicked(func_record_toggle)


# [复选框] 自动缩放
rax = plt.axes([0.16, 0.08, 0.1, 0.05]) 
check = CheckButtons(rax, ['Auto Scale'], [False])
def func_check(label):
    global is_auto_scale
    if label == 'Auto Scale':
        is_auto_scale = not is_auto_scale
        if not is_auto_scale: ax.set_ylim(0, 5)
check.on_clicked(func_check)

# [按钮] 清除显示
bax = plt.axes([0.16, 0.02, 0.1, 0.05])
btn_clear = Button(bax, 'Reset View', color='lightgray', hovercolor='orange')
def func_clear(event):
    global data_buffer, last_valid_voltage, active_markers
    data_buffer.clear()
    data_buffer.extend([last_valid_voltage] * MAX_POINTS)
    for line, txt, _ in active_markers:
        line.remove(); txt.remove()
    active_markers.clear()
    print("🗑️ 视图已重置")
btn_clear.on_clicked(func_clear)

# 预设按钮
btns = []
start_x, start_y, width, gap = 0.3, 0.15, 0.12, 0.01
def make_callback(label):
    def callback(event): pending_event[0] = label 
    return callback
for i, label in enumerate(PRESET_LABELS):
    bx = plt.axes([start_x + i*(width+gap), start_y, width, 0.06])
    btn = Button(bx, label, color='#e1f5fe', hovercolor='#b3e5fc')
    btn.on_clicked(make_callback(label))
    btns.append(btn)

# 自定义输入
tax = plt.axes([0.3, 0.05, 0.4, 0.06])
text_box = TextBox(tax, 'Custom:', initial="Mark")
cax = plt.axes([0.72, 0.05, 0.15, 0.06])
btn_custom = Button(cax, 'Record Note', color='#fff9c4', hovercolor='#fff59d')
def func_custom_record(event):
    if text_box.text: pending_event[0] = text_box.text
btn_custom.on_clicked(func_custom_record)

# --- 7. 核心更新函数 ---
def update(frame):
    global last_valid_voltage, active_markers, last_save_time_str
    
    try:
        loop_limit = 10 
        while ser.in_waiting and loop_limit > 0:
            loop_limit -= 1
            raw_line = ser.readline().decode('utf-8', errors='ignore').strip()
            if not raw_line: continue
            
            try:
                voltage = float(raw_line)
                data_buffer.append(voltage)
                last_valid_voltage = voltage
                
                # 标记移动
                dead_markers = []
                for i in range(len(active_markers)):
                    active_markers[i][2] -= 1 
                    if active_markers[i][2] < 0: dead_markers.append(i)
                for i in reversed(dead_markers):
                    line, txt, _ = active_markers.pop(i)
                    line.remove(); txt.remove()

                # 事件处理
                note_to_save = ""
                if pending_event[0] is not None:
                    note_to_save = pending_event[0]
                    pending_event[0] = None 
                    init_x = MAX_POINTS - 1
                    v_line = ax.axvline(x=init_x, color='gray', linestyle='--', alpha=0.6)
                    t_lbl = ax.text(init_x, 0.9, note_to_save, 
                            transform=ax.get_xaxis_transform(),
                            rotation=90, verticalalignment='top', fontsize=9, color='purple', fontweight='bold')
                    active_markers.append([v_line, t_lbl, init_x])

                # === 核心保存逻辑 ===
                # 只有当 is_recording 为真时，且文件已打开，才写入
                if is_recording and csv_writer:
                    now = datetime.now()
                    time_str = now.strftime("%H:%M:%S.%f")[:-3]
                    # 计算相对于当前Run开始的时间，还是总程序时间？通常总时间方便对齐
                    elapsed = time.time() - program_start_time
                    
                    csv_writer.writerow([time_str, f"{elapsed:.3f}", voltage, note_to_save])
                    csv_file.flush() # 实时保存
                    last_save_time_str = now.strftime("%H:%M:%S")
                
            except ValueError:
                pass

        # 绘图 (省略重复逻辑...)
        y_data = np.array(data_buffer)
        line_normal.set_ydata(y_data)
        
        y_error = y_data.copy()
        y_error[(y_error >= 0) & (y_error <= 5)] = np.nan 
        line_error.set_ydata(y_error)
        
        current_point.set_data([MAX_POINTS-1], [last_valid_voltage])
        
        for line, txt, current_x in active_markers:
            line.set_xdata([current_x, current_x])
            txt.set_x(current_x)

        # 统计
        curr_val = last_valid_voltage
        max_val = np.max(y_data); min_val = np.min(y_data)
        amp_val = max_val - min_val
        avg_val = np.mean(y_data)
        
        trend_str, trend_c = "Wait...", "black"
        if len(y_data) >= 50:
            diffs = np.diff(list(data_buffer)[-50:])
            up = np.sum(diffs > NOISE_THRESHOLD)
            down = np.sum(diffs < -NOISE_THRESHOLD)
            if up > down + 5: trend_str, trend_c = "Rising 📈", "red"
            elif down > up + 5: trend_str, trend_c = "Falling 📉", "green"
            else: trend_str, trend_c = "Stable ➡️", "blue"

        # === 状态栏更新 ===
        # 左上角：录制状态
        if is_recording:
            status_text = f"RUN #{current_run_id}: REC 🔴\nFile: {current_filename}\nSaved: {last_save_time_str}"
            text_left.get_bbox_patch().set_edgecolor("red")
            text_left.get_bbox_patch().set_linewidth(2)
        else:
            status_text = f"RUN #{current_run_id}: PAUSED\nNext: Run_{current_run_id+1:02d}...\nSaved: {last_save_time_str}"
            text_left.get_bbox_patch().set_edgecolor("gray")
            text_left.get_bbox_patch().set_linewidth(1)
        text_left.set_text(status_text)

        # 右上角：数据
        right_str = (
            f"Current: {curr_val:.4f} V\n"
            f"Max:     {max_val:.4f} V\n"
            f"Min:     {min_val:.4f} V\n"
            f"Avg:     {avg_val:.4f} V\n"
            f"Amp:     {amp_val:.4f} V\n"
            f"-----------------\n"
            f"Trend:   {trend_str}"
        )
        text_right.set_text(right_str)
        text_right.get_bbox_patch().set_edgecolor(trend_c)
        
        if is_auto_scale:
            margin = max(amp_val * 0.1, 0.02)
            ax.set_ylim(min_val - margin, max_val + margin)

    except Exception as e:
        print(f"Error: {e}")
    
    return line_normal, line_error

def on_close(event):
    global csv_file
    if csv_file: csv_file.close()
    try: ser.close()
    except: pass
    print("❌ 结束")

fig.canvas.mpl_connect('close_event', on_close)
ani = animation.FuncAnimation(fig, update, interval=30, blit=False, cache_frame_data=False)
plt.show()
