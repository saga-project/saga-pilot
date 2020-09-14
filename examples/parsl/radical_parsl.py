import parsl
import radical.pilot as rp
import os 
from parsl.app.app import python_app, bash_app
from parsl import File

from parsl.config import Config
from radical.pilot.agent.executing.parsl_rp import RADICALExecutor as RADICALExecutor

parsl.set_stream_logger()
config = Config(
         executors=[RADICALExecutor(
                        label = 'RADICALExecutor',
                        resource = 'local.localhost_funcs', #'local.localhost',
                        login_method = 'local',
                        tasks =list(),
                        task_process_type = rp.FUNC,
                        cores_per_task=1,
                        managed = True,
                        max_tasks = 1)
                        ],
strategy= None,
usage_tracking=True)

parsl.load(config)


@python_app
def timer():

    x = time.time()
    return x

r = timer()

print(r)

parsl.dfk().cleanup()
