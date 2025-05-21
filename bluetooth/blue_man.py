#!/usr/bin/env python3
import asyncio
from datetime import datetime, timedelta
from dbus_next.aio import MessageBus
from dbus_next.constants import BusType
from dbus_next import Variant, DBusError

BLUEZ_SERVICE = 'org.bluez'
ADAPTER_PATH = '/org/bluez/hci0'

class BluetoothManager:
    def __init__(self, scan_ttl_seconds=60):
        self.bus = None
        self.adapter = None
        # devices: name -> {path, address, rssi, connected}
        self.devices = {}
        self.last_scan = None
        self.scan_ttl = timedelta(seconds=scan_ttl_seconds)

    async def connect_bus(self):
        if self.bus is None:
            self.bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            xml = await self.bus.introspect(BLUEZ_SERVICE, ADAPTER_PATH)
            obj = self.bus.get_proxy_object(BLUEZ_SERVICE, ADAPTER_PATH, xml)
            self.adapter = obj.get_interface('org.bluez.Adapter1')

    async def scan(self, duration=5):
        """Scan for nearby Bluetooth devices and cache them."""
        await self.connect_bus()
        try:
            await self.adapter.call_start_discovery()
            await asyncio.sleep(duration)
            await self.adapter.call_stop_discovery()
        except DBusError as e:
            print(f'❌ Discovery error: {e}')
            return
        # Retrieve devices
        xml = await self.bus.introspect(BLUEZ_SERVICE, '/')
        mgr_obj = self.bus.get_proxy_object(BLUEZ_SERVICE, '/', xml)
        mgr = mgr_obj.get_interface('org.freedesktop.DBus.ObjectManager')
        objs = await mgr.call_get_managed_objects()
        # Rebuild cache
        self.devices.clear()
        for path, interfaces in objs.items():
            props = interfaces.get('org.bluez.Device1')
            if not props:
                continue
            name = props.get('Name').value if props.get('Name') else None
            addr = props.get('Address').value if props.get('Address') else None
            rssi = props.get('RSSI').value if props.get('RSSI') else None
            connected = props.get('Connected').value if props.get('Connected') else False
            if name:
                self.devices[name] = {
                    'path': path,
                    'address': addr,
                    'rssi': rssi,
                    'connected': connected
                }
        self.last_scan = datetime.now()

    async def list_devices(self, online_only=False):
        """
        List cached devices. If cache expired or empty, perform a scan.
        online_only=True filters to devices with RSSI or Connected=True.
        Returns list of device names.
        """
        if self.last_scan is None or datetime.now() - self.last_scan > self.scan_ttl:
            print('ℹ️ Cache expired or empty; scanning...')
            await self.scan()
        print('🎯 Available devices:')
        result = []
        for name, info in self.devices.items():
            is_online = info['rssi'] is not None or info['connected']
            if online_only and not is_online:
                continue
            status_parts = []
            if info['connected']:
                status_parts.append('connected')
            if info['rssi'] is not None:
                status_parts.append(f'RSSI={info["rssi"]}')
            status = ' '.join(status_parts) if status_parts else 'offline'
            print(f"• {name} [{info['address']}] ({status}) at {info['path']}")
            result.append(name)
        return result

    async def connect(self, names):
        """Pair, trust, and connect to named devices."""
        await self.connect_bus()
        # Refresh cache if stale
        if self.last_scan is None or datetime.now() - self.last_scan > self.scan_ttl:
            await self.scan()
        for name in names:
            info = self.devices.get(name)
            if not info:
                print(f'⚠️ Device "{name}" not found')
                continue
            path = info['path']
            xml = await self.bus.introspect(BLUEZ_SERVICE, path)
            dev_obj = self.bus.get_proxy_object(BLUEZ_SERVICE, path, xml)
            dev = dev_obj.get_interface('org.bluez.Device1')
            props = dev_obj.get_interface('org.freedesktop.DBus.Properties')
            try:
                print(f'🔗 Pairing {name}...')
                await dev.call_pair()
                print(f'✅ Paired {name}')
            except DBusError:
                print(f'⚠️ Pair skipped for {name}')
            try:
                print(f'🤝 Trusting {name}...')
                await props.call_set('org.bluez.Device1', 'Trusted', Variant('b', True))
                print(f'✅ Trusted {name}')
            except DBusError as e:
                print(f'❌ Trust failed for {name}: {e}')
            try:
                print(f'🔌 Connecting {name}...')
                await dev.call_connect()
                print(f'✅ Connected {name}')
            except DBusError as e:
                print(f'❌ Connect failed for {name}: {e}')

    async def disconnect(self, names):
        """Disconnect named devices."""
        await self.connect_bus()
        for name in names:
            info = self.devices.get(name)
            if not info:
                print(f'⚠️ Device "{name}" not found')
                continue
            path = info['path']
            xml = await self.bus.introspect(BLUEZ_SERVICE, path)
            dev_obj = self.bus.get_proxy_object(BLUEZ_SERVICE, path, xml)
            dev = dev_obj.get_interface('org.bluez.Device1')
            try:
                print(f'⏏️ Disconnecting {name}...')
                await dev.call_disconnect()
                print(f'✅ Disconnected {name}')
            except DBusError as e:
                print(f'❌ Disconnect failed for {name}: {e}')

# Example usage
async def main():
    mgr = BluetoothManager(scan_ttl_seconds=30)
    print('All devices:')
    await mgr.list_devices(online_only=False)

    print('\nOnline devices:')
    #online = await mgr.list_devices(online_only=True)
    #if not online:
    #    print('⚠️ No online devices found.')

    # Connect/disconnect example
    targets = ['BASS Bluetooth music']
    await mgr.connect(targets)
    #await asyncio.sleep(2)
    #await mgr.disconnect(targets)

if __name__ == '__main__':
    asyncio.run(main())
