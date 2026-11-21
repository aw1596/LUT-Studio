"""兼容入口：实现已拆分到 lut_studio 包，这里只负责启动。

用法不变：python server.py
"""

import sys

if __name__ == '__main__' and len(sys.argv) > 1 and sys.argv[1] == '--pick-dialog':
    from lut_studio.dialog import run as run_dialog

    sys.exit(run_dialog(sys.argv[2:]))

from lut_studio.main import app, main

if __name__ == '__main__':
    main()
