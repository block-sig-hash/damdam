"""Worker durability settings are a contract — US-42, chunk 26D.

These assertions look tautological and are not. Each value below is the
difference between a killed worker losing its work silently and the broker
redelivering it, and each is the kind of setting somebody reverts while tuning
throughput without realising what it was for. The reason lives next to the
assertion so the next person has to argue with it rather than around it.
"""

from __future__ import annotations

from datetime import timedelta

from app.worker import celery_app


class TestNoWorkIsLostWhenAWorkerDies:
    def test_tasks_are_acknowledged_after_the_work_not_on_receipt(self) -> None:
        """Celery's default acks on pickup, so `kill -9` loses the task.

        Everything in this worker provisions eSIMs, settles calls or moves
        money. None of it is work that may vanish without a trace.
        """
        assert celery_app.conf.task_acks_late is True

    def test_a_task_whose_worker_vanished_is_requeued(self) -> None:
        assert celery_app.conf.task_reject_on_worker_lost is True

    def test_a_worker_holds_one_task_at_a_time(self) -> None:
        """With late acks, prefetching turns one lost worker into a burst.

        It also stops a single slow task parking a whole queue behind it.
        """
        assert celery_app.conf.worker_prefetch_multiplier == 1

    def test_redelivery_cannot_overtake_a_task_that_is_still_running(self) -> None:
        """The duplicate-purchase scenario, in scheduling form.

        Redis has no broker-side ack timeout, so an unacked task is redelivered
        after `visibility_timeout`. If that were shorter than the slowest task's
        hard limit, a task still running would get a second worker.
        """
        visibility = celery_app.conf.broker_transport_options["visibility_timeout"]

        assert visibility > celery_app.conf.task_time_limit

    def test_the_hard_limit_leaves_room_for_the_soft_one_to_be_handled(self) -> None:
        """The soft limit raises inside the task; the hard limit kills it.

        Equal limits would make the soft one unusable — there would be no
        window in which a task could clean up after itself.
        """
        assert celery_app.conf.task_time_limit > celery_app.conf.task_soft_time_limit


class TestAWorkerCanBeRestartedSafely:
    def test_a_deploy_that_starts_before_the_broker_does_not_exit(self) -> None:
        assert celery_app.conf.broker_connection_retry_on_startup is True

    def test_sigterm_finishes_the_task_in_hand(self) -> None:
        assert celery_app.conf.worker_soft_shutdown_timeout > 0

    def test_workers_are_recycled_so_a_slow_leak_is_not_an_outage(self) -> None:
        assert 0 < celery_app.conf.worker_max_tasks_per_child <= 1000

    def test_results_expire_because_they_are_diagnostic_not_authoritative(
        self,
    ) -> None:
        """Every task records its real outcome in the database.

        Keeping results forever grows Redis without bound for data nothing
        reads back.
        """
        assert celery_app.conf.result_expires == timedelta(hours=6)


class TestTheScheduleStillHoldsItsPromises:
    def test_the_calling_deadline_check_runs_faster_than_a_hold_can_expire(
        self,
    ) -> None:
        """V03's bound: a renewal check slower than the shortest hold arrives
        after the money is already spoken for."""
        entry = celery_app.conf.beat_schedule["calling-resolve-due-deadlines"]

        assert entry["schedule"] <= 60.0
