import threading

from plextrakt.plex.listener import SupervisedListener


class DyingListener:
    def __init__(self, server, callback, callback_error):
        self.alive = False

    def start(self):
        self.alive = True

    def stop(self):
        self.alive = False

    def is_alive(self):
        # dies immediately after the first liveness check
        was = self.alive
        self.alive = False
        return was


def test_restarts_dead_listener_until_stopped():
    created = []
    stop = threading.Event()
    sleeps = []

    def factory(server, callback, callback_error):
        listener = DyingListener(server, callback, callback_error)
        created.append(listener)
        return listener

    def fake_sleep(s):
        sleeps.append(s)
        if len(created) >= 3:
            stop.set()

    sup = SupervisedListener(
        server=object(),
        on_playing=lambda n: None,
        listener_factory=factory,
        sleep=fake_sleep,
        stop_event=stop,
    )
    sup.run_forever()
    assert len(created) >= 3
    assert 15.0 in sleeps  # restart backoff was applied


def test_callback_filters_playing_alerts():
    seen = []
    sup = SupervisedListener(
        server=object(),
        on_playing=seen.append,
        listener_factory=lambda s, c, e: DyingListener(s, c, e),
        stop_event=threading.Event(),
    )
    sup._callback(
        {
            "type": "playing",
            "PlaySessionStateNotification": [{"state": "playing", "sessionKey": "7"}],
        }
    )
    sup._callback({"type": "timeline", "TimelineEntry": [{}]})
    assert seen == [{"state": "playing", "sessionKey": "7"}]


def test_callback_survives_handler_exception():
    def boom(n):
        raise RuntimeError("handler bug")

    sup = SupervisedListener(
        server=object(),
        on_playing=boom,
        listener_factory=lambda s, c, e: DyingListener(s, c, e),
        stop_event=threading.Event(),
    )
    # must not raise
    sup._callback({"type": "playing", "PlaySessionStateNotification": [{"state": "playing"}]})
