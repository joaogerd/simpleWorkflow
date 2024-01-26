#!/usr/bin/env python
#-----------------------------------------------------------------------------#
#           Group on Data Assimilation Development - GDAD/CPTEC/INPE          #
#-----------------------------------------------------------------------------#
#BOP
#
# !SCRIPT:
#
# !DESCRIPTION:
#
# !CALLING SEQUENCE:
#
# !REVISION HISTORY: 
# 05 nov 2023 - J. G. de Mattos - Initial Version
#
# !REMARKS:
#
#EOP
#-----------------------------------------------------------------------------#
#BOC
from app.ScriptExecutor import ScriptExecutor
from app.DynamicTaskScheduler import DynamicTaskScheduler  # Import the DynamicTaskScheduler class

def main():
    email_config = {
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_username": "joao.gerd@gmail.com",
        "smtp_password": "Huhm$80306",  # Replace with your Gmail App Password
        "from_email": "joao.gerd@gmail.com",
        "to_email": "joao.gerd@inpe.br"
    }

    # Replace 'script_config.yaml' with the correct path to your YAML file
    yaml_file_path = 'script_config.yaml'

    # Initialize the ScriptExecutor class
    executor = ScriptExecutor(verbose=True)

    # Initialize the DynamicTaskScheduler class with email configuration, YAML file path, and update interval
    task_scheduler = DynamicTaskScheduler(email_config, yaml_file_path, update_interval=60, max_attempts=3, sleep_failure=1)

    # Execute tasks using TaskScheduler
    failed_tasks = task_scheduler.start_scheduler()

    # If there are failed tasks, print their names
    if failed_tasks:
        for task in failed_tasks:
            print(f"Task Name: {task['name']}")

    # If no tasks failed, print a success message
    if not failed_tasks:
        print("All tasks executed successfully.")

if __name__ == '__main__':
    main()

#EOC
#-----------------------------------------------------------------------------#

