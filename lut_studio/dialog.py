"""文件 / 文件夹选择对话框：打包后由主程序以子进程方式调用，避免在服务线程里操作 Tk。"""

import os


def run(argv):
    """argv = [mode, title, initial]；把选择结果打印到标准输出，取消时为空行"""
    mode = argv[0] if argv else 'dir'
    title = argv[1] if len(argv) > 1 else '选择'
    initial = argv[2] if len(argv) > 2 else ''
    if not os.path.isdir(initial):
        initial = os.path.expanduser('~')

    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as e:
        print(f'ERROR: {e}')
        return 1

    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    root.update()
    if mode == 'file':
        picked = filedialog.askopenfilename(
            parent=root, title=title, initialdir=initial,
            filetypes=[('视频文件', '*.mp4 *.mov *.mkv *.avi *.mxf *.webm'), ('所有文件', '*.*')])
    else:
        picked = filedialog.askdirectory(parent=root, title=title, initialdir=initial)
    root.destroy()
    print(picked or '')
    return 0
