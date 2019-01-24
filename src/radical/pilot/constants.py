
# ------------------------------------------------------------------------------
#
# global constants
#
PMGR_LAUNCHING_QUEUE           = 'pmgr_launching_queue'
PMGR_LAUNCHING_COMPONENT       = 'PMGRLaunchingComponent'

UMGR_SCHEDULING_QUEUE          = 'umgr_scheduling_queue'
UMGR_STAGING_INPUT_QUEUE       = 'umgr_staging_input_queue'
UMGR_STAGING_OUTPUT_QUEUE      = 'umgr_staging_output_queue'

UMGR_SCHEDULING_COMPONENT      = 'UMGRSchedulingComponent'
UMGR_STAGING_INPUT_COMPONENT   = 'UMGRStagingInputComponent'
UMGR_STAGING_OUTPUT_COMPONENT  = 'UMGRStagingOutputComponent'

AGENT_STAGING_INPUT_QUEUE      = 'agent_staging_input_queue'
AGENT_SCHEDULING_QUEUE         = 'agent_scheduling_queue'
AGENT_EXECUTING_QUEUE          = 'agent_executing_queue'
AGENT_STAGING_OUTPUT_QUEUE     = 'agent_staging_output_queue'

AGENT_STAGING_INPUT_COMPONENT  = 'AgentStagingInputComponent'
AGENT_SCHEDULING_COMPONENT     = 'AgentSchedulingComponent'
AGENT_EXECUTING_COMPONENT      = 'AgentExecutingComponent'
AGENT_STAGING_OUTPUT_COMPONENT = 'AgentStagingOutputComponent'

UMGR_UNSCHEDULE_PUBSUB         = 'umgr_unschedule_pubsub'
UMGR_RESCHEDULE_PUBSUB         = 'umgr_reschedule_pubsub'

AGENT_UNSCHEDULE_PUBSUB        = 'agent_unschedule_pubsub'
AGENT_SCHEDULE_PUBSUB          = 'agent_schedule_pubsub'

CONTROL_PUBSUB                 = 'control_pubsub'
STATE_PUBSUB                   = 'state_pubsub'
LOG_PUBSUB                     = 'log_pubsub'

AGENT_QUEUE_IN                 = 'agent_queue_in'
AGENT_QUEUE_OUT                = 'agent_queue_out'
AGENT_PUBSUB                   = 'agent_pubsub'

AGENT_BRIDGES                  = [AGENT_QUEUE_IN, AGENT_QUEUE_OUT, AGENT_PUBSUB]


# ------------------------------------------------------------------------------
#
# two-state for resource occupation.
#
FREE = 0
BUSY = 1


# -----------------------------------------------------------------------------
#
# definitions of metrics
#
UNIT_STATE           = 'UNIT_STATE'
WAIT_QUEUE_SIZE      = 'WAIT_QUEUE_SIZE'
UMGR_METRICS         = [UNIT_STATE, 
                        WAIT_QUEUE_SIZE]

PILOT_STATE          = 'PILOT_STATE'
PMGR_METRICS         = [PILOT_STATE]


# ------------------------------------------------------------------------------
#
# staging defines
#
COPY     = 'Copy'     # local cp
LINK     = 'Link'     # local ln -s
MOVE     = 'Move'     # local mv
TRANSFER = 'Transfer' # saga remote transfer TODO: This might just be a special case of copy
TARBALL  = 'Tarball'  # remote staging will be executed using a tarball.

#
# Flags - inherit from RS where possible, add custom ones
#
import radical.saga.filesystem as rsf

CREATE_PARENTS = rsf.CREATE_PARENTS  # Create parent directories if needed
SKIP_FAILED    = 4096                # Don't stage out files if tasks failed
NON_FATAL      = 8192                # Don't fail the CU if input is missing


#
# CU MPI flags
#
SERIAL         = 'Serial'
MPI            = 'MPI'
OpenMP         = 'OpenMP'
GPU            = 'GPU'
GPU_MPI        = 'GPU_MPI'
GPU_OpenMP     = 'GPU_OpenMP'

#
# Defaults
#
DEFAULT_ACTION   = TRANSFER
DEFAULT_PRIORITY = 0
DEFAULT_FLAGS    = CREATE_PARENTS
STAGING_AREA     = 'staging_area'


# scheduler names (and backwards compat)
SCHEDULER_ROUND_ROBIN  = "round_robin"
SCHEDULER_BACKFILLING  = "backfilling"
SCHEDULER_DEFAULT      = SCHEDULER_ROUND_ROBIN

# ------------------------------------------------------------------------------

