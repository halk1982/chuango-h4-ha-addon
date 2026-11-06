"""MQTT Discovery, fresh-state availability and gated commands. No raw logs."""
import hashlib
import http.client
import json
import logging
import os
import queue
import ssl
import threading
import time
from dataclasses import dataclass, field

import paho.mqtt.client as mqtt
from .errors import MQTTError

LOG = logging.getLogger(__name__)
VERSION = "0.2.2"
ACTIONS = {"ARM_AWAY": "0", "DISARM": "1", "ARM_HOME": "2"}


@dataclass(frozen=True)
class BrokerSettings:
    host: str
    port: int = 1883
    username: str = field(default="", repr=False)
    password: str = field(default="", repr=False)
    tls: bool = False


def broker_settings(options):
    if options.get("mqtt_host"):
        data = {"host": options["mqtt_host"], "port": options.get("mqtt_port",1883),
                "username": options.get("mqtt_username",""), "password": options.get("mqtt_password",""),
                "ssl": options.get("mqtt_tls",False)}
    else:
        token = os.environ.get("SUPERVISOR_TOKEN")
        if not token:
            raise MQTTError("MQTT auto-discovery requires HAOS; configure a broker manually outside HAOS")
        # Fixed local HAOS endpoint. HTTPConnection never follows redirects or
        # forwards its bearer token to a different host or an outbound proxy.
        connection = http.client.HTTPConnection("supervisor", 80, timeout=10)
        try:
            connection.request("GET", "/services/mqtt", headers={"Authorization":"Bearer "+token})
            response = connection.getresponse()
            body = response.read(65537)
            if response.status != 200:
                raise MQTTError(f"HAOS MQTT service returned HTTP {response.status}; start Mosquitto and check service access")
            if len(body) > 65536:
                raise MQTTError("HAOS MQTT settings response was oversized")
            document = json.loads(body)
            if document.get("result") != "ok":
                raise ValueError("HAOS MQTT service did not return connection settings")
            data = document["data"]
        except (OSError, http.client.HTTPException, ValueError, KeyError, TypeError, AttributeError):
            raise MQTTError("Cannot obtain HAOS MQTT settings; check that Mosquitto is running") from None
        finally:
            connection.close()
    try:
        result = BrokerSettings(data["host"],data["port"],data.get("username",""),
                                data.get("password",""),data.get("ssl",False))
        if not isinstance(result.host,str) or not result.host or "/" in result.host:
            raise ValueError()
        if type(result.port) is not int or not 1 <= result.port <= 65535 or type(result.tls) is not bool:
            raise ValueError()
        if not isinstance(result.username,str) or not isinstance(result.password,str):
            raise ValueError()
        return result
    except (ValueError, KeyError, TypeError):
        raise MQTTError("Invalid MQTT connection settings") from None


def discovery(device_key, controls, interval):
    base = "chuango_h4/"+device_key
    device = {"identifiers":["chuango_h4_"+device_key], "name":"Chuango H4",
              "manufacturer":"Chuango", "model":"H4", "sw_version":VERSION}
    common = {"device":device,"availability_topic":base+"/availability",
              "payload_available":"online","payload_not_available":"offline"}
    items = {
        f"homeassistant/sensor/{device_key}/mode/config": {
            **common,"name":"Chuango H4 Mode","unique_id":device_key+"_mode",
            "state_topic":base+"/state","icon":"mdi:shield-home",
            "expire_after":interval+35},
        f"homeassistant/sensor/{device_key}/accessories/config": {
            **common,"name":"Chuango H4 Accessory count","unique_id":device_key+"_accessories",
            "state_topic":base+"/attributes","value_template":"{{ value_json.accessory_count }}",
            "entity_category":"diagnostic","expire_after":interval+35},
        f"homeassistant/sensor/{device_key}/command/config": {
            **common,"name":"Chuango H4 Command result","unique_id":device_key+"_command",
            "state_topic":base+"/command_result","entity_category":"diagnostic"},
    }
    alarm_topic = f"homeassistant/alarm_control_panel/{device_key}/alarm/config"
    items[alarm_topic] = ({**common,"name":"Chuango H4 Alarm","unique_id":device_key+"_alarm",
        "state_topic":base+"/state","command_topic":base+"/command",
        "supported_features":["arm_home","arm_away"],"code_arm_required":False,
        "code_disarm_required":False,"retain":False} if controls else None)
    return items


