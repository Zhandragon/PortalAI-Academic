"""Demand transitions with synthetic identity/state only; no production GUI/key."""
import sys
from pathlib import Path as _PortablePath
sys.path.insert(0,str(_PortablePath(__file__).resolve().parents[1]/'app'))
from host_runtime import default_target
import asyncio
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'app'), str(ROOT/'Tests'), str(ROOT/'Runtime/packages'), str(default_target()/'Agent')]
from viewer_demand import ViewerDemand
from projection_client import Client
from connection_vault import new_connection, public_pairing
from test_native_transport import Source, HubSocket, NativeHub, NativeTransport
from test_projection import receiver
import projection_worker as worker

spec = importlib.util.spec_from_file_location('ha_viewer_demand', ROOT.parent/'PortalAI HA Setup/Setup Files/HomeAssistant/custom_components/portalai_projection/viewer_demand.py')
ha = importlib.util.module_from_spec(spec); spec.loader.exec_module(ha)


def packet(screen=False, native=False):
    return {'version': 1, 'screen': screen, 'native': native, 'lease_seconds': 5}


class DemandTests(unittest.TestCase):
    def test_host_missing_malformed_and_expired_leases_fail_closed(self):
        now = [10.]; d = ViewerDemand(lambda: now[0])
        self.assertFalse(d.active('screen')); self.assertEqual(d.status(), 'receiver_update_required')
        d.update(packet(True), 10); token = d.token('screen')
        d.update(packet(True), 11); self.assertEqual(token, d.token('screen'))
        now[0] = 16; self.assertFalse(d.valid('screen', token))
        d.update(packet(True), 16); self.assertNotEqual(token, d.token('screen'))
        for value in ({**packet(), 'native': 1}, {**packet(), 'lease_seconds': 500}, {**packet(), 'extra': True}):
            with self.assertRaises(ValueError):d.update(value, 16)
            self.assertFalse(d.active('screen'))
        d.update(packet(True, True), 16); d.update(None, 16)
        self.assertFalse(d.active('native')); self.assertEqual(d.status(), 'receiver_update_required')

    def test_slow_response_cannot_extend_lease(self):
        d = ViewerDemand(lambda: 100.)
        d.update(packet(True, True), 90.)
        self.assertFalse(d.active('screen')); self.assertFalse(d.active('native'))

    def test_frame_guard_runs_after_slow_status_and_keeps_replies(self):
        now = [1.]; d = ViewerDemand(lambda: now[0]); d.update(packet(True), 1)
        token = d.token('screen'); replies = queue.Queue(); replies.put({'id': 'a'*32, 'result': {'accepted': True}})
        def status():now[0] = 9.; return {}
        client = Mock()
        worker.poll_ready(client, Mock(), {'png': 'private'}, replies, status, lambda: d.valid('screen', token))
        self.assertIsNone(client.poll.call_args.args[0]); self.assertEqual(len(client.poll.call_args.args[2]), 1)

    def test_old_receiver_stays_connected_without_unsolicited_frames(self):
        client = Client(new_connection('https://example.invalid', '../PortalAI', 'Fixture'), ROOT/'Runtime/cacert.pem')
        client.session = 'synthetic'; sent = []
        client.request = lambda value: sent.append(value) or {'commands': []}
        client.poll({'png': 'must not leave'}, {}, [])
        self.assertIsNone(sent[0]['frame']); self.assertEqual(client.frame_uploads, 0)
        self.assertEqual(client.demand.status(), 'receiver_update_required')

    def test_receiver_leases_are_separate_scoped_bounded_and_revocable(self):
        now = [1.]; device = 'a'*32; viewer = 'b'*32
        approved = {device: {'fingerprint': 'original'}}; grants = {device}
        book = ha.DemandBook(approved, lambda d: d in grants, lambda: now[0])
        first = SimpleNamespace(user=SimpleNamespace(id='one')); second = SimpleNamespace(user=SimpleNamespace(id='two'))
        book.change(device, first, viewer, 'native', 'acquire')
        self.assertEqual(book.packet(device), packet(False, True))
        book.change(device, second, viewer, 'native', 'release'); self.assertTrue(book.packet(device)['native'])
        book.change(device, second, viewer, 'native', 'acquire')
        book.change(device, first, viewer, 'native', 'release'); self.assertTrue(book.packet(device)['native'])
        book.change(device, second, viewer, 'screen', 'acquire')
        grants.clear(); self.assertEqual(book.packet(device), packet(True, False))
        approved[device]['fingerprint'] = 'replacement'; self.assertEqual(book.packet(device), packet())
        book.change(device, second, viewer, 'screen', 'acquire'); now[0] = 17
        self.assertFalse(book.packet(device)['screen'])
        with self.assertRaises(PermissionError):book.change(device, second, viewer, 'screen', 'renew')
        for i in range(16):book.change(device, second, f'{i:032x}', 'screen', 'acquire')
        with self.assertRaises(PermissionError):book.change(device, second, 'f'*32, 'screen', 'acquire')

    def test_ha_poll_rechecks_admin_and_clears_cached_last_frame(self):
        device = 'a'*32; conn = SimpleNamespace(user=SimpleNamespace(id='user'))
        book = ha.DemandBook({device: {'fingerprint': 'x'}}, lambda _: True)
        book.change(device, conn, 'b'*32, 'screen', 'acquire')
        async def get_user(_):return SimpleNamespace(is_admin=False, is_active=True)
        hass = SimpleNamespace(data={'portalai_projection': {'viewer_demand': book}}, auth=SimpleNamespace(async_get_user=get_user))
        target = SimpleNamespace(devices={device: {'frame': {'png': 'old'}, 'frame_at': 1}},approved={device:{}},
                                 sessions={'token':{'device_id':device,'expires':time.monotonic()+60}})
        result = asyncio.run(ha.poll_response(hass, target, device, {'commands': []},token='token'))
        self.assertEqual(result['viewer_demand'], packet()); self.assertIsNone(target.devices[device]['frame'])

    def test_reauthentication_during_ha_user_check_rejects_old_poll(self):
        device='a'*32;conn=SimpleNamespace(user=SimpleNamespace(id='user'))
        book=ha.DemandBook({device:{'fingerprint':'x'}},lambda _:True)
        book.change(device,conn,'b'*32,'native','acquire')
        target=SimpleNamespace(devices={device:{}},approved={device:{}},
                               sessions={'token':{'device_id':device,'expires':time.monotonic()+60}})
        async def get_user(_):
            target.sessions.clear()
            return SimpleNamespace(is_admin=True,is_active=True)
        hass=SimpleNamespace(data={'portalai_projection':{'viewer_demand':book}},auth=SimpleNamespace(async_get_user=get_user))
        with self.assertRaises(PermissionError):asyncio.run(ha.poll_response(hass,target,device,{'commands':[]},token='token'))

    def native(self):
        connection = new_connection('https://example.invalid', '../PortalAI', 'Fixture')
        public = public_pairing(connection); identity = connection['device_id']
        hub = NativeHub({identity: public}, {identity: public['fingerprint']})
        demand = ViewerDemand(); source = Source(); ws = HubSocket(hub, identity)
        client = NativeTransport(connection, Mock(), threading.Event(), demand=demand)
        client.local = source; client.ws = ws; client.authenticate()
        self.addCleanup(client.close)
        return client, demand, source, ws, hub, identity

    def test_native_idle_never_reads_GUI_and_wake_rotates_binding(self):
        client, demand, source, ws, hub, identity = self.native()
        self.assertFalse(client.step()); self.assertEqual(source.reads, 0)
        demand.update(packet(native=True), time.monotonic()); self.assertTrue(client.step())
        old = dict(client.binding); reads = source.reads
        demand.update(packet(), time.monotonic()); self.assertFalse(client.step()); self.assertFalse(client.step())
        self.assertEqual(source.reads, reads)
        self.assertEqual(sum(p['kind'] == 'invalidate' for p in ws.sent), 1)
        with self.assertRaises(PermissionError):hub.read(identity)
        demand.update(packet(native=True), time.monotonic()); self.assertTrue(client.step())
        self.assertNotEqual(old, client.binding)

    def test_disconnect_during_native_bind_publishes_no_snapshot(self):
        client, demand, source, ws, hub, identity = self.native()
        demand.update(packet(native=True), time.monotonic())
        ws.after_bound = lambda: demand.update(packet(), time.monotonic())
        self.assertFalse(client.step())
        self.assertFalse(any(row['kind'] == 'snapshot' for row in ws.sent))

    def test_worker_idle_native_only_screen_then_disconnect(self):
        # Run the actual worker loops/executors against real protocol classes,
        # synthetic captures and the receiver's signature-verifying state machine.
        import mission_runner, portalai_target, projection_client, native_transport
        connection = new_connection('https://example.invalid', '../PortalAI', 'Fixture')
        public = public_pairing(connection); identity = connection['device_id']
        _, approval = receiver.pairing(public)
        remote = receiver.Receiver({identity: approval})
        hub = NativeHub({identity: public}, {identity: public['fingerprint']})
        book = ha.DemandBook(remote.approved, hub.permitted)
        browser = SimpleNamespace(user=SimpleNamespace(id='admin')); viewer = 'a'*32
        source = Source(); done = threading.Event(); captures = []; observations = []; delivered = []
        manager = Mock(); manager.status.return_value = {'running': True}; manager.frame.side_effect = lambda *a, **kw: captures.append(1) or {'windows': []}
        manager.lifecycle.return_value={'accepted': True}
        real_client = Client(connection, ROOT/'Runtime/cacert.pem')
        count = [0]
        def request(body):
            if body['action'] == 'challenge':return remote.challenge(identity)
            if body['action'] == 'authenticate':return remote.authenticate(body)
            index = count[0]; count[0] += 1
            observations.append({'poll': index, 'captures': len(captures), 'reads': source.reads,
                                 'frame': body['frame'] is not None, 'uploads': real_client.frame_uploads})
            result = remote.poll(real_client.session, body)
            delivered.extend(body['replies'])
            if index == 0:
                # An authorized receiver dispatch while no viewer is present.
                result['commands']=[{'id':'b'*32,'action':'native_ui','payload':{'operation':'describe'},'ttl':5},
                                    {'id':'c'*32,'action':'start','payload':{'request_id':'d'*32},'ttl':5}]
            if index == 2:book.change(identity, browser, viewer, 'native', 'acquire')
            if index == 4:book.change(identity, browser, viewer, 'screen', 'acquire')
            if index == 6:
                for kind in ('screen', 'native'):book.change(identity, browser, viewer, kind, 'release')
            if index == 8:done.set()
            result['viewer_demand'] = book.packet(identity)
            return result
        real_client.request = request
        def native_factory(conn, mgr, stop, report, **kwargs):
            transport = NativeTransport(conn, mgr, stop, report, connect=lambda *args: HubSocket(hub, identity), **kwargs)
            transport.local = source
            return transport
        class Input:
            def readline(self, _):return json.dumps(connection)
            def __iter__(self):
                done.wait(20)
                return iter(())
        with tempfile.TemporaryDirectory(prefix='portalai-demand-fixture-') as folder:
            (Path(folder)/'state/input').mkdir(parents=True)
            with patch.object(worker, 'MODULE', Path(folder)), patch.object(worker, 'input_owner', return_value='synthetic'), \
                    patch.object(worker, 'target_valid', return_value=True), patch.object(worker, 'resolve_target', return_value=default_target()), \
                    patch.object(mission_runner, 'process_lock', return_value=contextlib.nullcontext()), \
                    patch.object(portalai_target, 'Manager', return_value=manager), patch.object(projection_client, 'Client', return_value=real_client), \
                    patch.object(native_transport, 'NativeTransport', side_effect=native_factory), patch.object(sys, 'stdin', Input()), \
                    contextlib.redirect_stdout(io.StringIO()):
                worker.main()
        self.assertEqual(len(observations), 9, observations)
        self.assertEqual(observations[1]['captures'], 0); self.assertEqual(observations[1]['reads'], 0)
        self.assertEqual(observations[4]['captures'], 0); self.assertGreater(observations[4]['reads'], 0)
        self.assertFalse(observations[4]['frame']); self.assertTrue(observations[6]['frame'])
        self.assertGreater(observations[6]['captures'], 0)
        self.assertFalse(observations[8]['frame'])
        for key in ('captures', 'reads', 'uploads'):self.assertEqual(observations[7][key], observations[8][key], observations)
        manager.native_ui.assert_not_called();manager.lifecycle.assert_called_once()
        self.assertTrue(any(r['id']=='b'*32 and 'error' in r for r in delivered))
        self.assertTrue(any(r['id']=='c'*32 and r.get('result',{}).get('accepted') for r in delivered))


if __name__ == '__main__':unittest.main()
