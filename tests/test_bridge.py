import json
import contextlib
import io
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from zoneinfo import ZoneInfo

from h4.bridge import Confirmation,connected_loop,run_bridge
from h4.client import NetworkError
from h4.mqtt_bridge import BrokerSettings,MQTTBridge,broker_settings,discovery
from h4.errors import MQTTError
from h4.__main__ import main
from h4.protocol import AuthenticationError,Status


class BridgeTests(unittest.TestCase):
    def test_supervisor_discovery_uses_fixed_local_endpoint_and_hides_credentials(self):
        data={'result':'ok','data':{'host':'core-mosquitto','port':1883,
                                  'username':'fake-user','password':'fake-password','ssl':False}}
        connection=Mock();connection.getresponse.return_value.status=200
        connection.getresponse.return_value.read.return_value=json.dumps(data).encode()
        with patch.dict('os.environ',{'SUPERVISOR_TOKEN':'fake-token'}), \
                patch('h4.mqtt_bridge.http.client.HTTPConnection',return_value=connection) as factory:
            settings=broker_settings({})
            factory.assert_called_once_with('supervisor',80,timeout=10)
            connection.request.assert_called_once_with('GET','/services/mqtt',headers={'Authorization':'Bearer fake-token'})
        self.assertEqual(settings.host,'core-mosquitto')
        self.assertNotIn('fake-password',repr(settings))
        self.assertNotIn('fake-user',repr(settings))

    def test_supervisor_redirect_is_not_followed(self):
        connection=Mock();connection.getresponse.return_value.status=302
        connection.getresponse.return_value.read.return_value=b'private-response'
        with patch.dict('os.environ',{'SUPERVISOR_TOKEN':'fake-token'}), \
                patch('h4.mqtt_bridge.http.client.HTTPConnection',return_value=connection):
            with self.assertRaises(MQTTError) as caught:broker_settings({})
            self.assertNotIn('private-response',str(caught.exception))
            self.assertEqual(connection.request.call_count,1)

    def test_supervisor_failure_is_visible_in_cli_without_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'options.json'
            path.write_text(json.dumps({'run_mode':'mqtt','password':'secret-not-to-log'}))
            errors=io.StringIO()
            with patch('h4.bridge.run_bridge',side_effect=MQTTError('HAOS MQTT service returned HTTP 403')), \
                    contextlib.redirect_stderr(errors):
                self.assertEqual(main(['--options',str(path)]),1)
            self.assertIn('MQTT failure: HAOS MQTT service returned HTTP 403',errors.getvalue())
            self.assertNotIn('secret-not-to-log',errors.getvalue())

    def test_discovery_controls_are_opt_in_and_state_has_availability(self):
        off=discovery('abc',False,10);on=discovery('abc',True,10)
        alarm='homeassistant/alarm_control_panel/abc/alarm/config'
        self.assertIsNone(off[alarm])
        self.assertEqual(on[alarm]['supported_features'],['arm_home','arm_away'])
        self.assertFalse(on[alarm]['retain'])
        for config in on.values():self.assertEqual(config['availability_topic'],'chuango_h4/abc/availability')

    def test_retained_duplicate_stale_and_busy_commands_are_not_queued(self):
        bridge=MQTTBridge(BrokerSettings('localhost'),'PANEL0001',controls=True)
        bridge.connected.set()
        import time
        bridge._fresh_at=time.monotonic()
        for retain,dup in ((True,False),(False,True)):
            message=SimpleNamespace(topic=bridge.base+'/command',payload=b'ARM_HOME',retain=retain,dup=dup)
            bridge._on_message(None,None,message)
            self.assertIsNone(bridge.take_command(0))
        message=SimpleNamespace(topic=bridge.base+'/command',payload=b'ARM_HOME',retain=False,dup=False)
        bridge._fresh_at=time.monotonic()-100
        bridge._on_message(None,None,message);self.assertIsNone(bridge.take_command(0))
        bridge._fresh_at=time.monotonic()
        bridge._on_message(None,None,message)
        self.assertEqual(bridge.take_command(0),(0,'ARM_HOME'))
        bridge._on_message(None,None,message);self.assertIsNone(bridge.take_command(0))
        bridge._invalidate();bridge._fresh_at=time.monotonic()
        self.assertFalse(bridge.command_valid(0))
        bridge._on_message(None,None,message)
        bridge.release_command(0) # stale completion must not release the new command.
        self.assertEqual(bridge._busy,2)
        self.assertEqual(bridge.take_command(0),(1,'ARM_HOME'))

    def test_confirmation_requires_state_and_obeys_deadline(self):
        confirmation=Confirmation('ARM_HOME',30,100)
        self.assertIsNone(confirmation.outcome(Status('disarmed','1',()),101))
        self.assertEqual(confirmation.outcome(Status('armed_home','2',()),102),'confirmed')
        self.assertEqual(confirmation.outcome(Status('disarmed','1',()),131),'not_confirmed')
        self.assertEqual(confirmation.outcome(Status('armed_home','2',()),131),'not_confirmed')

    def test_worker_does_not_publish_requested_mode_from_ack(self):
        stop=threading.Event();reports=[];results=[]
        class Client:
            commands=[]
            def status(self,now):
                codes=['1','1','2'];code=codes[len(reports)]
                if len(reports)==2:stop.set()
                return Status({'1':'disarmed','2':'armed_home'}[code],code,())
            def change_mode(self,code):self.commands.append(code)
            def heartbeat(self):pass
        class Broker:
            sent=False
            def report(self,status):reports.append(status.mode)
            def result(self,result):results.append((result,len(reports)))
            def release_command(self,epoch):pass
            def command_valid(self,epoch):return True
            def take_command(self,timeout):
                if self.sent:return None
                self.sent=True;return 0,'ARM_HOME'
        client=Client()
        stable=Mock()
        connected_loop(client,Broker(),stop,interval=0,zone=ZoneInfo('UTC'),confirmation_timeout=30,on_stable=stable)
        self.assertEqual(client.commands,['2'])
        self.assertEqual(reports,['disarmed','disarmed','armed_home'])
        self.assertEqual(results,[('pending',1),('confirmed',3)])
        stable.assert_called_once()

    def test_authentication_notifications_stop_without_relogin(self):
        client=Mock();client.connect.side_effect=AuthenticationError('session ended')
        broker=Mock();stop=threading.Event()
        options={'device_id':'PANEL0001','username':'owner123','password':'secret456',
                 'allow_plaintext':True,'mqtt_host':'localhost'}
        with self.assertRaises(AuthenticationError):
            run_bridge(options,stop=stop,client_factory=lambda *a,**k:client,
                       broker_factory=lambda *a,**k:broker)
        self.assertEqual(client.connect.call_count,1)
        broker.close.assert_called_once()

    def test_network_retries_are_bounded(self):
        client=Mock();client.connect.side_effect=NetworkError('connection timed out')
        broker=Mock();stop=Mock();stop.is_set.return_value=False;stop.wait.return_value=False
        options={'device_id':'PANEL0001','username':'owner123','password':'secret456',
                 'allow_plaintext':True,'mqtt_host':'localhost','reconnect_attempts':2}
        with self.assertRaises(NetworkError):
            run_bridge(options,stop=stop,client_factory=lambda *a,**k:client,
                       broker_factory=lambda *a,**k:broker)
        self.assertEqual(client.connect.call_count,3)
        self.assertEqual([call.args[0] for call in stop.wait.call_args_list],[30,60])

    def test_uncertain_command_is_not_replayed_after_network_reconnect(self):
        stop=threading.Event()
        client=Mock();reads=[]
        def status(now):
            reads.append(now)
            if len(reads)==2:stop.set()
            return Status('disarmed','1',())
        client.status.side_effect=status
        client.change_mode.side_effect=NetworkError('mode command timed out')
        broker=Mock();broker.take_command.side_effect=[(0,'ARM_HOME'),None]
        broker.command_valid.return_value=True
        options={'device_id':'PANEL0001','username':'owner123','password':'secret456',
                 'allow_plaintext':True,'mqtt_host':'localhost','enable_controls':True}
        with patch.object(stop,'wait',return_value=False):
            run_bridge(options,stop=stop,client_factory=lambda *a,**k:client,
                       broker_factory=lambda *a,**k:broker)
        self.assertEqual(client.connect.call_count,2)
        client.change_mode.assert_called_once_with('2')
        self.assertIn(('unconfirmed',),[call.args for call in broker.result.call_args_list])
        self.assertNotIn(('confirmed',),[call.args for call in broker.result.call_args_list])


if __name__=='__main__':unittest.main()
