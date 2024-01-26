from datetime import datetime, timedelta
import subprocess
import yaml
from dateutil.relativedelta import relativedelta
from .DateTimeParser import TimeParser

class ScriptExecutor:
    """
    A class for executing and managing scripts.

    This class provides methods to run different scripts and handle their execution results. 
    It is designed to execute scripts in a controlled environment, capturing output and errors.

    Attributes:
        None

    Methods:
        execute(script_path: str) -> str
            Executes a script located at the given path and returns its output.

            Args:
                script_path (str): The file path of the script to execute.

            Returns:
                str: The output of the executed script.

            Raises:
                FileNotFoundError: If the script file is not found.
                ScriptExecutionError: If there is an error during script execution.

            Example:
                >>> se = ScriptExecutor()
                >>> output = se.execute("/path/to/script.sh")

    """

    def __init__(self, verbose=False):
        """
        Initialize the ScriptExecutor class.

        Args:
            email_config (dict, optional): A dictionary containing email configuration details for sending notifications.
        """
        self.parser = TimeParser()
        self.context = {}
        self.failed_scripts = []  # Track scripts that fail
        self.verbose = verbose

    def run_script(self, command):
        """
        Run a script with the provided command.

        Args:
            command (str): The command to execute the script.

        Returns:
            bool: True if the script executed successfully, False if it failed.
        """
        try:
            subprocess.run(command, shell=True, check=True)
            return True
        except subprocess.CalledProcessError:
            return False
        except FileNotFoundError:
            print(f"Error: File not found - {command}")
            self.failed_scripts.append({"command": command, "error": "File not found"})
            return False

    def execute_scripts(self, script_list):
        """
        Execute a list of scripts, considering date-based loops and custom dates.

        Args:
            script_list (list): A list of scripts with command and optional loop information.

        Returns:
            list: A list of dictionaries containing information about failed scripts, if any.
        """
        self.failed_scripts = []  # Reset the list of failed scripts

        for cmd in script_list:
            if 'run' in cmd:
                modified_command = cmd['run']
                if not self.run_script(modified_command):
                    self.failed_scripts.append({"command": modified_command, "error": "Failed to execute"})
                    return False
            elif 'while' in cmd:
                while_block = cmd['while']
                if not self.run_while_block(while_block):
                    self.failed_scripts.append({"while_block": while_block, "error": "Failed to execute while block"})
                    return False

        return True

    def run_while_block(self, while_block):
        """
        Execute commands within a 'while' block based on the specified conditions.

        Args:
            while_block (dict): The 'while' block configuration.
        """
        from_date = self.parser.parse_expression(while_block["condition"]["from"])
        to_date = self.parser.parse_expression(while_block["condition"]["to"])
        increment = self.parser.parse_time_expression(while_block["condition"]["increment"])

        current_date = from_date
        while current_date < to_date:
            for cmd in while_block["do"]:
                if "run" in cmd:
                    modified_command = current_date.strftime(cmd['run'])
                    if self.verbose:
                        print(f"Executing: {modified_command}")
                    if not self.run_script(modified_command):
                        return False
                elif "while" in cmd:
                    nested_while_block = cmd["while"]
                    if self.verbose:
                        print("Executing nested 'while' block")
                    if not self.run_while_block(nested_while_block):
                        return False
            current_date += increment

        return True
        
    def load_yaml_file(self, file_path):
        """
        Load a YAML file and return its contents as a Python dictionary.

        Args:
            file_path (str): The path to the YAML file.

        Returns:
            dict: The contents of the YAML file as a Python dictionary.
        """
        with open(file_path, 'r') as file:
            yaml_contents = yaml.safe_load(file)
        return yaml_contents


