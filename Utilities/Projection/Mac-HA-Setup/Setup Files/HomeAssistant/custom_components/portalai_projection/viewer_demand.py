"""Ephemeral viewer intent. Merge into the CURRENT trusted HA receiver.

This is not a grant, account binding, controller lease or command API. All
existing authentication, pairing, native read and effect checks remain required.
"""
import re
import time

PRESENCE_SECONDS = 15
BACKGROUND_SECONDS = 10
HOST_LEASE_SECONDS = 5
KINDS = ('screen', 'native')


def opaque(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{32}', value):
        raise ValueError('Invalid viewer identity')
    return value


class DemandBook:
    """Bounded leases, keyed to the actual HA connection, user and pairing."""
    def __init__(self, approved, native_permitted, clock=time.monotonic):
        self.approved = approved
        self.native_permitted = native_permitted
        self.clock = clock
        self.rows = {}

    def prune(self):
        now = self.clock()
        for key, row in list(self.rows.items()):
            pairing = self.approved.get(row['device'])
            if (row['until'] <= now or not pairing or pairing.get('fingerprint') != row['fingerprint']
                    or (row['kind'] == 'native' and not self.native_permitted(row['device']))):
                self.rows.pop(key, None)

    def change(self, device, connection, viewer, kind, action):
        opaque(device); opaque(viewer)
        if kind not in KINDS or action not in ('acquire', 'renew', 'release', 'background', 'foreground'):
            raise ValueError('Invalid viewer request')
        self.prune()
        key = (device, id(connection), connection.user.id, viewer, kind)
        if action == 'release':
            self.rows.pop(key, None)
            return
        pairing = self.approved.get(device)
        if not pairing or (kind == 'native' and not self.native_permitted(device)):
            raise PermissionError('Viewer permission required')
        if action in ('renew', 'background', 'foreground') and key not in self.rows:
            raise PermissionError('Viewer lease expired; explicitly reconnect')
        if action == 'background':
            # Duplicate notifications and late heartbeats cannot extend grace.
            if not self.rows[key].get('background'):
                self.rows[key].update(until=self.clock()+BACKGROUND_SECONDS, background=True)
            return
        if action in ('acquire', 'renew') and self.rows.get(key, {}).get('background'):
            return
        if key not in self.rows and (len(self.rows) >= 128 or
                sum(r['device'] == device for r in self.rows.values()) >= 16):
            raise PermissionError('Viewer capacity reached')
        self.rows[key] = {'device': device, 'connection': connection,
                          'user': connection.user.id, 'viewer': viewer, 'kind': kind,
                          'fingerprint': pairing['fingerprint'], 'until': self.clock() + PRESENCE_SECONDS}

    def remove_user(self, user):
        for key, row in list(self.rows.items()):
            if row['user'] == user:
                self.rows.pop(key, None)

    def packet(self, device):
        self.prune()
        return {'version': 1, 'screen': any(r['device'] == device and r['kind'] == 'screen' for r in self.rows.values()),
                'native': any(r['device'] == device and r['kind'] == 'native' for r in self.rows.values()),
                'lease_seconds': HOST_LEASE_SECONDS}


async def authorized_user(hass, connection):
    user = await hass.auth.async_get_user(connection.user.id)
    if user is None or not user.is_admin or not user.is_active:
        raise PermissionError('Active HA administrator required')


def install(hass):
    """Call once after hass.data['portalai_projection']['receiver'] exists."""
    import voluptuous as vol
    from homeassistant.components import websocket_api
    projection = hass.data['portalai_projection']
    if 'viewer_demand' in projection:
        raise RuntimeError('Viewer demand already installed')
    def native_permitted(device):
        receiver = hass.data.get('portalai_native', {}).get('receiver')
        return bool(receiver and receiver.hub.permitted(device))
    book = DemandBook(projection['receiver'].approved, native_permitted)
    projection['viewer_demand'] = book

    @websocket_api.websocket_command({vol.Required('type'): 'portalai_projection/viewer',
        vol.Required('device_id'): str, vol.Required('viewer'): str,
        vol.Required('kind'): vol.In(KINDS), vol.Required('action'): vol.In(('acquire', 'renew', 'release', 'background', 'foreground'))})
    @websocket_api.require_admin
    @websocket_api.async_response
    async def viewer(hass, connection, msg):
        try:
            await authorized_user(hass, connection)
            book.change(msg['device_id'], connection, msg['viewer'], msg['kind'], msg['action'])
            connection.send_result(msg['id'], {'accepted': True, 'lease_seconds': PRESENCE_SECONDS})
        except (PermissionError, ValueError, KeyError) as exc:
            connection.send_error(msg['id'], 'portalai_viewer_refused', str(exc))
    websocket_api.async_register_command(hass, viewer)


async def poll_response(hass, receiver, device, result, *, token):
    """Call ONLY after receiver.poll authenticated the exact device session."""
    book = hass.data['portalai_projection']['viewer_demand']
    session = receiver.sessions.get(token)
    state = receiver.devices.get(device)
    if not session or session['device_id'] != device or state is None:
        raise PermissionError('Projection session changed')
    book.prune()
    for user_id in {r['user'] for r in book.rows.values() if r['device'] == device}:
        user = await hass.auth.async_get_user(user_id)
        if user is None or not user.is_admin or not user.is_active:
            book.remove_user(user_id)
    if (receiver.sessions.get(token) is not session or receiver.devices.get(device) is not state
            or device not in receiver.approved or session['expires'] < time.monotonic()):
        raise PermissionError('Projection session changed')
    packet = book.packet(device)
    # No cached screenshot survives standby, including an in-flight last frame.
    if not packet['screen']:
        state.update(frame=None, frame_at=0)
    return {**result, 'viewer_demand': packet}


async def screen_request(hass, connection, device, viewer):
    """Optional legacy-card compatibility: actual frame requests renew demand.

    Call before the existing frame freshness check, not on status or input.
    Existing controller lease checks still run in the caller.
    """
    await authorized_user(hass, connection)
    book = hass.data['portalai_projection']['viewer_demand']
    book.change(device, connection, viewer, 'screen', 'acquire')


def screen_disconnect(hass, connection, device, viewer):
    book = hass.data['portalai_projection']['viewer_demand']
    book.change(device, connection, viewer, 'screen', 'release')
