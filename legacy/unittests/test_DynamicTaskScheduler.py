
import unittest
from DynamicTaskScheduler import DynamicTaskScheduler

class TestDynamicTaskScheduler(unittest.TestCase):
    """Unit tests for DynamicTaskScheduler class."""

    def setUp(self):
        """Set up test environment for DynamicTaskScheduler."""
        self.scheduler = DynamicTaskScheduler()

    def test_add_and_remove_task(self):
        """Test adding and removing a task."""
        task_id = self.scheduler.add_task(lambda: None)
        self.assertIn(task_id, self.scheduler.tasks)
        self.scheduler.remove_task(task_id)
        self.assertNotIn(task_id, self.scheduler.tasks)

if __name__ == '__main__':
    unittest.main()
