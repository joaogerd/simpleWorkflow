import threading
import time
from .TaskScheduler import TaskScheduler
from .ScriptExecutor import ScriptExecutor  # Import the ScriptExecutor class

class DynamicTaskScheduler(TaskScheduler):
    """
    A class for dynamically scheduling and managing tasks.

    This class allows for the scheduling of tasks which can be dynamically updated based on certain conditions 
    or events. It provides methods to add, remove, and update tasks, as well as to execute them based on a schedule.

    Attributes:
        tasks (list): A list of scheduled tasks.

    Methods:
        add_task(task: Task) -> None
            Adds a new task to the scheduler.

            Args:
                task (Task): The task to add to the scheduler.

            Example:
                >>> dts = DynamicTaskScheduler()
                >>> dts.add_task(my_task)

        remove_task(task_id: int) -> None
            Removes a task from the scheduler.

            Args:
                task_id (int): The ID of the task to remove.

            Example:
                >>> dts = DynamicTaskScheduler()
                >>> dts.remove_task(123)

        update_task(task_id: int, new_task: Task) -> None
            Updates an existing task in the scheduler.

            Args:
                task_id (int): The ID of the task to update.
                new_task (Task): The new task details.

            Example:
                >>> dts = DynamicTaskScheduler()
                >>> dts.update_task(123, updated_task)

    """

    def __init__(self, email_config, yaml_file_path, update_interval=60, **kwargs):
        super().__init__(email_config, **kwargs)
        self.yaml_file_path = yaml_file_path
        self.update_interval = update_interval
        self.executor = ScriptExecutor(verbose=True)  # Create an instance of ScriptExecutor
        
    def update_tasks(self):
        print("Updating tasks...")
        while True:
            yaml_data = self.executor.load_yaml_file(self.yaml_file_path)

            # Clear existing tasks
            self.tasks = []

            # Add new tasks
            tasks = [item for item in yaml_data if 'task' in item]
            for task_data in tasks:
                self.add_task(task_data['task'])
                
            
            time.sleep(self.update_interval)

    def start_scheduler(self):
        """
        Start the task scheduler and execute tasks.
    
        This method continuously checks the current time and executes tasks that match the scheduled time.
        It considers task dependencies and tracks the status of executed tasks.
    
        Returns:
            None
        """

        # Start the update_tasks method in a separate thread
        update_thread = threading.Thread(target=self.update_tasks)
        update_thread.daemon = True  # Allow the program to exit even if this thread is still running
        update_thread.start()

        while True:
            current_time = time.strftime("%H:%M", time.localtime())
    
            for task in self.tasks:
                task_name = task["name"]
    
                # Check if the task should be executed based on the scheduled time
                if task["time"] is None or current_time in task["time"]:

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

#EOC
#-----------------------------------------------------------------------------#

