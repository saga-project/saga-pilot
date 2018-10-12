
import zmq
import copy
import time
import errno
import msgpack

import threading         as mt
import radical.utils     as ru

from .misc import hostip as rpu_hostip


# --------------------------------------------------------------------------
# defines for pubsub roles
#
PUBSUB_PUB    = 'pub'
PUBSUB_SUB    = 'sub'
PUBSUB_BRIDGE = 'bridge'
PUBSUB_ROLES  = [PUBSUB_PUB, PUBSUB_SUB, PUBSUB_BRIDGE]

_USE_MULTIPART   = False  # send [topic, data] as multipart message
_LINGER_TIMEOUT  =   250  # ms to linger after close
_HIGH_WATER_MARK =     0  # number of messages to buffer before dropping


# --------------------------------------------------------------------------
#
# zmq will (rightly) barf at interrupted system calls.  We are able to rerun
# those calls.
#
# FIXME: how does that behave wrt. tomeouts?  We probably should include
#        an explicit timeout parameter.
#
# kudos: https://gist.github.com/minrk/5258909
#
def _uninterruptible(f, *args, **kwargs):
    cnt = 0
    while True:
        cnt += 1
        try:
            return f(*args, **kwargs)
        except zmq.ContextTerminated as e:
            return None
        except zmq.ZMQError as e:
            if e.errno == errno.EINTR:
                if cnt > 10:
                    raise
                # interrupted, try again
                continue
            else:
                # real error, raise it
                raise


