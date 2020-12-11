
# pylint: disable=protected-access, unused-argument, no-value-for-parameter

__copyright__ = "Copyright 2013-2016, http://radical.rutgers.edu"

import tasktest

from tasktest import mock

import radical.utils as ru

from radical.pilot.agent.launch_method.base import LaunchMethod
from radical.pilot.agent.executing.popen    import Popen


# ------------------------------------------------------------------------------
#


class TestBase(tasktest.TestCase):

    # ------------------------------------------------------------------------------
    #
    def setUp(self):

        fname = 'tests/test_executing/test_task/test_cases/test_base.json'

        return ru.read_json(fname)


    # --------------------------------------------------------------------------
    #
    @mock.patch.object(Popen, '__init__', return_value=None)
    @mock.patch.object(Popen, 'initialize', return_value=None)
    def test_handle_task(self, mocked_init, mocked_initialize):

        global_launcher = []
        global_cu = []

        def spawn_side_effect(launcher, t):
            nonlocal global_launcher
            nonlocal global_cu
            global_launcher.append(launcher)
            global_cu.append(t)

        tests = self.setUp()
        t    = dict()

        t['uid']         = tests['task']['uid']
        t['description'] = tests['task']['description']

        component = Popen()
        component._mpi_launcher          = mock.Mock()
        component._mpi_launcher.name     = 'mpiexec'
        component._mpi_launcher.command  = 'mpiexec'
        component._task_launcher         = mock.Mock()
        component._task_launcher.name    = 'ssh'
        component._task_launcher.command = 'ssh'

        component.spawn = mock.MagicMock(side_effect=spawn_side_effect
                               (launcher=component._mpi_launcher, t=t))

        component._log = ru.Logger('dummy')
        component._handle_task(t)
        self.assertEqual(t, global_cu[0])


    # --------------------------------------------------------------------------
    #
    @mock.patch.object(Popen, '__init__', return_value=None)
    @mock.patch.object(Popen, 'initialize', return_value=None)
    def test_check_running(self, mocked_init, mocked_initialize):

        global_cu      = []
        global_state   = None
        global_publish = None
        global_push    = None

        def _advance_side_effect(t, state, publish, push):
            nonlocal global_cu
            nonlocal global_state
            nonlocal global_publish
            nonlocal global_push

            global_cu.append(t)
            global_state   = 'FAILED'
            global_publish = True
            global_push    = True

        tests = self.setUp()
        t = dict()
        t = tests['task']
        t['target_state'] = None
        t['proc']         = mock.Mock()
        t['proc'].poll    = mock.Mock(return_value=1)
        t['proc'].wait    = mock.Mock(return_value=1)

        component = Popen()
        component._cus_to_watch = list()
        component._cus_to_cancel = list()
        component._cus_to_watch.append(t)
        component.advance = mock.MagicMock(side_effect=_advance_side_effect)
        component._prof = mock.Mock()
        component.publish = mock.Mock()
        component._log = ru.Logger('dummy')
        component._check_running()
        self.assertEqual(t['target_state'], global_state)

    # --------------------------------------------------------------------------
    #
    @mock.patch.object(Popen, '__init__', return_value=None)
    @mock.patch.object(Popen, 'initialize', return_value=None)
    @mock.patch.object(LaunchMethod, '__init__', return_value=None)
    @mock.patch.object(LaunchMethod, 'construct_command',
                       return_value=('mpiexec echo hello',None))
    def test_spawn(self, mocked_init, mocked_initialize,
                   mocked_launchmethod, mocked_construct_command):
        tests = self.setUp()
        _pids = []
        t = dict()
        t = tests['task']
        t['slots'] = tests['setup']['lm']['slots']
        t['task_sandbox_path'] = tests['setup']['lm']['task_sandbox']

        launcher  = LaunchMethod()
        component = Popen()
        component._cfg = dict()

        component._cfg['sid']  = 'sid0'
        component._cfg['pid']  = 'pid0'
        component._cfg['aid']  = 'aid0'
        component._uid         = mock.Mock()
        component.gtod         = mock.Mock()
        component._pwd         = mock.Mock()
        component._prof        = mock.Mock()
        component._cu_tmp      = mock.Mock()
        component._watch_queue = mock.Mock()
        component._log         = ru.Logger('dummy')

        component.spawn(launcher=launcher, t=t)
        self.assertEqual(len(_pids), 0)


# ------------------------------------------------------------------------------
# pylint: enable=protected-access, unused-argument, no-value-for-parameter
