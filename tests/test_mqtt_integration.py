"""Opt-in real Mosquitto tests. No HAOS, cloud account or alarm required."""
import json
import os
import queue
import subprocess
import sys
import time
import unittest
import uuid

import paho.mqtt.client as mqtt

from h4.mqtt_bridge import BrokerSettings,MQTTBridge
from h4.protocol import Status


class Observer:
    def __init__(self,port):
        self.messages=queue.Queue()
        self.client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_message=lambda c,u,m:self.messages.put((m.topic,m.payload,m.retain))
        self.client.connect('127.0.0.1',port,keepalive=10)
        self.client.loop_start()
        self.client.subscribe('#',qos=1)
        # SUBACK completion: a round-trip publication is not sufficient when
        # retained messages exist, so wait explicitly for the subscription.
        self.ready=__import__('threading').Event()
        self.client.on_subscribe=lambda *args:self.ready.set()
        self.client.subscribe('#',qos=1)
        if not self.ready.wait(3):raise RuntimeError('Test subscriber failed')

    def wait(self,topic,payload=None,timeout=4):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:t,p,r=self.messages.get(timeout=max(.01,deadline-time.monotonic()))
            except queue.Empty:break
            if t==topic and (payload is None or p==payload):return p,r
        raise AssertionError('Expected MQTT test message did not arrive: '+topic)

    def publish(self,topic,payload,retain=False):
        info=self.client.publish(topic,payload,qos=1,retain=retain)
        info.wait_for_publish(3)

    def close(self):
        self.client.disconnect();self.client.loop_stop()


@unittest.skipUnless(os.environ.get('MQTT_TEST_PORT'),'Set MQTT_TEST_PORT to a local isolated test broker')
class MQTTIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.port=int(os.environ['MQTT_TEST_PORT'])
        self.observer=Observer(self.port)
        self.bridges=[]

    def tearDown(self):
        for bridge in self.bridges:bridge.close()
        self.observer.close()

    def bridge(self,controls=False,device_id=None):
        bridge=MQTTBridge(BrokerSettings('127.0.0.1',self.port),device_id or uuid.uuid4().hex,controls=controls)
        self.bridges.append(bridge);return bridge

    def test_discovery_state_availability_and_no_retained_state(self):
        bridge=self.bridge();bridge.start()
        config,_=self.observer.wait(f'homeassistant/sensor/{bridge.key}/mode/config')
        self.assertEqual(json.loads(config)['device']['model'],'H4')
        self.assertTrue(bridge.report(Status('armed_home','2',())))
        self.observer.wait(bridge.base+'/state',b'armed_home')
        self.observer.wait(bridge.base+'/availability',b'online')
        late=Observer(self.port)
        try:
            # A subscriber joining now sees availability, not a retained old
            # armed/disarmed assertion. Discovery must wait for the next poll.
            with self.assertRaises(AssertionError):late.wait(bridge.base+'/state',timeout=.2)
        finally:late.close()
        bridge.offline()
        self.observer.wait(bridge.base+'/availability',b'offline')

    def test_retained_command_is_not_replayed_and_offline_clears_queue(self):
        bridge=self.bridge(controls=True)
        self.observer.publish(bridge.base+'/command','ARM_HOME',retain=True)
        bridge.start();bridge.report(Status('disarmed','1',()))
        self.assertIsNone(bridge.take_command(.2))
        self.observer.publish(bridge.base+'/command','ARM_AWAY')
        token,action=bridge.take_command(3)
        self.assertEqual(action,'ARM_AWAY');self.assertTrue(bridge.command_valid(token))
        self.observer.publish(bridge.base+'/command','DISARM')
        self.assertIsNone(bridge.take_command(.2)) # busy; no second command
        bridge.offline();self.assertFalse(bridge.command_valid(token))
        self.assertIsNone(bridge.take_command(.1))

    def test_last_will_marks_a_crashed_bridge_offline(self):
        device=uuid.uuid4().hex
        bridge=self.bridge(device_id=device) # same deterministic topic; not connected
        script=('import os;from h4.mqtt_bridge import MQTTBridge,BrokerSettings;'
                'from h4.protocol import Status;'
                f'b=MQTTBridge(BrokerSettings("127.0.0.1",{self.port}),"{device}");'
                'b.start();assert b.report(Status("disarmed","1",()));os._exit(0)')
        process=subprocess.run([sys.executable,'-c',script],timeout=10,capture_output=True,text=True)
        self.assertEqual(process.returncode,0,process.stderr)
        self.observer.wait(bridge.base+'/availability',b'online')
        self.observer.wait(bridge.base+'/availability',b'offline')


if __name__=='__main__':unittest.main()
