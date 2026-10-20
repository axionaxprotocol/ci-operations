"""The poll interval must react to the remaining GitHub rate limit."""
import unittest

import desktop_service


class AdaptivePollTests(unittest.TestCase):
    def test_thin_rate_limit_slows_the_poll_down(self):
        self.assertGreaterEqual(desktop_service.poll_interval(rate_remaining='10'), 120)

    def test_healthy_rate_limit_keeps_the_poll_fast(self):
        self.assertLessEqual(desktop_service.poll_interval(rate_remaining='4500'), 30)

    def test_unknown_rate_limit_uses_the_default(self):
        self.assertEqual(desktop_service.poll_interval(rate_remaining=None), 30)

    def test_running_work_polls_faster_than_idle(self):
        idle = desktop_service.poll_interval(rate_remaining='4500', running=False)
        busy = desktop_service.poll_interval(rate_remaining='4500', running=True)
        self.assertLess(busy, idle)

    def test_a_low_rate_limit_never_polls_faster_than_the_backoff_floor(self):
        self.assertGreaterEqual(desktop_service.poll_interval(rate_remaining='1', running=True), 120)

    def test_the_interval_never_leaves_the_supported_range(self):
        for rate in ('0', '1', '199', '500', '999', '1000', '5000', None, 'garbage'):
            for running in (True, False):
                interval = desktop_service.poll_interval(rate_remaining=rate, running=running)
                self.assertGreaterEqual(interval, desktop_service.MIN_POLL_SECONDS)
                self.assertLessEqual(interval, desktop_service.MAX_POLL_SECONDS)

    def test_a_soft_rate_limit_backs_off_moderately(self):
        interval = desktop_service.poll_interval(rate_remaining='500')
        self.assertGreater(interval, desktop_service.MIN_POLL_SECONDS)
        self.assertLess(interval, desktop_service.MAX_POLL_SECONDS)


if __name__ == '__main__':
    unittest.main()
