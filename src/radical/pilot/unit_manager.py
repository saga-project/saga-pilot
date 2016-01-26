
__copyright__ = "Copyright 2013-2016, http://radical.rutgers.edu"
__license__   = "MIT"


import os
import time
import threading

import radical.utils as ru

from .  import utils     as rpu
from .  import states    as rps
from .  import constants as rpc
from .  import types     as rpt


# ------------------------------------------------------------------------------
#
class UnitManager(rpu.Component):
    """
    A UnitManager manages :class:`radical.pilot.ComputeUnit` instances which
    represent the **executable** workload in RADICAL-Pilot. A UnitManager connects
    the ComputeUnits with one or more :class:`Pilot` instances (which represent
    the workload **executors** in RADICAL-Pilot) and a **scheduler** which
    determines which :class:`ComputeUnit` gets executed on which
    :class:`Pilot`.

    Each UnitManager has a unique identifier :data:`radical.pilot.UnitManager.uid`
    that can be used to re-connect to previoulsy created UnitManager in a
    given :class:`radical.pilot.Session`.

    **Example**::

        s = radical.pilot.Session(database_url=DBURL)

        pm = radical.pilot.PilotManager(session=s)

        pd = radical.pilot.ComputePilotDescription()
        pd.resource = "futuregrid.alamo"
        pd.cores = 16

        p1 = pm.submit_pilots(pd) # create first pilot with 16 cores
        p2 = pm.submit_pilots(pd) # create second pilot with 16 cores

        # Create a workload of 128 '/bin/sleep' compute units
        compute_units = []
        for unit_count in range(0, 128):
            cu = radical.pilot.ComputeUnitDescription()
            cu.executable = "/bin/sleep"
            cu.arguments = ['60']
            compute_units.append(cu)

        # Combine the two pilots, the workload and a scheduler via
        # a UnitManager.
        um = radical.pilot.UnitManager(session=session,
                                       scheduler=radical.pilot.SCHED_ROUND_ROBIN)
        um.add_pilot(p1)
        um.submit_units(compute_units)
    """

    # --------------------------------------------------------------------------
    #
    def __init__(self, session, scheduler=None):
        """
        Creates a new UnitManager and attaches it to the session.

        **Args:**
            * session   (`string`): The session instance to use.
            * scheduler (`string`): The name of the scheduler plug-in to use.
        """

        from .. import pilot as rp
        
        self._session    = session
        self._cfg        = None
        self._components = None
        self._bridges    = None
        self._pilots     = dict()
        self._units      = dict()
        self._callbacks  = dict()
        self._cb_lock    = threading.RLock()
        self._closed     = False
        self._rec_id     = 0       # used for session recording

        # get an ID and initialize logging and profiling
        # FIXME: log and prof are already provided by the base class -- but it
        #        will take a while until we can initialize that, and meanwhile
        #        we use these...
        self._uid  = ru.generate_id('umgr')
        self._log  = ru.get_logger(self.uid, "%s.%s.log" % (session.uid, self._uid))
        self._prof = rpu.Profiler("%s.%s" % (session.uid, self._uid))

        self._session.prof.prof('create umgr', uid=self._uid)

        self._log.report.info('<<create unit manager')

        try:

            self._cfg = ru.read_json("%s/configs/umgr_%s.json" \
                    % (os.path.dirname(__file__),
                       os.environ.get('RADICAL_PILOT_UMGR_CONFIG', 'default')))

            self._cfg['session_id']  = self._session.uid
            self._cfg['mongodb_url'] = self._session._dburl
            self._cfg['owner_id']    = self._uid

            if scheduler:
                # overwrite the scheduler from the config file
                self._cfg['scheduler'] = scheduler

            if not self._cfg.get('scheduler'):
                # set default scheduler if needed
                self._cfg['scheduler'] = SCHED_DEFAULT

            bridges    = self._cfg.get('bridges',    [])
            components = self._cfg.get('components', [])

            # always start update and heartbeat workers
            components[rpc.UPDATE_WORKER]    = 1
            components[rpc.HEARTBEAT_WORKER] = 1

            # we also need a map from component names to class types
            typemap = {
                rpc.UMGR_STAGING_INPUT_COMPONENT  : rp.umgr.Input,
                rpc.UMGR_SCHEDULING_COMPONENT     : rp.umgr.Scheduler,
                rpc.UMGR_STAGING_OUTPUT_COMPONENT : rp.umgr.Output,
                rpc.UPDATE_WORKER                 : rp.worker.Update,
                rpc.HEARTBEAT_WORKER              : rp.worker.Heartbeat
                }

            # before we start any components, we need to get the bridges up they
            # want to connect to
            self._bridges = rpu.Component.start_bridges(bridges)

            # get bridge addresses from our bridges, and append them to the
            # config, so that we can pass those addresses to the components
            if not 'bridge_addresses' in self._cfg:
                self._cfg['bridge_addresses'] = dict()

            for b in self._bridges:

                # to avoid confusion with component input and output, we call bridge
                # input a 'sink', and a bridge output a 'source' (from the component
                # perspective)
                sink   = ru.Url(self._bridges[b]['in'])
                source = ru.Url(self._bridges[b]['out'])

                # for the unit manager, we assume all bridges to be local, so we
                # really are only interested in the ports for now...
                sink.host   = '127.0.0.1'
                source.host = '127.0.0.1'

                # keep the resultin URLs as strings, to be used as addresses
                self._cfg['bridge_addresses'][b] = dict()
                self._cfg['bridge_addresses'][b]['sink']   = str(sink)
                self._cfg['bridge_addresses'][b]['source'] = str(source)

            # the bridges are up, we can start to connect the components to them
            self._components = rpu.Component.start_components(components,
                    typemap, self._cfg)

            # FIXME: make sure all communication channels are in place.  This could
            # be replaced with a proper barrier, but not sure if that is worth it...
            time.sleep(1)

            # we only can initialize the base class once we have the bridges up
            # and running, as those are needed to register any message event
            # callbacks
            rpu.Component.__init__(self, 'UnitManager', self._cfg)

            # the command pubsub is used to communicate with the scheduler,
            # to shut down components, and to cancel units.  The queue is
            # used to forward submitted units to the scheduler
            self.declare_publisher('command', rpc.COMMAND_PUBSUB)
            self.declare_output(rps.UMGR_SCHEDULING_PENDING, rpc.UMGR_SCHEDULING_QUEUE)


        except Exception as e:
            self._log.exception("UMGR setup error: %s" % e)
            raise

        self._prof.prof('UMGR setup done', logger=self._log.debug)

        self._log.report.ok('>>ok\n')


    # --------------------------------------------------------------------------
    #
    def close(self):
        """Shuts down the UnitManager and its background workers in a 
        coordinated fashion.
        """
        if self._closed:
            raise RuntimeError("instance is already closed")

        self._log.report.info('<<close unit manager')

     ## if self._worker:
     ##     self._worker.stop()
     ## TODO: kill bridges, components

        self._session.prof.prof('closed umgr', uid=self._uid)
        self._log.info("Closed UnitManager %s." % str(self._uid))

        self._closed = True

        self._log.report.ok('>>ok\n')


    # --------------------------------------------------------------------------
    #
    def as_dict(self):
        """
        Returns a dictionary representation of the UnitManager object.
        """

        ret = {
            'uid':       self.uid,
            'scheduler': self._cfg.get('scheduler'),
        }

        return ret


    # --------------------------------------------------------------------------
    #
    def __str__(self):

        """
        Returns a string representation of the UnitManager object.
        """

        return str(self.as_dict())


    # --------------------------------------------------------------------------
    #
    @staticmethod
    def _default_unit_state_cb (unit, state):

        self._log.info("[Callback]: unit %s state on pilot %s: %s.", 
                       unit.uid, unit.pilot_id, state)


    # --------------------------------------------------------------------------
    #
    @staticmethod
    def _default_wait_queue_size_cb(umgr, wait_queue_size):
        # FIXME: this needs to come from the scheduler?

        self._log.info("[Callback]: wait_queue_size: %s.", wait_queue_size)


    # --------------------------------------------------------------------------
    #
    @property
    def uid(self):
        """
        Returns the unique id.
        """
        return self._uid


    # --------------------------------------------------------------------------
    #
    @property
    def session(self):
        """
        Returns the session object
        """
        return self._session


    # --------------------------------------------------------------------------
    #
    @property
    def scheduler(self):
        """
        Returns the scheduler name.
        """

        return self._cfg.get('scheduler')



    # --------------------------------------------------------------------------
    #
    def add_pilots(self, pilots):
        """Associates one or more pilots with the unit manager.

        **Arguments:**

            * **pilots** [:class:`radical.pilot.ComputePilot` or list of
              :class:`radical.pilot.ComputePilot`]: The pilot objects that will be
              added to the unit manager.
        """

        if self._closed:
            raise RuntimeError("instance is already closed")

        if not isinstance(pilots, list):
            pilots = [pilots]

        if len(pilots) == 0:
            raise ValueError('cannot add no pilots')

        self._log.report.info('<<add %d pilot(s)' % len(pilots))

        for pilot in pilot:

            pid = pilot.uid

            # sanity check
            if pid in self._pilots:
                raise ValueError('pilot %s already added' % pid)

            # publish to the command channel for the scheduler to pick up
            self.publish('command', {'cmd' : 'add_pilot', 
                                     'arg' : {'pid'  : pid, 
                                              'umgr' : self.uid})

            # also keep pilots around for inspection
            self._pilots[pid] = pilot<F3>

        self._log.report.ok('>>ok\n')


    # --------------------------------------------------------------------------
    #
    def list_pilots(self):
        """
        Lists the UIDs of the pilots currently associated with the unit manager.

        **Returns:**
              * A list of :class:`radical.pilot.ComputePilot` UIDs [`string`].
        """

        if self._closed:
            raise RuntimeError("instance is already closed")

        return self._pilots.keys()


    # --------------------------------------------------------------------------
    #
    def get_pilots(self):
        """
        Get the pilots instances currently associated with the unit manager.

        **Returns:**
              * A list of :class:`radical.pilot.ComputePilot` instances.
        """
        if self._closed:
            raise RuntimeError("instance is already closed")

        return self._pilots.values()


    # --------------------------------------------------------------------------
    #
    def remove_pilots(self, pilot_ids, drain=False):
        """
        Disassociates one or more pilots from the unit manager.

        After a pilot has been removed from a unit manager, it won't process
        any of the unit manager's units anymore. Calling `remove_pilots`
        doesn't stop the pilot itself.

        **Arguments:**

            * **drain** [`boolean`]: Drain determines what happens to the units
              which are managed by the removed pilot(s). If `True`, all units
              currently assigned to the pilot are allowed to finish execution.
              If `False` (the default), then `ACTIVE` units will be canceled.
        """

        # TODO: Implement 'drain'.

        if self._closed:
            raise RuntimeError("instance is already closed")

        if drain:
            raise RuntimeError("'drain' is not yet implemented")

        if not isinstance(pilot_ids, list):
            pilot_ids = [pilot_ids]

        for pid in pilot_ids:

            if pid not in self._pilots:
                raise ValueError('pilot %s not added' % pid)

            del(self._pilots[pid])

            # publish to the command channel for the scheduler to pick up
            self.publish('command', {'cmd' : 'remove_pilot', 
                                     'arg' : pid})


    # --------------------------------------------------------------------------
    #
    def list_units(self):
        """
        Returns the UIDs of the :class:`radical.pilot.ComputeUnit` managed by
        this unit manager.

        **Returns:**
              * A list of :class:`radical.pilot.ComputeUnit` UIDs [`string`].
        """

        if self._closed:
            raise RuntimeError("instance is already closed")

        return self._units.keys()


    # --------------------------------------------------------------------------
    #
    def submit_units(self, unit_descriptions):
        """
        Submits on or more :class:`radical.pilot.ComputeUnit` instances to the
        unit manager.

        **Arguments:**
            * **unit_descriptions** [:class:`radical.pilot.ComputeUnitDescription`
              or list of :class:`radical.pilot.ComputeUnitDescription`]: The
              description of the compute unit instance(s) to create.

        **Returns:**
              * A list of :class:`radical.pilot.ComputeUnit` objects.
        """

        from .compute_unit import ComputeUnit

        if self._closed:
            raise RuntimeError("instance is already closed")

        return_list_type = True
        if not isinstance(unit_descriptions, list):
            return_list_type  = False
            unit_descriptions = [unit_descriptions]

        if len(unit_descriptions) == 0:
            raise ValueError('cannot submit no unit descriptions')


        self._log.report.info('<<submit %d unit(s)\n\t' % len(unit_descriptions))

        # we return a list of compute units
        cus = list()
        for ud in unit_descriptions :

            cu = ComputeUnit.create (umgr=self, descr=ud)
            cus.append(cu)

            # keep units around
            self._units[cu.uid] = cu

            if self._session._rec:
                import radical.utils as ru
                ru.write_json(ud.as_dict(), "%s/%s.batch.%03d.json" \
                        % (self._session._rec, cu.uid, self._rec_id))
            self._log.report.progress()

            self.advance(cu.as_dict(), rps.UMGR_SCHEDULING_PENDING, 
                         publish=True, push=True)

        if self._session._rec:
            self._rec_id += 1

        self._log.report.ok('>>ok\n')

        if return_list_type: return cus
        else               : return cus[0]


    # --------------------------------------------------------------------------
    #
    def get_units(self, unit_ids=None):
        """Returns one or more compute units identified by their IDs.

        **Arguments:**
            * **unit_ids** [`string` or `list of strings`]: The IDs of the
              compute unit objects to return.

        **Returns:**
              * A list of :class:`radical.pilot.ComputeUnit` objects.
        """
        
        if self._closed:
            raise RuntimeError("instance is already closed")

        if not unit_ids:
            return self._units.values()


        return_list_type = True
        if (not isinstance(unit_ids, list)) and (unit_ids is not None):
            return_list_type = False
            unit_ids = [unit_ids]

        ret = list()
        for uid in unit_ids:
            if uid not in self._units:
                raise ValueError('unit %s not known' % uid)
            ret.append(self._units[uid])

        if  return_list_type :
            return ret
        else :
            return ret[0]


    # --------------------------------------------------------------------------
    #
    def wait_units(self, unit_ids=None, state=None, timeout=None):
        """
        Returns when one or more :class:`radical.pilot.ComputeUnits` reach a
        specific state.

        If `unit_uids` is `None`, `wait_units` returns when **all**
        ComputeUnits reach the state defined in `state`.  This may include units
        which have previously terminated or waited upon.

        **Example**::

            # TODO -- add example

        **Arguments:**

            * **unit_uids** [`string` or `list of strings`]
              If unit_uids is set, only the ComputeUnits with the specified
              uids are considered. If unit_uids is `None` (default), all
              ComputeUnits are considered.

            * **state** [`string`]
              The state that ComputeUnits have to reach in order for the call
              to return.

              By default `wait_units` waits for the ComputeUnits to
              reach a terminal state, which can be one of the following:

              * :data:`radical.pilot.rps.DONE`
              * :data:`radical.pilot.rps.FAILED`
              * :data:`radical.pilot.rps.CANCELED`

            * **timeout** [`float`]
              Timeout in seconds before the call returns regardless of Pilot
              state changes. The default value **None** waits forever.
        """

        if self._closed:
            raise RuntimeError("instance is already closed")

        if not unit_ids:
            unit_ids = list()
            for uid,cu in self._units.iteritems():
                if cu.state not in rps.FINAL:
                    unit_ids.append(uid)

        if not state:
            states = rps.FINAL
        elif isinstance(state, list):
            states = state
        else:
            states = [state]

        return_list_type = True
        if not isinstance(unit_ids, list):
            return_list_type = False
            unit_ids = [unit_ids]

        self._log.report.info('<<wait for %d unit(s)\n\t' % len(unit_ids))

        start    = time.time()
        to_check = [self._units[uid] for uid in unit_ids]

        # We don't want to iterate over all units again and again, as that would
        # duplicate checks on units which were found in matching states.  So we
        # create a list from which we drop the units as we find them in
        # a matching state
        self._log.report.idle(mode='start')
        while to_check and not self._session._terminate.is_set():

            self._log.report.idle()

            to_check = [cu for cu in to_check \
                            if cu.state not in states and \
                               cu.state not in rps.final]
            # check timeout
            if to_check:
                if timeout and (timeout <= (time.time() - start)):
                    self._log.debug ("wait timed out")
                    break

                time.sleep (0.5)

        self._log.report.idle(mode='stop')

        if to_check: self._log.report.warn('>>timeout\n')
        else       : self._log.report.ok(  '>>ok\n')

        # grab the current states to return
        states = [self._units[uid].state for uid in unit_ids]

        # done waiting
        if  return_list_type :
            return states
        else :
            return states[0]


    # --------------------------------------------------------------------------
    #
    def cancel_units(self, unit_ids=None):
        """
        Cancel one or more :class:`radical.pilot.ComputeUnits`.

        **Arguments:**
            * **unit_ids** [`string` or `list of strings`]: The IDs of the
              compute unit objects to cancel.
        """
        if self._closed:
            raise RuntimeError("instance is already closed")

        if not unit_ids:
            unit_ids = self._units.keys()

        if not isinstance(unit_ids, list):
            unit_ids = [unit_ids]

        cus = self.get_units(unit_ids)
        for cu in cus:
            cu.cancel()


    # --------------------------------------------------------------------------
    #
    def register_callback(self, cb_func, metric=rpt.UNIT_STATE, cb_data=None):
        """
        Registers a new callback function with the UnitManager.  Manager-level
        callbacks get called if the specified metric changes.  The default
        metric `UNIT_STATE` fires the callback if any of the ComputeUnits
        managed by the PilotManager change their state.

        All callback functions need to have the same signature::

            def cb_func(obj, value, cb_data)

        where ``object`` is a handle to the object that triggered the callback,
        ``value`` is the metric, and ``data`` is the data provided on
        callback registration..  In the example of `UNIT_STATE` above, the
        object would be the unit in question, and the value would be the new
        state of the unit.

        Available metrics are:

          * `UNIT_STATE`: fires when the state of any of the units which are
            managed by this unit manager instance is changing.  It communicates
            the unit object instance and the units new state.

          * `WAIT_QUEUE_SIZE`: fires when the number of unscheduled units (i.e.
            of units which have not been assigned to a pilot for execution)
            changes.
        """

        # FIXME: the signature should be (self, metrics, cb, cb_data)

        if  metric not in rpt.UNIT_MANAGER_METRICS :
            raise ValueError ("Metric '%s' is not available on the unit manager" % metric)

        with self._cb_lock:
            self._callbacks['umgr'][metric].append([cb_func, cb_data])


# ------------------------------------------------------------------------------

