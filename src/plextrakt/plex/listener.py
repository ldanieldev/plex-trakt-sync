import threading
import time

import structlog

from plextrakt.obs import metrics

log = structlog.get_logger()


def _default_factory(server, callback, callback_error):
    from plexapi.alert import AlertListener

    return AlertListener(server, callback, callback_error)


class SupervisedListener:
    def __init__(
        self,
        server,
        on_playing,
        listener_factory=None,
        check_interval=5.0,
        restart_delay=15.0,
        sleep=time.sleep,
        stop_event: threading.Event | None = None,
    ):
        self._server = server
        self._on_playing = on_playing
        self._factory = listener_factory or _default_factory
        self._check_interval = check_interval
        self._restart_delay = restart_delay
        self._sleep = sleep
        self._stop = stop_event or threading.Event()

    def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                listener = self._factory(self._server, self._callback, self._on_error)
                listener.start()
            except Exception:
                metrics.LISTENER_RESTARTS.inc()
                log.exception("listener_start_failed", delay=self._restart_delay)
                self._sleep(self._restart_delay)
                continue
            log.info("listener_started")
            while listener.is_alive() and not self._stop.is_set():
                self._sleep(self._check_interval)
            if self._stop.is_set():
                listener.stop()
                return
            metrics.LISTENER_RESTARTS.inc()
            log.warning("listener_died_restarting", delay=self._restart_delay)
            self._sleep(self._restart_delay)

    def stop(self) -> None:
        self._stop.set()

    def _callback(self, data: dict) -> None:
        if data.get("type") != "playing":
            return
        for notification in data.get("PlaySessionStateNotification", []):
            try:
                self._on_playing(notification)
            except Exception:
                log.exception("playing_handler_failed", notification=notification)

    def _on_error(self, error) -> None:
        log.warning("listener_error", error=str(error))
