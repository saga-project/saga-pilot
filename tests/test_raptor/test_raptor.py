#!/usr/bin/env python3

import time

from   unittest import mock
from   unittest import TestCase

import radical.utils as ru
import radical.pilot as rp


# ------------------------------------------------------------------------------
#
class TestWorker(TestCase):

    def test_alloc(self):

        cfg = {'uid': 'worker.0000',
               'cores': 8,
               'gpus' : 2,
               'sid'  : str(time.time())}

        rp.utils.Component.register_subscriber = mock.Mock()
        rp.utils.Component.register_publisher  = mock.Mock()

        ru.zmq.Putter = mock.Mock()
        ru.zmq.Getter = mock.Mock()

        worker = rp.task_overlay.Worker(cfg, session=mock.Mock())

        task_1 = {'cores': 1, 'gpus' : 1}
        task_2 = {'cores': 2, 'gpus' : 1}
        task_3 = {'cores': 3, 'gpus' : 1}


        self.assertEqual(worker._resources['cores'], [0, 0, 0, 0, 0, 0, 0, 0])

        worker._alloc_task(task_1)
        self.assertEqual(worker._resources['cores'], [1, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(worker._resources['gpus' ], [1, 0])
        self.assertEqual(task_1['resources'], {'cores': [0], 'gpus': [0]})

        worker._alloc_task(task_2)
        self.assertEqual(worker._resources['cores'], [1, 1, 1, 0, 0, 0, 0, 0])
        self.assertEqual(worker._resources['gpus' ], [1, 1])
        self.assertEqual(task_2['resources'], {'cores': [1, 2], 'gpus': [1]})

        worker._alloc_task(task_3)
        self.assertEqual(worker._resources['cores'], [1, 1, 1, 0, 0, 0, 0, 0])
        self.assertEqual(worker._resources['gpus' ], [1, 1])
        self.assertEqual(task_3.get('resources'), None)

        worker._dealloc_task(task_1)
        self.assertEqual(worker._resources['cores'], [0, 1, 1, 0, 0, 0, 0, 0])
        self.assertEqual(worker._resources['gpus' ], [0, 1])

        worker._alloc_task(task_3)
        self.assertEqual(worker._resources['cores'], [1, 1, 1, 1, 1, 0, 0, 0])
        self.assertEqual(worker._resources['gpus' ], [1, 1])
        self.assertEqual(task_3['resources'], {'cores': [0, 3, 4], 'gpus': [0]})

        worker._dealloc_task(task_2)
        self.assertEqual(worker._resources['cores'], [1, 0, 0, 1, 1, 0, 0, 0])
        self.assertEqual(worker._resources['gpus' ], [1, 0])

        worker._dealloc_task(task_3)
        self.assertEqual(worker._resources['cores'], [0, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(worker._resources['gpus' ], [0, 0])


# ------------------------------------------------------------------------------
#
if __name__ == '__main__':

    tc = TestWorker()
    tc.test_alloc()


# ------------------------------------------------------------------------------