# ------------------------------------------------------------------------------
#
# Notifications between components are based on pubsub channels.  Those channels
# have different scope (bound to the channel name).  Only one specific topic is
# predefined: 'state' will be used for unit state updates.
#
class Pubsub(object):

    def __init__(self, channel, role, cfg):
        '''
        Addresses are of the form 'tcp://host:port'.  Both 'host' and 'port' can
        be wildcards for BRIDGE roles -- the bridge will report the in and out
        addresses as obj.addr_in and obj.addr_out.
        '''

        self._channel = channel
        self._cid     = channel.replace('_', '.')
        self._role    = role
        self._cfg     = copy.deepcopy(cfg)

        assert(self._role in PUBSUB_ROLES), 'invalid role %s' % self._role

        if self._role == PUBSUB_BRIDGE:
            self._uid = ru.generate_id("rp.%s.%s" % (self._cid, self._role),
                                       ru.ID_CUSTOM)
        else:
            self._uid = ru.generate_id("rp.%s.%s.%(counter)04d" 
                                       % (self._cid, self._role),
                                       ru.ID_CUSTOM)

        self._log = ru.Logger(name=self._uid, 
                              level=self._cfg.get('log_level'))

        # avoid superfluous logging calls in critical code sections
        if self._log.getEffectiveLevel() == 10:  # logging.DEBUG:
            self._debug  = True
        else:
            self._debug  = False

        self._log.info("create %s - %s", self._channel, self._role)


        # ----------------------------------------------------------------------
        # behavior depends on the role...
        if self._role == PUBSUB_PUB:

            # get addr from bridge.url
            bridge_uid = ru.generate_id("rp.%s.bridge" % (self._cid))

            with open('%s.url' % bridge_uid, 'r') as fin:
                for line in fin.readlines():
                    elems = line.split()
                    if elems and elems[0] == 'IN':
                        self._addr = elems[1]
                        break

            self._ctx      = zmq.Context()  # rely on the GC destroy the context
            self._q        = self._ctx.socket(zmq.PUB)
            self._q.linger = _LINGER_TIMEOUT
            self._q.hwm    = _HIGH_WATER_MARK
            self._q.connect(self._addr)


        # ----------------------------------------------------------------------
        elif self._role == PUBSUB_SUB:

            # get addr from bridge.url
            bridge_uid = ru.generate_id("rp.%s.bridge" % (self._cid))

            with open('%s.url' % bridge_uid, 'r') as fin:
                for line in fin.readlines():
                    elems = line.split()
                    if elems and elems[0] == 'OUT':
                        self._addr = elems[1]
                        break

            self._ctx      = zmq.Context()  # rely on the GC destroy the context
            self._q        = self._ctx.socket(zmq.SUB)
            self._q.linger = _LINGER_TIMEOUT
            self._q.hwm    = _HIGH_WATER_MARK
            self._q.connect(self._addr)


        # ----------------------------------------------------------------------
        elif self._role == PUBSUB_BRIDGE:

            self._initialize_bridge()


    # --------------------------------------------------------------------------
    #
    @property
    def name(self):
        return self._uid

    @property
    def uid(self):
        return self._uid

    @property
    def channel(self):
        return self._channel

    @property
    def role(self):
        return self._role

    @property
    def addr(self):
        return self._addr

    @property
    def addr_in(self):
        assert(self._role == PUBSUB_BRIDGE), 'addr_in only set on bridges'
        return self._addr_in

    @property
    def addr_out(self):
        assert(self._role == PUBSUB_BRIDGE), 'addr_out only set on bridges'
        return self._addr_out


    # --------------------------------------------------------------------------
    # 
    def _initialize_bridge(self):

        self._log.info('start bridge %s', self._uid)

        self._addr       = 'tcp://*:*'

        self._ctx        = zmq.Context()  # rely on the GC destroy the context
        self._in         = self._ctx.socket(zmq.XSUB)
        self._in.linger  = _LINGER_TIMEOUT
        self._in.hwm     = _HIGH_WATER_MARK
        self._in.bind(self._addr)

        self._out        = self._ctx.socket(zmq.XPUB)
        self._out.linger = _LINGER_TIMEOUT
        self._out.hwm    = _HIGH_WATER_MARK
        self._out.bind(self._addr)

        # communicate the bridge ports to the parent process
        _addr_in  = self._in.getsockopt( zmq.LAST_ENDPOINT)
        _addr_out = self._out.getsockopt(zmq.LAST_ENDPOINT)

        # store addresses
        self._addr_in  = ru.Url(_addr_in)
        self._addr_out = ru.Url(_addr_out)

        # use the local hostip for bridge addresses
        self._addr_in.host  = rpu_hostip()
        self._addr_out.host = rpu_hostip()

        self._log.info('bound bridge %s to %s : %s', 
                       self._uid, _addr_in, _addr_out)

        # start polling for messages
        self._poll = zmq.Poller()
        self._poll.register(self._in,  zmq.POLLIN)
        self._poll.register(self._out, zmq.POLLIN)

        self._bridge_thread = mt.Thread(target=self._bridge_work)
        self._bridge_thread.daemon = True
        self._bridge_thread.start()

        with open(self.uid, 'w') as fout:
            fout.write('IN  %s\n' % self.addr_in)
            fout.write('OUT %s\n' % self.addr_out)


    # --------------------------------------------------------------------------
    # 
    def wait(self, timeout=None):
        '''
        join negates the daemon thread settings, in that it stops us from
        killing the parent process w/o hanging it.  So we do a slow pull on the
        thread state.
        '''

        start = time.time()

        if self._role == PUBSUB_BRIDGE:

            while True:

                if not self._bridge_thread.is_alive():
                    return True

                if  timeout is not None and \
                    timeout < time.time() - start:
                    return False

                time.sleep(1)


    # --------------------------------------------------------------------------
    # 
    def _bridge_work(self):

        try:

            while True:

                _socks = dict(_uninterruptible(self._poll.poll, timeout=1000))
                # timeout in ms

                if self._in in _socks:

                    # if any incoming socket signals a message, get the
                    # message on the subscriber channel, and forward it
                    # to the publishing channel, no questions asked.
                    if _USE_MULTIPART:
                        msg = _uninterruptible(self._in.recv_multipart, flags=zmq.NOBLOCK)
                        _uninterruptible(self._out.send_multipart, msg)
                    else:
                        msg = _uninterruptible(self._in.recv, flags=zmq.NOBLOCK)
                        _uninterruptible(self._out.send, msg)
                  # if self._debug:
                  #     self._log.debug("-> %s", pprint.pformat(msg))


                if self._out in _socks:
                    # if any outgoing socket signals a message, it's
                    # likely a topic subscription.  We forward that on
                    # the incoming channels to subscribe for the
                    # respective messages.
                    if _USE_MULTIPART:
                        msg = _uninterruptible(self._out.recv_multipart)
                        _uninterruptible(self._in.send_multipart, msg)
                    else:
                        msg = _uninterruptible(self._out.recv)
                        _uninterruptible(self._in.send, msg)
                  # if self._debug:
                  #     self._log.debug("<- %s", pprint.pformat(msg))

        except  Exception as e:
            print 'error: %s' % e
            self._log.exception('bridge failed')


    # --------------------------------------------------------------------------
    #
    def subscribe(self, topic):

        assert(self._role == PUBSUB_SUB), 'incorrect role on subscribe'

        topic = topic.replace(' ', '_')

      # self._log.debug("~~ %s", topic)
        _uninterruptible(self._q.setsockopt, zmq.SUBSCRIBE, topic)


    # --------------------------------------------------------------------------
    #
    def put(self, topic, msg):

        assert(self._role == PUBSUB_PUB), 'incorrect role on put'
        assert(isinstance(msg,dict)),     'invalide message type'

      # self._log.debug("?> %s", pprint.pformat(msg)

        topic = topic.replace(' ', '_')
        data  = msgpack.packb(msg) 

        if _USE_MULTIPART:
          # if self._debug:
          #     self._log.debug("-> %s", ([topic, pprint.pformat(msg)]))
            _uninterruptible(self._q.send_multipart, [topic, data])

        else:
          # if self._debug:
          #     self._log.debug("-> %s %s", topic, pprint.pformat(msg))
            _uninterruptible(self._q.send, "%s %s" % (topic, data))


    # --------------------------------------------------------------------------
    #
    def get(self):

        assert(self._role == PUBSUB_SUB), 'invalid role on get'

        # FIXME: add timeout to allow for graceful termination

        if _USE_MULTIPART:
            topic, data = _uninterruptible(self._q.recv_multipart)

        else:
            raw = _uninterruptible(self._q.recv)
            topic, data = raw.split(' ', 1)

        msg  = msgpack.unpackb(data) 

      # if self._debug:
      #     self._log.debug("<- %s", ([topic, pprint.pformat(msg)]))

        return [topic, msg]


    # --------------------------------------------------------------------------
    #
    def get_nowait(self, timeout=None):  # timeout in ms

        assert(self._role == PUBSUB_SUB), 'invalid role on get_nowait'

        if _uninterruptible(self._q.poll, flags=zmq.POLLIN, timeout=timeout):

            if _USE_MULTIPART:
                topic, data = _uninterruptible(self._q.recv_multipart, 
                                               flags=zmq.NOBLOCK)

            else:
                raw = _uninterruptible(self._q.recv)
                topic, data = raw.split(' ', 1)

            msg = msgpack.unpackb(data) 
          # if self._debug:
          #     self._log.debug("<< %s", ([topic, pprint.pformat(msg)]))
            return [topic, msg]

        else:
            return [None, None]


# ------------------------------------------------------------------------------

