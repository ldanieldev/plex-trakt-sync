from plextrakt.trakt.ratelimit import WriteRateLimiter


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept: list[float] = []

    def clock(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s


def test_first_call_does_not_sleep():
    fc = FakeClock()
    rl = WriteRateLimiter(clock=fc.clock, sleep=fc.sleep)
    rl.wait()
    assert fc.slept == []


def test_back_to_back_calls_are_spaced():
    fc = FakeClock()
    rl = WriteRateLimiter(min_interval=1.0, clock=fc.clock, sleep=fc.sleep)
    rl.wait()
    fc.now += 0.3
    rl.wait()
    assert fc.slept == [0.7]


def test_no_sleep_when_enough_time_passed():
    fc = FakeClock()
    rl = WriteRateLimiter(min_interval=1.0, clock=fc.clock, sleep=fc.sleep)
    rl.wait()
    fc.now += 5.0
    rl.wait()
    assert fc.slept == []
