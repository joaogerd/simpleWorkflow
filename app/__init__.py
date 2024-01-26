#!/usr/bin/env python
# -----------------------------------------------------------------------------#
# Group on Data Assimilation Development - GDAD/CPTEC/INPE
# -----------------------------------------------------------------------------#
# BOP
#
# !SCRIPT:
# This is the __init__.py file for the runCycle package. It serves as an
# indicator that this directory is a Python package.
#
# !DESCRIPTION:
# This file defines the package for your runCycle project.
#
# !CALLING SEQUENCE:
# This package is designed to be imported and used in other Python scripts and
# projects for running tasks on a schedule.
#
# !REVISION HISTORY:
# - Nov 12, 2023, J. G. de Mattos: Initial Version
# - Nov 14, 2023, J. G. de Mattos: Added package documentation and formatting.
#
# !REMARKS:
# - The `runCycle` package is part of a project for managing and executing
#   scheduled tasks with dynamic updates. It includes components to facilitate
#   the execution of tasks in various environments.
#
# EOP
# -----------------------------------------------------------------------------#
# BOC
# Import the necessary modules and functions from within the package
from .TaskScheduler import TaskScheduler
from .ScriptExecutor import ScriptExecutor
from .DynamicTaskScheduler import DynamicTaskScheduler
from .EmailConfigManager import EmailConfigManager

# Optionally, you can make functions or classes available at the package level
__all__ = ['TaskScheduler', 'ScriptExecutor', 'DynamicTaskScheduler', 'EmailConfigManager']

# EOC
# -----------------------------------------------------------------------------#


