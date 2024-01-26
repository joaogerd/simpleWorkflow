# Task Scheduler

Task Scheduler is a Python application that allows you to schedule and execute tasks based on time and dependencies. It can be used to automate various tasks, such as running scripts, sending notifications, and more.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Contributing](#contributing)
- [License](#license)
- [Contact](#contact)

## Overview

Task Scheduler is designed to simplify the process of automating tasks in a scheduled and organized manner. It reads task configurations from a YAML file, checks the scheduled time, and executes tasks accordingly. You can set up dependencies between tasks, receive email notifications upon completion, and track task execution status.

## Features

- Schedule tasks based on time and dependencies.
- Execute scripts and commands.
- Email notifications on task completion.
- Track task execution status.
- Supports YAML configuration for task definitions.
- Easy-to-use and customizable.

## Requirements

- Python 3.6 or higher
- `pip` (Python package manager)

## Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/yourusername/task-scheduler.git
   cd task-scheduler
   ```
2. Install the required dependencies:

   ```bash
   pip install -r requirements.txt
   ```

## Configuration

1. Create a YAML file (`script_config.yaml`) to define your tasks. You can use the provided `scripts.yaml` as a template.

2. Customize the task configurations in the YAML file, specifying task names, execution times, dependencies, and more.

3. Configure your email settings in the `email_config` dictionary in `runCycle.py` to enable email notifications.

## Usage

1. Create a YAML file (`script_config.yaml`) to define your tasks. You can use the provided `scripts.yaml` as a template.

2. Customize the task configurations in the YAML file, specifying task names, execution times, dependencies, and more.

3. Configure your email settings in the `email_config` dictionary in `runCycle.py` to enable email notifications.

4. Modify the `runCycle.py` script to fit your specific requirements, including task execution functions and email settings.

5. Run the `runCycle.py` script to start the task scheduler:

   ```bash
   python runCycle.py
   ```

6. The script will continuously check the current time and execute tasks that match the scheduled time, considering task dependencies and tracking task statuses.

7. You will receive email notifications upon successful task completion or failures, depending on your email configuration.

8. Monitor the execution and status of your tasks in the console output and email notifications.

9. Customize and expand the functionality as needed for your specific workflow.

10. Enjoy efficient task scheduling and automation with the RunCycle framework!

## Example Task Configuration (script_config.yaml):

    ```yaml
    - task:
        name: Task1
        time:
          - "08:00"
          - "12:00"
          - "16:00"
        block:
          - run: /bin/bash script1.sh arg1 arg2
          - run: /bin/bash script2.sh arg1 arg2
          - run: /bin/bash script3.sh arg1 arg2
    
    - task:
        name: Task2
        cron_expression: "0 3 * * *"
        block:
          - run: /bin/bash script4.sh arg1 arg2
    
    - task:
        name: Task3
        time:
          - "09:00"
        block:
          - run: /bin/bash script5.sh arg1 arg2
        depend_on: Task1
    ```

## Contributing
Contributions are welcome! If you want to contribute to this project, please follow the guidelines in the CONTRIBUTING file.

## License
This project is licensed under the MIT License - see the LICENSE file for details.

## Contact
For questions or feedback, you can contact the project maintainer:

Name: Joao Gerd
Email: joao.gerd@inpe.br
GitHub: github.com/joaogerd

