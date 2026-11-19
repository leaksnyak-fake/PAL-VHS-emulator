"""Worker-death regression tests, including an actual abrupt child exit."""
import os
from pathlib import Path
os.environ['PAL_VHS_LOG_DIR'] = str(Path(__file__).resolve().parents[1]/'validation'/'test_logs')
import unittest
from unittest.mock import patch
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
import numpy as np
from pal_vhs.pipeline import Renderer,_deck_for
from pal_vhs.params import Params


def crash_child():
    os._exit(91)


class RendererRecoveryTests(unittest.TestCase):
    def test_real_abrupt_child_exit_recovers_and_renders(self):
        rend=Renderer(1,backend='process')
        try:
            with self.assertRaises(BrokenProcessPool):
                rend.pool.submit(crash_child).result(timeout=30)
            self.assertTrue(rend.recover())
            self.assertEqual((rend.backend,rend.workers),('thread',1))
            field=np.full((288,720,3),70,np.uint8)
            result,taps=rend.submit(field,field,0,Params().to_dict()).result()
            self.assertEqual(result.shape,(576,720,3))
            self.assertGreater(result.std(),0)
            self.assertFalse(rend.recover())
        finally:
            rend.close()

    def test_frozen_defaults_to_single_background_thread(self):
        with patch.dict(os.environ,{},clear=False):
            os.environ.pop('PAL_VHS_RENDER_BACKEND',None)
            with patch('sys.frozen',True,create=True):
                rend=Renderer(8)
                self.assertEqual((rend.backend,rend.workers),('thread',1))
                rend.close()

    def test_explicit_backend_overrides_frozen_default(self):
        with patch('sys.frozen',True,create=True):
            rend=Renderer(2,backend='process')
            self.assertEqual((rend.backend,rend.workers),('process',2))
            rend.close()

    def test_partial_submission_cancels_first_field(self):
        rend=Renderer(1,backend='thread')
        rend.pool.shutdown()
        first=Future()
        with patch.object(rend,'pool') as pool:
            pool.submit.side_effect=[first,BrokenProcessPool('lost worker')]
            with self.assertRaises(BrokenProcessPool):
                rend.submit(None,None,0,{})
            self.assertTrue(first.cancelled())
        rend.close()

    def test_decks_are_thread_local_for_concurrent_preview_export(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        barrier=threading.Barrier(2)
        def task():
            deck=_deck_for(Params().to_dict())
            barrier.wait(timeout=20)
            return id(deck)
        with ThreadPoolExecutor(2) as pool:
            a,b=pool.submit(task),pool.submit(task)
            self.assertNotEqual(a.result(),b.result())

    def test_closed_renderer_rejects_new_work_without_retry(self):
        rend=Renderer(1,backend='thread')
        rend.close();rend.close()
        with self.assertRaisesRegex(RuntimeError,'closed'):
            rend.submit(None,None,0,{})


os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6 import QtWidgets as W
from pal_vhs.gui import MainWindow


class StubSource:
    n_out=2
    def fields(self,*args):return None,None
    def close(self):pass


class StubRenderer:
    workers=1
    backend='process'
    def __init__(self,error,recover=False):
        self.error,self.recovery,self.calls=error,recover,0
    def submit(self,*args):
        self.calls+=1
        raise self.error
    def close(self):pass
    def recover(self):
        self.backend='thread'
        return self.recovery


class PreviewRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=W.QApplication.instance() or W.QApplication([])

    def window(self,renderer):
        with patch('pal_vhs.gui.Renderer',return_value=renderer):
            w=MainWindow()
        w.timer.stop()
        w.src=StubSource()
        self.addCleanup(w.close)
        return w

    def test_scheduler_error_is_latched_not_repeated_every_tick(self):
        r=StubRenderer(BrokenProcessPool('child terminated'),recover=False)
        w=self.window(r)
        for _ in range(25):w.tick()
        self.assertEqual(r.calls,1)
        self.assertIsNotNone(w.render_error)
        self.assertIn('Renderer stopped',w.lab_stat.text())
        self.assertFalse(w.btn_play.isEnabled())

    def test_plain_render_error_stops_without_backend_switch(self):
        r=StubRenderer(ValueError('invalid field'),recover=True)
        w=self.window(r)
        w.tick();w.tick()
        self.assertEqual(r.calls,1)
        self.assertEqual(r.backend,'process')
        self.assertIn('invalid field',w.render_error)

    def test_async_future_failure_is_handled_before_resubmission(self):
        r=StubRenderer(BrokenProcessPool('child terminated'),recover=False)
        w=self.window(r)
        class FailedFrame:
            def done(self):return True
            def cancelled(self):return False
            def cancel(self):pass
            def result(self):raise BrokenProcessPool('dead on result')
        w.inflight[0]=(FailedFrame(),w.gen)
        w.tick();w.tick()
        self.assertEqual(r.calls,0)
        self.assertIsNotNone(w.render_error)

    def test_one_fallback_then_thread_failure_stops_loop(self):
        r=StubRenderer(BrokenProcessPool('child terminated'),recover=True)
        w=self.window(r)
        w.tick()
        self.assertIsNone(w.render_error)
        self.assertIn('background',w.render_notice)
        # A second failure in the safe backend cannot trigger an endless retry.
        r.recovery=False
        for _ in range(20):w.tick()
        self.assertEqual(r.calls,2)
        self.assertIsNotNone(w.render_error)

    def test_manual_retry_preserves_source_and_settings(self):
        r=StubRenderer(ValueError('failed'),recover=False)
        w=self.window(r)
        w.params.tape_wear=.4
        source=w.src
        w.tick()
        fresh=StubRenderer(ValueError('not used'),recover=False)
        with patch('pal_vhs.gui.Renderer',return_value=fresh):
            w.retry_renderer()
        self.assertIsNone(w.render_error)
        self.assertIs(w.src,source)
        self.assertEqual(w.params.tape_wear,.4)
        self.assertTrue(w.btn_play.isEnabled())
        self.assertTrue(w.btn_retry.isHidden())
