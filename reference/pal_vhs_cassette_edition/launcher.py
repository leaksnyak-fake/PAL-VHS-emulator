"""Frozen-app entry point: freeze_support must precede application imports."""
import multiprocessing
import os

if __name__ == '__main__':
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
        os.environ[name]='1'
    multiprocessing.freeze_support()
    from pal_vhs.diagnostics import enable_fault_log
    enable_fault_log('application')
    from pal_vhs.__main__ import main
    main()
