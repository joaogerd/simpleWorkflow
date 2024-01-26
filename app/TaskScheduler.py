#!/usr/bin/env python

import time
import threading
import subprocess

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

class TaskScheduler:
    """
    A Python utility class for scheduling and managing tasks.

    This class facilitates the automation of task execution, managing dependencies, 
    handling failures, and sending email notifications.

    Attributes:
        None

    Methods:
        schedule_task(task_id: str, task_details: dict) -> None
            Schedules a new task with the given details.

            Args:
                task_id (str): The unique identifier for the task.
                task_details (dict): A dictionary containing details about the task, 
                                     such as time to run, action to perform, etc.

            Raises:
                TaskSchedulingError: If the task cannot be scheduled.

            Example:
                >>> ts = TaskScheduler()
                >>> ts.schedule_task("backup", {"time": "03:00", "action": "backup_database"})

        cancel_task(task_id: str) -> None
            Cancels a scheduled task.

            Args:
                task_id (str): The unique identifier for the task to be cancelled.

            Raises:
                TaskNotFoundError: If the task_id is not found in the scheduled tasks.

            Example:
                >>> ts = TaskScheduler()
                >>> ts.cancel_task("backup")

    """

    def __init__(self, email_config, max_attempts=3, sleep_failure=60, sleep_between_tasks=15):

        """
        Initialize the TaskScheduler with email configuration and optional parameters.

        Args:
            email_config (dict): A dictionary containing email configuration details.
            max_attempts (int, optional): Maximum number of retry attempts in case of failure. Default is 3.
            sleep_failure (int, optional): Time to sleep between retry attempts in seconds. Default is 60.
            sleep_between_tasks (int, optional): Time to sleep between checking for tasks in seconds. Default is 15.
        """

        self.email_config = email_config
        self.sleep_failure = sleep_failure # Time in seconds
        self.sleep_between_tasks = sleep_between_tasks # Time in seconds
        self.max_attempts = max_attempts  # Set a default value for max_attempts

        self.tasks = []
        self.completed_tasks = {} # Keep track of tasks that have been executed successfully

    def create_base_task(self, task_data):
        """
        Create a base task dictionary with common information.
    
        Args:
            task_name (str): The name of the task.
            task_time (str): The scheduled time for the task (in HH:MM format).
            task_func (callable): The function to be executed for the task.
            func_args (tuple): The arguments to be passed to the task function.
            depends_on (list or str): The dependencies for the task. Default is None.
            max_attempts (int): The maximum number of attempts for the task. Default is self.max_attempts.
    
        Returns:
            dict: The base task dictionary.
        """

        task_name     = task_data['name']
        task_time     = task_data.get('time', None)
        task_dep      = task_data.get('depend_on', None)
        task_attempts = task_data.get('max_attempts', self.max_attempts)
        task_block    = (task_data['block'],)
        task_func     = self.executor.execute_scripts

        return {
            "name": task_name,
            "time": task_time,
            "function": task_func,
            "function_args": task_block,
            "depends_on": task_dep,
            "max_attempts": task_attempts,
            "status": "Queue",  # Initial status when the task is added to the scheduler
            "subtasks": []
        }
    
    def add_task(self, task_data):
        """
        Add a task to the scheduler.
    
        Args:
            task_name (str): The name of the task.
            task_time (str): The scheduled time for the task (in HH:MM format).
            task_func (callable): The function to be executed for the task.
            func_args (tuple): The arguments to be passed to the task function.
            depends_on (list or str): The dependencies for the task. Default is None.
            max_attempts (int): The maximum number of attempts for the task. Default is self.max_attempts.
            subtasks (list): List of subtasks for the task. Each subtask is a dictionary.
    
        Returns:
            None
        """


        base_task = self.create_base_task(task_data)

        # Set subtask with a default value, which can be None
        subtask = None
        
        # Get the list of subtasks
        task_subtask = task_data.get('subtasks', None)
          
        # Process subtasks if available
        task_subtasks = task_data.get('subtasks', None)
        
        if task_subtasks:
            base_task["subtasks"] = [self.create_base_task(subtask) for subtask in task_subtasks]
    
        self.tasks.append(base_task)

        
    def start_scheduler(self):
        """
        Start the task scheduler and execute tasks.
    
        This method continuously checks the current time and executes tasks that match the scheduled time.
        It considers task dependencies and tracks the status of executed tasks.
    
        Returns:
            None
        """
        while True:
            current_time = time.strftime("%H:%M", time.localtime())
    
            for task in self.tasks:
                task_name = task["name"]
    
                # Check if the task should be executed based on the scheduled time
                if task["time"] is None or task["time"] == current_time:

                    # Check if the task has not been previously executed
                    is_task_not_completed = not self.is_task_completed(task_name)

                    # Check if the task dependencies are satisfied
                    are_dependencies_satisfied = self.check_dependencies(task)
                    
                    # Check if the maximum attempts for the task have not been reached
                    is_below_max_attempts = self.check_max_attempts(task)

                    if is_task_not_completed and are_dependencies_satisfied and is_below_max_attempts:
                        print(f"Executing task: {task_name}")
                        success = self.execute_task(task)
        
                        # Update the completed_tasks dictionary with the task status
                        if success:
                            self.completed_tasks[task_name] = {"status": "success"}
                            self.send_notification(task)
                        else:
                            self.handle_failure(task)
    
            time.sleep(self.sleep_between_tasks)

    def check_dependencies(self, task):
        """
        Check if all task dependencies are satisfied.

        Args:
            task (dict): The task to check for dependencies.

        Returns:
            bool: True if all dependencies are satisfied, otherwise False.
        """

        dependencies = task.get("depends_on")

        if not dependencies:
            return True

        if not isinstance(dependencies, list):
            dependencies = [dependencies]  # If it's not a list, transform it into one

        for dependency in dependencies:
            if not self.is_task_completed(dependency):
                return False
        return True
        
    def check_max_attempts(self, task):
        """
        Check if a task has reached its maximum number of retry attempts.

        Args:
            task (dict): The task to check.

        Returns:
            bool: True if the task has reached its maximum attempts, otherwise False.
        """
        task_name    = task.get('name')
        max_attempts = task.get('max_attempts',self.max_attempts)

        if task_name in self.completed_tasks:
            if self.completed_tasks[task_name]["status"] == "failed":
                if self.completed_tasks[task_name]["max_attempts"] >= max_attempts:
                    return False
        return True


    def is_task_completed(self, task_name):
        """
        Check if a specific task has been completed successfully.
    
        Args:
            task_name (str): The name of the task to check.
    
        Returns:
            bool: True if the task is completed successfully, otherwise False.
        """
        
        if task_name in self.completed_tasks:
            if self.completed_tasks[task_name]["status"] == "success":
                return True

        return False
        
    def execute_task(self, task):
        """
        Execute the specified task and update its status.
    
        Args:
            task (dict): The task to be executed.
    
        Returns:
            bool: True if the task was executed successfully, otherwise False.
        """
        try:
            success = task["function"](*task["function_args"])
            task["status"] = "success" if success else "failed"

            # Execute subtasks
            subtasks_success = all(self.execute_subtask(subtask) for subtask in task["subtasks"])

            print(f"Task executed {'successfully' if success and subtasks_success else 'with failure'}: {task['name']}")

            return success and subtasks_success
            
        except Exception as e:
            task["status"] = "Failed"
            print(f"Task execution failed: {task['name']}")
            print(f"Error details: {e}")
            return False


    def execute_subtask(self, subtask):
        """
        Execute a subtask and update its status.
    
        Args:
            subtask (dict): The subtask to be executed.
    
        Returns:
            bool: True if the subtask was executed successfully, otherwise False.
        """
        try:
            success = subtask["function"](*subtask["function_args"])
            subtask["status"] = "success" if success else "failed"
            print(f"Subtask executed {'successfully' if success else 'with failure'}: {subtask['name']}")
            return success
        except Exception as e:
            subtask["status"] = "Failed"
            print(f"Subtask execution failed: {subtask['name']}")
            print(f"Error details: {e}")
            return False

    def handle_failure(self, task):
        """
        Handle task failures, including retry attempts.

        Args:
            task (dict): The task that failed.
        """
        task_name = task.get('name')
        max_attempts = task.get('max_attempts', self.max_attempts)

        if task_name in self.completed_tasks:
            self.completed_tasks[task_name]['status'] = 'failed'
            self.completed_tasks[task_name]['max_attempts'] += 1
        else:
            self.completed_tasks[task_name] = {"status": "failed", "max_attempts": 1}

        print(f"Failure in task: {task_name}")
        remaining_attempts = max_attempts - self.completed_tasks[task_name]['max_attempts']

        # Check if the maximum attempts have been reached for the task
        if remaining_attempts > 0:
            print(f"Retrying {remaining_attempts} more times...")
            time.sleep(self.sleep_failure)
        else:
            print(f"Maximum attempts reached for task: {task_name}")

    def send_notification(self, task, success=True, error_message=None):
        """
        Send email notifications upon task completion.

        Args:
            task (dict): The task that was completed or failed.
            success (bool): True if the task was completed successfully, False otherwise.
            error_message (str, optional): Custom error message to include in the notification.
        """
        subject_prefix = "Task Completed" if success else "Task Failed"
        subject = f"{subject_prefix}: {task['name']}"
        
        body = f"Task {task['name']} was completed successfully." if success else f"Task {task['name']} failed."
        if error_message:
            body += f"\nError Details: {error_message}"

        try:
            msg = MIMEMultipart()
            msg.attach(MIMEText(body, 'plain'))
            msg["Subject"] = subject
            msg["From"] = self.email_config["from_email"]
            msg["To"] = self.email_config["to_email"]

            with smtplib.SMTP(self.email_config["smtp_server"], self.email_config["smtp_port"]) as server:
                server.starttls()
                server.login(self.email_config["smtp_username"], self.email_config["smtp_password"])
                server.sendmail(self.email_config["from_email"], self.email_config["to_email"], msg.as_string())
            print(f"Notification sent successfully for task: {task['name']}")

        except Exception as e:
            print(f"Failed to send notification for task {task['name']}.\nError: {e}")

# Example usage:
# task_scheduler = TaskScheduler(email_config, ...)
# task_scheduler.send_notification(task, success=True, error_message="Optional custom error message.")

#EOC

