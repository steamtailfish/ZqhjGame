from concurrent.futures import Future
from pathlib import Path
import sys
import unittest
sys.path[:0]=[str(Path(__file__).resolve().parent)]
from test_vision import frame
from zqhj_async import AsyncPhotoEntryAgent
from zqhj_vision import PixelBox


class Executor:
    def __init__(self):self.futures=[]
    def submit(self,*args):
        future=Future();self.futures.append(future);return future


def agent():
    a=AsyncPhotoEntryAgent('alpha');a.detector=lambda p:[];a.reset()
    a.close_detector();a._detector_executor=Executor();return a


class AsyncTests(unittest.TestCase):
    def test_pending_work_is_bounded_and_does_not_block_control(self):
        a=agent()
        for i in range(10):
            a.sensor(frame(i*.1,str(i).encode()),.1)
            a.decide(frame(i*.1),.1)
        self.assertEqual(len(a._detector_executor.futures),1)
        self.assertEqual(a.vision_stats['inferences'],0)

    def test_result_retains_original_photo_receipt_time(self):
        a=agent();a.sensor(frame(0.,b'a'),.1)
        a._pending.set_result(([PixelBox(30,30,50,50,.8,1024,768)],.2))
        a.sensor(frame(.3,b'b'),.1)
        self.assertEqual(a.photo_time,0.)
        self.assertEqual(a.vision_stats['inferences'],1)
        self.assertEqual(a.pixel_hits,1)

    def test_late_or_failed_result_does_not_create_candidate(self):
        a=agent();a.sensor(frame(0.,b'a'),.1);a._pending.set_result(([],2.))
        a.sensor(frame(2.,b'b'),.1)
        self.assertEqual(a.vision_stats['async_dropped'],1)
        self.assertEqual(a.vision_stats['inferences'],0)
        a._pending.set_exception(ValueError('test failure'))
        a.sensor(frame(2.2,b'c'),.1)
        self.assertEqual(a.vision_stats['failures'],1)
        self.assertEqual(a.pending_geo,[])


if __name__=='__main__':unittest.main()
