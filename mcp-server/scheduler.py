"""Background task scheduler for portfolio operations."""

import sys
import json
import uuid
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List
from collections import deque

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

# Add crypto-portfolio src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "crypto-portfolio" / "src"))
from crypto_portfolio.manager import PortfolioManager

logger = logging.getLogger(__name__)

VALID_TASK_TYPES = [
    "daily_report",
    "sync_binance",
    "check_recommendations",
    "get_status",
]


class TaskScheduler:
    """Manages scheduled and on-demand portfolio tasks."""

    def __init__(self, portfolio_file: str, use_binance: bool = False):
        self.portfolio_file = portfolio_file
        self.use_binance = use_binance
        self._task_meta: Dict[str, Dict] = {}
        self._results: deque = deque(maxlen=100)

        self._scheduler = BackgroundScheduler(timezone="UTC")
        self._scheduler.start()
        logger.info("Scheduler started")

    # ------------------------------------------------------------------
    # Internal execution
    # ------------------------------------------------------------------

    def _execute(self, task_type: str) -> str:
        pm = PortfolioManager(self.portfolio_file, use_binance=self.use_binance)

        if task_type == "daily_report":
            return pm.get_daily_report()

        if task_type == "sync_binance":
            balances = pm.sync_from_binance()
            lines = [f"  {b['asset']}: {b['amount']}" for b in balances]
            return f"Synced {len(balances)} assets from Binance:\n" + "\n".join(lines)

        if task_type == "check_recommendations":
            recs = pm.get_recommendations()
            if not recs:
                return "No recommendations at this time."
            lines = [
                f"- [{r['priority'].upper()}] {r['action']} {r['asset']}: {r['rationale']}"
                for r in recs[:10]
            ]
            return f"{len(recs)} recommendation(s):\n" + "\n".join(lines)

        if task_type == "get_status":
            return pm.get_status(format="text")

        raise ValueError(f"Unknown task type '{task_type}'. Valid: {VALID_TASK_TYPES}")

    def _run_and_record(self, task_type: str, job_id: str = "") -> str:
        timestamp = datetime.utcnow().isoformat() + "Z"
        try:
            output = self._execute(task_type)
            status = "success"
            error = None
        except Exception as exc:
            output = f"Task failed: {exc}"
            status = "error"
            error = str(exc)
            logger.error("Task %s failed: %s", task_type, exc)

        self._results.appendleft(
            {
                "task_type": task_type,
                "job_id": job_id,
                "timestamp": timestamp,
                "status": status,
                "output": output,
                "error": error,
            }
        )
        return output

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_task(
        self,
        task_type: str,
        trigger_type: str,
        trigger_config: Dict,
        label: str = "",
    ) -> str:
        if task_type not in VALID_TASK_TYPES:
            raise ValueError(
                f"Unknown task type '{task_type}'. Valid: {VALID_TASK_TYPES}"
            )

        if trigger_type == "cron":
            trigger = CronTrigger(**trigger_config)
        elif trigger_type == "interval":
            trigger = IntervalTrigger(**trigger_config)
        else:
            raise ValueError(
                f"Unknown trigger type '{trigger_type}'. Use 'cron' or 'interval'."
            )

        job_id = str(uuid.uuid4())[:8]
        job_name = label or task_type

        self._scheduler.add_job(
            self._run_and_record,
            trigger=trigger,
            args=[task_type, job_id],
            id=job_id,
            name=job_name,
            replace_existing=True,
        )

        self._task_meta[job_id] = {
            "task_type": task_type,
            "trigger_type": trigger_type,
            "trigger_config": trigger_config,
            "label": job_name,
        }

        logger.info("Scheduled %s (id=%s) with %s trigger", task_type, job_id, trigger_type)
        return job_id

    def cancel_task(self, job_id: str) -> None:
        try:
            self._scheduler.remove_job(job_id)
        except Exception as exc:
            raise ValueError(f"Job '{job_id}' not found: {exc}") from exc
        self._task_meta.pop(job_id, None)
        logger.info("Cancelled task %s", job_id)

    def list_tasks(self) -> List[Dict]:
        tasks = []
        for job in self._scheduler.get_jobs():
            meta = self._task_meta.get(job.id, {})
            tasks.append(
                {
                    "id": job.id,
                    "label": job.name,
                    "task_type": meta.get("task_type", "unknown"),
                    "trigger": str(job.trigger),
                    "next_run": (
                        job.next_run_time.isoformat()
                        if job.next_run_time
                        else "paused"
                    ),
                    "status": "active" if job.next_run_time else "paused",
                }
            )
        return tasks

    def run_task_now(self, task_type: str) -> str:
        return self._run_and_record(task_type)

    def get_recent_results(self, limit: int = 10) -> List[Dict]:
        return list(self._results)[:limit]

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")
