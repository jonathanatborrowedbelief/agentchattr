"""Agent trigger — writes to queue files picked up by visible worker terminals."""

import json
import logging
from pathlib import Path

from agent_activity import AgentActivityStore
from queue_io import queue_lock

log = logging.getLogger(__name__)


class AgentTrigger:
    def __init__(
        self,
        registry,
        data_dir: str = "./data",
        activity_store: AgentActivityStore | None = None,
    ):
        self._registry = registry
        self._data_dir = Path(data_dir)
        self._activity = activity_store or AgentActivityStore()

    def is_available(self, name: str) -> bool:
        return self._registry.is_registered(name)

    @staticmethod
    def _append_queue_entry(queue_file: Path, entry: dict) -> None:
        with queue_lock(queue_file):
            with open(queue_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

    def get_status(self) -> dict:
        from mcp_bridge import get_role, is_active, is_online
        instances = self._registry.get_all()
        status = {}
        for name, info in instances.items():
            activity = self._activity.snapshot(name)
            status[name] = {
                "available": is_online(name),
                "busy": activity["state"] == "WORKING" or is_active(name),
                "label": info["label"],
                "color": info["color"],
                "role": get_role(name),
                **activity,
            }
        return status

    async def trigger(self, agent_name: str, message: str = "", channel: str = "general",
                      job_id: int | None = None, **kwargs):
        """Write to the agent's queue file. The worker terminal picks it up."""
        queue_file = self._data_dir / f"{agent_name}_queue.jsonl"
        self._data_dir.mkdir(parents=True, exist_ok=True)

        import time
        entry = {
            "sender": message.split(":")[0].strip() if ":" in message else "?",
            "text": message,
            "time": time.strftime("%H:%M:%S"),
            "channel": channel,
        }
        custom_prompt = kwargs.get("prompt", "")
        if isinstance(custom_prompt, str) and custom_prompt.strip():
            entry["prompt"] = custom_prompt.strip()
        if job_id is not None:
            entry["job_id"] = job_id

        self._append_queue_entry(queue_file, entry)

        self._activity.mark_queued(agent_name, channel=channel, job_id=job_id or 0)
        log.info("Queued @%s trigger (ch=%s, job=%s)", agent_name, channel, job_id)

    def trigger_sync(self, agent_name: str, message: str = "", channel: str = "general",
                     job_id: int | None = None, **kwargs):
        """Synchronous version of trigger — writes to queue file without async."""
        queue_file = self._data_dir / f"{agent_name}_queue.jsonl"
        self._data_dir.mkdir(parents=True, exist_ok=True)

        import time
        entry = {
            "sender": message.split(":")[0].strip() if ":" in message else "?",
            "text": message,
            "time": time.strftime("%H:%M:%S"),
            "channel": channel,
        }
        custom_prompt = kwargs.get("prompt", "")
        if isinstance(custom_prompt, str) and custom_prompt.strip():
            entry["prompt"] = custom_prompt.strip()
        if job_id is not None:
            entry["job_id"] = job_id

        self._append_queue_entry(queue_file, entry)

        self._activity.mark_queued(agent_name, channel=channel, job_id=job_id or 0)
        log.info("Queued @%s trigger (ch=%s, job=%s)", agent_name, channel, job_id)
