"""No credentials/DSN arguments; owned full application and native MySQL only."""
from tests.run_teacher_work_full_app import main


if __name__ == "__main__":
    raise SystemExit(main(scenarios=("task_history",), test_file="native_teacher_work_task_history.py"))
