"""Best-effort file diagnostics; logging must never prevent startup/rendering."""
from pathlib import Path
import faulthandler
import logging
from logging.handlers import RotatingFileHandler
import os
import sys

_FAULT_FILES = []


def log_directory():
    configured = os.environ.get('PAL_VHS_LOG_DIR')
    if configured:
        return Path(configured)
    base = Path(os.environ['LOCALAPPDATA']) if os.environ.get('LOCALAPPDATA') else Path.home()/'.cache'
    return base/'PAL-VHS'/'logs'


def logger():
    log = logging.getLogger('pal_vhs')
    if not log.handlers:
        log.setLevel(logging.INFO)
        try:
            folder = log_directory()
            folder.mkdir(parents=True,exist_ok=True)
            handler = RotatingFileHandler(folder/f'render-{os.getpid()}.log',
                                          maxBytes=2_000_000,backupCount=2,encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(asctime)s %(process)d %(threadName)s %(levelname)s %(message)s'))
            log.addHandler(handler)
        except OSError:
            log.addHandler(logging.NullHandler())
    return log


def enable_fault_log(role):
    try:
        folder = log_directory()
        folder.mkdir(parents=True,exist_ok=True)
        stream = (folder/f'{role}-fault-{os.getpid()}.log').open('a',encoding='utf-8')
        faulthandler.enable(file=stream,all_threads=True)
        _FAULT_FILES.append(stream)  # faulthandler retains the descriptor, not ownership
    except (OSError,RuntimeError):
        pass
    logger().info('Startup role=%s frozen=%s python=%s',role,bool(getattr(sys,'frozen',False)),sys.version.split()[0])