class MQTTBridge:
    def __init__(self, settings, device_id, *, controls=False, interval=10):
        self.key = hashlib.sha256(device_id.encode("ascii")).hexdigest()[:16]
        self.base = "chuango_h4/"+self.key
        self.settings, self.controls, self.interval = settings, controls, interval
        self.fresh_window = min(30,interval+20)
        self.connected = threading.Event()
        self._initial = threading.Event()
        self._lock = threading.Lock()
        self._fresh_at, self._busy, self._epoch = None, False, 0
        self._last_result = "idle"
        self._commands = queue.Queue(maxsize=1)
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id="chuango_h4_"+self.key,clean_session=True)
        self.client.connect_timeout = 10
        if settings.username:
            self.client.username_pw_set(settings.username,settings.password)
        if settings.tls:
            self.client.tls_set_context(ssl.create_default_context())
        self.client.will_set(self.base+"/availability","offline",qos=1,retain=True)
        self.client.reconnect_delay_set(min_delay=1,max_delay=60)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _invalidate(self):
        with self._lock:
            self._epoch += 1
            self._fresh_at, self._busy = None, False
            while not self._commands.empty():
                try:self._commands.get_nowait()
                except queue.Empty:break

    def _on_connect(self, client, userdata, flags, reason, properties):
        if reason.is_failure:
            LOG.error("MQTT connection rejected; check broker credentials and permissions")
            self._initial.set()
            return
        self._invalidate()
        self.connected.set()
        client.publish(self.base+"/availability","offline",qos=1,retain=True)
        self.publish_discovery()
        client.subscribe("homeassistant/status",qos=1)
        if self.controls:client.subscribe(self.base+"/command",qos=0)
        self._initial.set()

    def _on_disconnect(self, client, userdata, flags, reason, properties):
        self.connected.clear()
        self._invalidate()

    def publish_discovery(self):
        for topic, config in discovery(self.key,self.controls,self.interval).items():
            self.client.publish(topic,"" if config is None else json.dumps(config),qos=1,retain=True)

    def _on_message(self, client, userdata, message):
        if message.topic == "homeassistant/status" and message.payload == b"online":
            self.publish_discovery()
            return
        if message.topic != self.base+"/command":return
        if not self.controls or message.retain or message.dup:
            LOG.warning("Ignored disabled, retained or duplicated MQTT command")
            return
        if len(message.payload) > 16:return
        try:action = message.payload.decode("ascii")
        except UnicodeDecodeError:return
        if action not in ACTIONS:
            LOG.warning("Ignored unsupported MQTT command")
            return
        with self._lock:
            if (not self.connected.is_set() or self._fresh_at is None or self._busy
                    or time.monotonic()-self._fresh_at > self.fresh_window):
                LOG.warning("Ignored command while offline, stale or busy")
                return
            try:self._commands.put_nowait((self._epoch,action))
            except queue.Full:return
            self._busy = self._epoch+1

    def start(self):
        try:
            self.client.connect(self.settings.host,self.settings.port,keepalive=30)
            self.client.loop_start()
            if not self._initial.wait(15) or not self.connected.is_set():
                raise MQTTError("MQTT connection was not accepted")
        except OSError:
            raise MQTTError("Cannot connect to MQTT broker") from None

    def _publish(self, topic, payload, *, retain=False):
        if not self.connected.is_set():raise MQTTError("MQTT disconnected")
        info = self.client.publish(self.base+"/"+topic,payload,qos=1,retain=retain)
        try:
            info.wait_for_publish(timeout=5)
            if info.rc != mqtt.MQTT_ERR_SUCCESS or not info.is_published():
                raise MQTTError("MQTT publish was not acknowledged")
        except (ValueError,RuntimeError):
            raise MQTTError("MQTT publish failed") from None

    def report(self, status):
        received_at = time.monotonic()
        with self._lock:epoch = self._epoch
        try:
            self._publish("state",status.mode)
            self._publish("attributes",json.dumps({"mode_code":status.mode_code,
                                                   "accessory_count":len(status.accessories)}))
            self._publish("command_result",self._last_result)
            with self._lock:
                if self._epoch != epoch:return False
            if time.monotonic()-received_at > self.fresh_window:
                self.offline()
                return False
            self._publish("availability","online",retain=True)
        except MQTTError:
            self._invalidate()
            return False
        with self._lock:
            if self._epoch == epoch:
                self._fresh_at = received_at if status.mode != "unknown" else None
                return True
        self.offline()
        return False

    def offline(self):
        self._invalidate()
        try:self._publish("availability","offline",retain=True)
        except MQTTError:pass

    def take_command(self, timeout):
        try:epoch,action = self._commands.get(timeout=timeout)
        except queue.Empty:return None
        with self._lock:
            if (epoch != self._epoch or self._fresh_at is None
                    or time.monotonic()-self._fresh_at > self.fresh_window):
                if self._busy == epoch+1:self._busy = False
                return None
        return epoch,action

    def command_valid(self, epoch):
        with self._lock:
            return (self.connected.is_set() and epoch == self._epoch and self._busy == epoch+1
                    and self._fresh_at is not None and time.monotonic()-self._fresh_at <= self.fresh_window)

    def result(self, value):
        self._last_result = value
        try:self._publish("command_result",value)
        except MQTTError:pass

    def release_command(self, epoch):
        with self._lock:
            if self._busy == epoch+1:self._busy = False

    def close(self):
        self.offline()
        self.client.disconnect()
        self.client.loop_stop()
