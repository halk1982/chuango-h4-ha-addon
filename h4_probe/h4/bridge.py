"""Continuous worker. One cloud session; no automatic retries of commands."""
import logging
import signal
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .client import NetworkError, StatusClient
from .mqtt_bridge import ACTIONS, MQTTBridge, MQTTError, broker_settings
from .protocol import AuthenticationError, CommandRejectedError, PanelOfflineError, ProtocolError

LOG = logging.getLogger(__name__)


class Confirmation:
    def __init__(self, action, timeout, now):
        self.target = ACTIONS[action]
        self.deadline = now+timeout

    def outcome(self, status, now):
        if now >= self.deadline:return "not_confirmed"
        if status.mode_code == self.target:return "confirmed"
        return None


def connected_loop(client, broker, stop, *, interval, zone, confirmation_timeout, on_stable=None):
    pending = None
    pending_epoch = None
    next_poll, next_heartbeat = 0, time.monotonic()+10
    stable_reads = 0
    while not stop.is_set():
        now = time.monotonic()
        if now >= next_poll:
            status = client.status(datetime.now(zone))
            broker.report(status)
            stable_reads += 1
            if stable_reads == 3 and on_stable:on_stable()
            if pending:
                outcome = pending.outcome(status,time.monotonic())
                if outcome:
                    broker.result(outcome)
                    broker.release_command(pending_epoch)
                    pending = None
            LOG.info("Panel mode=%s; accessories=%d",status.mode,len(status.accessories))
            next_poll = time.monotonic()+interval
        if time.monotonic() >= next_heartbeat:
            client.heartbeat()
            next_heartbeat = time.monotonic()+10
        command = broker.take_command(timeout=min(1,max(0,next_poll-time.monotonic())))
        if command is not None:
            epoch,action = command
            if not broker.command_valid(epoch):
                broker.release_command(epoch)
                continue
            broker.result("pending")
            try:
                client.change_mode(ACTIONS[action])
            except CommandRejectedError:
                broker.result("rejected")
                broker.release_command(epoch)
                continue
            pending = Confirmation(action,confirmation_timeout,time.monotonic())
            pending_epoch = epoch
            # Read actual state after the acknowledgement; never set the
            # reported state from the requested action or the ACK alone.
            next_poll = 0
    return stable_reads


def run_bridge(options, *, stop=None, client_factory=StatusClient, broker_factory=MQTTBridge):
    interval = options.get("interval",10)
    controls = options.get("enable_controls",False)
    confirm_timeout = options.get("confirmation_timeout",120)
    retries = options.get("reconnect_attempts",3)
    if type(interval) is not int or not 5 <= interval <= 300:
        raise ValueError("Invalid polling interval")
    if type(controls) is not bool or type(options.get("allow_plaintext",False)) is not bool:
        raise ValueError("Invalid control/transport flags")
    if type(confirm_timeout) is not int or not 15 <= confirm_timeout <= 300:
        raise ValueError("Invalid command confirmation timeout")
    if type(retries) is not int or not 0 <= retries <= 5:
        raise ValueError("Invalid reconnect limit")
    zone = ZoneInfo(options.get("timezone","Europe/Athens"))
    install_handlers = stop is None and threading.current_thread() is threading.main_thread()
    stop = stop if stop is not None else threading.Event()
    if install_handlers:
        for signum in (signal.SIGTERM,signal.SIGINT):
            signal.signal(signum,lambda *_:stop.set())
    client = client_factory(options.get("device_id",""),options.get("username",""),
                            options.get("password",""),allow_plaintext=options.get("allow_plaintext",False))
    broker = broker_factory(broker_settings(options),options["device_id"],controls=controls,interval=interval)
    LOG.info("Starting MQTT bridge; controls %s", "enabled (experimental)" if controls else "disabled")
    failures = 0
    def stable():
        nonlocal failures
        failures = 0
    try:
        broker.start()
        broker.result("idle")
        while not stop.is_set():
            try:
                client.connect()
                connected_loop(client,broker,stop,interval=interval,zone=zone,
                               confirmation_timeout=confirm_timeout,on_stable=stable)
                return
            except AuthenticationError:
                LOG.error("Alarm authentication/session ended. Stopping without login retries.")
                raise
            except (NetworkError,PanelOfflineError) as error:
                broker.offline()
                broker.result("unconfirmed")
                client.close()
                if failures >= retries:
                    LOG.error("Cloud reconnect limit reached; bridge stopped")
                    raise
                delay = min(300,30*2**failures)
                failures += 1
                LOG.warning("Alarm connection unavailable; retry %d/%d in %d seconds: %s",failures,retries,delay,error)
                if stop.wait(delay):return
            except ProtocolError:
                # Unrecognized replies or uncertain command outcomes need
                # review; reconnecting must not silently repeat a command.
                broker.result("unconfirmed")
                raise
    finally:
        try:client.close()
        finally:broker.close()
